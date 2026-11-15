"""Independent read-only verification of the four owned PR1112 retirements.

2026-11-15. Inputs: explicit task root and recorded current root-head advance
chain. Output: JSON stdout; --private adds local registrations/recovery paths.
Uses the exact retained canary hashing/Git reader. All preserved descendants,
source recovery objects and staged-snapshot backup bytes are read back. No Git,
GitHub, runtime, restoration or cleanup mutation; no generic apply capability.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

LABELS = ('review-1112-final', 'review-1112-original', 'repair-1112', 'review-1112-integration')
SOURCE = '3da76c840590b8f579535aacd853b65ebf4f0009'
MERGE = 'bd2b07480afd3b3984491a7fc729c64220d4dd81'
MERGE_TREE = 'fbc3e1cd1b4a2290fca56d93be78e87a6a96a9b7'
PLAN = 'e85417c9e7ddc907ab40453df3c941f1d22d2ee747d13abd0fa849c875976400'
MODULE_PIN = 'ac422830ec1719f2acdc6a1a9be52a8428277dc0b8112656bf826856d7bed348'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--root-advance', action='append', required=True)
    parser.add_argument('--private', action='store_true')
    args = parser.parse_args()
    task = args.task_root
    require(task.is_absolute() and task == task.resolve(), 'Canonical explicit task required')
    module_path = Path(__file__).parents[1] / 'cleanup-canary/verify_cleanup_canary.py'
    require(sha(module_path.read_bytes()) == MODULE_PIN, 'Retained reader changed')
    spec = importlib.util.spec_from_file_location('canary_reader', module_path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    quarantine = task / 'cleanup/quarantine-20261115-after-merge'
    all_before, completed, raws = {}, {}, {}
    for label in LABELS:
        q = quarantine / label
        raw = {name: reader.regular(q / name) for name in ('before.json', 'preserved.json', 'completed.json', 'recovery.json')}
        raw['proof'] = reader.regular(task / 'cleanup/operator-proofs' / (label + '.json'))
        raw['apply'] = reader.regular(task / 'cleanup/operator-proofs' / (label + '-apply.json'))
        raw['dry_run'] = reader.regular(task / 'cleanup/operator-proofs' / (label + '-dry-run.json'))
        all_before[label] = json.loads(raw['before.json'])
        completed[label] = json.loads(raw['completed.json'])
        raws[label] = raw
    removed_by_common = {}
    for label, before in all_before.items():
        removed_by_common.setdefault(before['proof']['common_git'], set()).add(completed[label]['worktree'])
    current_by_common = {common: reader.registrations(Path(common)) for common in removed_by_common}
    root_advances = []
    rows, private_rows = [], []
    live = reader.api('repos/CultureBotAI/culturebotai-claw/pulls/1112')
    require(live['merged'] is True and live['state'] == 'closed' and live['base']['ref'] == 'main', 'PR1112 not merged')
    require(live['head']['sha'] == SOURCE and live['merge_commit_sha'] == MERGE, 'Published source/merge differs')
    remote_refs = reader.api('repos/CultureBotAI/culturebotai-claw/git/matching-refs/heads/' + live['head']['ref'])
    require(not any(row['ref'] == 'refs/heads/' + live['head']['ref'] for row in remote_refs), 'Remote source branch reappeared')
    for label in LABELS:
        before, done, raw = all_before[label], completed[label], raws[label]
        proof = json.loads(raw['proof'])
        common = Path(proof['common_git'])
        recovery = json.loads(raw['recovery.json'])
        expected = json.loads(raw['preserved.json'])
        require(before['proof'] == proof and before['proof_sha256'] == sha(raw['proof']), 'Proof binding differs')
        require(proof['owner_complete'] is True and proof['readers_clear'] is True, 'Missing completion/reader attestations')
        require(done['mode'] == 'applied' and done['head'] == proof['expected_head'] == recovery['head'], 'Completion/head differs')
        require(done == json.loads(raw['apply']), 'Apply/completion differs')
        dry = json.loads(raw['dry_run'])
        require(dry['actions_performed'] == 0 and dry['manifest_sha256'] == done['manifest_sha256'], 'Dry run differs')
        require(done['manifest_sha256'] == sha(raw['preserved.json']), 'Preserved manifest digest differs')
        require({p: {k: v for k, v in row.items() if k != 'fingerprint'} for p, row in before['preserved'].items()} == expected, 'Original preserved content differs')
        observed = reader.walk(quarantine / label / 'preserved')
        containers = {str(parent) for path in done['preservation_roots'] for parent in Path(path).parents if str(parent) != '.'}
        for path in containers - set(expected):
            require(observed[path]['kind'] == 'directory', 'Unexpected containing node')
            del observed[path]
        require(observed == expected and len(observed) == done['preservation_entries'], 'Preserved complete bytes/modes/targets differ')
        require(not os.path.lexists(done['worktree']) and not os.path.lexists(before['gitdir']), 'Target worktree or Git registration remains')
        require(done['recovery_ref'] == recovery['ref'] and reader.git(common, 'rev-parse', recovery['ref']).decode().strip() == done['head'], 'Recovery ref differs')
        reader.git(common, 'merge-base', '--is-ancestor', done['head'], SOURCE)
        require(reader.git(common, 'rev-parse', MERGE + '^{tree}').decode().strip() == MERGE_TREE, 'Published merge tree differs')
        tree = {}
        for row in reader.git(common, 'ls-tree', '-r', '-z', done['head']).split(b'\0'):
            if row:
                metadata, path = row.split(b'\t', 1)
                mode, kind, oid = metadata.decode().split()
                tree[path.decode()] = (mode, kind, oid)
        require(set(tree) == set(before['tracked']), 'Source tracked inventory differs')
        for path, (mode, kind, oid) in tree.items():
            entry = before['entries'][path]
            require(kind == 'blob', 'Unexpected submodule')
            if entry['kind'] == 'symlink':
                target = entry['target'].encode()
                blob = hashlib.sha1(b'blob ' + str(len(target)).encode() + b'\0' + target).hexdigest()
                require(mode == '120000', 'Symlink Git mode differs')
            else:
                blob = entry['git_blob']
                require(bool(entry['mode'] & 0o111) == (mode == '100755'), 'Source executable mode differs')
            require(blob == oid, 'Recorded source differs from recoverable HEAD')
        branch = done['branch_deleted']
        if label == 'repair-1112':
            require(branch == proof['expected_branch'] == 'refs/heads/repair/pr1112-refresh-20261115', 'Unexpected deleted branch')
            refs = reader.git(common, 'for-each-ref', '--format=%(refname)', branch).decode().splitlines()
            require(branch not in refs, 'Retired local branch exists')
        else:
            require(branch is None and proof['expected_branch'] is None, 'Detached review deleted a branch')
        old = {row['worktree']: row for row in before['registrations']}
        new = {row['worktree']: row for row in current_by_common[str(common)]}
        require(set(old) - set(new) == removed_by_common[str(common)] & set(old), 'Unaccounted registration removal')
        require(not (set(new) - set(old)), 'Unaccounted registration addition')
        for path in set(old) & set(new):
            if old[path] == new[path]:
                continue
            require(path == str(task / 'worktree'), 'Unaccounted registration change')
            require({k: v for k, v in old[path].items() if k != 'HEAD'} == {k: v for k, v in new[path].items() if k != 'HEAD'}, 'Root registration identity changed')
            require(old[path]['HEAD'] == args.root_advance[0] and new[path]['HEAD'] == args.root_advance[-1], 'Root advance endpoints differ')
            for first, second in zip(args.root_advance, args.root_advance[1:]):
                reader.git(common, 'merge-base', '--is-ancestor', first, second)
            root_advances.append({'before': old[path]['HEAD'], 'after': new[path]['HEAD'], 'chain': args.root_advance})
        rows.append({'label': label, 'source_head': done['head'], 'preserved_entries': len(observed),
                     'preservation_roots': len(done['preservation_roots']), 'tracked_paths_recoverable': len(tree),
                     'recovery_ref_verified': True, 'source_ancestor_of_merged_pr': True,
                     'full_preserved_hash_mode_symlink_readback': True, 'target_and_gitdir_absent': True,
                     'deleted_branch': branch, 'registration_removals_accounted': True,
                     'evidence_sha256': {name: sha(value) for name, value in raw.items()}})
        private_rows.append({'label': label, 'worktree': done['worktree'], 'common_git': str(common), 'recovery_ref': done['recovery_ref']})
    preservation = task / 'cleanup/dirty-snapshot-preservation-20261115'
    plan_raw = reader.regular(preservation / 'RESTORATION-PLAN.json')
    require(sha(plan_raw) == PLAN, 'Accepted restoration plan differs')
    restoration_raw = reader.regular(preservation / 'review-1112/restoration-receipt.json')
    restoration = json.loads(restoration_raw)
    capture_path = preservation / 'review-1112/capture.json'
    capture = json.loads(reader.regular(capture_path))
    require(restoration['plan_sha256'] == PLAN and restoration['capture_sha256'] == sha(reader.regular(capture_path)), 'Restoration input binding differs')
    require(restoration['restored_paths'] == capture['staged_paths'] and restoration['restored_path_count'] == 15, 'Restoration path selection differs')
    require(restoration['original_index_sha256'] == capture['original_index']['sha256'], 'Original index binding differs')
    require(restoration['result_index_sha256'] == all_before['review-1112-integration']['index_sha256'], 'Restored/retired index binding differs')
    expected_command = ['restore', '--source=' + capture['head'], '--staged', '--worktree', '--pathspec-from-file=' + str(preservation / 'review-1112/staged-paths.z'), '--pathspec-file-nul']
    require(restoration['command'] == expected_command, 'Restoration command scope differs')
    payload_count = 0
    for label in ('review-1112', 'remote-verifier'):
        bundle = preservation / label
        captured = json.loads(reader.regular(bundle / 'capture.json'))
        for name, pin in captured['payload_sha256'].items():
            require(sha(reader.regular(bundle / name)) == pin, 'Original preservation payload differs')
            payload_count += 1
    fresh_readback = reader.regular(preservation / 'pre-1112-restoration-readback/verification.json')
    receipt = json.loads(fresh_readback)
    require(receipt['plan_sha256'] == PLAN and all(row['all_payloads_exact'] and row['patch_roundtrip_exact'] for row in receipt['snapshots']), 'Pre-restoration review binding differs')
    stale_refs = []
    for group, common in enumerate(current_by_common, start=1):
        name = 'refs/remotes/origin/' + live['head']['ref']
        for line in reader.git(Path(common), 'for-each-ref', '--format=%(refname) %(objectname)', name).decode().splitlines():
            ref, oid = line.split()
            if ref == name:
                stale_refs.append({'git_group': group, 'ref': ref, 'object': oid, 'remote_branch_absent': True, 'deleted_by_reviewer': False})
        require(reader.registrations(Path(common)) == current_by_common[common], 'Registration changed during readback')
    value = {'reviewed_at': datetime.now(timezone.utc).isoformat(), 'verdict': 'PASS', 'pr': 1112,
             'merged_source_head': SOURCE, 'merge_sha': MERGE, 'merge_tree': MERGE_TREE,
             'quarantines': rows, 'total_preserved_entries': sum(row['preserved_entries'] for row in rows),
             'recorded_local_branch_deletions': 1, 'remote_source_branch_absent': True,
             'all_original_snapshot_payloads_retained': payload_count, 'accepted_restoration_plan_sha256': PLAN,
             'restoration_receipt_sha256': sha(restoration_raw), 'pre_restoration_readback_sha256': sha(fresh_readback),
             'legitimate_root_advances': root_advances, 'stale_exact_origin_tracking_refs': stale_refs,
             'branch_census_scope': 'Recorded intended deletion and all remaining registered branches; no historical complete unregistered-ref census was supplied.',
             'helper_sha256': sha(Path(__file__).read_bytes()), 'reused_reader_sha256': MODULE_PIN,
             'git_github_source_cleanup_mutations_by_reviewer': False}
    if args.private:
        value['private_detail'] = {'quarantines': private_rows, 'current_registrations': current_by_common}
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
