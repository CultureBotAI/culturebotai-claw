"""Read-only proof for the declared freshness release; never publish or adopt.

The operator supplies the exact independently reviewed integration base/tree.
Fresh GitHub reads and immutable Git objects must agree with that boundary.
No future source SHA is embedded in the declaration that the SHA will contain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kg_microbe_governance.artifacts.scripts.auto_merge_ready_prs import (
    AdmissionError,
    GitHub,
    check_reason,
)

REPOSITORY = 'CultureBotAI/culturebotai-claw'
TAG = 'repository-freshness-v1.0.0'
DECLARATION = 'src/kg_microbe_governance/releases/' + TAG + '.json'
POLICY = {'schema_version': '1.0.0', 'id': 'repository-freshness', 'version': '1.0.0',
          'tag': TAG, 'repository': REPOSITORY, 'source_pr': 1128,
          'default_branch': 'main', 'source_rule': 'actual_protected_squash_merge',
          'adoption_authority': False}
# These source artifacts supplement the complete reviewed Git tree identity.
# Every executable dependency is also bound by that complete tree, not merely
# by this human-readable list of the feature's direct entry points.
PAYLOADS = (
    DECLARATION, 'src/kg_microbe_workflows/templates/repository-freshness-v1.yaml',
    'src/kg_microbe_workflows/schema/repository-freshness-v1.yaml',
    'src/kg_microbe_skills/canonical/repository-freshness.md',
    'src/kg_microbe_workflows/freshness.py', 'src/kg_microbe_workflows/freshness_cli.py',
    'src/kg_microbe_workflows/freshness_contract.py',
    'src/kg_microbe_governance/freshness_candidates.py',
    'src/kg_microbe_workflows/freshness_release.py',
    'scripts/mech_session_supervisor.py', 'scripts/fleet_pull.py',
    'plugins/lock_manager.py', 'plugins/repository_settings.py',
    'src/kg_microbe_fleet/fleet.yaml', 'src/kg_microbe_fleet/__init__.py',
    'pyproject.toml', 'uv.lock', 'docs/guides/REPOSITORY_FRESHNESS_RELEASE.md',
)


class ReleaseError(ValueError):
    """Insufficient or contradictory release evidence; hold publication."""


def _oid(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ReleaseError('complete immutable Git SHA required')
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ReleaseError('duplicate declaration key')
        result[key] = value
    return result


def encoded(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


class Git:
    """Read existing objects only, with no hooks, replacement or lazy fetch."""
    def __init__(self, root: Path):
        self.root = root
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_GRAFT_FILE=os.devnull,
                        GIT_TERMINAL_PROMPT='0', LC_ALL='C')
        origin = self.text('remote', 'get-url', 'origin')
        if origin not in {f'https://github.com/{REPOSITORY}.git', f'https://github.com/{REPOSITORY}',
                          f'git@github.com:{REPOSITORY}.git'}:
            raise ReleaseError('audit object store origin differs')

    def raw(self, *args: str) -> bytes:
        try:
            result = subprocess.run(['git', '-c', f'core.hooksPath={os.devnull}',
                                     '-c', 'gc.auto=0', '-C', str(self.root), *args],
                                    env=self.env, capture_output=True, check=True, timeout=90)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError('required local Git object unavailable') from exc
        if len(result.stdout) > 16_000_000:
            raise ReleaseError('Git observation exceeds audit bound')
        return result.stdout

    def text(self, *args: str) -> str:
        return self.raw(*args).decode().strip()

    def blob(self, commit: str, path: str) -> tuple[str, bytes]:
        row = self.raw('ls-tree', '-z', commit, '--', path)
        prefix, separator, named = row.partition(b'\t')
        fields = prefix.split()
        if (not separator or named != path.encode() + b'\0' or len(fields) != 3
                or fields[0] not in {b'100644', b'100755'} or fields[1] != b'blob'):
            raise ReleaseError('release payload missing or unsafe mode: ' + path)
        return fields[0].decode(), self.raw('cat-file', 'blob', fields[2].decode())


def audit_source(root: Path, *, reviewed_head: str, merge_commit: str,
                 reviewed_base: str, reviewed_tree: str, api=None) -> dict[str, Any]:
    """Bind the actual merged source to exact-head and integration review evidence.

    This is not an independent review: the supplied reviewed digests must come
    from that review. GitHub and local object contradictions fail closed.
    """
    head, merge, base, tree = map(_oid, (reviewed_head, merge_commit, reviewed_base, reviewed_tree))
    api = api or GitHub(REPOSITORY)
    git = Git(root)
    pr = api.pr(1128)
    if (pr.get('number') != 1128 or pr.get('state') != 'closed' or pr.get('merged') is not True
            or not pr.get('merged_at') or pr.get('merge_commit_sha') != merge
            or pr.get('head', {}).get('sha') != head
            or pr.get('head', {}).get('repo', {}).get('full_name') != REPOSITORY
            or pr.get('base', {}).get('ref') != 'main'
            or pr.get('base', {}).get('repo', {}).get('full_name') != REPOSITORY):
        raise ReleaseError('actual merged PR identity differs from reviewed source')
    rules = api.rules()  # Existing reader requires active main merge-queue protection.
    if not rules.checks:
        raise ReleaseError('protected main required checks absent')
    runs, statuses = api.checks(head)
    if check_reason(runs, statuses, rules, head):
        raise ReleaseError('reviewed head required checks not successful')
    main = _oid(api.get(f'repos/{REPOSITORY}/commits/main')['sha'])
    if api.integrity_reason():
        raise ReleaseError('protected main integrity not verified')
    if merge not in git.text('rev-list', '--first-parent', '--max-count=10000', main).splitlines():
        raise ReleaseError('actual merge absent from observed main first-parent history')
    if git.text('rev-list', '--parents', '-n', '1', merge).split() != [merge, base]:
        raise ReleaseError('actual squash parent differs from reviewed integration base')
    if git.text('rev-parse', merge + '^{tree}') != tree:
        raise ReleaseError('actual merged tree differs from reviewed integration tree')
    mode, declaration = git.blob(merge, DECLARATION)
    if mode != '100644' or len(declaration) > 65536:
        raise ReleaseError('declaration mode or size differs')
    policy = json.loads(declaration, object_pairs_hook=_pairs)
    # bool is not accepted in place of the source PR integer.
    if (not isinstance(policy, dict) or policy != POLICY
            or type(policy.get('source_pr')) is not int or policy.get('adoption_authority') is not False):
        raise ReleaseError('release declaration differs from the declared feature')
    if git.blob(head, DECLARATION) != (mode, declaration):
        raise ReleaseError('declaration was not present at the reviewed PR head')
    if git.raw('ls-tree', '-z', base, '--', DECLARATION):
        raise ReleaseError('release declaration already existed before this merge')
    if git.text('log', '-1', '--format=%H', base, '--', DECLARATION):
        raise ReleaseError('release declaration was deleted and reintroduced')
    payloads = {}
    for path in PAYLOADS:
        mode, raw = git.blob(merge, path)
        payloads[path] = {'mode': mode, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    if api.rules() != rules or api.get(f'repos/{REPOSITORY}/commits/main')['sha'] != main:
        raise ReleaseError('remote protection or main changed during source audit; re-observe')
    again = api.pr(1128)
    if any(again.get(key) != pr.get(key) for key in ('head', 'merge_commit_sha', 'merged', 'merged_at', 'state')):
        raise ReleaseError('PR identity changed during source audit')
    return {'schema_version': '1.0.0', 'kind': 'verified_freshness_release_source',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'declaration': policy,
            'reviewed_head': head, 'reviewed_base': base, 'source_commit': merge,
            'source_tree': tree, 'observed_main': main, 'merged_at': pr['merged_at'],
            'required_checks': [{'name': name, 'app_id': app} for name, app in rules.checks],
            'payloads': payloads, 'installed': False, 'adopted': False,
            'tag_protection_claimed': False, 'release_immutability_claimed': False}


def verify_publication(audit: dict[str, Any], api=None) -> dict[str, Any]:
    """Re-read the exact tag and audit asset digest; this never creates a release."""
    if audit.get('kind') != 'verified_freshness_release_source' or audit.get('declaration') != POLICY:
        raise ReleaseError('not a source audit for this declared feature')
    merge = _oid(audit['source_commit'])
    api = api or GitHub(REPOSITORY)
    ref = api.get(f'repos/{REPOSITORY}/git/ref/tags/{TAG}')
    obj = ref['object']
    for _ in range(4):
        if obj.get('type') == 'commit':
            break
        if obj.get('type') != 'tag':
            raise ReleaseError('unexpected release tag object type')
        obj = api.get(f'repos/{REPOSITORY}/git/tags/{_oid(obj["sha"])}')['object']
    if obj.get('type') != 'commit' or obj.get('sha') != merge:
        raise ReleaseError('release tag does not resolve to the audited source')
    release = api.get(f'repos/{REPOSITORY}/releases/tags/{TAG}')
    if (release.get('tag_name') != TAG or release.get('draft') is not False
            or not release.get('published_at') or release.get('target_commitish') != merge):
        raise ReleaseError('published release metadata differs')
    assets = api.pages(f'repos/{REPOSITORY}/releases/{release["id"]}/assets')
    matches = [row for row in assets if row.get('name') == 'release-audit.json']
    expected = encoded(audit)
    if (len(matches) != 1 or matches[0].get('size') != len(expected)
            or matches[0].get('digest') != 'sha256:' + hashlib.sha256(expected).hexdigest()):
        raise ReleaseError('published source audit asset differs')
    if api.get(f'repos/{REPOSITORY}/git/ref/tags/{TAG}') != ref:
        raise ReleaseError('tag changed during publication readback')
    return {'status': 'verified', 'tag': TAG, 'source_commit': merge,
            'url': release['html_url'], 'audit_sha256': hashlib.sha256(expected).hexdigest(),
            'release_immutable_observed': release.get('immutable'),
            'installed': False, 'adopted': False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reviewed-head', required=True)
    parser.add_argument('--merge-commit', required=True)
    parser.add_argument('--reviewed-base', required=True)
    parser.add_argument('--reviewed-tree', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ReleaseError('audit output already exists')
        value = audit_source(args.root, reviewed_head=args.reviewed_head, merge_commit=args.merge_commit,
                             reviewed_base=args.reviewed_base, reviewed_tree=args.reviewed_tree)
        with args.output.open('xb') as stream:
            stream.write(encoded(value))
        print(json.dumps({'status': 'verified', 'source_commit': value['source_commit'], 'tag': TAG}))
        return 0
    except (ReleaseError, AdmissionError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'hold', 'reason': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
