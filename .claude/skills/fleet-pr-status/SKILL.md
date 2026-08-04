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
uv run python scripts/fleet_pr_status.py            # the standard report
uv run python scripts/fleet_pr_status.py --json     # machine-readable
uv run python scripts/fleet_pr_status.py --no-drafts
uv run python scripts/fleet_pr_status.py --limit 500
```

Exit codes: `0` report produced, `1` at least one repo could not be queried,
`2` bad usage or `gh` missing. **A non-zero exit means the report is
incomplete** — do not quote its total as if it were the answer.

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
  default to **30**; `gh repo list` caps at `--limit` with no signal. The script
  passes an explicit limit and warns when a listing reaches it.
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
one, because a clean run is not where this can mislead you. Mutation-checked:
silently dropping a failed repo, rendering UNKNOWN as a conflict, suppressing
the truncation warning, hiding drafts without saying so, omitting zero-PR repos
from coverage, and absorbing a new Mech unflagged each fail at least one test.
