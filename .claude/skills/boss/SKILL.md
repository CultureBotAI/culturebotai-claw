---
name: boss
description: Use ONLY when the user explicitly asks to orchestrate parallel external agents (Claude Code) in tmux sessions, or says you are the boss/orchestrator. Resolve all applicable Mech repositories from kg_microbe_fleet, use isolated worktrees, and coordinate writes through the shared lock manager.
argument-hint: '[ "curate" | "enrich" | "sync" | "status" | "kill" | <QUESTION> ] [INFO]'
category: orchestration
requires_database: false
requires_internet: true
version: 1.0.0
tags: [orchestration, parallel, worktree, tmux, multi-repo, agents, boss, fleet]
---

# boss: orchestrate parallel agents across the CultureBotAI repos

## Overview

Turns the main session into an **orchestrator** of external Claude Code processes
running in isolated tmux sessions, each on its own branch in its own git worktree.

**Core principle:** one worker = one task = one unique branch = one unique
worktree. Repository locks protect only short shared metadata transitions.

**Ground rules:**
- Boss delegates all file-editing to workers; boss plans, monitors, and steers
- Workers inherit CLAUDE.md and all skills — one-line prompts suffice
- Workers edit only their isolated branch and do not hold a repo lock while
  running commands that may invoke repository hooks
- Boss does not merge PRs without human confirmation (@marcin reviews)

---

## Dispatch Mode Selection

| Scenario | Use |
|----------|-----|
| Short task (< 30 min), no persistent state needed | **Mode A**: Agent tool with `isolation: "worktree"` |
| Long-running curation, needs observability, multi-hour | **Mode B**: External tmux + `claude` CLI |
| Sequential cross-repo pipeline | Mode B preferred (explicit isolated worktrees) |
| Research / read-only analysis | Mode A |

---

## Mode A — In-Process Agents (Agent tool with worktree isolation)

Use Claude Code's built-in Agent tool with `isolation: "worktree"` for parallelizable
tasks that complete within one session context. The worktree is created automatically,
cleaned up if no changes are made.

```
Agent(
  subagent_type="general-purpose",
  isolation="worktree",
  prompt="<one-line task>",
  run_in_background=True   # for parallel dispatch
)
```

**Best for:** schema validation, report generation, read-only analysis, and
control-plane-only tasks where you need the result before proceeding. A Mode A
worker may write a downstream Mech only when the Agent tool provides its own
unique worktree and branch. Do not hold a repository lease across the Agent
call—the worker's hooks would block. Use Mode B when explicit metadata locking,
session observability, or manual worktree lifecycle is required.

**Limit:** ~5-6 parallel agents without saturating context.

---

## Mode B — External tmux Agents

For long-running or observable tasks. Each agent runs in its own tmux session
with its own worktree under the portable `FLEET_WORKTREE_ROOT`.

### Resolve fleet and set up (once per orchestration run)

```bash
SLUG="${SLUG:-}"
TARGET_KEY="${TARGET_KEY:-}"
set -euo pipefail
case "$SLUG" in
  ""|*[!a-z0-9-]*) echo "Invalid task slug: $SLUG" >&2; exit 2 ;;
esac
test -n "$TARGET_KEY" || { echo "TARGET_KEY is required" >&2; exit 2; }
ORCHESTRATION_ROOT="$(git rev-parse --show-toplevel)"
test -f "$ORCHESTRATION_ROOT/plugins/lock_manager.py"
FLEET_WORKTREE_ROOT="${FLEET_WORKTREE_ROOT:-${TMPDIR:-/tmp}/culturebotai-worktrees}"
mkdir -p "$FLEET_WORKTREE_ROOT"
TARGET_ROWS="$(uv run python -m kg_microbe_fleet targets \
  --capability coordination_hooks)"
```

`targets` resolves configured roots through `RepositorySettings` and verifies
their exact `origin` GitHub identities before printing any rows. Select a target
by manifest key; the fifth field is its validated root. Empty means explicitly
unconfigured and is a hard stop for a writing task:

```bash
target_row="$(awk -F '\t' -v key="$TARGET_KEY" '$1 == key' <<< "$TARGET_ROWS")"
test -n "$target_row" || { echo "Unknown coordination target: $TARGET_KEY" >&2; exit 2; }
IFS=$'\t' read -r TARGET_KEY TARGET_NAME TARGET_GITHUB \
  TARGET_ROOT_VARIABLE REPO <<< "$target_row"
test -n "$REPO" || { echo "Set $TARGET_ROOT_VARIABLE" >&2; exit 2; }
```

`boss` includes GitHub PR follow-through and launches an authenticated external
agent, so it declares `requires_internet: true`. Read-only planning can still be
done offline, but do not claim the complete workflow is offline.

### Prepare task input without shell interpolation

Put every initial prompt or follow-up in a private file. Do not place user task
text in a command string, shell variable expansion, `tmux send-keys` argument, or
Claude command-line argument.

```bash
PROMPT_FILE="$(mktemp "$FLEET_WORKTREE_ROOT/.${SLUG}.prompt.XXXXXX")"
chmod 600 "$PROMPT_FILE"
"${EDITOR:?Set EDITOR to create the task prompt}" "$PROMPT_FILE"
test -s "$PROMPT_FILE" || { echo "Prompt file is empty" >&2; exit 2; }
PROMPT_FILES=("$PROMPT_FILE")

paste_prompt_file() {
  session=$1
  prompt_file=$2
  test -s "$prompt_file" || { echo "Prompt file is empty" >&2; return 2; }
  buffer_name="boss-${session}-$$"
  tmux load-buffer -b "$buffer_name" "$prompt_file"
  tmux paste-buffer -b "$buffer_name" -d -t "$session"
  tmux send-keys -t "$session" Enter
}
```

`tmux load-buffer` reads the bytes directly, and `paste-buffer` sends them to the
Claude TUI without asking either shell to evaluate the prompt. Verify that the
Claude input window is active before every paste.

### Use one bounded lock owner for metadata transitions

Create a unique private helper file, then save the fixed code below in it. The
helper contains no task text and is used only for short operations such as
registering or removing a worktree and deleting its local branch.

```bash
LOCK_RUNNER="$(mktemp "$FLEET_WORKTREE_ROOT/.locked-command.XXXXXX.py")"
chmod 700 "$LOCK_RUNNER"
"${EDITOR:?Set EDITOR to save the reviewed fixed helper}" "$LOCK_RUNNER"
```

One Python process acquires the lease, checks the boolean result, runs the exact
argument-vector metadata command for a bounded interval, and releases its own
lease in `finally`. Passing an argument vector avoids a shell.

```python
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

orchestration_root = Path(os.environ["OPENCLAW_ORCHESTRATION_ROOT"]).resolve()
sys.path.insert(0, str(orchestration_root))

from plugins.lock_manager import LockManager

resource, operation, raw_limit, separator, *command = sys.argv[1:]
task_limit = int(raw_limit)
if separator != "--" or not command or not 60 <= task_limit <= 86_400:
    raise SystemExit("invalid command or task limit")


def stop_on_signal(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


for handled_signal in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(handled_signal, stop_on_signal)

manager = LockManager({"my_id": f"boss-{os.getpid()}"})
# The child is forcibly bounded below this lease. There is deliberately no
# renewal protocol: increase both values before launch if the approved task is
# expected to take longer.
acquired = manager.acquire_lock(
    resource,
    operation,
    timeout=task_limit + 300,
    wait=False,
)
if not acquired:
    raise SystemExit(f"could not acquire repository lock: {resource}")

exit_code = 1
child: subprocess.Popen[bytes] | None = None
try:
    try:
        child = subprocess.Popen(command)
        exit_code = child.wait(timeout=task_limit)
    except subprocess.TimeoutExpired:
        print("worker exceeded its approved duration", file=sys.stderr)
        exit_code = 124
finally:
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    if not manager.release_lock(resource):
        print("the owned repository lock could not be released", file=sys.stderr)
        exit_code = 70

raise SystemExit(exit_code)
```

Use the helper locally without reconstructing a shell command:

```bash
run_locked_command() {
  operation=$1
  task_limit=$2
  shift 2
  test "$#" -gt 0 || { echo "Missing locked command" >&2; return 2; }
  OPENCLAW_ORCHESTRATION_ROOT="$ORCHESTRATION_ROOT" \
    uv run --project "$ORCHESTRATION_ROOT" python "$LOCK_RUNNER" \
      "$TARGET_KEY" "$operation" "$task_limit" -- "$@"
}
```

Do not acquire in one `python -c` process and release in another: leases are
owned by the `LockManager` instance and token in the acquiring process. The
wrapper's child is forcibly bounded five minutes below the lease, with no
renewal. Never run Claude, validation, commit, or push under this wrapper: the
installed safety hooks treat any active repository lock as blocking and do not
have an owner-token bypass. Isolation—not a long lease—protects worker edits.

### Dispatch a worker

```bash
# 1. Create a collision-resistant worktree on a new branch
TASK_DIR="$(mktemp -d "$FLEET_WORKTREE_ROOT/${SLUG}.XXXXXX")"
WORKTREE="$TASK_DIR/worktree"
TASK_ID="${TASK_DIR##*.}"
BRANCH="feat/$SLUG-$TASK_ID"
SESSION="$SLUG-$TASK_ID"
run_locked_command "fetch-main-$SLUG" 300 \
  git -C "$REPO" fetch origin \
    refs/heads/main:refs/remotes/origin/main
run_locked_command "create-$SLUG" 300 \
  git -C "$REPO" worktree add -b "$BRANCH" "$WORKTREE" origin/main
BASE_SHA="$(git -C "$WORKTREE" rev-parse HEAD)"
test "$BASE_SHA" = "$(git -C "$REPO" rev-parse origin/main)"

# 2. Start tmux session
tmux new-session -d -s "$SESSION" -c "$WORKTREE"

# 3. Launch plain Claude with its normal permissions and no active repo lock.
# The command is fixed and contains no task text.
tmux send-keys -t "$SESSION" -l -- "claude"
tmux send-keys -t "$SESSION" Enter

# 4. Wait for prompt to appear (~3-5s), then deliver task
sleep 4
tmux capture-pane -t "$SESSION" -p | tail -5
paste_prompt_file "$SESSION" "$PROMPT_FILE"
```

---

## Multi-Repo Coordination (REQUIRED for workers that modify repos)

Workers that write to any repository returned by the `coordination_hooks`
capability query **must** use the unique worktree/branch flow above. The
orchestrator uses the bounded lock wrapper only while registering/removing the
worktree or deleting its branch, checks acquisition, and releases in the same
process. It must release before Claude starts. Never ask the worker to acquire a
long repo lock: its own pre-edit/pre-commit hooks would correctly block it.

The manifest key is the lock identity. Claw itself is the control plane rather
than a Mech target and follows the active session's ordinary branch discipline.

Lock files live in the workspace resolved by the claw lock manager. A metadata
command is capped below its lease; the long-running task has no expiring lease.

---

## Planning

Before dispatching, use TodoWrite. For each task, note:

- **Slug**: short (< 20 chars), lowercase, hyphens, no repo prefix. `enrich-feba-b4` not `culturemech-enrich-feba-b4`
- **Target repo**: which downstream repo is being modified
- **Metadata lock**: target key and each short transition it protects
- **Initial prompt**: one line — workers know the skills, don't repeat them
- **Mode**: A (in-process) or B (external tmux)

Confirm plan with the user before dispatching > 3 tasks or if repos overlap.

---

## Workflow

```
plan → dispatch → verify → monitor → steer → PR → complete → clean
```

### Dispatch (Mode B) — ordered steps, do not skip

Follow the complete **Dispatch a worker** block above. Target identities and
paths come from the manifest query and declared root environment variables;
never reconstruct a path from a display name. Launch plain `claude` through the
tmux session with its normal permission model and no active repository lease.

#### Verify the prompt window appeared

```bash
tmux capture-pane -t "$SESSION" -p | tail -5
# Should show claude TUI with input prompt, not a shell prompt
```

#### Deliver the task prompt

```bash
paste_prompt_file "$SESSION" "$PROMPT_FILE"
```

#### Verify the task landed

```bash
sleep 3
tmux capture-pane -t "$SESSION" -p | tail -10
# Should show the agent processing the task, not waiting at input
```

If the prompt did not land, confirm the TUI is at its input first, then paste
the same file again:

```bash
paste_prompt_file "$SESSION" "$PROMPT_FILE"
```

---

## Monitor

```bash
# List all sessions
tmux list-sessions

# Watch a specific session (exit with q)
tmux capture-pane -t "$SESSION" -p -S -50 | tail -30

# Attach briefly to observe (detach with Ctrl-B D)
tmux attach -t "$SESSION"
```

---

## Steer

Send follow-ups to an active agent by creating another private prompt file:

```bash
FOLLOWUP_FILE="$(mktemp "$FLEET_WORKTREE_ROOT/.${SLUG}.followup.XXXXXX")"
chmod 600 "$FOLLOWUP_FILE"
"${EDITOR:?Set EDITOR to create the follow-up}" "$FOLLOWUP_FILE"
test -s "$FOLLOWUP_FILE" || { echo "Follow-up file is empty" >&2; exit 2; }
PROMPT_FILES+=("$FOLLOWUP_FILE")
# Capture the pane and confirm the Claude input is active before pasting.
paste_prompt_file "$SESSION" "$FOLLOWUP_FILE"
```

---

## Stuck-Agent Protocol

Symptoms: session shows repeated failures, confusion, or no output for > 10 min.

1. Capture and read recent output: `tmux capture-pane -t "$SESSION" -p -S -100 | tail -50`
2. **Nudge once**: create another private file, append it to `PROMPT_FILES`,
   and use `paste_prompt_file "$SESSION" "$NUDGE_FILE"` after confirming the
   input is active:

   ```bash
   NUDGE_FILE="$(mktemp "$FLEET_WORKTREE_ROOT/.${SLUG}.nudge.XXXXXX")"
   chmod 600 "$NUDGE_FILE"
   "${EDITOR:?Set EDITOR to create the nudge}" "$NUDGE_FILE"
   test -s "$NUDGE_FILE" || { echo "Nudge file is empty" >&2; exit 2; }
   PROMPT_FILES+=("$NUDGE_FILE")
   paste_prompt_file "$SESSION" "$NUDGE_FILE"
   ```

3. If still stuck after one nudge: flag to user with session name, symptom, proposed fix
4. Do not rescue the same session more than twice — escalate

---

## PR Follow-Through

**A PR opened is NOT completion.** PRs are reviewed by @marcin (human review — no automated
claude-review bot in CultureBotAI repos). A task is done when:
- PR is opened with passing validation
- Human has reviewed and approved
- Branch is merged

After the worker reports "PR opened", query GitHub from the orchestrator shell,
using the manifest's exact `owner/repository` value:

```bash
PR_NUMBER="${PR_NUMBER:-}"
case "$PR_NUMBER" in
  ""|*[!0-9]*) echo "Set PR_NUMBER to the worker's exact PR number" >&2; exit 2 ;;
esac
gh pr view -R "$TARGET_GITHUB" "$PR_NUMBER" \
  --json number,url,state,headRefOid,statusCheckRollup
```

Mark the task as needing human review, don't tear down until merged. Immediately
before an approved merge, fail closed if `main` advanced, the pushed head differs
from the reviewed local head, or GitHub no longer reports a clean PR:

```bash
run_locked_command "refresh-main-$SLUG" 300 \
  git -C "$WORKTREE" fetch origin \
    refs/heads/main:refs/remotes/origin/main

if ! git -C "$WORKTREE" merge-base --is-ancestor origin/main HEAD; then
  echo "origin/main advanced; rebase the unique branch and rerun validation/CI" >&2
  exit 2
fi

local_head="$(git -C "$WORKTREE" rev-parse HEAD)"
remote_head="$(git -C "$REPO" ls-remote origin "refs/heads/$BRANCH" \
  | awk 'NR == 1 {print $1}')"
test -n "$remote_head"
test "$local_head" = "$remote_head"
gh pr checks -R "$TARGET_GITHUB" "$PR_NUMBER"
pr_gate="$(gh pr view -R "$TARGET_GITHUB" "$PR_NUMBER" \
  --json baseRefName,headRefName,headRefOid,headRepository,mergeable,mergeStateStatus \
  --jq '[.baseRefName,.headRefName,.headRefOid,.headRepository.nameWithOwner,.mergeable,.mergeStateStatus] | @tsv')"
IFS=$'\t' read -r pr_base pr_branch pr_head pr_head_repo pr_mergeable pr_merge_state \
  <<< "$pr_gate"
test "$pr_base" = "main"
test "$pr_branch" = "$BRANCH"
test "$pr_head" = "$local_head"
test "$pr_head_repo" = "$TARGET_GITHUB"
test "$pr_mergeable:$pr_merge_state" = "MERGEABLE:CLEAN"
```

If any guard fails, do not merge; update only the unique branch, rerun validation
and CI, and obtain review again as required. The confirmed CLI merge must pin
the reviewed bytes with
`gh pr merge "$PR_NUMBER" -R "$TARGET_GITHUB" --match-head-commit "$local_head"`
(plus the reviewed merge strategy); a web merge cannot provide this SHA guard.

---

## Tear Down

```bash
# After PR is merged:
test "$(git -C "$WORKTREE" rev-parse HEAD)" = "$local_head"
merged_gate="$(gh pr view -R "$TARGET_GITHUB" "$PR_NUMBER" \
  --json state,baseRefName,headRefName,headRefOid,headRepository \
  --jq '[.state,.baseRefName,.headRefName,.headRefOid,.headRepository.nameWithOwner] | @tsv')"
IFS=$'\t' read -r merged_state merged_base merged_branch merged_head merged_head_repo \
  <<< "$merged_gate"
test "$merged_state" = "MERGED"
test "$merged_base" = "main"
test "$merged_branch" = "$BRANCH"
test "$merged_head" = "$local_head"
test "$merged_head_repo" = "$TARGET_GITHUB"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION"
fi
run_locked_command "remove-$SLUG" 300 \
  git -C "$REPO" worktree remove "$WORKTREE"
run_locked_command "delete-branch-$SLUG" 300 \
  git -C "$REPO" update-ref -d "refs/heads/$BRANCH" "$local_head"
rmdir "$TASK_DIR"
rm -- "${PROMPT_FILES[@]}" "$LOCK_RUNNER"
```

The worktree path came from this run's `mktemp -d`. Never pre-delete an
existing worktree and never force its removal; a refusal means the
worktree contains state that must be inspected and preserved.
The compare-and-delete `update-ref` works after squash merges and refuses if the
unique branch moved after review. Remove the recorded prompt/helper files only
after every teardown guard and metadata operation succeeds; preserve them on
failure for recovery.

Batch clean (for multiple completed slugs):
```bash
# Compare registered worktrees with task records before removing each
# confirmed-clean, merged worktree by its recorded unique path.
git -C "$REPO" worktree list --porcelain
```

---

## CultureBotAI-Specific Task Templates

Write the selected template into `PROMPT_FILE` with the editor workflow above;
the quoted text below is not a shell command.

### Ingredient curation batch (MIM)
```bash
# Prompt:
"map the unmapped ingredients in workspace/batch_N.yaml — use the map-media-ingredients skill,
prefer CHEBI over FOODON, dry-run first then apply; open a PR when done"
```

### FEBA enrichment (culturebotai-claw)
```bash
# Prompt:
"run the feba-integration skill pipeline — analyze, enrich-test, enrich-full, apply to CultureMech;
dry-run before each apply step; open a PR in CultureMech when done"
```

### MIM→CultureMech sync (culturebotai-claw)
```bash
# Prompt:
"run cross-repo-sync — build-unified-mapping then sync-mim-to-culturemech-dry, review output,
then sync-mim-to-culturemech; open a PR in CultureMech with the updated YAML files"
```

### CAS-RN enrichment batch (MIM)
```bash
# Prompt:
"run cas-rn-integration — enrich_mim_cas_rn.py --max-queries 100, then export-unmapped;
commit the updated MIM ingredient files and open a PR"
```

### CommunityMech evidence repair
```bash
# Prompt:
"run the evidence-curation skill repair workflow: batch_snippet_fixer, fix_invalid_snippets,
apply_pmc_conversions; validate with review-communities; open a PR"
```

---

## Command Cheatsheet

| Intent | Command |
|--------|---------|
| Create worktree | use a unique `TASK_DIR="$(mktemp -d ...)"`, then run `git worktree add` through `run_locked_command` |
| Start session | `tmux new-session -d -s "$SESSION" -c "$WORKTREE"` |
| Launch agent | send the fixed literal `claude` command with normal permissions and no active lease |
| Send task | `paste_prompt_file "$SESSION" "$PROMPT_FILE"` after verifying the TUI |
| Read output | `tmux capture-pane -t "$SESSION" -p -S -50 \| tail -30` |
| Attach | `tmux attach -t "$SESSION"` (Ctrl-B D to detach) |
| List sessions | `tmux list-sessions` |
| Kill session | `tmux kill-session -t "$SESSION"` after the worker is idle |
| Remove worktree | run `git worktree remove "$WORKTREE"` through `run_locked_command` after merge and clean-state checks |
| Check locks | use the claw lock-manager status command/API |
| Release stale lock | use the reviewed lock-manager release path after ownership verification |

---

## Red Flags — STOP

| Thought | Reality |
|---------|---------|
| "I'll skip the worktree, just use the repo directly" | No. Multiple agents on the same checkout corrupt each other's state. |
| "Two agents can share a branch or worktree" | No. Give each a collision-resistant branch and worktree; lock only short shared metadata transitions. |
| "The prompt says 'in parallel' so I'll use boss" | Only if the user explicitly named boss / tmux / external agents. Otherwise use the Agent tool with `isolation: "worktree"`. |
| "PR opened = done, tear down now" | No. Wait for human review (@marcin) and merge before cleaning up. |
| "I'll send follow-ups without checking the agent is at input" | The agent may be mid-execution. Capture the pane first; only send when you see the input prompt. |
| "I'll modify two repos at once from the same worktree" | No. One worktree = one target repo. Cross-repo tasks get separate isolated branches. |
| "The worker needs to know about CLAUDE.md rules / validation steps / skill names" | No. Workers inherit CLAUDE.md and all skills automatically. One-line prompts only. |

---

## Comparison: Boss vs. In-Process Agents

| | Boss (external tmux) | Agent tool (in-process) |
|--|---------------------|------------------------|
| **Observability** | Full tmux pane, real-time | Result only |
| **Duration** | Hours, survives session end | Minutes, session-bound |
| **Setup** | Manual (worktree + tmux) | Automatic (Claude handles) |
| **Parallelism** | Unlimited (separate processes) | ~5-6 before context pressure |
| **Lock handling** | Bounded wrapper only for worktree/ref metadata | Unique worktree/branch; no lease across the Agent call |
| **PR workflow** | Worker opens PR, boss monitors | Boss gets result, opens PR itself |
| **Best for** | Multi-hour curation, enrichment | Short analysis, report gen, search |

---

## Related Skills

- `cross-repo-sync` — standard sync sequence; good candidate for boss dispatch
- `feba-integration` — long-running enrichment pipeline; ideal for Mode B
- `cas-rn-integration` — bounded enrichment; can run Mode A or B
- `evidence-curation` (CommunityMech) — snippet repair; good Mode B task
