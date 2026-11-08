---
name: stats-report
description: "Generate reproducible corpus, field-population, grounding, and validation statistics from {{ display_name }}'s live records without relying on hardcoded snapshot counts."
category: reporting
requires_database: false
requires_internet: false
version: 1.0.0
tags: [reporting, statistics, metrics, corpus, validation]
---

# Corpus Statistics Report

- Repository: `{{ github }}`
- Package: `{{ package_path }}`
- Schema: {{ schema_paths }}
- Records: {{ record_globs }}

## Live measurement rule

<!-- canonical:begin live-measurement-rule -->
**Durable session state.**
Use the gitignored `<repo>/.temp/` as the durable work root for review campaigns,
worktrees, batch state, draft review bundles and handoffs. Use
`~/agent-work/<repo>/` when a separate clone is needed. Verify `.temp/` is ignored
before use; provision a missing ignore rule through an authorized repository
change. Keep maintained helpers and accepted evidence in their native tracked
directories; a durable scratch root does not replace their provenance contract.

Never store session state or helper scripts in `/tmp/`, `/private/tmp/` or `$TMPDIR`.
Only disposable caches and pytest temporary fixtures may use system temp roots.
Use a unique subdirectory for each task and preserve other sessions' state.

Report every auxiliary clone for identity verification and inventory in
session_repository_roots, and owned campaign/handoff directories in
session_state_paths. Missing inventory is unknown, not healthy. Report new paths
to the supervisor/operator; do not edit live configuration or expand authority.

For authorized Git work, push each committed batch branch to `origin` the same
day, whether or not a PR is opened. Verify the exact pushed head with the remote;
a local commit or remote-tracking ref alone is not publication proof. Inspect
the repository's current workflow triggers before claiming a branch push runs
no CI. A goal delivering commits cannot close while recorded commits exist only
locally. Publication failure is a retained blocker, never permission to discard
the branch. This rule grants no Git mutation, merge, cleanup or provider
authorization beyond the task and the skill's existing boundaries.

**Never copy a hardcoded record, category, or error count from skill prose or an
older report.** Always compute counts from the current checkout (or verified
`origin/main`) at run time and record the commit SHA alongside the numbers.

Use the shared fleet corpus reporter to tabulate deterministic record counts,
byte totals per glob, and declared field population rates across
{{ record_globs }}:

```bash
uv run --project <claw-root> kg-microbe-corpus report --mech {{ mech_key }}
```

An unreadable YAML file exits nonzero and is named explicitly so a broken record
is never silently omitted from the denominator.
<!-- canonical:end live-measurement-rule -->

## Verification and reporting rules

<!-- canonical:begin verification-rules -->
- **Pair statistics with validation**: run the repository's native validation
  gate alongside any statistics summary so reported totals distinguish valid
  records from schema or grounding failures.
- **Pin provenance**: state the exact command, UTC timestamp, and `git rev-parse --short HEAD`
  commit SHA whenever updating `README.md`, release notes, or manuscript tables.
- **Never hand-edit generated statistics artifacts**: re-run the generator after
  data changes so tables and JSON reports remain reproducible.
<!-- canonical:end verification-rules -->

## Repository-specific commands and breakdowns

This section is {{ display_name }}'s. List this repository's native `just`
recipes for corpus summaries, source/category breakdowns, and validation gates,
plus any domain-specific strata (such as evidence tier, ontology prefix coverage,
or causal-graph scope) that belong in a standard {{ display_name }} status
report.
