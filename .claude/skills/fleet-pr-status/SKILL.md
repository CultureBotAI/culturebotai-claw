---
name: fleet-pr-status
description: "Answer \"what PRs are open?\" across claw and the five Mech repos in one standard format. Runs scripts/fleet_pr_status.py, which discovers repos from the GitHub org, queries each with explicit limits, and always reports its own coverage — which repos were checked, which failed, whether any listing truncated. Read-only inventory: it does not review, edit, or merge anything."
category: cross-repo
requires_database: false
requires_internet: true
version: 1.0.0
tags: [pr, status, cross-repo, fleet, inventory, read-only, reporting]
---

# Fleet PR status

## Purpose

Answer one question, the same way every time: **what is open across the fleet
right now?**

Use this before a merge round, when picking up work, or any time someone asks
"any open PRs?". It is a thirty-second inventory, not an analysis.

## Run it

```bash
uv run python scripts/fleet_pr_status.py            # table + datestamped TSV
uv run python scripts/fleet_pr_status.py --json     # machine-readable
uv run python scripts/fleet_pr_status.py --no-drafts
uv run python scripts/fleet_pr_status.py --no-tsv   # table only
uv run python scripts/fleet_pr_status.py --tsv-dir DIR
uv run python scripts/fleet_pr_status.py --repo-limit 500   # org grew
uv run python scripts/fleet_pr_status.py --pr-limit 500     # a repo has >200 open
```

**Two limits, not one**, because they bound unrelated things and fail
differently:

- `--repo-limit` (default 300) caps org discovery. Truncating here drops
  **entire repos** from the report. Proven: `--repo-limit 5` against a 38-repo
  org silently loses CommunityMech and proteintraitsmech.
- `--pr-limit` (default 200) caps open PRs listed per repo. Truncating here
  undercounts *within* a repo that is still present.

Each warns separately and names the flag to raise, so the message tells you
which knob to turn rather than leaving you to guess.

Exit codes: `0` report produced, `1` at least one repo could not be queried,
`2` bad usage or `gh` missing. **A non-zero exit means the report is
incomplete** — do not quote its total as if it were the answer.

## The datestamped TSV

Every run also writes a snapshot to `workspace/reports/` (gitignored):

```
workspace/reports/fleet_pr_status_2026-08-04.tsv
```

15 fixed columns — `snapshot_utc, repo, number, url, title, state, mergeable,
is_draft, author, additions, deletions, changed_files, head_ref, created_at,
updated_at` — so snapshots from different days diff and concatenate cleanly.
Append new columns at the end rather than inserting.

It is written **unquoted**: every field is whitespace-flattened first, so no
cell can contain a tab or newline and `cut -f5` / `awk -F'\t'` work directly.
That is the point of choosing TSV over CSV, and csv's default quoting would
have wrapped any title containing a double quote and doubled its quotes —
correct to a `csv` reader, mangled to every naive consumer.

Three further properties worth knowing:

- **The TSV keeps drafts even when `--no-drafts` hides them from the table.**
  The table is a view; the TSV is the record. `is_draft` lets any consumer
  filter for itself, and a data export that silently omits rows is the exact
  failure this script exists to avoid.
- **An incomplete snapshot is named `.partial.tsv`.** If a repo could not be
  queried, or either listing truncated, the fact travels *in the filename* —
  the console warning does not survive, and a month later the file is all
  anyone has.
- **Re-running on the same date overwrites.** The file means "the state on that
  date", not an append log. `snapshot_utc` carries the full timestamp, so the
  last run of a day is identifiable.

`--no-tsv` prints the table only; `--tsv-dir` puts it elsewhere.

## Report the output as-is

The script's format *is* the standard. Do not re-summarise it into prose that
drops the coverage section, and do not silently reformat between runs — two
runs should diff cleanly. If the reader needs a narrative, put it *after* the
report, not instead of it.

Sample:

```
Open PRs across the CultureBotAI fleet: 7

REPO                     PR  STATE              SIZE  TITLE
culturebotai-claw       #63  ok               +71/-0  Write imported records back into…
MediaIngredientMech    #195  CONFLICTS  +25842/-2246  Promote the 386 reviewed…

Coverage
  queried 6 repos: culturebotai-claw=1, CultureMech=2, …, TraitMech=0
```

## Why a script and not `gh pr list` in a loop

Because the ad-hoc version has produced wrong answers here, and every one was a
**denominator** problem — a count that looked complete and was not:

- **Both `gh` listings truncate silently.** `gh pr list` and `gh issue list`
  default to **30**; `gh repo list` caps at its limit with no signal. The
  script passes explicit limits and warns when either is reached, naming which
  one so you know whether whole repos or only PRs were lost.
- **A failed repo query vanishes from a hand-rolled loop.** `for r in …; do gh
  pr list …; done` prints nothing for a repo that 502s, which reads identically
  to "nothing open". The script names it, and marks the total a lower bound.
- **Filesystem discovery misses repos.** ProteinTraitsMech was invisible to
  local sweeps for weeks; a stale clone also misreports a repo's state entirely.
  Discovery is from the org, and nothing here reads a working tree.
- **A repo with zero open PRs must still appear.** Otherwise "checked, nothing
  there" is indistinguishable from "not checked".

## Reading the STATE column

- `ok` — GitHub reports MERGEABLE.
- `CONFLICTS` — genuinely conflicting *by GitHub's reckoning*.
- `?` — **UNKNOWN, not a problem.** GitHub computes mergeability lazily, so a
  freshly-pushed or freshly-rebased PR reports UNKNOWN until asked again. Query
  it a second time before believing anything.

One caveat worth knowing: GitHub and git can disagree. A PR that modifies a file
`main` has since renamed is a modify/delete, which `git merge-tree` resolves via
rename detection while GitHub's check reports CONFLICTING. **GitHub's answer is
the one that gates the merge button** — if they disagree, merge `main` into the
branch explicitly and verify the result, rather than concluding it is fine
because git said so.

## Boundaries

- **This does not review anything.** For a per-PR verdict with findings, use
  `fleet-pr-review`, which is the deep pass; this is the breadth-first
  inventory that tells you what to point it at.
- **Read-only.** It never edits, pushes, comments, or merges.
- **It reports state, not judgement.** "7 open" is the deliverable; deciding
  which to work is a separate step, and merging is always a human call.

## Adding a repo to the fleet

Membership is the regex `(?i)mech$|^culturebotai-claw$` in
`scripts/fleet_pr_status.py`. Anything matching is included automatically, so a
sixth Mech needs no code change — it appears in the report and is **flagged** as
a repo not in the known list, rather than being silently absorbed. Add it to
`PREFERRED_ORDER` to fix its position in the table.

A repo that does not end in `mech` needs the pattern widened. Note that
`PFASCommunityAgents`, `MicroGrowAgents` and `kg-microbe` are deliberately
**out** of scope.

## Tests

`tests/test_fleet_pr_status.py` covers the failure paths rather than the happy
one, because a clean run is not where this can mislead you. Every guard is
mutation-checked — each of these fails at least one test when removed:

| mutation | |
|---|---|
| silently drop a failed repo | render + `collect` |
| render UNKNOWN as CONFLICTS | render |
| suppress either truncation warning | render |
| stop *detecting* truncation in `collect` | `collect` |
| hide drafts without saying so | render |
| omit zero-PR repos from coverage | render |
| absorb a new Mech unflagged | render |
| cut a title with no marker | render |

The `collect` rows exist because of a hole the split exposed: mutating
`collect()` to stop recording PR truncation passed every test, since `render()`
was covered against hand-built data while the code that *builds* it was not
exercised at all. That is precisely the guard-that-verifies-nothing this script
exists to catch, found inside the script's own tests. `collect()` is now tested
by stubbing `_gh`, so discovery, listing, both truncation detections, error
capture and fleet filtering run offline.
