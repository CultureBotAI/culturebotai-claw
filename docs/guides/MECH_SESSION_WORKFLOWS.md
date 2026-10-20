# Mech session workflows

`scripts/mech_session_supervisor.py` observes existing Antigravity CLI (`agy`)
sessions in macOS Terminal. With explicit `--apply`, it sends bounded workflow
instructions to an idle session. The coding agent performs repository mutations;
the supervisor verifies evidence before starting the next goal. Importing the
committed Terminal adapter performs no UI actions. This guide can serve as the
agent's `workflow_prompt_path`; its operational instructions are below.

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
`MECH_INITIAL_STAGE` to the stage matching its actual last goal (1–4).
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
profiles = [
    (1, "Use the add-record skill to review and add traits until the documented search finds no new candidates.", "add-trait"),
    (2, "Use the causal-graph skill to review, edit, and update every record's causal graph.", "research-causal-graphs"),
    (3, "Review all records and add supported UniProt examples, especially for gene or protein graph elements.", "add-uniprot-protein-examples"),
    (4, "Use the record-review skill to review every TraitMech record.", "review-yaml-record"),
]
stages = []
for number, objective, skill in profiles:
    path = repo_root / ".claude/skills" / skill / "SKILL.md"
    assert path.is_file(), f"Required canonical skill missing: {path}"
    stages.append({"stage": number, "goal_text": objective, "skill_paths": [str(path)],
                   "applicability": "available"})
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
        "workflow_prompt_path": str(root / "docs/guides/MECH_SESSION_WORKFLOWS.md"),
        "stages": stages,
    }],
}
(runtime / "config.json").write_text(json.dumps(config, indent=2) + "\n")
print(runtime / "config.json")
print(json.dumps(goal, indent=2))
PY
```

Review the printed goal and generated configuration before running it.
`native_reader_path` and `notifier_path` default to the committed sibling
scripts; explicit overrides remain supported for a reviewed local adapter.
For other Mechs, assess native skills and domain applicability separately.
Missing representations or writers should block a stage. A nonbiological domain
can use an explicit `applicability_audit` profile with its appropriate local
review skill and an evidence-backed no-change result. Do not invent graph fields
or UniProt annotations to satisfy a generic sequence.

## Running, stopping, and recovery

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
A send is acknowledged only through matching native history or a new goal marker.

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
`progress.json` with the same run/repository/stage/goal identity as `status.json`,
an ISO UTC `updated_at`, `phase: "blocked"`, and a concrete `summary`.
Progress is informational and never completion authority.

## Closure receipts and verification

Write `<runtime_dir>/<repository_key>/completion.json`. Copy the exact run,
repository, stage and adopted `goal_identity` from `status.json`. Replace every
placeholder below with observed values; hashes are the real artifact SHA-256
and Git SHAs. Store coverage, review and validation artifacts in the repository
or that repository's runtime directory. Runtime artifacts avoid committing a
report that would change the very head it claims to review.

```json
{
  "schema_version": 1,
  "run_id": "<run>",
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
  "cleanup": {
    "remote_branch_deleted": true,
    "local_branch_deleted": true,
    "checkout_ready": true
  }
}
```

Use `issues: []` when review found no issues. For a proven no-change goal, use
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
Stage 4 closes the pipeline; it does not restart stage 1.
