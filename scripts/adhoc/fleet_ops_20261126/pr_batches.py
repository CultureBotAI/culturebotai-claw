"""Acquire exact PR changed-file evidence and form bounded review work packets.

Uses the existing captured PR intake; this is not a second issue inventory.
Groups describe the actual changed artifact kinds, not approval or shared defects.
"""
import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def gh(*args):
    proc = subprocess.run(['gh', *args], text=True, capture_output=True, check=True)
    return json.loads(proc.stdout)


def refuse_existing(paths):
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'evidence output already exists: {path}')


def write_new(path, text):
    with path.open('x') as handle:
        handle.write(text)


def capture(pr, repo, root):
    number = pr['number']
    output = root / f'pr-files-{number}.json'
    refuse_existing([output])
    pages = gh('api', '--paginate', '--slurp', f'repos/{repo}/pulls/{number}/files?per_page=100')
    files = [item for page in pages for item in page]
    current = gh('api', f'repos/{repo}/pulls/{number}')
    receipt = {'number': number, 'expected_head': pr['head']['sha'],
               'observed_head': current['head']['sha'], 'state': current['state'],
               'changed_files': current['changed_files'], 'files': files,
               'checked_utc': datetime.now(timezone.utc).isoformat()}
    receipt['complete_stable'] = (receipt['expected_head'] == receipt['observed_head']
                                  and receipt['state'] == 'open'
                                  and len(files) == receipt['changed_files']
                                  and len({f['filename'] for f in files}) == len(files))
    write_new(output, json.dumps(receipt, indent=2) + '\n')
    return receipt


def theme(paths):
    if paths and all(p.startswith('workflow/candidates/') for p in paths):
        return 'inert-canonical-candidates'
    if paths and all(p.startswith(('reviews/', 'review/')) for p in paths):
        return 'immutable-review-artifacts'
    if any(p.startswith(('data/', 'curation/')) and p.endswith(('.yaml', '.yml', '.tsv', '.csv', '.jsonl')) for p in paths):
        return 'scientific-input-and-record-changes'
    if any(p.startswith(('src/', 'scripts/', 'tests/', '.github/')) or p in ('pyproject.toml', 'uv.lock', 'justfile') for p in paths):
        return 'implementation-and-validation'
    return 'evidence-documents-and-other-artifacts'


GATES = {
    'inert-canonical-candidates': 'Verify inert bytes and unchanged active pins; wait for canonical release and separately approved adoption. No installation.',
    'immutable-review-artifacts': 'Verify immutable YAML/Markdown pairs, source-head/input hashes, append-only lineage, original versus fresh checks, and unresolved scientific findings. No record promotion.',
    'scientific-input-and-record-changes': 'Review primary-source claims and identity/quantity boundaries; verify documented writer/seeder, histories, reproduction, generated output, and final-head checks. Shared record paths serialize.',
    'implementation-and-validation': 'Review behavior and regression/mutation tests; identify governed owners before edits; check generated effects and current main/PR CI. Serialize shared code and outputs.',
    'evidence-documents-and-other-artifacts': 'Read evidence lineage, source access and outstanding acceptance criteria; verify reports against retained sources and preserve uncertainty. Documents alone do not close scientific issues.',
    'unverified-acquisition': 'Resolve missing file coverage, changed head or API failure before assigning substantive review.',
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    root = args.directory
    repo = json.loads((root / 'counts.json').read_text())['data']['repository']['nameWithOwner']
    prs = json.loads((root / 'prs.json').read_text())
    refuse_existing([root / 'review-batches.json', root / 'review-batches.md',
                     *(root / f"pr-files-{pr['number']}.json" for pr in prs)])
    rows = []
    failures = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [(pr, pool.submit(capture, pr, repo, root)) for pr in prs]
        for pr, future in tasks:
            try:
                receipt = future.result()
                paths = [f['filename'] for f in receipt['files']]
                category = theme(paths) if receipt['complete_stable'] else 'unverified-acquisition'
                error = None
            except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
                category, paths, error = 'unverified-acquisition', [], str(exc)
                failures.append({'number': pr['number'], 'error': error})
            rows.append({'number': pr['number'], 'url': pr['html_url'], 'head': pr['head']['sha'],
                         'title': pr['title'], 'theme': category, 'paths': paths, 'error': error,
                         'review_status': 'queued; no approval or scientific completion claimed'})
    packets = []
    for category in sorted({row['theme'] for row in rows}):
        members = sorted((r for r in rows if r['theme'] == category), key=lambda r: r['number'])
        for start in range(0, len(members), 10):
            batch = members[start:start + 10]
            packets.append({'id': f'{category}-{start // 10 + 1:02d}', 'theme': category,
                            'prs': [r['number'] for r in batch], 'owner': 'existing stewardship owner; resume proposed only',
                            'acceptance': GATES[category], 'parallelism': 'Read-only review may parallelize; overlapping file changes serialize.'})
    result = {'repository': repo, 'created_utc': datetime.now(timezone.utc).isoformat(),
              'source': 'prs.json plus per-PR paginated changed-file and final-head receipts',
              'new_prs_and_discovery': 'paused until open PR count below 25 and status checks pass',
              'coverage': {'prs': len(prs), 'stable_complete': sum(r['theme'] != 'unverified-acquisition' for r in rows),
                           'failures': failures}, 'packets': packets, 'prs': rows}
    write_new(root / 'review-batches.json', json.dumps(result, indent=2) + '\n')
    lines = ['# Bounded review queue', '',
             'Artifact themes come from complete changed-file lists with unchanged-head checks. This is a work queue, not completed scientific review or merge approval.', '',
             '| Packet | PRs | Acceptance |', '|---|---|---|']
    lines += [f"| {p['id']} | {', '.join('#' + str(n) for n in p['prs'])} | {p['acceptance']} |" for p in packets]
    write_new(root / 'review-batches.md', '\n'.join(lines) + '\n')
    print(json.dumps({'repository': repo, 'coverage': result['coverage'], 'packets': len(packets)}))
    return 1 if failures or any(r['theme'] == 'unverified-acquisition' for r in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
