---
name: next-tasks
description: "Assess and maintain the {{ display_name }} backlog. Reconciles NEXT_TASKS.md against what actually shipped (merged PRs, git log, open issues/PRs), separates genuinely-pending actionable work from done/stale/upstream-blocked items, surfaces a short prioritized menu with a recommendation, and — when asked — picks one up. Use whenever the user asks \"next tasks\", \"what's next\", \"is the backlog current\", or after finishing a work thread."
category: workflow
requires_database: false
requires_internet: true
version: 1.0.0
tags: [backlog, triage, planning, maintenance]
---

# Next Tasks (backlog assessment + maintenance)

## Overview

- Repository: `{{ github }}`
- Backlog: `NEXT_TASKS.md`

**Purpose**: answer "what should I work on next?" *accurately*, and keep
`NEXT_TASKS.md` honest while doing it.

**When to use**: the user says "next tasks" / "what's next" / "anything left?",
or a work thread has just finished.

**When NOT to use**: this section is {{ display_name }}'s. Say what this
repository does *instead* of this skill for discovering brand-new work, and
name the skill that does it. This skill works the *existing* backlog.

## Workflow

### Step 1 — Reconcile

<!-- canonical:begin reconcile-commands -->
```bash
sed -n '1,400p' NEXT_TASKS.md
git log --oneline -20
gh pr list --state merged --limit 20 --json number,title,mergedAt \
  -q '.[] | "\(.number)\t\(.mergedAt[:10])\t\(.title)"'
gh pr list  --state open  --limit 20 2>/dev/null | head
gh issue list --state open --limit 30 2>/dev/null | head -30
```
<!-- canonical:end reconcile-commands -->

For each pending item: *is its deliverable already in a merged PR or in the
code?* If yes → DONE. Spot-check any slot/recipe/file the item names
(`grep -rl <slot> {{ package_path }}/schema/`) — backlog notes cite things that
were later renamed.

{{ display_name }}-specific traps when judging "done":

- Replace this list with the traps that actually bite here. They are the reason
  anyone reads this skill, and no template can supply them: a fix applied to
  one data surface and not its twin, a warn-mode gate whose green exit hides a
  count, a record set addressed by a slug that is only unique within a
  category. Whatever has caught someone out in this repository belongs here.

### Step 2 — Present the menu

Short, ranked, with reasons. For each candidate say what it unblocks and what
it costs. Then:

- **recommend one** — usually the item that continues the active thread, is
  fully specified, or unblocks the most downstream work.

### Step 3 — Maintain NEXT_TASKS.md (every invocation, even if only bookkeeping)

- Mark shipped items **DONE (YYYY-MM-DD, PR #NNN)** in place, or move them out.
- Add anything newly deferred, with enough context to restart cold.
- Bump the reconcile date.

### Step 4 — Pick it up (only if the user says to)

Follow this repository's own change conventions: branch, work, run its gates,
open a PR, watch CI, squash-merge with `--delete-branch`, then re-run Step 3 to
record the new state.

## Conventions this skill enforces

<!-- canonical:begin conventions -->
- **Reconcile-before-relay**: the file is a starting point, not ground truth.
- **Honest classification**: don't recommend upstream-blocked items; don't hide
  them either.
- **Every invocation updates the file** (at minimum the reconcile date).
- **Absolute dates**, PR numbers on done items, cold-start context on new items.
<!-- canonical:end conventions -->

## Notes & limitations

{{ display_name }}'s. Record what this skill cannot see here — vendored files
it must not edit, gates whose green exit does not mean zero findings, corpora
too large to read in one pass.

## Related files

- `NEXT_TASKS.md` — the backlog this skill reads and maintains.
