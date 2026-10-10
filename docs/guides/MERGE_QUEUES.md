# Merge queues and deterministic automation

CLAW maintains the queue policy for itself and every Mech in the packaged fleet
manifest. Repository identities come from `kg_microbe_fleet`; exact GitHub Actions
job contexts and their source workflows live in
`src/kg_microbe_merge_queue/policy.json`. A newly admitted Mech must add its mapping.

A Mech admitted before its CI exists instead declares only
`{"blocked": "reason"}`. Planning reports it as blocked without constructing
a ruleset, and applying a saved plan refuses it until queue-ready workflows and
exact passing job contexts have been verified.
Replace the blocked entry with the measured workflow mapping to begin adoption.

DUFMech's measured mapping is `.github/workflows/validate.yaml: [qc]`, verified
on main `658dc8c9e4ed2587f7bf1c62ee59563f327706de` after PR #109. Its separate
Pages publisher is not a required context. This mapping permits a fresh supported
plan; it does not assert that remote rules have been applied or a PR has executed
through the queue. Retain those operational receipts separately.

The managed ruleset is named **CLAW merge queue** and targets only
`refs/heads/main`. It requires a pull request and the declared Actions checks
(app ID 15368), with no bypass actors. The queue uses squash merges, ALLGREEN,
three concurrent builds, one PR merged at a time and a 120-minute check timeout.
It imposes no new approval count. Existing review requirements remain applicable.
The strict/up-to-date PR option is false because the queue validates against
current main. Auto-merge is enabled so the CLI can schedule queue admission while
required PR checks finish.

AIMech's admission maps `.github/workflows/validate-strict.yaml` to the
`validate-strict` job, which calls `just check`. Main
`38594d6436195e7fdb0882613e9004a0132dd4fc` declares unconditional PR and
`merge_group` triggers; its bootstrap PR passed that exact job in
[run 38035359449](https://github.com/CultureBotAI/AIMech/actions/runs/38035359449).
Recheck readiness before applying a scoped queue plan. Registration is not
remote queue activation; retain the configuration receipt and an actual
queue-merge receipt separately.

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


## Automatic admission

`merge-queue-admission.yaml` runs hourly at minute 23 and accepts manual dry runs.
It executes the governed `auto_merge_ready_prs.py` from the default branch using
Python's standard library and `gh`; it does not invoke a model. Claw executes the
canonical packaged script, while each Mech executes its byte-identical vendored
copy. These deterministic workflows are independent of model-agent cron profiles.

A sweep admits at most three PRs, oldest first. Each candidate must target main,
be ready for review, have no human assignee or `hold`, `do-not-merge`,
`merge-queue:hold`, or `wip` label, and have a latest current-head approval from a
repository owner, member, or collaborator other than its author. Bot accounts
receive no blanket trust. Outstanding changes-requested reviews hold admission.
GitHub's additional review requirements and all required checks must also pass
on the same head. The controller rereads eligibility and uses the atomic `enqueuePullRequest` mutation with the exact PR head. Missing queue state, incomplete API pages, changing rules, and
failed reads hold admission; they never select a direct merge or bypass.

Automatic admission also waits for the Actions `merge-integrity` check on current
main. A missing, pending, or failed check holds candidates. This gate is separate
from PR/merge-group validation and does not change existing required contexts.

The built-in token performs reads. The existing `AGENT_APP_ID` and
`AGENT_APP_PRIVATE_KEY` mint a repository-scoped token with contents and pull
requests write permissions, passed only to the queue mutation subprocess. An uncertain write outcome stops
the sweep; the controller never enables deferred auto-merge. An App token
allows the resulting queue events to start Actions; ordinary built-in token writes
can suppress downstream workflows ([GitHub event/token behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)).
The separate reviewer App is not used to manufacture approvals.

```bash
# Local inspection never writes by default.
python scripts/auto_merge_ready_prs.py --repository OWNER/REPO \
  --report /tmp/merge-admission.json
# In claw, use src/kg_microbe_governance/artifacts/scripts/ instead of scripts/.
gh workflow run merge-queue-admission.yaml -R OWNER/REPO -f apply=false
# Operational pause; resume by deleting the variable or setting it false.
gh variable set MERGE_QUEUE_AUTOMATION_PAUSED -R OWNER/REPO --body true
```

Two failed-check queue ejections hold unchanged content. GitHub's removal events
lack the PR-head SHA, so the controller conservatively counts complete event
history since the earliest commit with the current tree in the PR or its force-push
history. Empty commits, unchanged force-pushes, and tree reverts do not reset
that hold; old/backdated commits can retain it.
A content repair can become eligible after fresh checks and current-head review.
There is no automatic rerun or unlimited retry. Diagnose infrastructure failures
before a deliberate manual queue retry.

Cache coordination reserves complete changed files across existing queue entries
and the current sweep. Overlapping files wait for a later sweep; missing or
truncated cache patches hold admission. This accommodates both ontology CSV
caches and heterogeneous `references_cache/` records without rewriting content.
A repository can replace the default cache globs through
`conf/merge_queue_automation.json`, containing only a nonempty
`{"cache_path_globs": ["references_cache/**", "cache/**"]}` mapping. Such policy
changes belong in reviewed PRs. Native queue CI remains the final integration gate;
human/manual enqueue operations do not participate in the controller's reservation.

## Post-merge tree verification

`verify-merge-integrity.yaml` runs for every main push without path filters or
cancellation. The `merge-integrity` job checks the entire first-parent push range.
For each single-parent commit mapped by GitHub to a merged PR, it reconstructs
`git merge-tree --write-tree PARENT PR_HEAD` and compares that tree with the
published commit tree. It verifies the exact repository, branch, merged commit,
and stable PR head through API reads. Commit subjects are not identity evidence.
Reconstruction uses a disposable bare object store, so project merge drivers,
hooks, replacement objects, the index, and working files cannot affect the result.

The JSON report distinguishes verified squash trees, explicitly skipped multi-parent
commits, demonstrated mismatches, and incomplete evidence. A single-parent commit
without an exact merged PR association fails incomplete; an empty API response
is not evidence of a safe direct/rebase landing. Missing
boundaries, missing objects, ambiguous PR identity, conflicts, and API failures
fail the job. A skipped multi-parent commit is never described as a verified squash. Tree
verification does not prove human review provenance or correctness of the PR.

A real mismatch fails the job and creates or updates a marker-tagged incident
issue with parent, PR head, expected tree, and actual tree. Incomplete evidence
fails without asserting corruption. Concurrent first-time incidents can race to
create duplicate issues; reconcile those rather than cancelling push verification.
Pause automatic admission while investigating a confirmed mismatch, including if
a later main push verifies successfully. Repair through a reviewed PR and rerun
verification after resolving transient lookup/reporting failures.

```bash
python scripts/verify_merge_integrity.py --repository OWNER/REPO \
  --repo-root . --before FULL_SHA --after FULL_SHA --report /tmp/integrity.json
# Issue reporting is explicitly opt-in locally via --report-issues.
gh workflow run verify-merge-integrity.yaml -R OWNER/REPO
```

The manual workflow checks the dispatched main revision (latest commit by default),
or a supplied nonempty first-parent range ending at that same revision. Historical
or empty ranges cannot provide a green check for unrelated current main. CLI exit
codes are 0 for complete examination with no mismatch, 1 for a demonstrated tree
mismatch, and 2 for incomplete verification/reporting.
