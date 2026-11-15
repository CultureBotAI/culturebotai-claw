"""Prepare inert, provenance-bound freshness proposals in owned task worktrees.

The batch never releases, adopts or dispatches. Canonical source may be a
reviewed PR commit, explicitly recorded as proposal provenance, not a release.
All selected repositories are preflighted before the first write; a later race
fails nonzero and identifies already-prepared repositories, without rollback of
unrelated work. Downstream active workflow and vendored pins are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from kg_microbe_fleet import (
    FleetManifest,
    UniqueKeySafeLoader,
    load_fleet_manifest,
    parse_fleet_manifest,
)
from kg_microbe_workflows.freshness import (
    FreshnessError,
    Git,
    identity,
    owner_snapshot,
    worktree_roots,
)
from kg_microbe_workflows.freshness_contract import repository_identity
from kg_microbe_write import ValidatedWriteTransaction
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositorySettings, RepositoryTarget

SOURCE_PATHS = {
    'contract.yaml': 'src/kg_microbe_workflows/templates/repository-freshness-v1.yaml',
    'schema.yaml': 'src/kg_microbe_workflows/schema/repository-freshness-v1.yaml',
    'SKILL.md': 'src/kg_microbe_skills/canonical/repository-freshness.md',
}
FLEET_SOURCE_PATHS = {
    'manifest': 'src/kg_microbe_fleet/fleet.yaml',
    'loader': 'src/kg_microbe_fleet/__init__.py',
}
CANDIDATE_PATH = Path('workflow/candidates/repository-freshness-v1')
PRESERVED_PATHS = (
    'workflow/mech-workflow.yaml', 'workflow/parent/mech-cycle.yaml',
    'workflow/parent/workflow.yaml', 'scripts/.vendored_canon_ref',
)


class CandidateError(ValueError):
    """A proposal cannot be prepared safely; no authority to bypass a hold."""


def _git(root: Path, *args: str) -> str:
    try:
        return Git(root, timeout=30).run(*args)
    except FreshnessError as exc:
        raise CandidateError(str(exc)) from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _full_sha(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise CandidateError('a full immutable source/HEAD commit is required')
    return value


def _path(value: Any) -> Path:
    if not isinstance(value, str):
        raise CandidateError('paths must be explicit absolute strings')
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise CandidateError('paths must be absolute with no symlink or parent alias')
    return path


def _settings(key: str, root: Path, manifest: FleetManifest | None = None) -> RepositoryTarget:
    # No implicit .env/current-directory fallback; claw is explicit control plane.
    try:
        if key == 'claw':
            target = RepositoryTarget(key, root, 'CultureBotAI/culturebotai-claw')
        else:
            if manifest is None:
                raise CandidateError('explicit pinned manifest is required')
            settings = RepositorySettings.from_environment(
                {'repositories': {key: {'path': str(root)}}}, environ={},
                manifest=manifest)
            target = settings.get_target(key)
        identity(Git(root, timeout=30), target)
        target.open()
        return target
    except (ValueError, OSError) as exc:
        raise CandidateError('configured repository identity/path validation failed') from exc


def _verified_source_blob(root: Path, commit: str, source: str) -> bytes:
    entry = _git(root, 'ls-tree', commit, '--', source)
    if not entry.startswith('100644 blob '):
        raise CandidateError(f'source is not a regular canonical blob: {source}')
    # Prove exact bytes, including comments and terminal newlines. The loader is
    # data-bound as well; no code from the proposed source commit is executed.
    packaged = Path(__file__).parents[1] / source.removeprefix('src/')
    raw = packaged.read_bytes()
    if len(raw) > 1048576:
        raise CandidateError('canonical candidate payload exceeds bound')
    if _git(root, 'rev-parse', '--show-object-format') != 'sha1':
        raise CandidateError('canonical Git object format is unsupported')
    object_id = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if entry.split()[2] != object_id:
        raise CandidateError('source payload differs from the running canonical package')
    return raw


def _source(root: Path, commit: str) -> dict[str, bytes]:
    _path(str(root))
    _settings('claw', root)
    _full_sha(commit)
    if _git(root, 'rev-parse', commit + '^{commit}') != commit:
        raise CandidateError('source commit identity differs')
    return {destination: _verified_source_blob(root, commit, source)
            for destination, source in SOURCE_PATHS.items()}


def _pinned_fleet(root: Path, commit: str) -> tuple[FleetManifest, dict[str, str]]:
    if 'KG_MICROBE_FLEET_MANIFEST' in os.environ:
        raise CandidateError('candidate preparation forbids ambient manifest overrides')
    _path(str(root))
    _settings('claw', root)
    _full_sha(commit)
    if _git(root, 'rev-parse', commit + '^{commit}') != commit:
        raise CandidateError('source commit identity differs')
    manifest_path = Path(__file__).parents[1] / FLEET_SOURCE_PATHS['manifest'].removeprefix('src/')
    fleet = load_fleet_manifest(manifest_path)
    manifest_raw = _verified_source_blob(root, commit, FLEET_SOURCE_PATHS['manifest'])
    loader_raw = _verified_source_blob(root, commit, FLEET_SOURCE_PATHS['loader'])
    # The public loader caches by path. Prove its returned model still matches
    # the exact bytes bound above, without mutating any shared loader cache.
    fresh = parse_fleet_manifest(yaml.load(manifest_raw, Loader=UniqueKeySafeLoader), manifest_path)
    if (fleet.source != manifest_path or fleet.mechs != fresh.mechs
            or fleet.capability_catalogue != fresh.capability_catalogue
            or fleet.vendored_governance != fresh.vendored_governance):
        raise CandidateError('loaded manifest differs from the exact pinned bytes')
    return fleet, {
        'manifest_path': FLEET_SOURCE_PATHS['manifest'],
        'manifest_sha256': _sha(manifest_raw),
        'loader_path': FLEET_SOURCE_PATHS['loader'],
        'loader_sha256': _sha(loader_raw),
    }


def _preserved(root: Path) -> dict[str, str | None]:
    result = {}
    for relative in PRESERVED_PATHS:
        path = root / relative
        if path.is_symlink():
            raise CandidateError('active workflow/pin path must not be a symlink')
        result[relative] = _sha(path.read_bytes()) if path.exists() else None
    return result


def _verify(key: str, record: dict[str, Any], owner_id: str, manifest: FleetManifest) -> tuple[Path, dict[str, Any]]:
    fields = {'root', 'expected_head', 'expected_branch', 'default_branch', 'ownership'}
    if not isinstance(record, dict) or set(record) != fields:
        raise CandidateError('root map row has unknown or missing fields')
    root = _path(record['root'])
    _settings(key, root, manifest)
    head = _full_sha(record['expected_head'])
    branch = record['expected_branch']
    if not isinstance(branch, str) or not branch or branch == record['default_branch'] or branch in {'main', 'master'}:
        raise CandidateError('candidate preparation requires an isolated feature branch')
    ownership = {'owner_id': owner_id, 'repository_key': key, 'root': str(root),
                 'head': head, 'branch': branch}
    if record['ownership'] != ownership:
        raise CandidateError('isolated checkout belongs to another or unverified owner')
    if _git(root, 'rev-parse', '--show-toplevel') != str(root):
        raise CandidateError('target is not the exact worktree root')
    if _git(root, 'rev-parse', 'HEAD') != head or _git(root, 'symbolic-ref', '--short', 'HEAD') != branch:
        raise CandidateError('target branch or HEAD changed')
    if _git(root, 'status', '--porcelain=v1', '--untracked-files=all'):
        raise CandidateError('target has staged, unstaged or untracked work')
    for marker in ('index.lock', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD',
                   'rebase-apply', 'rebase-merge', 'sequencer'):
        path = Path(_git(root, 'rev-parse', '--git-path', marker))
        if not path.is_absolute():
            path = root / path
        if path.exists() or path.is_symlink():
            raise CandidateError('target has an active Git operation or lock')
    destination = root / CANDIDATE_PATH
    for component in (destination, *destination.parents):
        if component == root:
            break
        if component.is_symlink():
            raise CandidateError('candidate destination traverses a symlink')
    # Includes ignored content: no proposal can overwrite a pre-existing path.
    if destination.exists() or destination.is_symlink():
        raise CandidateError('candidate destination already exists, including ignored evidence')
    paths = [str(CANDIDATE_PATH),
             *(str(CANDIDATE_PATH / p) for p in (*SOURCE_PATHS, 'proposal.json'))]
    ignored = Git(root, timeout=30).run('check-ignore', '--no-index', *paths, allowed=(0, 1))
    if ignored:
        raise CandidateError('candidate path is ignored and cannot be reviewed')
    owners = owner_snapshot(worktree_roots(Git(root, timeout=30)), {})
    return root, {'head': head, 'branch': branch, 'preserved': _preserved(root),
                  'owner_holders': owners['cwd_holders']}


def _proposal(key: str, source_commit: str, blobs: dict[str, bytes], before: dict[str, Any],
              fleet: FleetManifest, provenance: dict[str, str]) -> dict[str, Any]:
    return {
        'schema_version': '1.0.0', 'authority': 'proposal_only',
        'state': 'blocked_on_canonical_release', 'installed': False, 'adopted': False,
        'repository_key': key, 'github_repository': repository_identity(key, fleet),
        'canonical_source': {'repository': 'CultureBotAI/culturebotai-claw',
                             'reviewed_source_commit': source_commit, 'released': False,
                             'files': {SOURCE_PATHS[p]: _sha(raw) for p, raw in sorted(blobs.items())}},
        'fleet_provenance': provenance,
        'observed_base': {k: v for k, v in before.items() if k != 'owner_holders'},
        'activation_requirements': [
            'canonical merge and protected release proof', 'consumer review and merge',
            'approved immutable boundary adoption record',
            'verified cycle boundary with exact predecessor closure',
            'reviewed deployment for any live claw control checkout',
        ],
        'runtime_requirements': ['pre_goal_before_inventory', 'post_merge_before_closure',
                                 'no_change_goals', 'agy_and_codex_same_runner'],
    }


def prepare_batch(
    *, source_root: Path, source_commit: str, root_map: dict[str, Any],
    locks_dir: Path, owner_id: str, apply: bool = False, keys: list[str] | None = None,
) -> dict[str, Any]:
    """Dry-run every target, then transactionally stage inert candidate files.

    ``ownership`` is a trusted coordinator's explicit isolated-worktree
    declaration, not a scan for arbitrary OS processes. Never manufacture it
    for a live or other-owned checkout. Lock leases serialize cooperating edits.
    """
    fleet, provenance = _pinned_fleet(Path(source_root), source_commit)
    all_keys = [*fleet.keys, 'claw']
    selected = all_keys if keys is None else keys
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(all_keys):
        raise CandidateError('batch scope must use unique canonical manifest keys or claw')
    if not isinstance(root_map, dict) or set(root_map) != set(selected):
        raise CandidateError('root map must exactly cover the selected canonical scope')
    if not isinstance(owner_id, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', owner_id):
        raise CandidateError('explicit bounded owner ID is required')
    blobs = _source(Path(source_root), source_commit)
    manager = LockManager({'locks_dir': _path(str(locks_dir)), 'my_id': owner_id})
    plans = []
    for key in selected:
        with manager.lock(key, 'prepare_freshness_candidate'):
            root, before = _verify(key, root_map[key], owner_id, fleet)
            desired = dict(blobs)
            label = 'CLAW' if key == 'claw' else fleet.get(key).display_name
            desired['SKILL.md'] = (desired['SKILL.md']
                                   .replace(b'{{ display_name }}', label.encode())
                                   .replace(b'{{ github }}', repository_identity(key, fleet).encode()))
            desired['proposal.json'] = (json.dumps(_proposal(key, source_commit, blobs, before, fleet, provenance),
                                                  indent=2, sort_keys=True) + '\n').encode()
            plans.append((key, root, before, desired))
    results: list[dict[str, Any]] = []
    for key, root, before, desired in plans:
        try:
            with manager.lock(key, 'prepare_freshness_candidate'):
                if _verify(key, root_map[key], owner_id, fleet)[1] != before:
                    raise CandidateError('target changed after batch preflight')
                def validate(path: Path, content: str) -> None:
                    relative = path.relative_to(root / CANDIDATE_PATH).as_posix()
                    if relative not in desired or content.encode() != desired[relative]:
                        raise CandidateError('candidate staged content differs from canonical plan')
                    if relative == 'proposal.json':
                        proposal = json.loads(content)
                        if (proposal['authority'] != 'proposal_only'
                                or proposal['state'] != 'blocked_on_canonical_release'
                                or proposal['installed'] is not False
                                or proposal['adopted'] is not False):
                            raise CandidateError('candidate cannot acquire execution authority')
                transaction = ValidatedWriteTransaction(root, validator=validate)
                for path, raw in desired.items():
                    transaction.stage(CANDIDATE_PATH / path, raw.decode())
                transaction.commit(apply=False)
                if apply:
                    if _verify(key, root_map[key], owner_id, fleet)[1] != before:
                        raise CandidateError('target changed immediately before mutation')
                    transaction.commit(apply=True)
                    if _preserved(root) != before['preserved'] or _git(root, 'rev-parse', 'HEAD') != before['head']:
                        raise CandidateError('active workflow/pins or HEAD changed during preparation')
                    for path, raw in desired.items():
                        if (root / CANDIDATE_PATH / path).read_bytes() != raw:
                            raise CandidateError('candidate readback differs')
                results.append({'repository_key': key, 'github_repository': repository_identity(key, fleet),
                                'status': 'prepared' if apply else 'would_prepare',
                                'head': before['head'], 'candidate_path': str(CANDIDATE_PATH),
                                'files': {p: _sha(b) for p, b in sorted(desired.items())},
                                'installed': False, 'adopted': False})
        except Exception as exc:
            raise CandidateError(f'{key}: {exc}; prior results={json.dumps(results)}') from exc
    return {'schema_version': '1.0.0', 'canonical_source_commit': source_commit,
            'fleet_manifest_sha256': provenance['manifest_sha256'],
            'fleet_loader_sha256': provenance['loader_sha256'], 'fleet_provenance': provenance,
            'canonical_denominator': len(all_keys), 'selected': len(selected),
            'apply': apply, 'results': results}


def _unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise CandidateError('duplicate root-map JSON key')
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--root-map', type=Path, required=True)
    parser.add_argument('--locks-dir', type=Path, required=True)
    parser.add_argument('--owner-id', required=True)
    parser.add_argument('--repository', action='append')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = prepare_batch(source_root=args.source_root, source_commit=args.source_commit,
                               root_map=json.loads(args.root_map.read_text(), object_pairs_hook=_unique_pairs),
                               locks_dir=args.locks_dir,
                               owner_id=args.owner_id, apply=args.apply, keys=args.repository)
        print(json.dumps(result, indent=2))
        return 0
    except (CandidateError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
