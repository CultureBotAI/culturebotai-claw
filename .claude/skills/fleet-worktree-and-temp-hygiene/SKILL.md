---
name: fleet-worktree-and-temp-hygiene
description: "Audit temporary directories (/tmp/, /private/tmp, $TMPDIR), claw/workspace/, registered and prunable git worktrees, local branches, stashes, and lock leases across claw, the manifest-defined Mech fleet, CultureBotAI.github.io, and kg-microbe. Flags helper scripts in temp roots that must be promoted to scripts/adhoc/ for provenance before macOS 4-day cleanup. Read-only."
category: cross-repo
requires_database: false
requires_internet: false
version: 1.0.0
tags: [fleet, hygiene, worktrees, branches, locks, temp, provenance, read-only]
---

# Fleet Worktree, Branch, Lock, and Temp Hygiene

Run the read-only hygiene inspector from the `culturebotai-claw` root:

```bash
uv run python scripts/fleet_git_and_temp_hygiene.py
just fleet-hygiene
```

## Purpose

Answer in one offline, zero-mutation pass:

1. **What Mech/KG-Microbe artifacts are sitting in `/tmp/`, `/private/tmp`, and `$TMPDIR`?**
   - Deduplicates symlinked roots (on macOS `/tmp/` resolves to `/private/tmp`) so items are never double-counted.
   - Classifies every matching item into:
     - `PROVENANCE_PROMOTE_REQUIRED` — helper scripts (`.py`, `.sh`, `.R`, `.jq`, `.sql`) in temporary directories. Under the repository provenance agreement, helper scripts must live in `<repo>/scripts/adhoc/` (or the target repository's designated script directory), never in `/tmp/`.
     - `TEMP_GIT_CHECKOUT` — temporary clones or worktrees (`cross-mech-*`, `.git`-bearing directories).
     - `TOOL_CACHE_OR_PROFILE` — regenerable caches or sandbox profile directories (`*pip-audit-cache*`, `pytest_cache*`, `claude-*`, `codex*`).
     - `SCRATCH_DATA_OR_LOG` — intermediate TSV/JSON/log outputs.
   - Flags items approaching or exceeding the **macOS 4-day (`96h`) reaper window** (`reaper_risk=true` when `age_days >= 3.0`).
2. **What is inside `workspace/` in `culturebotai-claw`?**
   - Cross-references subdirectories of `workspace/` against `git worktree list --porcelain` so active linked worktrees (`REGISTERED_WORKTREE`) are never mistaken for leftover directories (`ORPHAN_WORKTREE`) or runtime data (`RUNTIME_STATE`).
   - Inspects `workspace/locks/*.lock` and `*.lock.guard` **strictly read-only** (never calling `cleanup_expired_locks()`, never acquiring a lease, and never deleting a lock file) and classifies each lock as `ACTIVE`, `DEAD_PID`, `EXPIRED`, `ORPHAN_GUARD`, or `MALFORMED`.
3. **What is the local Git, worktree, branch, and stash state across every repository?**
   - Resolves `claw`, all 14 manifest-declared Mechs, the companion `CultureBotAI.github.io` checkout, and `kg-microbe`.
   - Reports current branch, dirty tracked files, untracked count, stash count, in-progress Git operations (`merge`, `rebase`, `cherry-pick`, `bisect`), registered vs prunable worktrees, non-default local branches (merged vs unmerged into `origin/main`), and duplicate sibling checkouts (`sibling_shadow`: a checkout at the default sibling path that is not the root `.env` configures, such as a CommunityMech clone beside claw while `.env` points at one nested a level deeper).

## Options

```bash
uv run python scripts/fleet_git_and_temp_hygiene.py --json
uv run python scripts/fleet_git_and_temp_hygiene.py --claw-root /path/to/culturebotai-claw
uv run python scripts/fleet_git_and_temp_hygiene.py --tmp-root /private/tmp
```

## Interpreting findings and next steps

- **`TEMP_PROVENANCE_RISK` (`PROVENANCE_PROMOTE_REQUIRED`)**:
  Inspect the script in `/tmp/`. If its output contributed to a commit, figure, issue, or PR, copy it into `<repo>/scripts/adhoc/` in the appropriate repository with a header comment (purpose, inputs, outputs, issue/PR, date) before any cleanup.
- **`ORPHAN_WORKTREE`**:
  A directory under `workspace/` carrying a `.git` file/directory that is no longer registered in `git worktree list`. Inspect `git status` and unpushed commits inside it before deciding whether to archive or clean up via `/fleet-repo-crud-cleanup`.
- **`PRUNABLE_WORKTREE`**:
  A worktree entry registered in `<repo>/.git/worktrees` whose working directory is gone. Safe to prune with `git worktree prune` once verified.
- **`SIBLING_SHADOW_CHECKOUT`**:
  A second checkout of the same repository under a sibling path. Verify which path `.env` points to (`openclaw-cli config validate`) and check whether the shadowed directory holds unique local branches or stashes before retiring it.
- **Remote branch parity**:
  Pair this local hygiene report with `/fleet-branch-status` (`scripts/fleet_branch_status.py`) when auditing remote branches on GitHub.

## Boundaries

This skill and `scripts/fleet_git_and_temp_hygiene.py` are strictly **read-only**. They never delete files, remove worktrees, drop stashes, delete branches, or break locks. Any cleanup requires explicit human approval scoped to the concrete paths surfaced by the report.
