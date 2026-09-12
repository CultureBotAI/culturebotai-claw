# Native merge queues

CLAW maintains the queue policy for itself and every Mech in the packaged fleet
manifest. Repository identities come from `kg_microbe_fleet`; exact GitHub Actions
job contexts and their source workflows live in
`src/kg_microbe_merge_queue/policy.json`. A newly admitted Mech must add its mapping.

The managed ruleset is named **CLAW merge queue** and targets only
`refs/heads/main`. It requires a pull request and the declared Actions checks
(app ID 15368), with no bypass actors. The queue uses squash merges, ALLGREEN,
three concurrent builds, one PR merged at a time and a 120-minute check timeout.
It imposes no new approval count. Existing review requirements remain applicable.
The strict/up-to-date PR option is false because the queue validates against
current main. Auto-merge is enabled so the CLI can schedule queue admission while
required PR checks finish.

Required validation workflows run on every PR and on
`merge_group: {types: [checks_requested]}`. Their default checkout validates the
combined event commit. Path filters may remain on pushes, never on required PR
checks. New PR commits can cancel older PR runs; non-PR runs use a unique run ID.
Pages, scheduled advisory reports and model-driven reviews are outside queue
requirements. ProteinTraitsMech runs full validation for merge groups.

## Inspect and reconcile

These commands use `gh` authentication. Reading the public fleet needs no local
Mech checkouts. Applying settings requires repository administration permission.
The automatic rollout supports public organization repositories with main as the
default branch and squash merges already enabled.

```bash
uv run kg-microbe-merge-queue check
uv run kg-microbe-merge-queue plan --output /tmp/queue-plan.json
# Optional scope: --repository taxonmech (repeat for several repositories).
# Review the saved desired rules, existing settings and readiness evidence.
uv run kg-microbe-merge-queue apply --plan /tmp/queue-plan.json \
  --receipt /tmp/queue-apply.json
```

`plan` and `check` never write GitHub. `check` exits nonzero for drift or readiness
failures. `apply` rechecks every selected repository before the first write and
again immediately before each repository's writes. Changed settings or workflow
bytes invalidate a plan; unrelated main commits with identical workflows do not.
An existing receipt is never overwritten. Reports put updated repositories first
and unchanged, blocked or unattempted repositories at the end.

The command writes only the named repository ruleset and `allow_auto_merge`.
It preserves other rulesets and repository settings, and refuses a conflicting
queue or existing classic branch protection until explicitly reconciled. Never
remove an existing protection merely to make adoption succeed.

Readiness checks cover triggers, cancellation, required jobs and their transitive
prerequisites, candidate repository and commit, and separate immutable auxiliary
checkouts. Concurrency belongs at workflow level to avoid jobs contending with
their own workflow. The checker also requires exact unique successful job names observed in the ten latest
completed runs using the same workflow bytes. No match requires a fresh CI run.
This is not a proof of arbitrary workflow shell code: review step conditions,
changed-file selection, matrix behavior and pinned reusable workflow internals
before rollout. Recheck required names after renaming a job or changing its matrix.

## Bootstrap and verify a repository

1. Land CI readiness through a reviewed PR and passing checks before activating
   the queue. Preserve governed artifacts and pins unless they are in scope.
2. Generate and review a fresh scoped plan, then apply it with a new receipt.
3. Put an authorized, reviewed PR through the real queue. Record its reviewed
   head, merge-group SHA, `merge_group` Actions runs and actual merged commit.
   A successful configuration read-back alone does not prove queue execution.
4. Run `check` again and retain the report with the rollout evidence.

## Merge an authorized PR

Use `cross-mech-sync` or the repository's normal review process to verify scope,
repository/base/head identity and the exact reviewed commit. Query active rules
before selecting the queue path. For a branch requiring a native queue:

```bash
gh pr merge "$PR_NUMBER" -R "$TARGET_GITHUB" \
  --match-head-commit "$local_head"
```

Do not pass `--admin`. GitHub may enqueue the PR or enable auto-merge until required
PR checks finish. Neither response means merged. Do not rebase simply because main
advanced; the queue validates the combined changes. Repair actual conflicts and
repeat validation/review when the branch changes.

Wait until GitHub reports `state: MERGED`, and verify the same base, source
repository, branch and reviewed head before deleting branches or worktrees.
Delete the remote branch separately with a force-with-lease bound to the reviewed
head; preserve it and the worktree if someone has pushed another commit.
Keep worktrees while a PR is queued or ejected. Inspect failing **merge-group**
runs, fix the owned branch, and re-enqueue only after passing checks and review.
For an infrastructure failure, retry the failed run once after diagnosing it;
repeated failure requires fixing the cause, not bypassing protection.

## Failed or interrupted apply

The receipt contains the freshly verified before state and a durable intent before
each API write. `actions` records confirmed responses; `attempts` also records
pending or unknown outcomes. A failed response can follow a successful remote
write. A storage failure preserves the last complete receipt, which can still
show a pending attempt. Inspect GitHub before deciding whether that write happened.
An API failure stops further writes and marks later repositories unattempted. Inspect
GitHub and generate a fresh plan to resume; the operation is idempotent. Never
replay a stale plan or delete an unrelated ruleset. If an enabled queue cannot run,
repair CI through an authorized branch first. Any explicit emergency rollback
must use the receipt's exact managed ruleset ID, compare current state against
this run's changes, and restore only those changes with user authorization.

GitHub references: [queue behavior and CI requirements](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue),
[CLI queue admission](https://cli.github.com/manual/gh_pr_merge), and
[repository rules API](https://docs.github.com/en/rest/repos/rules).
