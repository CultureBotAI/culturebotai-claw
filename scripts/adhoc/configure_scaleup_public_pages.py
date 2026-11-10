"""Set the user-authorized Scaleup repository visibility and native Pages mode.

Inputs: canonical fleet, gh authentication; default is read-only plan, --apply
changes only remote repository settings. Outputs: before/after JSON receipts.
Serves CLAW PR #1146 and the explicit settings request, 2026-11-10.
No checkout, corpus, branch, workflow or suite-exclusion tag is changed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from plugins.lock_manager import LockManager


def gh(*args: str):
    result = subprocess.run(['gh', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def state(repository: str):
    repo = gh('api', f'repos/{repository}')
    if repo['full_name'] != repository:
        raise RuntimeError('Remote identity differs from canonical fleet')
    pages = gh('api', f'repos/{repository}/pages') if repo['has_pages'] else None
    return {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'repository': repository, 'visibility': repo['visibility'],
        'has_pages': repo['has_pages'],
        'pages': {key: pages.get(key) for key in ('html_url', 'build_type', 'source', 'status', 'public')}
        if pages else None,
    }


def receipt(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(pending, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--receipts', required=True, type=Path)
    args = parser.parse_args()
    member = load_fleet_manifest().get('scaleupmech')
    if member.github != 'CultureBotAI/ScaleupMech' or member.is_public:
        raise RuntimeError('Expected identity and suite-exclusion policy required')
    with LockManager().lock(member.key, 'configure_public_repository_and_native_pages'):
        before = state(member.github)
        plan = {'before': before, 'requested_visibility': 'public',
                'requested_pages_build_type': 'workflow', 'apply': args.apply}
        print(json.dumps(plan, indent=2))
        if not args.apply:
            return
        if args.receipts.exists():
            raise RuntimeError('Use a fresh receipt directory; never overwrite before-state evidence')
        receipt(args.receipts / 'before.json', before)
        if before['visibility'] != 'public':
            gh('api', '--method', 'PATCH', f'repos/{member.github}', '-f', 'visibility=public')
        visible = state(member.github)
        receipt(args.receipts / 'visibility.json', visible)
        if visible['visibility'] != 'public':
            raise RuntimeError('Visibility did not persist')
        if not visible['has_pages']:
            gh('api', '--method', 'POST', f'repos/{member.github}/pages', '-f', 'build_type=workflow')
        elif visible['pages']['build_type'] != 'workflow':
            gh('api', '--method', 'PUT', f'repos/{member.github}/pages', '-f', 'build_type=workflow')
        after = state(member.github)
        receipt(args.receipts / 'after.json', after)
        if not (after['visibility'] == 'public' and after['has_pages']
                and after['pages']['build_type'] == 'workflow'):
            raise RuntimeError('Requested settings did not persist')
        print(json.dumps(after, indent=2))


if __name__ == '__main__':
    main()
