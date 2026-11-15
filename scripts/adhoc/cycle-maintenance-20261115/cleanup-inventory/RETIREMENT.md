# Clean owned-worktree retirement helper

Prepared 2026-11-15 for the task's existing cleanup plan and issue #1230. This
helper adds no merge, cleanup, runtime or session authority. It has not been
applied to a task checkout. The caller must review the exact worktree and proof
before invoking `--apply`; omission is a read-only dry run.

Inputs are explicit `--task-scope`, `--worktree`, `--expected-head`, `--common-git`,
`--quarantine`, `--proof`, `--action-plan`, `--locks-dir`, and `--owner`. Use a
fresh per-worktree quarantine directory under an existing durable parent, outside
all registered checkouts and on the worktree's filesystem. Proof/plan/locks must
also be outside registered checkouts. Run from outside the selected worktree,
using an environment that is not being retired. Never select a live runtime.

The JSON proof is a trusted operator attestation, not cryptographic or independent
GitHub verification. Root must refresh actual GitHub head/base/merge and owner/
reader completion immediately beforehand. Required fields:

- `schema_version: 1`, `repository: CultureBotAI/culturebotai-claw`, exact absolute
  `task_scope`, `worktree`, `common_git`, `quarantine`, `expected_head`, and
  `expected_branch` (full ref, or null for detached worktrees).
- `disposition: retire_clean`, `owner_complete: true`, `readers_clear: true`,
  nonempty `owner_evidence`, UTC `observed_at` no older than 15 minutes, and the
  actual SHA-256 of the existing ACTION-PLAN.json in `plan_sha256`.
- `merged_pr`: positive `number`, exact `url`, `repository`, `state: MERGED`,
  `base_ref: main`, full `head`, `merge_commit`, `published_main`, same
  `observed_at`, and `merge_method: merge` or `squash`. The selected head must
  be an ancestor of the merged PR head; the merge must be in recorded main.
  Squash additionally requires `exact_squash_head_verified: true` from root's
  exact GitHub head/merge readback. This explicit trust cannot be inferred from
  a branch name or a green check.
- A nonempty `plan_override_reason` if current head differs from the old plan or
  its item is held: explain the fresh publication/merge/owner evidence that
  supersedes the dated observation. Historical plan bytes remain unchanged.

The helper refuses dirty tracked bytes/modes or index entries, conflicted/sparse
or assume-unchanged indexes, primary clones, main/master branches, nested Git
boundaries, operation markers, wrong identities, unknown readers and any lsof
error. Dirty snapshot cleanup is intentionally unsupported: preserve its index,
binary patches and exact changed bytes in a separately reviewed operation before
any exact-path restoration. This helper never restores, resets or cleans files.

It hashes every ignored/untracked descendant, including empty directories and
symlink targets without following links. It refuses unreadable/special/cross-device
entries. Apply creates an exclusive mode0700 quarantine and mode0600 records,
then a collision-free recovery ref. Exact rename moves preserve extras. Full
hash readback happens outside leases. Cooperating-agent metadata transitions use
the shared LockManager resource `claw`, with a 45-second operation budget inside
60-second leases. Immediate index/ref/registration/path/fingerprint checks detect
changes after hashing. The reader probe is read-only `lsof`, never a kill action.

Only after preservation does Git remove the exact linked worktree **without
force**. An unused proved-owned local branch is deleted with its exact old SHA.
There is no remote branch action, global prune, Git clean, reset, broad removal
or disposal of quarantine. A quarantine move reclaims no disk space. Complete
receipts contain private absolute paths and must not be published verbatim.

On partial failure, keep `before.json`, `recovery.json`, any `failure.json`, the
quarantine and remaining registration. Review recorded exact roots and retained
hashes before manually restoring to absent paths; there is no automatic rollback
that might overwrite new work. The recovery ref retains the tracked commit.

Maintained tests in `tests/test_retire_owned_worktree.py` create miniature
offline Git fixtures under a fresh exclusive directory in the repository ignored
`.temp` root and remove only that disposable synthetic fixture afterward. Normal
pytest/CI needs no `--basetemp`. The test suite exercises dry run, one fixture-only successful apply,
preservation, staged-only/unstaged/identity/owner/operation/refusal cases and late
arrivals. `verify_retirement_controls.py --root CHECKOUT --evidence-dir NEW_DIR`
runs three paired fresh-process guard mutations against copies, retaining private
fixture/log evidence and emitting a public-safe hash receipt. Only fixture Git
objects are changed. No helper may be used as a substitute for root's pending
independent review or exact cleanup decision.


Issue #1269 records the independent proof/plan readback race in the first helper.
The repair parses and hashes the same captured bytes, checks those bytes again
at the end of inventory, and rechecks the same binding under each lease. Owner
approval withdrawn or a plan changed during inventory refuses before any output
or Git mutation. Exact initial helper/test bytes remain as inert `.initial.py.txt`
archives with the original receipts. One paired mutation uses that original
helper to reproduce the withdrawn-proof failure; it is never a cleanup entry
point. The original test archive retains a synthetic fixture email, not a person.
