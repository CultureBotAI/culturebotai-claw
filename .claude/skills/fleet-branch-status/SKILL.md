---
name: fleet-branch-status
description: "Catalogue every branch across claw and the manifest-defined Mech fleet — what each one is (merged leftover, open PR, no PR at all), how old it is, and whether it still holds commits main lacks. Runs scripts/fleet_branch_status.py, which always reports its coverage: which repos were catalogued, which failed, and whether any ref listing truncated. Read-only inventory: it never deletes, pushes, or merges a branch."
category: cross-repo
requires_database: false
requires_internet: true
version: 1.0.0
tags: [branches, status, cross-repo, fleet, inventory, cleanup, read-only, reporting]
---

# Fleet branch status

## Purpose

Answer **what branches exist across the fleet, and what is each one for?**

`fleet-pr-status` answers the same breadth-first question from the PR side and
cannot see two things: a branch with no PR, and a branch whose PR merged and was
never deleted. Both are common here. The first time this ran the fleet held 50
non-default branches, of which 3 had an open PR and 47 were merged leftovers.

Use it before a cleanup round, when a repository feels cluttered, or to find
work someone started and never opened a PR for.

## Run it

```bash
uv run python scripts/fleet_branch_status.py            # table + datestamped TSV
uv run python scripts/fleet_branch_status.py --json     # machine-readable
uv run python scripts/fleet_branch_status.py --no-compare   # skip ahead/behind
uv run python scripts/fleet_branch_status.py --stale-days 30
uv run python scripts/fleet_branch_status.py --ref-limit 1000
uv run python scripts/fleet_branch_status.py --no-tsv
```

Exit codes: `0` catalogue produced, `1` a repository could not be queried or a
ref listing truncated, `2` bad usage or `gh` missing. **A non-zero exit means
the catalogue is incomplete** — do not quote its total as the answer.

## Reading the report

### Never quote the branch count on its own

This is the whole reason the script exists. "50 branches" reads as fifty open
threads and was three. The first two lines are a unit:

```
Branches across the CultureBotAI fleet (excluding default): 50

  open-pr=3   no-pr=0   closed-pr=0   merged=47
```

Report them together, the same way `github-pages-status` refuses to report a
bare "N commits behind".

### DISPOSITION

| | |
|---|---|
| `merged` | an associated PR merged. The work landed; the branch is a leftover and can be deleted. |
| `open-pr` | an associated PR is open. In flight — `fleet-pr-status` is the report that covers it. |
| `closed-pr` | every associated PR was closed unmerged. Someone decided against it. |
| `no-pr` | no PR was ever opened. Either work nobody can see, or an abandoned experiment. |

`merged` wins over any other state. A branch whose PR merged and which later
had a second PR closed is finished, and calling it `closed-pr` would send
someone to redo work that already landed.

### AHEAD is not unfinished work — read it with DISPOSITION

**This fleet squash-merges.** A squash merge replays the branch as one new
commit, so the branch's own commits never appear on `main` and it reports
`ahead>0` forever. On the first run, 33 of the 47 merged branches read as ahead
by one to twelve commits, and none of it was unfinished.

- **`disposition=merged`** — AHEAD is a squash artifact. Ignore it. Deletable.
- **anything else** — AHEAD is the branch's genuinely unmerged commits, and
  `ahead=0` means `main` already contains everything the branch has.

Summing the AHEAD column would report a fully-landed fleet as carrying hundreds
of commits of open work. Don't.

`?` in AHEAD or BEHIND means **not measured**, not zero — either `--no-compare`
was passed or that repository's comparison failed. The coverage section says
which.

### The lines under Coverage

- `catalogued N repos: …` — the denominator. A repo with no branches still
  appears as `=0`, because "checked, nothing there" must not look like "not
  checked". A repo that failed appears as `=FAILED`.
- `N branch(es) have a merged PR and can be deleted` — the cleanup list.
- `N unmerged branch(es) hold no commits the default branch lacks` — deletable
  for a different reason: nothing is lost.
- `N branch(es) have no PR and no commit in 60+ days` — the interesting one.
  Work that exists and that no PR makes visible.

## Deleting what it finds

The script is **read-only**. It never deletes a branch, and it is not
permission to.

Deleting a branch in a downstream Mech is a cross-repository mutation and goes
through the checklist in `CLAUDE.md`: resolve the target through
`RepositorySettings`, confirm the worktree and `origin`, get approval, take the
lock. In practice a merged branch should have been deleted at merge time
(`gh pr merge --delete-branch`); a pile of them means that step was skipped, and
the fix is the habit rather than a bulk delete.

Treat `no-pr` branches as questions for their author, not as garbage. That is
exactly where unpushed-looking work hides.

## Why a script rather than `gh api .../branches` in a loop

Every ad-hoc version gets a denominator wrong:

- **A hand-rolled loop drops a repo that errors.** It prints nothing, which
  reads identically to "no branches there". The script names it and marks the
  total a lower bound.
- **Branch listings paginate.** A first page looks like the whole answer. The
  script paginates and reports when `--ref-limit` was reached.
- **Local clones disagree with the remote.** `git branch -r` reflects the last
  fetch and whatever stale remote-tracking refs a checkout kept. The script
  reads GitHub and no working tree.
- **Membership drifts.** Repositories are read from the canonical fleet
  manifest, so a Mech is catalogued because it is a fleet member, not because
  someone remembered it or because its name matched a pattern.

## The datestamped TSV

Every run also writes a snapshot to `workspace/reports/` (gitignored):

```
workspace/reports/fleet_branch_status_2026-09-09.tsv
```

12 fixed columns — `snapshot_utc, repo, branch, disposition, ahead, behind,
last_commit_utc, age_days, author, sha, pull_requests, url` — so snapshots from
different days diff and concatenate cleanly. Append new columns at the end
rather than inserting.

Three properties worth knowing, shared deliberately with `fleet-pr-status`:

- **Written unquoted.** Every field is whitespace-flattened first, so no cell
  can contain a tab or newline and `cut -f4` works directly.
- **An incomplete snapshot is named `.partial.tsv`.** The fact travels in the
  filename, because the console warning does not survive and a month later the
  file is all anyone has.
- **An unmeasured comparison is written empty, never `0`.** `0` means "contains
  nothing new"; empty means "not checked". Conflating them would mark branches
  deletable that were never examined.

## Boundaries

- **Read-only.** It never deletes, pushes, comments, or merges.
- **It reports state, not judgement.** Which branches to remove is a human call.
- **It does not review branch contents.** For what is *in* an open PR, use
  `fleet-pr-review`.
- **Membership comes from the manifest.** A GitHub repository that looks like a
  Mech but is not a declared fleet member is not catalogued; admitting it is a
  governance decision, not this script's.

## Tests

`tests/test_fleet_branch_status.py` covers the failure paths, and every guard is
mutation-checked — each of these turns at least one test red when removed:

| mutation | |
|---|---|
| swap `ahead` and `behind` | 2 tests |
| base the comparison on the branch instead of the default | 1 |
| let `CLOSED` outrank `MERGED` | 3 |
| drop a failed repository silently | 2 |
| stop detecting ref truncation | 1 |
| record a failed comparison as `0` rather than unknown | 1 |
| drop the squash-merge caveat | 1 |
| catalogue the default branch as a branch | 1 |
| omit zero-branch repos from coverage | 2 |
| count merged branches as stale no-PR work | 1 |

The comparison fixtures use `4` and `24` rather than a matched pair, because
`ref(X).compare(headRef: Y)` is symmetric in shape and not in meaning: with
equal values a swapped mapping passes. The direction was checked by hand against
`GET /compare/main...branch` before it was pinned.
