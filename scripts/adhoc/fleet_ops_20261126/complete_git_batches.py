"""Supplement a capped PR-file API acquisition using exact Git objects.

The original API receipts and incomplete work queue are preserved unchanged.
Writes separately named supplementary receipts and a completed work queue.
"""
import argparse
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .pr_batches import GATES, gh, theme
else:
    from pr_batches import GATES, gh, theme


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def git_paths(root, merge_base, head):
    raw = subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', '-z', merge_base, head])
    if raw and not raw.endswith(b'\0'):
        raise ValueError('Git path list lacks its NUL terminator')
    return [os.fsdecode(path) for path in raw.split(b'\0')[:-1]]


def exclusive(path, value):
    with path.open('x') as handle:
        handle.write(json.dumps(value, indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('git_evidence', type=Path)
    args = parser.parse_args(argv)
    root = args.directory
    result = json.loads((root / 'review-batches.json').read_text())
    repo = result['repository']
    if git(args.git_evidence, 'remote', 'get-url', 'origin') != f'https://github.com/{repo}.git':
        raise ValueError('unexpected Git evidence repository origin')
    initial = {p['number']: p for p in json.loads((root / 'prs.json').read_text())}
    for row in result['prs']:
        if row['theme'] != 'unverified-acquisition':
            continue
        number = row['number']
        current = gh('api', f'repos/{repo}/pulls/{number}')
        old = initial[number]
        if current['head']['sha'] != row['head'] or current['state'] != 'open':
            raise ValueError('PR head or state changed')
        base = current['base']['sha']
        if base != old['base']['sha']:
            raise ValueError('PR base changed; acquire a new snapshot')
        merge_base = git(args.git_evidence, 'merge-base', base, row['head'])
        paths = git_paths(args.git_evidence, merge_base, row['head'])
        if len(paths) != current['changed_files'] or len(paths) != len(set(paths)):
            raise ValueError('Git/API changed-file counts disagree')
        receipt = {'repository': repo, 'number': number, 'base': base, 'head': row['head'],
                   'merge_base': merge_base, 'changed_files': len(paths), 'paths': paths,
                   'checked_utc': datetime.now(timezone.utc).isoformat(),
                   'method': 'owned bare clone; exact merge-base to head NUL-delimited Git tree diff',
                   'original_api_receipt': f'pr-files-{number}.json'}
        exclusive(root / f'pr-files-{number}-git-supplement.json', receipt)
        row['paths'] = paths
        row['theme'] = theme(paths)
        row['supplement'] = f'pr-files-{number}-git-supplement.json'
    result['coverage']['stable_complete'] = sum(r['theme'] != 'unverified-acquisition' for r in result['prs'])
    result['supplement_created_utc'] = datetime.now(timezone.utc).isoformat()
    result['packets'] = []
    for category in sorted({r['theme'] for r in result['prs']}):
        members = sorted((r for r in result['prs'] if r['theme'] == category), key=lambda r: r['number'])
        for start in range(0, len(members), 10):
            result['packets'].append({'id': f'{category}-{start // 10 + 1:02d}', 'theme': category,
                                     'prs': [r['number'] for r in members[start:start + 10]],
                                     'owner': 'existing stewardship owner; resume proposed only',
                                     'acceptance': GATES[category],
                                     'parallelism': 'Read-only review may parallelize; overlapping file changes serialize.'})
    exclusive(root / 'review-batches-git-complete.json', result)
    lines = ['# Complete review queue (Git supplement)', '',
             'The original API-limited queue and receipts remain unchanged. No scientific or merge approval is inferred.', '',
             '| Packet | PRs | Acceptance |', '|---|---|---|']
    lines += [f"| {p['id']} | {', '.join('#' + str(n) for n in p['prs'])} | {p['acceptance']} |" for p in result['packets']]
    with (root / 'review-batches-git-complete.md').open('x') as handle:
        handle.write('\n'.join(lines) + '\n')
    print(json.dumps({'coverage': result['coverage'], 'themes': Counter(r['theme'] for r in result['prs'])}))


if __name__ == '__main__':
    main()
