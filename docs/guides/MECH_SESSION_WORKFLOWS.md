# Mech session workflows

`scripts/mech_session_supervisor.py` observes existing Antigravity CLI (`agy`)
sessions in macOS Terminal. With explicit `--apply`, it sends bounded workflow
instructions to an idle session. The coding agent performs repository mutations;
the supervisor verifies evidence before starting the next goal. Importing the
committed Terminal adapter performs no UI actions. This guide can serve as the
legacy agent's `workflow_prompt_path`; canonical cycles use the validated YAML contract and immutable runtime snapshot described below.

See [the shared workflow contract](MECH_WORKFLOW_CONTRACT.md) for parent v2's seven goals,
versioned review outputs, infrastructure intake, and cycle restart. Its YAML
parent and LinkML schema are the source of truth.

## Setup and session binding

Use the repository's existing development environment (`uv sync --extra dev`
for a new checkout), configured `.env` repository roots, `git`, authenticated
`gh`, and macOS Terminal. macOS must permit the invoking process to automate
Terminal through `osascript`. Observe mode reads Terminal screens; apply mode
can type. Both modes write local runtime evidence and may query GitHub.
This implementation does not support iTerm, tmux, Linux PTYs, or remote sessions.

The native reader understands the observed agy SQLite/protobuf storage under
`~/.gemini/antigravity-cli/`: `cache/last_conversations.json`, conversation
databases, and `history.jsonl`. It copies database/WAL/SHM files to a private
temporary directory, checks source metadata stability, and reads the copies.
It does not modify native storage. This is an internal storage format, not a
stable API: inspect actual goal and execution-state output after agy upgrades,
and keep apply mode off when decoding or UI recognition fails.

Read the current published fleet manifest at a pinned revision before adopting
fleet membership; use an explicit `manifest_path` when the local copy differs.
Resolve roots through `RepositorySettings` and verify origins. Do not derive
repository paths from their names.

The following creates a **TraitMech example** configuration using an existing
process. First inspect `/bin/ps ax -o pid=,tty=,lstart=,comm=` and the relevant
Terminal tab, then set `MECH_SESSION_PID` to its observed numeric PID and
`MECH_INITIAL_STAGE` to the stage matching its actual last goal in the pinned
parent version (1–7 for v2, 1–6 for v1).
Never relabel a different existing goal merely to fit the example. Stage 0 is
available for closing unrelated adopted work before starting stage 1.
Set `MECH_MANIFEST_PATH` to the verified manifest if needed.

Run from the CLAW checkout:

```bash
uv run --no-sync python - <<'PY'
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path.cwd().resolve()
sys.path.insert(0, str(root))
from kg_microbe_fleet import load_fleet_manifest
from plugins.repository_settings import RepositorySettings, merged_repository_environment

def helper(name):
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

native, terminal = helper("mech_session_native"), helper("mech_session_terminal")
manifest_path = Path(os.environ.get("MECH_MANIFEST_PATH", root / "src/kg_microbe_fleet/fleet.yaml")).resolve()
settings = RepositorySettings.from_environment(
    environ=merged_repository_environment(root / ".env"),
    manifest=load_fleet_manifest(manifest_path))
target = settings.get_target("traitmech")
repo_root = target.path.resolve()
pid = int(os.environ["MECH_SESSION_PID"])
process = terminal.live_process(pid)
assert process and terminal.process_cwd(pid) == repo_root
assert terminal.foreground(pid, process["tty"])
cache = json.loads((Path.home() / ".gemini/antigravity-cli/cache/last_conversations.json").read_text())
conversation = cache[str(repo_root)]
assessment = native.inspect(str(repo_root), conversation)
goal = assessment["current_goal"]
assert goal and goal["started_at"]
run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
runtime = root / "workspace/session-workflows" / run_id
runtime.mkdir(parents=True, exist_ok=False)
profile_path = repo_root / "workflow/mech-workflow.yaml"
assert profile_path.is_file(), "Install and validate this Mech's workflow adapter first"
from kg_microbe_workflows import load_workflow
resolved_workflow = load_workflow(profile_path)
assert resolved_workflow["repository_key"] == "traitmech"
default_branch = subprocess.check_output(
    ["gh", "api", f"repos/{target.expected_repository}", "--jq", ".default_branch"],
    text=True).strip()
config = {
    "run_id": run_id, "runtime_dir": str(runtime),
    "manifest_path": str(manifest_path), "env_file": str(root / ".env"),
    "input_lock_dir": str(root / "workspace/session-input-locks"),
    "targets": [{
        "repository_key": "traitmech", "root": str(repo_root),
        "github_repository": target.expected_repository,
        "native_session_id": conversation, "pid": pid, "tty": process["tty"],
        "process_identity": process["identity"], "default_branch": default_branch,
        "initial_stage": int(os.environ["MECH_INITIAL_STAGE"]),
        "initial_goal_identity": {"conversation_id": conversation,
            "started_at": goal["started_at"], "start_step_index": goal["start_step_index"]},
        "workflow_profile_path": str(profile_path),
        "workflow_next_profile_path": str(profile_path),
    }],
}
(runtime / "config.json").write_text(json.dumps(config, indent=2) + "\n")
print(runtime / "config.json")
print(json.dumps(goal, indent=2))
PY
```

Review the printed goal and generated configuration before running it. The
profile supplies every stage; do not copy a second stage list into the runtime
configuration. The active cycle retains an immutable effective-profile snapshot;
`workflow_next_profile_path` selects the candidate to validate after the active
infrastructure goal's closure (v2 stage 7; v1 stage 6).
`native_reader_path` and `notifier_path` default to the committed sibling
scripts; explicit overrides remain supported for a reviewed local adapter.
For other Mechs, assess native skills and domain applicability separately.
Missing representations or writers should block a stage. A nonbiological domain
can use `applicability: not_applicable` with an `applicability_reason`, an audit
objective, its appropriate local review skill, and an evidence-backed no-change
result. Do not invent graph fields
or UniProt annotations to satisfy a generic sequence.

## Migrating a six-goal cycle to seven goals

An active v1 cycle stays on its saved effective workflow while a v2 profile is
prepared and reviewed. Do not edit its snapshot, shift its stage, replace its
native goal, rewrite old receipts or rename historical evidence directories.
The ledger's `cycle_versions` records each cycle's parent version, and status
exposes `parent_version` and `stage_key` so a stage number is not mistaken for
the same goal across versions. Stage 0 remains not started.

Configure the target's reviewed `workflow_parent_migration` for the exact old
and candidate effective workflow hashes and its review artifact:

```json
{
  "workflow_parent_migration": {
    "from_sha256": "<old effective workflow digest>",
    "to_sha256": "<candidate effective workflow digest>",
    "reviewed_by": "<reviewer>",
    "reason": "<reviewed migration rationale>",
    "review": {"artifact": "<review artifact path>", "sha256": "<64 hex>"}
  }
}
```

The review artifact must be inside the Mech repository and committed at the
verified final closure head. Set `workflow_next_parent_path` and
`workflow_next_schema_path` when the candidate parent/schema inputs differ
from the active ones; these are target settings, with configuration defaults.
The supervisor
validates that candidate against the verified infrastructure closure commit.
Only after the current v1 infrastructure goal closes can it increment the
cycle, pin v2 and dispatch stage 1 `open_issue_triage`. Missing, changed or
invalid migration evidence blocks activation; it never replaces the active
goal as a recovery action. Keep the ordinary cycle-boundary review and all
existing closure gates effective.

Release and deployment are separate from preparing this code. DUFMech is the
chosen test Mech after a reviewed release and explicit adoption, followed by
the remaining fleet only after a complete stage-1 test closure. No downstream
pin is changed by the phase-1 Claw PR.

## Migrating an existing four-stage run to pinned v1

Stop the goal supervisor and save its configuration, ledgers, receipts, and
status before migration. Preserve the current run, conversation, native goal,
stage, and action history. Validate every repository profile and review the
proposed binding before changing the configuration.

This legacy mapping adopts a reviewed six-goal v1 profile first. It does not
reinterpret the four old stage numbers against v2's inserted first goal. Use
the six-to-seven boundary migration above only after that pinned cycle closes.

For each legacy target, add `workflow_profile_path`,
`workflow_next_profile_path`, and `workflow_migration`. The migration contains
`ledger_sha256` (the supervisor's canonical-JSON `digest` of the old ledger),
its exact `goal_identity`, a `reviewed_by` identity and `reason`, and a `review`
artifact with its SHA-256 and allowed `review_root`. The first sweep verifies
that record and atomically adopts cycle 1 without replacing the native goal.
A one-time policy handoff is sent only at a verified idle composer.

Only the already adopted legacy goal in stages 0–3 may finish with its old
receipt format. Existing stage 4 must produce the new versioned review evidence.
An old stage-5 terminal ledger is not proof of the new stage 5: it needs the
verified stage-4 evidence or a reviewed reassessment. Never reset a ledger or
reuse a completed receipt merely to make a migration pass.

## Running, stopping, and recovery

For an already configured deployment, use the [monitor lifecycle controls](MECH_MONITOR_CONTROL.md)
to start, stop, restart, or inspect both the supervisor and approval monitor.
They preserve existing session state and check process ownership. The direct
commands below remain useful for initial setup and diagnostics.

Set `MECH_SESSION_CONFIG` to the generated absolute configuration path:

```bash
uv run --no-sync python scripts/mech_session_supervisor.py --config "$MECH_SESSION_CONFIG" --observe
uv run --no-sync python scripts/mech_session_supervisor.py --config "$MECH_SESSION_CONFIG" --apply --loop --interval 30
```

The interval is **30 seconds between completed sweeps**, not a promise that every
session is read every 30 seconds. Native snapshots, Terminal reads, and GitHub
verification can lengthen a sweep. `heartbeat.json` includes sweep progress;
`dashboard.md` summarizes all targets. Per-repository directories contain
`status.json`, `ledger.json`, receipts, and optional agent progress.

Stop with SIGTERM or create `STOP` inside `runtime_dir`. Remove `STOP` only when
intentionally resuming. Restart the same run with the same config and ledger:
durable reserved/sent/uncertain actions suppress duplicate sends. Do not delete
receipts or reset the ledger to retry an uncertain delivery.

Binding checks include PID/start time, foreground process group, exact TTY,
working directory/origin, native conversation and initial goal identity, one
matching Terminal tab, empty composer, idle native execution, and absence of
queued/background work. Drafts, menus and unfamiliar screens remain untouched.
The final send rechecks process identity and the exact captured screen.
A successful Terminal API return is an attempted transport, not proof that the
agent submitted the whole instruction. The reservation remains `uncertain`
until the native reader proves one exact full user input after the reserved
step and time, in the same workspace, conversation and goal context. Hash-only
input evidence is bounded to the latest 200 user steps; a reservation older
than that window remains held for operator assessment. Missing, partial,
different or duplicate inputs never authorize a retry or an automatic Enter. Matching pending, queued or unknown-status inputs also defeat uniqueness. Only the observed plain-text input shape, or one SYSTEM goal declaration followed by its plain-text suffix, is supported; extra file or unknown scopes fail closed even when their displayed text has the same hash.
Workspace-history markers alone are not acceptance authority.

A `start_goal` additionally requires actual native SYSTEM `/goal` metadata and
a matching new goal identity. Literal `/goal` text or a marker in a checkpoint
cannot substitute for that declaration. Previously accepted action records are
preserved; they do not independently authorize adoption of another goal.

For an existing unsent draft, preserve the screen, action and native-input
evidence and prepare a separately reviewed recovery proposal. Do not clear or
submit it under an ordinary sweep, rewrite its action state, or resend a goal.
A valid ordinary closure receipt may still close an already completed goal once
all readiness and closure gates pass; delivery evidence is not closure proof.

A replacement agy process or conversation blocks the old binding. Stop,
inspect its current goal and any already delivered instructions/PRs, preserve
the old runtime for evidence, and make a new assessed configuration. Do not
blindly transplant an old ledger or repeat closure work.

An independently running approval monitor must acquire the **same**
`input_lock_dir/<tty-name>.lock` advisory lock before its final recheck/send.
Configure both tools to the same absolute directory (for example
`ttys030.lock`); using separate lock directories does not coordinate them.
The supervisor itself does not approve command, file, or URL menus.

The optional [agy port-pressure guard](MECH_PORT_PRESSURE.md) adds a separate
report-only maintenance command and an explicitly enabled exact-ID restart
transaction. It preserves the adopted goal and never dispatches goal text during
a maintenance transaction. At a verified completed-goal boundary, an eligible
agy session with at least the configured 500 listeners is recycled before the
supervisor's fresh checks and dispatch of its legitimate next goal. The idle
pressure scan remains a fallback; both paths share their limits and failure
latch. A report-mode boundary reports and holds instead of sending input.
Existing configurations keep this guard off.

Blocked progress requires operator assessment. At most three closure-repair
messages are allowed per stage, each after new native progress and the minimum
delay. An explicit current agent `blocked`/`prerequisite_blocked`/
`requires_intervention` progress report stops these repairs.

## Agent workflow

Read the adopted goal and run/stage identity in the supplied `status.json`.
Assess the last goal first; continue that same objective if incomplete.
Repository-local `.claude/skills/` is the skill source of truth. Read the
applicable skill and references before work; preserve human review requirements,
domain-specific schemas/writers, primary-source provenance, and scoped coverage
or search-exhaustion evidence.

After completing the goal, execute the user-authorized sequence:

1. Inspect Git state; isolate goal-owned changes and preserve unrelated work.
   Validate, commit, push a feature branch, and open its PR.
2. Obtain an independent adversarial review of the exact head. File issues for
   real findings, address them, and rerun affected validation and review.
3. Respect current repository checks, branch protection and merge-queue rules.
   Verify the PR actually merged, update the default-branch checkout to contain
   that merge, and safely remove the exact merged local and remote branches.
4. Write the structured closure receipt below and stop. Do not start another
   goal; the supervisor independently verifies closure before dispatching it.

Reuse already completed steps only after matching their goal, branch, head and
evidence. Do not force-delete branches, discard/stash unrelated edits, bypass a
queue, fabricate a review, or create an empty commit to obtain a receipt.
If a clean checkout or another prerequisite cannot be achieved safely, write
`progress.json` with the same run/repository/cycle/stage/goal identity as `status.json`,
an ISO UTC `updated_at`, `phase: "blocked"`, and a concrete `summary`.
Progress is informational and never completion authority.

## Closure receipts and verification

Write `<runtime_dir>/<repository_key>/completion.json`. Copy the exact run,
repository, cycle, stage, pinned `workflow_sha256`, and adopted `goal_identity`
from `status.json`. Replace every
placeholder below with observed values; hashes are the real artifact SHA-256
and Git SHAs. Store coverage, review and validation artifacts in the repository
or that repository's runtime directory. The final-head PR adversarial review
can remain a runtime artifact to avoid a self-referential commit. The stage's
domain-review outputs and `INFRA_TASKS.md` are separate: they must be committed
at the verified final head and bound in `goal_outputs`.

`status.json` includes a scope-bound `receipt_template` and the paths to the
effective workflow and evidence schema. Start from that template rather than
copying cycle or workflow hashes from an older receipt. Its placeholders are
not completion claims.

```json
{
  "schema_version": 2,
  "run_id": "<run>",
  "cycle": 1,
  "workflow_sha256": "<from status.json>",
  "repository_key": "traitmech",
  "stage": 1,
  "goal_identity": {
    "conversation_id": "<from status.json>",
    "started_at": "<from status.json>",
    "start_step_index": 0
  },
  "goal_complete": true,
  "status": "completed",
  "coverage": {"artifact": "<absolute coverage path>", "sha256": "<64 hex>"},
  "validation": [{
    "command": "<actual command>", "status": "passed",
    "head_sha": "<40 hex final PR head>",
    "artifact": "<absolute validation path>", "sha256": "<64 hex>"
  }],
  "review": {
    "status": "complete", "head_sha": "<40 hex final PR head>",
    "artifact": "<absolute review path>", "sha256": "<64 hex>",
    "remaining_findings": 0
  },
  "issues": [{"number": 1, "disposition": "addressed", "fix_commit_sha": "<40 hex>"}],
  "pr": {"number": 1, "head_sha": "<40 hex>", "branch": "<feature branch>", "base": "main"},
  "goal_outputs": {
    "infra_tasks": {"path": "INFRA_TASKS.md", "sha256": "<64 hex>"}
  },
  "cleanup": {
    "remote_branch_deleted": true,
    "local_branch_deleted": true,
    "checkout_ready": true
  }
}
```

All canonical receipts include `goal_outputs.infra_tasks`. The open_issue_triage,
record_review, resolve_review_findings and infrastructure goals also
include `goal_outputs.goal_evidence` with the repository-relative path and
SHA-256 of the versioned LinkML evidence manifest. The manifest binds the
stage's required reports and data artifacts. Resolve_review_findings must point
to this cycle's exact verified record_review manifest. Infrastructure uses the supervisor's frozen intake
snapshot from status, accounts for every outstanding task in it, and retains
new tasks in the current notebook for the next cycle.

For open_issue_triage (v2 stage 1), status supplies `issue_scope` with the exact
frozen queue content, hash and cutoff. Retain those bytes as issue_inventory;
save reviewed severity/reasons, stable groups, plans, dispositions and the
shared four-hour budget in the structured issue_triage evidence. A critical or
high blocker retains its prerequisite and prevents goal closure. The budget
starts only after critical/high work is resolved, is shared across both
workers, and cannot reset for a second group or another worker. Stage-1 work
does not alter the current cycle's later review-findings or infrastructure
policy. See the [contract](MECH_WORKFLOW_CONTRACT.md) and the stage's
triage-and-resolve-issues skill for selection and label rules.

The selected-group list and work intervals are cumulative across revisions.
Previously worked groups remain within the two-group cap even if later blocked;
new selections and intervals append without rewriting earlier work or clock
origins.

Use `python -m kg_microbe_workflows validate-evidence <manifest> --root <repo>`
from the reviewed CLAW environment; supply `--previous <manifest>` when required
for finding continuity. Packaged examples under
`src/kg_microbe_workflows/examples/` show versioned stage-specific records.
Validation checks shape and evidence; it does not replace Git and GitHub closure.

Use `issues: []` when the PR adversarial review found no issues. For a proven no-change goal, use
`status: "no_changes"`, `pr: null`, `issues: []`, and additionally:

```json
{
  "no_changes": {
    "head_sha": "<40 hex unchanged initial HEAD>",
    "explanation": "<coverage and reason no changes were needed>",
    "no_goal_owned_changes": true,
    "no_open_goal_pr": true
  }
}
```

Coverage, review, validation and checkout-readiness evidence are still required.
The conservative no-change verifier requires an initially clean checkout,
unchanged HEAD, a clean default-branch checkout, and no open PR in the repository.

The normal verifier checks artifact hashes and final-head agreement, clean
default-branch checkout, PR repository/base/head identity and actual merged
state, merge ancestry, passing required checks (plus configured `required_checks`
when supplied), closed issue states with fix commits in the PR, and actual
absence of the named local/remote branch. A failed query is not absence.
Native completion alone is insufficient. Review/coverage artifacts remain
claims made by the coding/review agents; the supervisor verifies their binding
and hashes, not their scientific correctness.

By default the native goal must also be completed. The opt-in target setting
`allow_receipt_completion_override: true` permits a fully verified receipt for
an active goal only after a matching accepted instruction; use it only after
assessing why ordinary continuation left native goal state active.
A canonical run advances only after each verified closure. Its infrastructure goal
then increments `cycle`, validates and pins the committed next-cycle profile,
and returns to stage 1. Actions, progress, receipts, archives, and reports carry
the cycle identity, so older evidence cannot complete a later cycle. Legacy
four-stage configurations remain supported until explicitly migrated.

## Previously resolved findings in later remediation goals

A completed single-PR `resolve_review_findings` receipt may identify an issue
whose same finding scope was already resolved in an earlier verified cycle.
Keep the current PR as the current goal's sole PR; a prior cycle's PR is not
an ordered same-goal member. Use the issue's top-level `fix_commit_sha` for
the actual fixing commit in the earlier PR, with this exact descriptor:

```json
{
  "number": 23,
  "disposition": "addressed",
  "fix_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "historical_resolution": {
    "github_repository": "CultureBotAI/ExampleMech",
    "pr_number": 42,
    "base": "main",
    "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "merge_commit_sha": "cccccccccccccccccccccccccccccccccccccccc",
    "receipt_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  }
}
```

These values are illustrative placeholders, not evidence. There is no nested
`fix_commit_sha`, alternative fixing PR, or automatic fallback when the
current PR lacks a claimed commit. The descriptor must bind exactly one earlier
verified remediation closure by canonical receipt digest, PR head and merge.
The retained manifest bytes must match its recorded snapshot. Its resolved
group and stable finding IDs, issue and summaries must match the current
cycle's frozen review and the current resolution group; a reopened or different
finding cannot inherit historical credit.

The verifier freshly checks the prior merged repository/base/head/merge,
complete bounded commit inventory, actual issue closure, and that the merge
is an ancestor of the current reviewed head, PR base and checkout. The issue's
fix must be in that historical PR. This proves declared provenance and
retention of the reviewed finding scope; commit membership alone is not a new
scientific review. Current-goal review, final-head artifacts, checks, merge,
cleanup, publication and native-goal gates still apply. Successful verification
retains `historical_issue_resolutions` in the new closure proof without rewriting
old records. Existing ordinary receipts and previously retained historical
proofs stay unchanged. This additive path is deliberately not combined with
ordered multi-PR receipts.

Incorrect existing receipts require a separately reviewed exact correction
record and user approval before any runtime replacement. Preparing or testing
this compatibility code grants no authority to edit a receipt, reset a repair
budget, replay a goal, or deploy it. See claw issue #1031.

## Ordered multi-PR closure receipts

A goal whose fixes and final evidence land in separate PRs may use the additive
version-2 `prs` and `evidence_attributions` fields. Existing single-PR receipts,
including their archived shape and public goal event, remain unchanged. This
format changes neither native completion authority nor stage dispatch: a native
goal mismatch still needs the documented operator assessment before closure.

Start from the supervisor's ordinary receipt template. Keep its top-level `pr`,
`review`, `validation`, and `cleanup` as the **final integration PR**. Add `prs`
with two to sixteen members, ordered by merge and integration ancestry. Every
member contains exactly `number`, `head_sha`, `branch`, `base`,
`merge_commit_sha`, `review`, `validation`, and `cleanup`. Copy the final
member's identity and proofs to the top-level fields without alteration. Each
member needs its own saved review and validation evidence at that exact head.
See [the illustrative receipt](../examples/ordered-closure-receipt.json); its
synthetic hashes and artifact names must be replaced with observed evidence.

Each `issues` entry additionally names `pr_number`. Its `fix_commit_sha` must
belong to that exact PR's independently queried complete commit inventory; an
issue fixed by an earlier PR must never be attributed to the evidence-repair PR.
Each `evidence_attributions` entry contains exactly `path`, `sha256`, `pr_number`,
and `commit_sha`. The set must equal the current goal evidence manifest plus
its current artifact payloads. The producer commit must belong to that PR,
actually change the path's blob, and produce the exact bytes retained at the
final reviewed head. Merely finding an inherited matching file in a later
commit does not prove production. `INFRA_TASKS.md`, earlier stage evidence,
and ancestor manifests remain independently checked at the final head; do not
claim that a current PR produced those retained files.

The supervisor reads only its configured session's private PR registry. Every
member must have the current run, repository, cycle, stage, adopted native goal,
and workflow digest recorded there. A conflicting retained goal, another stage
or workflow, or an already verified earlier closure blocks this multi-PR path.
A current valid binding takes precedence over an orphaned native identity in
the same cycle, stage and workflow; the orphan alone supplies no membership. This corroboration is not completion authority: every PR still
needs independent merged/base/head, exact merge commit, passing required and
repository-declared checks, issue-fix membership, and local/remote branch-cleanup
verification. A malformed or unsafe registry fails closed without being edited.

The goal window starts at the retained adopted goal's timestamp and ends at the
verification timestamp sampled once for this closure attempt. PR creation,
merge, and each PR commit's GitHub committer timestamp must be coherent within
that window. Evidence-repair PRs may merge after native goal completion while
the same stage awaits closure. No receipt assertion can extend the window or
borrow a prior-stage PR. Commit inventories are paginated and checked against
GitHub's exact PR commit count; PRs above the endpoint's 250-commit limit are
refused rather than treated as complete.

Every earlier merge commit must be an ancestor of the following reviewed head.
For squash merges this uses the merge commit, not the original feature commit.
Every changed path of an issue fix must retain the entry actually produced by
that fix commit at both its member's reviewed head and the final head. Entries
include the blob and executable mode, or exact absence for deletions. Git paths
are looked up literally, including names containing pathspec magic or globs. Comparing
only the two reviewed heads would incorrectly accept a fix reverted before
review. Exact content and mode reintroduction is accepted; a reverted fix is
refused even if the two reviewed trees agree.

A subsequent issue fix in the **same PR** may deliberately replace a path from
an earlier fix. Declare each necessary replacement in that earlier issue's
optional `superseded_paths` list, with one to 256 exact entries containing only
`path`, `pr_number`, and `commit_sha`. The successor must itself be another
independently verified attributed issue-fix commit in this receipt, strictly
descend from the original fix, and actually change that original changed path.
Its produced entry must survive at both the member and final reviewed heads.
Unknown paths, duplicate or self references, unnecessary or unchanged
replacements, unlisted mismatches, and cross-PR code replacements are refused.
No path prefix grants an exemption. DUFMech's PR365 is the motivating example:
its eight structured review files are explicitly replaced by the later fix
for issue366, while the scientific-data fixes retain their original entries.

Current-stage evidence uses only the separate `evidence_attributions` mechanism.
Its producer must be at or after the affected fix in the same PR, or belong to
a later ordered PR and descend from the affected PR's verified merge. An
unrelated earlier producer cannot waive a lost fix. This permits PR367's exact
manifest repair without attributing PR365's issue fixes to it. Producer/fix merge commits,
rename/copy diffs, symlinks, and submodules are refused because their attribution
is ambiguous under this deliberately bounded format.

The retained supervisor verification records every member's independently
verified merge plus the exact evidence attributions. Progress collection exports
all member PR observations and associations, but still only one goal closure,
whose existing top-level PR is the final integration PR. A candidate receipt
contributes informational associations only. No runtime ledger, registry,
counter, active workflow, or migration is rewritten by this feature.

## Historical identity reconciliation

A completed supervised goal followed by a separately directed native goal has a
separate, explicitly approved [historical reconciliation procedure](HISTORICAL_GOAL_RECONCILIATION.md).
It preserves ordinary closure evidence, installs a held next-goal boundary, and
requires a second reviewed release. Neither operation sends input. The real
DUFMech historical notebook versus later adoption intake remains blocked by #1005.
