"""Preserve an exact closed PR head in a new steward ref without overwriting.

Purpose: fleet-ops 20261126T0620Z retained-source requirement after an automated
branch disappears on closure. Created 2026-11-26 before use.
Inputs: validated Mech identity, numeric closed PR, exact head, new steward ref.
Output: JSON receipt on stdout; --apply creates one remote ref, never a PR.
Default is a read-only preflight. No credentials, prompts, merges or force push.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositorySettings, merged_repository_environment


def gh(*arguments: str) -> dict:
    return json.loads(subprocess.check_output(['gh', *arguments], text=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dotenv', required=True, type=Path)
    parser.add_argument('--mech', required=True)
    parser.add_argument('--pr', required=True, type=int)
    parser.add_argument('--head', required=True)
    parser.add_argument('--ref', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    expected_ref = f'refs/heads/steward/fleet-ops-20261126T0620Z-pr{args.pr}-retained'
    if args.pr < 1 or not re.fullmatch(r'[0-9a-f]{40}', args.head) or args.ref != expected_ref:
        parser.error('positive PR, exact SHA and canonical new steward ref required')
    target = RepositorySettings.from_environment(
        environ=merged_repository_environment(args.dotenv)
    ).get_target(args.mech)
    target.open()
    repository = target.expected_repository
    with LockManager().lock(args.mech, 'fleet_ops_20261126_preserve_closed_source'):
        target.open()
        status = subprocess.check_output(
            ['git', '-C', str(target.path), 'status', '--porcelain'], text=True
        )
        branch = subprocess.check_output(
            ['git', '-C', str(target.path), 'branch', '--show-current'], text=True
        ).strip()
        pr = gh('pr', 'view', str(args.pr), '--repo', repository,
                '--json', 'state,mergedAt,headRefOid,headRefName,number')
        if pr['state'] != 'CLOSED' or pr['mergedAt'] is not None or pr['headRefOid'] != args.head:
            raise ValueError('PR must remain closed, unmerged and at the exact retained head')
        endpoint = f'repos/{repository}/git/ref/{args.ref.removeprefix("refs/")}'
        probe = subprocess.run(['gh', 'api', endpoint], text=True, capture_output=True, check=False)
        if probe.returncode == 0:
            raise ValueError('destination already exists; never overwrite or repeat creation')
        if 'HTTP 404' not in probe.stderr or json.loads(probe.stdout).get('message') != 'Not Found':
            raise RuntimeError('destination absence not verified')
        commit = gh('api', f'repos/{repository}/git/commits/{args.head}')
        if commit['sha'] != args.head:
            raise ValueError('source commit readback mismatch')
        if args.apply:
            created = gh('api', '--method', 'POST', f'repos/{repository}/git/refs',
                         '-f', f'ref={args.ref}', '-f', f'sha={args.head}')
            if created['ref'] != args.ref or created['object']['sha'] != args.head:
                raise ValueError('creation readback mismatch; inspect and preserve')
            readback = gh('api', endpoint)
            if readback['ref'] != args.ref or readback['object']['sha'] != args.head:
                raise ValueError('remote verification mismatch; inspect and preserve')
        print(json.dumps({'time_utc': datetime.now(timezone.utc).isoformat(),
                          'repository': repository, 'pr': args.pr, 'head': args.head,
                          'ref': args.ref, 'applied': args.apply,
                          'local_branch': branch, 'local_status': status,
                          'remote_exact_head_verified': bool(args.apply)}, indent=2))


if __name__ == '__main__':
    main()
