---
name: fleet-issue-status
description: "Find all open issues across Claw and the manifest-defined Mech repositories and rank repositories from most to least open issues. Produce console, Markdown, TSV, and JSON tables with per-issue priority and keep/close/defer review columns. Use for backlog counts and review intake; evidence-based decisions come from fleet-issue-review. Read-only on GitHub."
metadata:
  category: cross-repo
  requires_database: false
  requires_internet: true
  version: 1.1.0
  tags: [issues, pr, status, cross-repo, fleet, inventory, read-only, reporting]
---

# Fleet issue status

Use `scripts/fleet_issue_status.py` as the shared inventory for status and review.
It includes Claw plus the canonical manifest's Mechs, even repositories with no
local clone or no open issues. It does not enumerate every repository in a
GitHub organization or on the machine. State that scope in the report; use
explicit identities when a subset is requested.

Run from an identity-verified Claw checkout at the current published default
revision so the script and packaged manifest agree. Follow
[fleet-issue-review](../fleet-issue-review/SKILL.md)'s baseline procedure when
this inventory feeds a review. A development branch must disclose its base and
any inventory changes; do not describe it as released tooling.

## Run it

```bash
# Full inventory, descending repository counts, with a per-issue TSV.
uv run python scripts/fleet_issue_status.py --all-issues --no-prs

# Markdown repository summary plus every issue and its review fields.
uv run python scripts/fleet_issue_status.py --all-issues --no-prs --markdown

# Machine-readable metadata, summary and issue rows.
uv run python scripts/fleet_issue_status.py --all-issues --no-prs --json

# Add the count of issues closed in the last seven days.
uv run python scripts/fleet_issue_status.py --all-issues --no-prs --closed-days 7 --markdown

# A named subset, also useful for the one-repository canary.
uv run python scripts/fleet_issue_status.py --all-issues --no-prs --repo CultureBotAI/culturebotai-claw
```

Before a fleet run, run one selected repository end to end through the same
command and environment, then verify the saved report and TSV are nonempty and
match the fetched count. Use a fresh report directory under `workspace/reports/`
for each acquisition; `--tsv-dir` selects that directory. Capture stdout to a
Markdown or JSON file as appropriate and preserve stderr and exit status.

Use `--all-issues` for "all open issues": it paginates and checks an independent
issue count. Without it, the existing `--issue-limit` (default 500) uses a cap
plus one probe row to detect truncation. PR counts remain optional and capped
by `--pr-limit` (default 200); `--no-prs` avoids that query for issue-only work.
`--stale-days` defaults to 60. `--no-tsv` suppresses TSV output.

Exit codes are `0` for a complete inventory, `1` for failed or truncated queues,
and `2` for invalid input or unavailable tooling. An incomplete report is still
useful, but its counts are lower bounds and its ranking provisional. Never
turn an inaccessible queue into zero. Inventory completeness is not evidence
review completeness or an atomic GitHub snapshot.

## Tables and decisions

The repository table is sorted by decreasing issue count, with manifest order
breaking ties and failed queues last. It retains the unassigned, stale, oldest,
and optional PR columns and adds review-progress/action counts. Issue counts
exclude pull requests, unlike GitHub's repository `open_issues_count`.

When requested, add `--closed-days 7` for a rolling seven-day closure count.
The window is fixed in UTC for the whole acquisition and saved in the output.
This counts currently closed issues whose latest closure falls in the window,
not every close event for reopened issues. PRs are excluded. A failed closure
query remains unknown and marks coverage partial without dropping the known
open-issue count. JSON retains the counted issue identities and closure times.

The full issue table starts at priority `Unranked` and action `unreviewed`.
It carries source labels separately. Read the shared
[report contract](references/review-table.md) to populate reviewed priority,
keep/close/defer recommendations, reasons, evidence, and deferral triggers using
`--triage-file`. Counts and age alone do not establish urgency or justify closure.

Use [fleet-issue-review](../fleet-issue-review/SKILL.md) for the evidence pass
across Mechs and [review-open-issues](../review-open-issues/SKILL.md) for Claw's
queue. Both feed this inventory format. A request for the table alone leaves
unassessed issues explicitly unreviewed. Read source bodies, all comments,
linked PRs, and current published code before filling recommendations.

Return the repository table and a link to the complete Markdown and structured
artifacts, preserving the coverage section. Include zero-issue repositories and
errors. The Markdown ledger is full-length even when the session summary is short.
Use `--markdown-file` with an output path to save the Markdown from the same
acquisition as console or JSON output, rather than querying the fleet twice.

## Boundaries and persistence

This script reads GitHub and writes local reports. The review overlay records
recommendations; it does not label, close, comment, assign, or defer issues on
GitHub. Applying decisions is a separate authorized action. Preserve pending
human review and other standing permission requirements.

The TSV retains its original 13 columns and appends review fields. It flattens
whitespace and neutralizes spreadsheet formulas. Partial snapshots carry
`.partial.tsv`; rerunning on the same date in the same output directory replaces
the prior TSV. Keep a separate decisions file and use fresh acquisition directories
so refreshes do not erase review history. Markdown and JSON emitted on stdout
carry coverage warnings themselves.

`tests/test_fleet_issue_status.py` verifies collection, ordering, review overlays,
rendering, and output safety. The canonical code, skills, and tests all live in
Claw; installed skill links and `.agents/skills` reuse that source.
