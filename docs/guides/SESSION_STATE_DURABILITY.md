# Durable session state and batch publication

New Mech session state belongs under the gitignored `<repo>/.temp/` durable
work root. Use a unique directory per task for worktrees, campaigns, batch
manifests, draft reviews, recovery evidence and handoffs. Use
`~/agent-work/<repo>/` when a separate clone is needed. Verify the ignore rule
before creating state; provision a missing rule through the normal reviewed
repository change. Avoid a symlink that resolves the durable root into a system
temporary directory.

Never store session state or helper scripts in `/tmp`, `/private/tmp` or `$TMPDIR`.
Only disposable caches and pytest temporary fixtures may use those roots.
Reproducible cache files are not the only copies of review inputs, unpushed Git
objects, handoffs, receipts or scientific evidence. A directory's name does not
make its contents disposable. Keep maintained helpers in `scripts/adhoc/` or the
repository's native script directory, with purpose, inputs, outputs, date and
issue reference. Commit accepted review/evidence artifacts through their native
writers and tracked output contract.

The work root is protection from system cleanup, not a backup or publication.
The reported macOS cleaner criterion is about four days since **all three** file
access, modification and status-change timestamps. A file approaching that
cutoff can disappear even while another part of its session is active. Refreshing
timestamps is not a durable-state policy and the monitor must never do it.

## Publish committed batches the same day

For authorized Git work, push each committed batch branch to the validated
`origin` the same day, even when there is no PR yet. Use the exact branch and
verify its published head; do not wait for an entire campaign to finish.
For example, from the already identity-validated owned worktree:

```bash
batch_branch="$(git branch --show-current)"
test -n "$batch_branch"
batch_head="$(git rev-parse HEAD)"
git push origin "HEAD:refs/heads/$batch_branch"
test "$(git ls-remote origin "refs/heads/$batch_branch" | awk 'NR == 1 {print $1}')" = "$batch_head"
```

A detached HEAD, rejected push, unavailable network or mismatched remote head
is a blocker to record and resolve. Preserve the durable worktree and commit
IDs; do not reset or delete unpublished work. Publishing is separate from
opening a PR, merging, or cleaning up a branch. This policy grants no additional
Git mutation authority to a read-only review task.

Inspect the current published workflow triggers before claiming that a branch
push starts no CI. Pull-request and merge-group checks are separate events;
scheduled, tag, manual or unusual push triggers must be reported as exceptions.
The fleet audit is dated evidence, not an invariant to assume forever. Avoiding
CI is not a reason to leave an authorized committed batch only on the host.

The [published fleet audit](../reviews/2026-11-07-session-state-fleet-audit.md)
on 2026-11-07 inspected all 14 Mechs and found:

| Published workflow scope | Non-main branch push event |
|---|---|
| CommunityMech | `manual-network-curation` can start `network-quality.yml` when `kb/communities/*.yaml` changes. |
| Other 13 manifest Mechs | Their audited workflow filters exclude non-main branch push events. |

The CommunityMech exception is pinned to
[`1ad70e7835570d2c74df4cfa2717e585a4e03493`](https://github.com/CultureBotAI/CommunityMech/blob/1ad70e7835570d2c74df4cfa2717e585a4e03493/.github/workflows/network-quality.yml#L28).
For every Mech, pushing the head of an existing PR can still trigger
`pull_request` synchronize checks. This is different from a `push`-event filter;
the audit does not promise that every feature-branch push causes zero CI.

## Existing sessions and migration

Inventory and preserve old state before preparing a move. Do not relocate a
live checkout or runtime, change a session binding, refresh access times, remove
a directory, or push another session's branch merely because the monitor warns.
Existing CLAW service runtimes remain at their configured durable roots under
`OPENCLAW_WORKSPACE`; any migration requires its own reviewed procedure and
authorization. Preserve all ignored/untracked evidence, Git objects and refs.

Every auxiliary clone must be declared as an identity-verified entry in
`session_repository_roots`; owned campaign and handoff directories belong in
`session_state_paths`. Missing inventory is unknown. Report new paths to the
supervisor/operator without editing live configuration or expanding the task's
authorization. A scanner cannot prove an undeclared clone has no unpublished work.

## Monitoring and goal closure

The monitor is read-only: it reports local branch commits absent from every
remote-tracking ref, and near-cutoff files in explicitly session-owned system
temporary paths. Unknown or incomplete measurements must remain visible; they
are not healthy zeroes. It must never delete, touch or push.

A goal delivering commits cannot close while its recorded deliverable commits
exist only locally. Closure requires verified origin publication, independently
of a cached local remote-tracking ref. A warning about another branch must not
silently redefine this goal's deliverables or claim they were published.

Each supervisor sweep observes the configured repository and its registered
Git worktrees. The private per-Mech `status.json` and dashboard include
`session_durability`: `status` (`healthy`, `alert`, `unknown`), `complete`,
`unpushed_commits`, `at_risk_files`, `overdue_files`, and observation time.
Private evidence includes bounded samples and coded errors. Unknown counts are
null, never zero; both an alert and an incomplete observation need attention.
The monitor does not gate dispatch or silently act on warnings.

Target configuration accepts two optional ownership inventories:

- `session_repository_roots`: additional absolute standalone-clone roots, each
  validated against that target's manifest GitHub identity. Linked worktrees
  share one Git object inventory. Commits are deduplicated across declared clones.
- `session_state_paths`: absolute owned directories. Omission means inventory
  coverage is unknown; an explicit empty list attests there are no additional
  directories beyond the repository roots and registered worktrees.

This is a bounded inventory, not a scan of all `/tmp` or every user directory.
Unregistered Git clones discovered inside owned directories, shallow history,
missing/unreadable roots, ref changes during observation and exhausted bounds
remain unknown. File inspection uses directory metadata and stat only, without
following symlink escapes or reading file bodies. It examines all three file
timestamps before Git object reads. Ordinary OS read effects are not timestamp
refresh or a retention guarantee. It reports files at least three days old as
at risk and at least four days old as overdue. Fresh cached remote-tracking refs
are **not** claimed: the monitor reports the local ref view without fetching.

To append the saved local observations to the existing progress summary:

```bash
uv run python scripts/mech_progress_status.py \
  --bundle workspace/progress-publisher/bundle.json \
  --durability-runtime workspace/mech-supervisor
```

Supply the actual configured runtime directory. This command only reads saved
state; it does not start monitoring, scan session directories or change a
binding. Observations older than 15 minutes, future-dated by over one minute,
and missing observations report unknown. Exit 3 means warnings/alerts, exit 1
means invalid input, and exit 0 means the validated observations are healthy.
Private paths and branch names stay out of the public Pages progress bundle;
this optional local view does not change that bundle's schema.

The new parent policy requires `deliverable_commits` in the goal receipt: every
delivered batch commit's full SHA, including the reviewed PR head. A no-change
receipt lists none. The supervisor verifies each against the independently
verified merged PR's commit list (which survives squash and branch deletion),
or freshly advertised origin branch tips and GitHub's server-side ancestry
comparison. Stale local remote refs and local graft/replace metadata do not
prove publication. Unknown, malformed, unavailable or bounded-out evidence
holds closure. Additional published batches do not waive the existing primary
PR review/merge/cleanup requirements. Historic pinned contracts remain readable;
legacy receipts without the new policy retain their already required verified
primary PR proof. A new policy is adopted through normal pin/profile review,
not by rewriting an active cycle's frozen contract.

## Validation and rollout boundary

Canonical and rendered skill instructions carry this policy. Regression tests
reject new instructions that place retained state in system temp while allowing
disposable cache/pytest examples and read-only inspections of risky paths.
Synthetic Git and timestamp fixtures test reporting and closure behavior
without scanning, touching or changing a live session.

This Claw change prepares the fleet capability. Updating Mech skills, ignore
rules and running deployments remains a separately approved rollout. Existing
pinned goal contracts and historical evidence remain readable.
