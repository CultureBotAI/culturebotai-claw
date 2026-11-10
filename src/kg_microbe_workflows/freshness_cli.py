"""Explicit, opt-in repository freshness batch for Codex and native goal runners.

The gate publishes immutable inventory/merge observations, not goal completion
or merge authority. Ordinary review, evidence, issue and cleanup gates still
apply. Proposal-only consumer adapters cannot execute this path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

from . import WorkflowError, load_effective_workflow
from .freshness import (
    FreshnessError,
    Git,
    digest,
    ensure_freshness,
    save_receipt,
    verify_inventory_head,
    verify_saved_receipt,
)
from .freshness_contract import load_adoption, repository_identity

# Measured TaxonMech inventory is 138.5 MB; requests remain capped at 1 MB.
ARTIFACT_LIMIT = 256_000_000

_FIELDS = {"schema_version", "repository_key", "repository_root", "lock_directory",
           "receipt_directory", "protected_roots", "adoption", "boundary_id", "phase",
           "workflow_sha256", "effective_workflow", "prior_inventory", "pull_requests"}


def _load(path: Path, *, limit: int = 1_000_000) -> Any:
    if not path.is_absolute() or path.resolve() != path or path.stat().st_size > limit:
        raise FreshnessError("request_path_unsafe_or_unbounded")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise FreshnessError("duplicate_request_key")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=pairs)


def _path(value: Any) -> Path:
    if not isinstance(value, str):
        raise FreshnessError("request_path_requires_text")
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise FreshnessError("request_path_must_be_absolute_without_symlinks")
    return path


def read_artifact(reference: Any) -> dict[str, Any]:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise FreshnessError("invalid_artifact_reference")
    path = _path(reference['path'])
    value = _load(path, limit=ARTIFACT_LIMIT)
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference['sha256'] or not isinstance(value, dict):
        raise FreshnessError("artifact_digest_or_shape_differs")
    return value


def github_pr(repository: str, number: int) -> dict[str, Any]:
    try:
        result = subprocess.run(["gh", "api", "--hostname", "github.com",
                                 f"repos/{repository}/pulls/{number}"],
                                check=True, text=True, capture_output=True, timeout=30)
        if len(result.stdout) > 2_000_000:
            raise FreshnessError("merge_observation_unbounded")
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise FreshnessError("actual_merge_observation_unavailable") from exc


def frozen_workflow_sources(reference: Any, *, root: Path, key: str,
                            repository: str, workflow_sha256: str) -> dict[str, str]:
    """Revalidate the complete approved loader output, never a caller's partial map."""
    effective = read_artifact(reference)
    if _path(reference['path']).is_relative_to(root):
        raise FreshnessError('effective_workflow_snapshot_must_live_outside_checkout')
    # Existing supervisor workflow identities use default JSON separators.
    # Receipt digest() is deliberately compact and is a different namespace.
    if hashlib.sha256(json.dumps(effective, sort_keys=True).encode()).hexdigest() != workflow_sha256:
        raise FreshnessError('effective_workflow_snapshot_identity_differs')
    sources = effective.get('sources')
    if not isinstance(sources, list) or not 3 <= len(sources) <= 32:
        raise FreshnessError('effective_workflow_sources_missing_or_malformed')
    primary: dict[str, Path] = {}
    seen: set[Path] = set()
    frozen: dict[str, str] = {}
    for source in sources:
        if (not isinstance(source, dict) or set(source) != {'path', 'sha256', 'kind'}
                or source['kind'] not in {'parent', 'profile', 'schema', 'extension'}):
            raise FreshnessError('effective_workflow_source_shape_differs')
        path = _path(source['path'])
        if path in seen:
            raise FreshnessError('effective_workflow_source_repeated')
        seen.add(path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise FreshnessError('effective_workflow_source_bytes_differ')
        if source['kind'] != 'extension':
            if source['kind'] in primary:
                raise FreshnessError('effective_workflow_primary_source_repeated')
            primary[source['kind']] = path
        if path.is_relative_to(root):
            frozen[path.relative_to(root).as_posix()] = source['sha256']
    if set(primary) != {'parent', 'profile', 'schema'} or not primary['profile'].is_relative_to(root):
        raise FreshnessError('effective_workflow_primary_sources_or_root_differ')
    # Re-running the native loader catches omitted extensions, modified pins and
    # invented effective fields even if a malformed snapshot was approved.
    try:
        actual = load_effective_workflow(primary['parent'], primary['profile'], key,
                                         schema_path=primary['schema'])
    except WorkflowError as exc:
        raise FreshnessError('effective_workflow_profile_or_pins_invalid') from exc
    if actual != effective or actual.get('github_repository') != repository:
        raise FreshnessError('effective_workflow_snapshot_or_repository_differs')
    return frozen


def execute(request: dict[str, Any], *, apply: bool = False,
            observe_pr: Callable[[str, int], dict[str, Any]] = github_pr) -> dict[str, Any]:
    """One batch member; neither starts a native goal nor edits a runtime ledger."""
    if not isinstance(request, dict) or set(request) != _FIELDS or request['schema_version'] != '1.0.0':
        raise FreshnessError("request_unknown_or_missing_fields")
    key = request['repository_key']
    root = _path(request['repository_root'])
    target = RepositoryTarget(key, root, repository_identity(key))
    reference = request['adoption']
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise FreshnessError('invalid_adoption_reference')
    candidate = read_artifact(reference)
    boundary = candidate.get('boundary', {})
    if not isinstance(boundary, dict):
        raise FreshnessError('invalid_adoption_boundary')
    if not isinstance(boundary.get('run_id'), str) or type(boundary.get('cycle')) is not int:
        raise FreshnessError('invalid_adoption_boundary_types')
    adoption = load_adoption(
        _path(reference['path']), expected_sha256=reference['sha256'], repository_key=key,
        repository_root=root, workflow_sha256=request['workflow_sha256'],
        run_id=boundary['run_id'], cycle=boundary['cycle'],
        predecessor_receipt_sha256=boundary.get('predecessor_receipt_sha256'),
    )
    workflow_reference = request['effective_workflow']
    frozen_paths = frozen_workflow_sources(
        workflow_reference, root=root, key=key, repository=target.expected_repository,
        workflow_sha256=request['workflow_sha256'],
    )
    if not isinstance(request['protected_roots'], list):
        raise FreshnessError('protected_roots_requires_list')
    protected = [_path(value) for value in request['protected_roots']]
    receipts = _path(request['receipt_directory'])
    if receipts == root or receipts.is_relative_to(root):
        raise FreshnessError('receipts_must_live_outside_curated_checkout')
    locks = LockManager({'locks_dir': _path(request['lock_directory']),
                         'my_id': 'repository-freshness-batch'})
    phase = request['phase']
    if phase not in {'pre_goal', 'post_merge', 'no_change'}:
        raise FreshnessError('unsupported_boundary_phase')
    prs = request['pull_requests']
    if not isinstance(prs, list) or len(prs) > 32:
        raise FreshnessError('invalid_pull_request_list')
    merged: list[str] = []
    merge_observations = []
    if phase == 'pre_goal' and (prs or request['prior_inventory'] is not None):
        raise FreshnessError('new_goal_cannot_replace_prior_evidence')
    slot = receipts / 'index' / key / (digest(request['boundary_id']) + '.json')
    if phase == 'pre_goal' and slot.exists():
        retained = _load(slot)
        previous = read_artifact(retained)
        if (previous.get('adoption') != reference or previous.get('boundary_id') != request['boundary_id']
                or previous.get('workflow_sha256') != request['workflow_sha256']
                or previous.get('effective_workflow') != workflow_reference):
            raise FreshnessError('existing_goal_inventory_context_differs')
        verify_inventory_head(target, previous['freshness'], boundary_id=request['boundary_id'],
                              policy_sha256=adoption['contract_sha256'])
        return {'status': 'verified', 'kind': previous['kind'], 'artifact': retained,
                'head': previous['head'], 'completion_authority': False, 'reused_frozen_inventory': True}
    if phase == 'pre_goal':
        if prs or request['prior_inventory'] is not None:
            raise FreshnessError('new_goal_cannot_replace_prior_evidence')
    else:
        prior = read_artifact(request['prior_inventory'])
        if (prior.get('kind') != 'verified_goal_inventory'
                or prior.get('boundary_id') != request['boundary_id']
                or prior.get('repository_key') != key or prior.get('adoption') != reference
                or prior.get('workflow_sha256') != request['workflow_sha256']
                or prior.get('effective_workflow') != workflow_reference):
            raise FreshnessError('post_merge_inventory_context_differs')
        verify_saved_receipt(prior.get('freshness', {}))
        if not slot.exists() or _load(slot) != request['prior_inventory']:
            raise FreshnessError('prior_inventory_is_not_the_registered_goal_inventory')
        if phase == 'no_change':
            if prs:
                raise FreshnessError('no_change_cannot_claim_merge')
            head = verify_inventory_head(target, prior['freshness'], boundary_id=request['boundary_id'],
                                         policy_sha256=adoption['contract_sha256'])
            if not apply:
                return {'status': 'preview', 'reason': 'no_execution_authority'}
            artifact = {'schema_version': '1.0.0', 'kind': 'verified_no_change_freshness',
                        'boundary_id': request['boundary_id'], 'repository_key': key,
                        'effective_workflow': workflow_reference,
                        'workflow_sha256': request['workflow_sha256'],
                        'prior_inventory': request['prior_inventory'], 'head': head,
                        'completion_authority': False}
            return {'status': 'verified', 'kind': artifact['kind'],
                    'artifact': save_receipt(receipts / 'boundaries', artifact), 'head': head,
                    'completion_authority': False}
        if not prs:
            raise FreshnessError('post_merge_requires_actual_pull_request')
        seen = set()
        for pr in prs:
            if (not isinstance(pr, dict) or set(pr) != {'number', 'head_sha', 'merge_commit_sha'}
                    or type(pr['number']) is not int or pr['number'] < 1 or pr['number'] in seen):
                raise FreshnessError('invalid_or_repeated_pull_request')
            seen.add(pr['number'])
            if not apply:
                continue
            remote = observe_pr(target.expected_repository, pr['number'])
            base, head = remote.get('base', {}), remote.get('head', {})
            if (remote.get('number') != pr['number'] or remote.get('merged') is not True
                    or not remote.get('merged_at') or head.get('sha') != pr['head_sha']
                    or remote.get('merge_commit_sha') != pr['merge_commit_sha']
                    or base.get('repo', {}).get('full_name', '').casefold() != target.expected_repository.casefold()):
                raise FreshnessError('actual_merge_identity_differs')
            merge_observations.append({'number': pr['number'], 'head_sha': head['sha'],
                                       'merge_commit_sha': remote['merge_commit_sha'],
                                       'base': base.get('ref'), 'merged_at': remote['merged_at']})
            merged.append(remote['merge_commit_sha'])
    if phase == 'post_merge' and not apply:
        return {'status': 'preview', 'reason': 'actual_merge_not_observed:no_execution_authority'}
    report = ensure_freshness(
        target, phase=phase, boundary_id=request['boundary_id'],
        policy_sha256=adoption['contract_sha256'], locks=locks, receipt_dir=receipts / 'observations',
        protected_roots=protected, merge_commits=merged, frozen_paths=frozen_paths, apply=apply,
    )
    if report['status'] != 'verified':
        return report
    artifact = {'schema_version': '1.0.0', 'repository_key': key,
                'boundary_id': request['boundary_id'], 'adoption': reference,
                'effective_workflow': workflow_reference,
                'workflow_sha256': request['workflow_sha256'], 'freshness': report,
                'completion_authority': False}
    if phase == 'pre_goal':
        # Executable ordering: no inventory read occurs before the gate succeeds.
        head = verify_inventory_head(target, report, boundary_id=request['boundary_id'],
                                     policy_sha256=adoption['contract_sha256'])
        git = Git(root, 30)
        entries = git.run('ls-tree', '-r', '-z', head).split('\0')
        files = []
        for entry in filter(None, entries):
            metadata, path = entry.split('\t', 1)
            mode, kind, sha = metadata.split()
            files.append({'path': path, 'mode': mode, 'kind': kind, 'object_sha': sha})
        # An owner/ref race while reading cannot publish an accepted inventory.
        verify_inventory_head(target, report, boundary_id=request['boundary_id'],
                              policy_sha256=adoption['contract_sha256'])
        artifact.update(kind='verified_goal_inventory', head=head, files=files)
    else:
        if any(pr['base'] != report['default_branch'] for pr in merge_observations):
            raise FreshnessError('merged_pull_request_not_for_canonical_default')
        artifact.update(kind='verified_post_merge_freshness', merges=merge_observations,
                        prior_inventory=request['prior_inventory'])
    if len(json.dumps(artifact, sort_keys=True, indent=2).encode()) + 1 > ARTIFACT_LIMIT:
        raise FreshnessError('inventory_artifact_exceeds_reader_bound')
    location = save_receipt(receipts / 'boundaries', artifact)
    if read_artifact(location) != artifact:
        raise FreshnessError('inventory_artifact_readback_failed')
    if phase == 'pre_goal':
        slot.parent.mkdir(parents=True, exist_ok=True)
        if slot.parent.resolve() != slot.parent:
            raise FreshnessError('inventory_index_path_unsafe')
        temporary = slot.parent / ('.new-' + uuid.uuid4().hex)
        try:
            with temporary.open('x') as stream:
                json.dump(location, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, slot)
            except FileExistsError:
                raise FreshnessError('inventory_already_frozen:preserve_existing_evidence') from None
        finally:
            temporary.unlink(missing_ok=True)
    return {'status': 'verified', 'kind': artifact['kind'], 'artifact': location,
            'head': report['after'], 'freshness_receipt': report['receipt'],
            'completion_authority': False}


def run_batch(requests: list[dict[str, Any]], *, apply: bool = False) -> dict[str, Any]:
    """All members reported; any hold makes the batch fail, never partial success."""
    if not isinstance(requests, list) or not requests or len(requests) > 64:
        raise FreshnessError('invalid_batch')
    identities = [(item.get('repository_key'), item.get('boundary_id'), item.get('phase'))
                  for item in requests if isinstance(item, dict)]
    if len(identities) != len(requests) or len(set(identities)) != len(identities):
        raise FreshnessError('duplicate_or_malformed_batch_member')
    results = []
    for request in requests:
        try:
            results.append(execute(request, apply=apply))
        except FreshnessError as exc:
            results.append({'status': 'hold', 'repository_key': request.get('repository_key'),
                            'reason': str(exc)})
        except (WorkflowError, OSError, ValueError, TypeError, KeyError):
            results.append({'status': 'hold', 'repository_key': request.get('repository_key'),
                            'reason': 'boundary_request_or_observation_failed'})
    return {'schema_version': '1.0.0', 'request_sha256': digest(requests), 'results': results,
            'status': 'verified' if all(item['status'] == 'verified' for item in results) else 'hold'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'verify'])
    parser.add_argument('--request', type=Path, required=True, help='absolute path to a JSON request list')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        requests = _load(args.request)
        if args.command == 'verify':
            if args.apply or not isinstance(requests, list) or any(row.get('phase') != 'pre_goal' for row in requests):
                raise FreshnessError('verify_requires_read_only_pre_goal_requests')
            for row in requests:
                slot = _path(row['receipt_directory']) / 'index' / row['repository_key'] / (digest(row['boundary_id']) + '.json')
                if not slot.is_file():
                    raise FreshnessError('inventory_not_yet_frozen')
        result = run_batch(requests, apply=args.apply)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result['status'] == 'verified' else 1
    except FreshnessError as exc:
        print(json.dumps({'status': 'hold', 'reason': str(exc)}), file=sys.stderr)
        return 1
    except (WorkflowError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'status': 'hold', 'reason': type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
