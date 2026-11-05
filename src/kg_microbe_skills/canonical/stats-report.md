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
