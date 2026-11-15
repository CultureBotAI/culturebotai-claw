"""Render a private exact-path cleanup plan from retained observations.

2026-11-15. Inputs: owned inventory and drift receipts. Outputs: PLAN.md and
ACTION-PLAN.json only. No mutation of checkouts, refs, worktrees or runtimes.
Protected directories are retained; action-time checks remain mandatory.
"""
import argparse,hashlib,json,os
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    task=a.task_root.resolve();audit=task/'cleanup';destination=a.output.absolute()
    if destination.is_symlink() or destination!=destination.resolve() or os.path.lexists(destination) or destination==task or task in destination.parents or destination in task.parents:
        raise ValueError('Plan output must be new and outside/unaliasing retained inputs')
    authenticated={}
    for relative,expected in {'cleanup/inventory-20261115/summary.json': 'e9679aab3114cea7e4ae089fdf868dbb5a276609f45768b376c853568b722db5', 'cleanup/owned-review-content-drift.json': '5b862dbba45fd678a3389c1010e1f04cefaa92ccf50f64991f703d507280c004'}.items():
        source=task/relative
        for ancestor in (source,*source.parents):
            if ancestor.is_symlink():
                raise ValueError('Historical plan input aliases are refused')
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError('Historical plan inputs differ from independently recorded bytes')
        authenticated[relative]=raw
    data=json.loads(authenticated['cleanup/inventory-20261115/summary.json'])
    drift={r['root']:r for r in json.loads(authenticated['cleanup/owned-review-content-drift.json'])}
    quarantine=audit/'quarantine-20261115-after-merge'
    if os.path.lexists(quarantine):raise ValueError('Planned quarantine already exists; choose a new collision-free destination')
    rows=[];lines=['# Read-only cleanup plan','',f"Observed {data['observed_at']}; published main `{data['actual_main']}`.",'',
      'Scope is only task-owned review/repair checkouts and their owned metadata under this task. This is a concrete plan, not an apply script. No files, branches, registrations, sessions or runtimes were removed or changed. The root owns execution only after exact merged-PR confirmation and current owner/reader checks. No new approval is requested.','',
      'The fleet-repo-crud-cleanup skill and cleanup-decisions reference were read. Ignored-inclusive Git pathname inventory and filesystem metadata scans covered 18 registered task checkouts in two common-Git groups. All 18 bounded candidate scans completed. Protected environment/data/evidence descendants were intentionally not opened or sized; this does not prove they are disposable. Unstaged content remains unmeasured except the two explicitly owned review snapshots checked below. There is no reclaimed-space estimate.','',
      '## Immediate holds','',
      '- Keep the root worktree and its environment unchanged while its full pytest run is active. The retained observation recorded active test processes using this task; inspect private reader evidence for exact identities. These are metadata observations only; do not stop or signal processes.',
      '- Keep the permanent-cycle reviewer worktree and all shared evidence while the other reviewer is active. The live collaboration census showed cooperating owners and reviewers still active. Lack of an lsof match is not owner completion.',
      '- Repair1197 local head66e6c6a and repair1211 local head553a610 differ from their observed published PR heads345a63c and a5a98c7. These are publication/owner holds, not cleanup candidates.',
      '- Only PR1236 was observed merged, at99fb0ac with exact head7070392. PRs1112/1138/1197/1211/1243 were still open. Requery every PR immediately before its own cleanup; queued/running checks are not merge proof.',
      '- The1112 integration snapshot has15 staged paths; the remote-verifier snapshot has7 actual tracked byte/mode changes and12 untracked files. Preserve their index/source snapshots before any cleanup. The40 additional remote-verifier stat mismatches were byte/mode-identical to index and are not reported as edits.',
      '', '## Git groups and metadata','']
    for common,group in sorted(data['groups'].items()):
        lines += [f'- Common directory `{common}`; anchor `{group["anchor"]}`; {len(group["worktrees"])} registered worktrees and {len(group["stashes"])} stashes.']
    lines += ['', 'The canonical-source common directory is outside this task and must not be removed, pruned or relocated. Its outside-task primary checkout remains untouched. The task-local reviews/1236/repo is a no-checkout primary clone; its1659 staged deletions and zero tracked index entries are the initial no-checkout state, not a feature patch to discard. Keep it until all ten linked task checkouts are retired. No alternates file was present at observation; do not infer object self-containment from that alone. Before moving this metadata clone, verify object connectivity/recovery refs and every remaining registration. Quarantine the entire exact clone only after linked worktrees are gone; do not delete its .git or global-prune either group.','',
      '## Preservation and later action sequence','',
      f'Proposed same-filesystem quarantine root (currently absent): `{quarantine}`. It is outside every inspected checkout. A quarantine move reclaims no disk space. No quarantine directory has been created.','',
      '1. Recheck exact origin, top level, branch/head, PR state/head/base/merge, index/working bytes, ignored/untracked names, operation markers and live readers for one named checkout. Stop for drift, an active owner, incomplete evidence or an unpublished commit.',
      '2. Record a collision-free recovery ref and a before-action manifest outside the checkout. For normal branches use exact old tip and verify ordinary ancestry or exact squash PR/head proof. Save staged/unstaged binary patches, exact changed file bytes and the index tree/index where present; do not treat source snapshots as unneeded merely because related work is now committed elsewhere.',
      '3. Rewalk and hash every exact ignored/untracked root below before moving it. Retain expensive environments, original helpers, mutation results and private outputs intact. Preserve symlinks as links; never follow them across roots. The metadata reports do not yet supply a full preservation hash inventory.',
      '4. After owner/merge proof and preservation, remove only the eligible exact worktree through Git without force, under a short ownership-aware metadata lock. Dirty snapshots stay held: either preserve and separately review exact-path restoration, or move the entire registered worktree to quarantine through Git and defer removal. No reset, clean, recursive deletion or broad glob is planned.',
      '5. Verify registration/path absence, kept evidence bytes, source/ref recovery and unchanged other owners. Delete an authorized local branch only when unused by all worktrees, after recovery-ref creation, with an atomic expected-old-SHA deletion. Remote branch deletion needs the existing PR-specific authorization and an exact-head lease. No remote action is performed by this plan.',
      '6. Keep task-level design, evidence, pr-audit, reports, cleanup artifacts and all review receipts/helpers outside checkouts. The151 nested fixture Git boundaries found outside registered roots are protected evidence, not extra worktrees to prune. No fixture subtree is selected for deletion.',
      '', '## Exact checkout actions','']
    for entry in data['repositories']:
        root=Path(entry['root']);rel=root.relative_to(task).as_posix();slug=rel.replace('/','__')
        if rel=='worktree':decision='HOLD active root/full-suite writer; remove only after the final root PR merges and all operations finish'
        elif rel=='reviews/permanent-cycle/worktree':decision='HOLD another active independent reviewer; owner release and final root PR merge required'
        elif rel in {'repairs/1197/worktree','repairs/1211/worktree'}:decision='HOLD newer local repair tip versus published PR; complete publication/review/merge first'
        elif rel=='reviews/1236/repo':decision='KEEP shared no-checkout Git metadata clone until every linked worktree is retired; later quarantine exact clone, never prune globally'
        elif rel=='reviews/1112/integration-worktree':decision='HOLD staged integration snapshot; preserve index/tree/15-path patch before separately reviewed restoration or whole-worktree quarantine'
        elif rel=='reviews/remote-verifier/worktree':decision='HOLD seven modified tracked files plus twelve untracked snapshot files; preserve complete source snapshot and patch before any restoration or quarantine'
        elif '1236/worktree' in rel:decision='Eligible for later canary only after current owner/reader check and preservation; exact PR1236 merge was observed'
        else:decision='CONDITIONAL after related exact PR merge, completed owner review, content comparison and preservation; no removal yet'
        paths=[]
        for name in sorted(set(entry.get('ignored_roots',[])+entry.get('untracked_roots',[]))):
            source=root/name.rstrip('/');dest=quarantine/rel/name.rstrip('/')
            paths.append({'source':str(source),'quarantine_destination':str(dest),'action':'preserve_then_reversible_exact_path_move_only_after_preflight','bytes':None,'size_complete':False,'reason':'ignored/untracked material; full descendant/hash inventory required; no disposal authorized'})
        item={'root':str(root),'head':entry.get('head'),'registration':entry['registration'],'common_git_directory':entry.get('git_common_dir'),'decision':decision,'recovery_ref':'refs/cleanup-recovery/cycle-maintenance-20261115/'+slug,'preservation_paths':paths,'staged_paths':entry.get('staged_status',[]),'content_drift':drift.get(str(root)),'unstaged_state':drift.get(str(root),'unmeasured: compare safely at final action'),'operations_observed':entry.get('operations'),'metadata_inventory':entry['source_report'],'actual_cleanup_performed':False}
        rows.append(item)
        lines += [f'### `{root}`','',f'- HEAD `{entry.get("head")}`; common Git `{entry.get("git_common_dir")}`.',f'- Decision: {decision}.',f'- Counts: {entry.get("git_path_counts")}; staged paths {len(entry.get("staged_status",[]))}; observed operation markers {entry.get("operations")}.',f'- Recovery ref to create only at action time: `{item["recovery_ref"]}`.']
        if paths:
            lines += ['- Exact preservation mappings (none moved):']
            for row in paths:lines += [f'  - `{row["source"]}` → `{row["quarantine_destination"]}`; size unmeasured/held.']
        else:lines += ['- No ignored/untracked pathname roots reported at observation; this is not a current content-clean assertion.']
        if entry.get('staged_status'):lines += ['- Exact staged path list is retained in ACTION-PLAN.json and the per-root inventory; do not erase it.']
        lines += ['']
    lines += ['## Original evidence, references and package','',
      f'Keep `{task}/reviews`, `{task}/evidence`, `{task}/pr-audit`, `{task}/design`, root review logs/fixture trees and this cleanup directory. Only the individually enumerated checkout children above are conditional worktree actions. The surrounding review directories remain recovery evidence.','',
      'Original private helpers and their executed hashes remain in place. Public copies are supplementary; never replace original provenance merely because a sanitized copy is committed. In particular, preserve the original1112/1236 helpers listed above and1243 .temp mutation evidence. Preserve the remote verifier snapshot, final integration receipts and every failed-attempt log.','',
      f'The14-file safe final-review bundle is staged at `{audit}/public-package/scripts/adhoc/cycle-maintenance-20261115/reviews/final-closeout/`. It is not installed into the active root checkout. Its PROVENANCE.json SHA256 is32ab05d56601d4900dd82bd955b889c602322a807b1591cc2abc285664c60351. The root can inspect/copy it after active source/test operations finish; originals and hashes are unchanged. No raw logs, home paths, email addresses or private runtime history are included.','',
      'No reference-absence claim is made for protected subtrees. Each suggested quarantine is retention, not a regeneration or deletion claim. Before purging any exact quarantined item, perform a separate authorized content/reference check and record its recovery decision. No purge authority is implied.','',
      '## Evidence and limitations','',
      '- inventory-20261115/summary.json binds exact roots, Git groups/registrations, live PR observations, active descriptor matches, nested fixture boundaries and helper hashes. Per-root reports include ignored/untracked pathname metadata and protected traversal exclusions.',
      '- owned-review-content-drift.json binds the two completed owned snapshots after raw blob/mode comparison. owned-review-unstaged.json and the initial helper are retained to show the stat-only distinction.',
      '- No readers were signaled; no external session was contacted. Root/test/reviewer work is held. All future decisions require fresh state because this task remains active.',
      '- No deletion occurred; reclaimed bytes are zero. Protected subtree sizes, complete future hash manifests and global process-reader coverage are not asserted.']
    destination.mkdir(parents=False,exist_ok=False)
    (destination/'PLAN.md').write_text('\n'.join(lines)+'\n')
    value={'observed_at':data['observed_at'],'mode':'read_only_plan','quarantine_root':str(quarantine),'quarantine_exists':False,'items':rows,'actions_performed':[],'plan_sha256':hashlib.sha256((destination/'PLAN.md').read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (destination/'ACTION-PLAN.json').write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'items':len(rows),'preservation_mappings':sum(len(r['preservation_paths']) for r in rows),'plan_sha256':value['plan_sha256']}))
if __name__=='__main__':main()
