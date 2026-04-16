---
name: boss
description: Use ONLY when the user explicitly asks to orchestrate parallel external agents (Claude Code) in tmux sessions, or says you are the boss/orchestrator. For in-process subagents use the Agent tool with isolation=worktree instead. Manages multi-repo work across CultureMech, MIM, CommunityMech, and culturebotai-claw with lock coordination.
argument-hint: [ "curate" | "enrich" | "sync" | "status" | "kill" | <QUESTION> ] [INFO]
category: orchestration
requires_database: false
requires_internet: false
version: 1.0.0
tags: [orchestration, parallel, worktree, tmux, multi-repo, agents, boss]
---

# boss: orchestrate parallel agents across the CultureBotAI repos

## Overview

Turns the main session into an **orchestrator** of external Claude Code processes
running in isolated tmux sessions, each on its own branch in its own git worktree.

**Core principle:** one worker = one task = one branch = one worktree = one repo lock.

**Ground rules:**
- Boss delegates all file-editing to workers; boss plans, monitors, and steers
- Workers inherit CLAUDE.md and all skills — one-line prompts suffice
- Workers must hold a repo lock before modifying any downstream repo
- Boss does not merge PRs without human confirmation (@marcin reviews)

---

## Dispatch Mode Selection

| Scenario | Use |
|----------|-----|
| Short task (< 30 min), no persistent state needed | **Mode A**: Agent tool with `isolation: "worktree"` |
| Long-running curation, needs observability, multi-hour | **Mode B**: External tmux + `claude` CLI |
| Sequential cross-repo pipeline (lock-heavy) | Mode B preferred (lock persistence) |
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

**Best for:** ingredient mapping batches, schema validation, report generation,
read-only analysis, tasks where you need the result before proceeding.

**Limit:** ~5-6 parallel agents without saturating context.

---

## Mode B — External tmux Agents

For long-running or observable tasks. Each agent runs in its own tmux session
with its own worktree under `~/worktrees/`.

### Setup (one-time)

```bash
mkdir -p ~/worktrees
```

### Dispatch a worker

```bash
# 1. Create worktree on a new branch
git -C ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
  worktree add ~/worktrees/culturemech-<slug> -b feat/<slug>

# 2. Start tmux session
tmux new-session -d -s <slug> -c ~/worktrees/culturemech-<slug>

# 3. Launch Claude Code in the session
tmux send-keys -t <slug> \
  "claude --dangerously-skip-permissions" Enter

# 4. Wait for prompt to appear (~3-5s), then deliver task
sleep 4
tmux send-keys -t <slug> "<task prompt>" Enter
```

**Combined one-liner:**
```bash
SLUG="mim-enrich-batch3"
REPO=~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech
git -C $REPO worktree add ~/worktrees/$SLUG -b feat/$SLUG && \
tmux new-session -d -s $SLUG -c ~/worktrees/$SLUG && \
tmux send-keys -t $SLUG "claude --dangerously-skip-permissions" Enter && \
sleep 5 && \
tmux send-keys -t $SLUG "map the unmapped ingredients in batch — prioritize simple chemicals" Enter
```

---

## Multi-Repo Coordination (REQUIRED for workers that modify repos)

Workers that write to CultureMech, MIM, or CommunityMech **must** use the lock manager.
Include this in every worker prompt that touches a downstream repo:

```
"Before modifying any files in [REPO], acquire a lock via:
  from plugins.lock_manager import LockManager
  lm = LockManager(); lm.acquire_lock('culturemech', '<slug>')
Release it when done. Never modify two repos simultaneously."
```

**Lock ownership rules:**
- CultureMech lock: required before editing `data/normalized_yaml/**`
- MIM lock: required before editing `data/ingredients/**`
- CommunityMech lock: required before editing community YAML files
- culturebotai-claw: no lock needed (orchestration repo, boss owns it)

Lock files live in `culturebotai-claw/workspace/locks/` and expire after 1 hour.

---

## Planning

Before dispatching, use TodoWrite. For each task, note:

- **Slug**: short (< 20 chars), lowercase, hyphens, no repo prefix. `enrich-feba-b4` not `culturemech-enrich-feba-b4`
- **Target repo**: which downstream repo is being modified
- **Lock needed**: yes/no and which repo
- **Initial prompt**: one line — workers know the skills, don't repeat them
- **Mode**: A (in-process) or B (external tmux)

Confirm plan with the user before dispatching > 3 tasks or if repos overlap.

---

## Workflow

```
plan → dispatch → verify → monitor → steer → PR → complete → clean
```

### Dispatch (Mode B) — ordered steps, do not skip

#### Step 1: Create worktree

```bash
git -C <REPO_PATH> worktree add ~/worktrees/<slug> -b feat/<slug>
```

Target repos and paths:
```
CultureMech:   ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech
MIM:           ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech
CommunityMech: ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CommunityMech/CommunityMech
```

#### Step 2: Start session + launch agent

```bash
tmux new-session -d -s <slug> -c ~/worktrees/<slug>
tmux send-keys -t <slug> "claude --dangerously-skip-permissions" Enter
sleep 5   # wait for TUI to render
```

#### Step 3: Verify prompt window appeared

```bash
tmux capture-pane -t <slug> -p | tail -5
# Should show claude TUI with input prompt, not a shell prompt
```

#### Step 4: Deliver task prompt

```bash
tmux send-keys -t <slug> "<one-line task>" Enter
```

#### Step 5: Verify task landed

```bash
sleep 3
tmux capture-pane -t <slug> -p | tail -10
# Should show the agent processing the task, not waiting at input
```

If prompt didn't land, redeliver:
```bash
tmux send-keys -t <slug> "<task>" Enter
```

---

## Monitor

```bash
# List all sessions
tmux list-sessions

# Watch a specific session (exit with q)
tmux capture-pane -t <slug> -p -S -50 | tail -30

# Attach briefly to observe (detach with Ctrl-B D)
tmux attach -t <slug>
```

---

## Steer

Send follow-ups to an active agent:
```bash
# Wait for agent to be at input prompt, then send
tmux send-keys -t <slug> "<follow-up instruction>" Enter
```

---

## Stuck-Agent Protocol

Symptoms: session shows repeated failures, confusion, or no output for > 10 min.

1. Capture and read recent output: `tmux capture-pane -t <slug> -p -S -100 | tail -50`
2. **Nudge once**: `tmux send-keys -t <slug> "<clarifying instruction>" Enter`
3. If still stuck after one nudge: flag to user with session name, symptom, proposed fix
4. Do not rescue the same session more than twice — escalate

---

## PR Follow-Through

**A PR opened is NOT completion.** PRs are reviewed by @marcin (human review — no automated
claude-review bot in CultureBotAI repos). A task is done when:
- PR is opened with passing validation
- Human has reviewed and approved
- Branch is merged

After worker reports "PR opened":
```bash
# Get PR URL
tmux send-keys -t <slug> "gh pr view --json url -q .url" Enter
# Then: note the URL, notify user for review
```

Mark the task as needing human review, don't tear down until merged.

---

## Tear Down

```bash
# After PR is merged:
tmux kill-session -t <slug>
git -C <REPO_PATH> worktree remove ~/worktrees/<slug>
git -C <REPO_PATH> branch -d feat/<slug>
```

Batch clean (for multiple completed slugs):
```bash
# List all worktrees in ~/worktrees/
ls ~/worktrees/
# Remove each confirmed-done one
```

---

## CultureBotAI-Specific Task Templates

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
| Create worktree | `git -C <repo> worktree add ~/worktrees/<slug> -b feat/<slug>` |
| Start session | `tmux new-session -d -s <slug> -c ~/worktrees/<slug>` |
| Launch agent | `tmux send-keys -t <slug> "claude --dangerously-skip-permissions" Enter` |
| Send task | `tmux send-keys -t <slug> "<task>" Enter` |
| Read output | `tmux capture-pane -t <slug> -p -S -50 \| tail -30` |
| Attach | `tmux attach -t <slug>` (Ctrl-B D to detach) |
| List sessions | `tmux list-sessions` |
| Kill session | `tmux kill-session -t <slug>` |
| Remove worktree | `git -C <repo> worktree remove ~/worktrees/<slug>` |
| Check locks | `ls culturebotai-claw/workspace/locks/` |
| Release stale lock | `rm culturebotai-claw/workspace/locks/<repo>.lock` |

---

## Red Flags — STOP

| Thought | Reality |
|---------|---------|
| "I'll skip the worktree, just use the repo directly" | No. Multiple agents on the same checkout corrupt each other's state. |
| "Two agents can work on the same repo simultaneously without a lock" | No. Lock manager exists precisely for this. Each worker acquires the lock before writing. |
| "The prompt says 'in parallel' so I'll use boss" | Only if the user explicitly named boss / tmux / external agents. Otherwise use the Agent tool with `isolation: "worktree"`. |
| "PR opened = done, tear down now" | No. Wait for human review (@marcin) and merge before cleaning up. |
| "I'll send follow-ups without checking the agent is at input" | The agent may be mid-execution. Capture the pane first; only send when you see the input prompt. |
| "I'll modify two repos at once from the same worktree" | No. One worktree = one target repo. Cross-repo tasks get sequential lock acquisition. |
| "The worker needs to know about CLAUDE.md rules / validation steps / skill names" | No. Workers inherit CLAUDE.md and all skills automatically. One-line prompts only. |

---

## Comparison: Boss vs. In-Process Agents

| | Boss (external tmux) | Agent tool (in-process) |
|--|---------------------|------------------------|
| **Observability** | Full tmux pane, real-time | Result only |
| **Duration** | Hours, survives session end | Minutes, session-bound |
| **Setup** | Manual (worktree + tmux) | Automatic (Claude handles) |
| **Parallelism** | Unlimited (separate processes) | ~5-6 before context pressure |
| **Lock handling** | Worker acquires lock explicitly | Boss acquires before dispatch |
| **PR workflow** | Worker opens PR, boss monitors | Boss gets result, opens PR itself |
| **Best for** | Multi-hour curation, enrichment | Short analysis, report gen, search |

---

## Install tp (optional — recommended for larger batches)

`tp` (tmux-pilot) wraps the above tmux workflow into single commands with built-in
readiness detection, status tracking, and batch management. Install via:

```bash
pip install tmux-pilot   # or: pipx install tmux-pilot
```

Once installed, replace the manual tmux commands above with:
```bash
tp new <slug> --profile claude --repo <path> --branch feat/<slug> --prompt "<task>"
tp ls --json
tp peek <slug> -n 30
tp send --wait <slug> "<follow-up>"
tp kill <slug>
```

See the dismech boss skill (monarch-initiative/dismech PR #1150) for full `tp` documentation.

---

## Related Skills

- `cross-repo-sync` — standard sync sequence; good candidate for boss dispatch
- `feba-integration` — long-running enrichment pipeline; ideal for Mode B
- `cas-rn-integration` — bounded enrichment; can run Mode A or B
- `evidence-curation` (CommunityMech) — snippet repair; good Mode B task
