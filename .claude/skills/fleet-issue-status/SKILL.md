---
name: fleet-issue-status
description: "Answer \"where does the fleet stand?\" as one table: per repository, the open-issue count, how many are unassigned, how many have gone quiet, the age of the oldest, and the open-PR count beside it, across claw and the manifest-defined Mech fleet. Runs scripts/fleet_issue_status.py, which queries the canonical fleet with explicit limits and always reports its coverage — which repos were checked, which failed, and whether any listing truncated. Read-only inventory: it does not triage, edit, close, or comment on anything."
category: cross-repo
requires_database: false
requires_internet: true
version: 1.0.0
tags: [issues, pr, status, cross-repo, fleet, inventory, read-only, reporting]
---

# Fleet issue status

## Purpose

Answer **how much is open, where, and how long has it sat?** in one table.

`fleet-pr-status` lists every open PR. This is the issue side, and because the
fleet carries hundreds of open issues at a time, the table is one row per
repository rather than one per issue. The per-issue record is the datestamped
TSV. The PR count sits in the same row so one run answers "PRs and issues
across the Mechs" without reconciling two reports.

Use it when picking a repository to work in, before a triage round, or when
someone asks "how big is the backlog?".

## Run it

```bash
uv run python scripts/fleet_issue_status.py                 # table + datestamped TSV
uv run python scripts/fleet_issue_status.py --json          # machine-readable
uv run python scripts/fleet_issue_status.py --no-prs        # issues only
uv run python scripts/fleet_issue_status.py --stale-days 30
uv run python scripts/fleet_issue_status.py --issue-limit 1000   # a repo has >500 open
uv run python scripts/fleet_issue_status.py --no-tsv
uv run python scripts/fleet_issue_status.py --tsv-dir DIR
```

`--issue-limit` (default 500) and `--pr-limit` (default 200) cap what is
listed per repository. Reaching a cap undercounts that repository, so the
report names it and the flag to raise. Membership has no limit: it comes from
the canonical fleet manifest.

Exit codes: `0` report produced, `1` at least one repository could not be
queried or a listing truncated, `2` bad usage or `gh` missing. **A non-zero
exit means the report is incomplete** — do not quote its totals as the answer.

## Reading the table

```
Open issues across the CultureBotAI fleet: 504; open PRs: 1

REPO                  ISSUES UNASSIGNED STALE 60d+  OLDEST  PRs CONFLICTS DRAFTS
culturebotai-claw         51         51         12    240d    0         0      0
CultureMech               46         46          9    310d    0         0      0
…

Coverage
  queried 11 repos: culturebotai-claw=51, CultureMech=46, …
  stale = no update in 60+ days as of 2026-09-13T10:00:00+00:00; issue counts exclude pull requests
```

- **ISSUES** — open issues from `gh issue list`. This is *smaller* than the
  `open_issues_count` badge on the repository page, which counts pull
  requests too. The report's number is the one that means "issues".
- **UNASSIGNED** — open issues with no assignee. In this fleet that is usually
  all of them; the column exists so the exceptions are visible.
- **STALE Nd+** — no update (comment, label, edit) in `--stale-days` or more,
  measured from the snapshot timestamp, never the wall clock. A snapshot
  summarises the same way whenever it is read.
- **OLDEST** — age of the oldest open issue.
- **PRs / CONFLICTS / DRAFTS** — open PRs, how many GitHub reports as
  CONFLICTING, how many are drafts. `UNKNOWN` mergeability is not counted as a
  conflict; see `fleet-pr-status` for why.
- A row reading `?  ?  ?  NOT QUERIED` is a repository the query failed for.
  It is deliberately not a row of zeros.

## The datestamped TSV

Every run writes a snapshot to `workspace/reports/` (gitignored):

```
workspace/reports/fleet_issue_status_2026-09-13.tsv
```

13 fixed columns — `snapshot_utc, repo, number, url, title, labels, assignees,
author, milestone, created_at, updated_at, age_days, days_since_update` —
one row per open issue, in manifest order. Append new columns at the end.

It is written **unquoted** with every field whitespace-flattened, so `cut -f5`
and `awk -F'\t'` work directly, and cells beginning with `=`, `+`, `-` or `@`
are prefixed with an apostrophe so a spreadsheet does not execute them. An
incomplete snapshot is named `.partial.tsv`, because the console warning does
not survive and a month later the file is all anyone has. Re-running on the
same date overwrites.

## Report the output as-is

The script's format *is* the standard. Do not re-summarise it into prose that
drops the coverage section. If the reader needs a narrative — which
repositories to triage first, say — put it *after* the report, not instead.

## Why a script and not `gh issue list` in a loop

The same denominator traps that justify `fleet-pr-status`:

- **`gh issue list` truncates silently** at 30 by default. The script asks for
  one row more than its cap and names any repository where that probe row
  came back.
- **A failed repository query vanishes from a hand-rolled loop**, and reads as
  "nothing open there". The script names it and marks the totals lower bounds.
  A repository whose issue query succeeded but whose PR query failed is an
  error too; half a row would read as a whole one.
- **Membership is declared, not discovered.** The manifest defines the fleet;
  a repository with zero open issues still appears in coverage, so "checked,
  nothing there" is distinguishable from "not checked".

## Boundaries

- **Read-only.** It never edits, closes, labels, or comments.
- **It reports state, not judgement.** Which issue to work is a separate step.
  For claw's own queue with prioritisation, use `review-open-issues`.
- **It does not review PRs.** `fleet-pr-review` is the deep pass.

## Tests

`tests/test_fleet_issue_status.py` covers the failure paths, and each guard is
mutation-checked — removing it fails at least one test:

| mutation | caught by |
|---|---|
| drop a failed repository from `errors` | `collect` error tests |
| stop detecting issue or PR truncation | `collect` truncation tests |
| count the probe row | probe-row test |
| render an unqueried repo as zeros | render error test |
| measure staleness from the wall clock | passed-`now` test |
| write the TSV quoted, or let a tab shift a column | TSV tests |
