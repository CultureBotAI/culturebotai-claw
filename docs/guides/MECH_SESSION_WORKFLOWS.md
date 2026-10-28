# Mech session workflows

`scripts/mech_session_supervisor.py` observes existing Antigravity CLI (`agy`)
sessions in macOS Terminal. With explicit `--apply`, it sends bounded workflow
instructions to an idle session. The coding agent performs repository mutations;
the supervisor verifies evidence before starting the next goal. Importing the
committed Terminal adapter performs no UI actions. This guide can serve as the
legacy agent's `workflow_prompt_path`; canonical cycles use the validated YAML contract and immutable runtime snapshot described below.

See [the shared workflow contract](MECH_WORKFLOW_CONTRACT.md) for the six goals,
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
`MECH_INITIAL_STAGE` to the stage matching its actual last goal (1–6).
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
profile supplies all six stages; do not copy a second stage list into the runtime
configuration. The active cycle retains an immutable effective-profile snapshot;
`workflow_next_profile_path` selects the candidate to validate after stage 6.
`native_reader_path` and `notifier_path` default to the committed sibling
scripts; explicit overrides remain supported for a reviewed local adapter.
For other Mechs, assess native skills and domain applicability separately.
Missing representations or writers should block a stage. A nonbiological domain
can use `applicability: not_applicable` with an `applicability_reason`, an audit
objective, its appropriate local review skill, and an evidence-backed no-change
result. Do not invent graph fields
or UniProt annotations to satisfy a generic sequence.

## Migrating an existing four-stage run

Stop the goal supervisor and save its configuration, ledgers, receipts, and
status before migration. Preserve the current run, conversation, native goal,
stage, and action history. Validate every repository profile and review the
proposed binding before changing the configuration.

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

Use `scripts/mech_monitor_control.py stop --service supervisor` and the matching
`start` command to pause and resume. Preserve the same config and ledger:
durable reserved/sent/uncertain actions suppress duplicate sends. Do not delete
receipts or reset the ledger to retry an uncertain delivery.

Each dispatched action saves its complete instructions under the session's
`instructions/` directory. The terminal receives a short marker and file-reading
instruction; the ledger preserves both texts and the instruction file hash.
A `sent` result proves only that Terminal accepted the transport call. CLI
history can also contain queued input, so acceptance requires the exact native
user message in the bound conversation after the send baseline. The first
acceptance timestamp is retained. Historical acceptances without matching
native input are explicitly marked unverified, without resetting workflow
progress. Inspect an existing draft or queue before repairing it; do not resend
an instruction or add Return merely because its display is collapsed.

Binding checks include PID/start time, foreground process group, exact TTY,
working directory/origin, native conversation and initial goal identity, one
matching Terminal tab, empty composer, idle native execution, and absence of
queued/background work. Drafts, menus and unfamiliar screens remain untouched.
The final send rechecks process identity and the exact captured screen.
A send is acknowledged only through the exact native user input. A new goal
must also match that input's native goal identity before adoption.

A replacement agy process or conversation blocks the old binding. Stop,
inspect its current goal and any already delivered instructions/PRs, preserve
the old runtime for evidence, and make a new assessed configuration. Do not
blindly transplant an old ledger or repeat closure work.

An independently running approval monitor must acquire the **same**
`input_lock_dir/<tty-name>.lock` advisory lock before its final recheck/send.
Configure both tools to the same absolute directory (for example
`ttys030.lock`); using separate lock directories does not coordinate them.
The supervisor itself does not approve command, file, or URL menus.

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

For a stage-5 finding already resolved in the frozen review, an issue
may explicitly reference its original verified closure instead of claiming that
its old fix belongs to the current PR:

```json
{
  "number": 76,
  "disposition": "addressed",
  "fix_commit_sha": "74aec27df2af344f46a4b183578f641d465e2a74",
  "historical_resolution": {
    "github_repository": "CultureBotAI/TaxonMech",
    "pr_number": 151,
    "base": "main",
    "head_sha": "74aec27df2af344f46a4b183578f641d465e2a74",
    "merge_commit_sha": "c520694e483373bf5274bac5bc08327d4f0d364c",
    "receipt_sha256": "7c5a12af4437a1eecb654bf2f9623241eec4881ecfecf23cddf5b9356707e0cb"
  }
}
```

`receipt_sha256` is the supervisor's canonical JSON digest recorded in
`completed_stages`, not the raw archive-file hash. It must identify one earlier
verified merged receipt with the same PR/head/merge. The prior evidence and
current frozen review must both identify the same already-resolved finding; a reopened or new finding requires a current fix. The
supervisor rechecks that the issue is a closed real issue, the original PR is
merged at its pinned repository/base/head/merge, and the stated fix is a member
of that PR. Its merge commit must be an ancestor of the current reviewed head,
current PR base and default checkout. For squash merges, membership is checked
for the original fix, while ancestry is checked for the squash merge commit.
Historical references are reported separately and do not add a new PR or goal
completion. Omitting `historical_resolution` retains the requirement that the
fix commit belongs to the current PR. Current review, CI and cleanup gates are
unchanged. Stage 6 continues to use its existing unresolved-task intake and
current-PR fix rules; this historical field is not accepted there. This optional receipt field does not alter the LinkML goal-evidence
manifest or its pinned workflow schema.

All canonical receipts include `goal_outputs.infra_tasks`. Stages 4–6 also
include `goal_outputs.goal_evidence` with the repository-relative path and
SHA-256 of the versioned LinkML evidence manifest. The manifest binds the
stage's required reports and data artifacts. Stage 5 must point to this cycle's
exact verified stage-4 manifest. Stage 6 uses the supervisor's frozen intake
snapshot from status, accounts for every outstanding task in it, and retains
new tasks in the current notebook for the next cycle.

Use `python -m kg_microbe_workflows validate-evidence <manifest> --root <repo>`
from the reviewed CLAW environment; supply `--previous <manifest>` when required
for finding continuity. Packaged examples under
`src/kg_microbe_workflows/examples/` show the three stage-specific records.
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
A canonical six-stage run advances only after each verified closure. Stage 6
then increments `cycle`, validates and pins the committed next-cycle profile,
and returns to stage 1. Actions, progress, receipts, archives, and reports carry
the cycle identity, so older evidence cannot complete a later cycle. Legacy
four-stage configurations remain supported until explicitly migrated.
