"""Replay CommunityMech supersession evidence without changing repositories.

Purpose: authorized fleet-ops 20261126T0620Z source-preservation review.
Inputs: exact prior review, newly acquired PR JSON, explicitly resolved clone.
Outputs: exclusive JSON and per-child source diffs in a durable stewardship path.
Created 2026-11-26 before use. No GitHub mutation or scientific verdict is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from plugins.repository_settings import RepositorySettings, merged_repository_environment


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(root), *args])


def tree(root: Path, revision: str) -> dict[str, str]:
    rows = git(root, 'ls-tree', '-r', '-z', revision).split(b'\0')
    return {row.split(b'\t', 1)[1].decode(): row.split(b'\t', 1)[0].decode()
            for row in rows if row}


def save(path: Path, raw: bytes) -> None:
    with path.open('xb') as handle:
        handle.write(raw)
    if path.read_bytes() != raw:
        raise ValueError('readback mismatch')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dotenv', type=Path, required=True)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.is_absolute() or args.output.exists():
        raise ValueError('output must be a new absolute durable directory')
    if any(p in ('tmp', 'private') for p in args.output.parts[:3]):
        raise ValueError('system temporary paths forbidden')
    for p in (args.output, *args.output.parents):
        if p.is_symlink():
            raise ValueError('symlink output component')
    env = dict(merged_repository_environment(args.dotenv))
    env['COMMUNITYMECH_ROOT'] = str(args.checkout)
    target = RepositorySettings.from_environment(environ=env).get_target('communitymech')
    root = target.path
    status = git(root, 'status', '--porcelain').decode()
    prior_raw = args.prior.read_bytes()
    prior = json.loads(prior_raw)
    parent = json.loads((args.baseline / 'pr-2804-baseline.json').read_bytes())
    if parent['state'] != 'OPEN':
        raise ValueError('parent no longer open')
    checks = parent['statusCheckRollup']
    if not checks or any(c.get('status') != 'COMPLETED' or c.get('conclusion') not in ('SUCCESS', 'SKIPPED') for c in checks):
        raise ValueError('parent checks incomplete or failing')
    required = {'history', 'Audit Network Integrity', 'docs-current', 'label-correspondence / label-correspondence', 'lint', 'validate-strict', 'vendored-sync'}
    if {c['name'] for c in checks if c['conclusion'] == 'SUCCESS'} != required:
        raise ValueError('required parent checks are not all successful')
    current = parent['headRefOid']
    subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', prior['parent'], current], check=True)
    previous_tree, current_tree = tree(root, prior['parent']), tree(root, current)
    repair_paths = set(git(root, 'diff', '--name-only', prior['parent'], current).decode().splitlines())
    rows = []
    diffs = {}
    for child in prior['children']:
        live = json.loads((args.baseline / f"pr-{child['number']}-baseline.json").read_bytes())
        if live['state'] != 'OPEN' or live['headRefOid'] != child['head']:
            raise ValueError(f"child {child['number']} changed state or head")
        # A stacked base may have advanced independently; only the child's
        # merge-base delta is its contribution, never reversed base-only work.
        paths = git(root, 'diff', '--name-only', child['base'] + '...' + child['head']).decode().splitlines()
        child_tree = tree(root, child['head'])
        old_different = [p for p in paths if child_tree.get(p) != previous_tree.get(p)]
        if len(paths) != child['changed_paths'] or set(old_different) != set(child['extended_paths']):
            raise ValueError(f"prior preservation result no longer reproduces for {child['number']}")
        different = [p for p in paths if child_tree.get(p) != current_tree.get(p)]
        if not set(different).issubset(set(old_different) | repair_paths):
            raise ValueError('unreviewed change outside prior additive differences and parent repair')
        if any(child_tree.get(p) and not current_tree.get(p) for p in paths):
            raise ValueError('child contribution path missing from parent')
        raw = git(root, 'diff', child['head'], current, '--', *different) if different else b''
        diffs[child['number']] = raw
        rows.append({**child, 'current_parent': current, 'current_identical_paths': len(paths)-len(different),
                     'current_different_paths': different, 'live_head_unchanged': True,
                     'current_diff_sha256': hashlib.sha256(raw).hexdigest(),
                     'disposition': 'eligible for individually reasoned supersession closure; source branches retained'})
    result = {'acquired_at_utc': datetime.now(timezone.utc).isoformat(),
              'repository': target.expected_repository, 'clone': str(root), 'clone_status': status,
              'prior_review_sha256': hashlib.sha256(prior_raw).hexdigest(),
              'prior_review_parent': prior['parent'], 'current_parent': current,
              'parent_checks': checks, 'parent_repair_paths': sorted(repair_paths), 'children': rows,
              'limits': 'Blob inclusion replay plus prior additive-difference review; not new scientific adjudication or merge approval.'}
    args.output.mkdir(parents=True, exist_ok=False)
    for number, raw in diffs.items():
        save(args.output / f'child-{number}-current.diff', raw)
    save(args.output / 'replay.json', (json.dumps(result, indent=2)+'\n').encode())
    print(json.dumps({'parent': current, 'children_replayed': len(rows), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
