---
name: scalability-and-health
description: "Assess whether {{ display_name }} remains scalable across Git/working-tree weight, .git history growth, and GitHub Pages size/file/browser-shard budgets as the corpus grows. Uses kg-microbe-health report and kg-microbe-pages audit to classify signals into Green/Watch/Act and recommend concrete adjustments. Analysis only."
category: quality
requires_database: false
requires_internet: false
version: 1.0.0
tags: [scalability, health, pages, budgets, git, audit]
---

# Scalability and Repository Health Check

- Repository: `{{ github }}`
- Schema: {{ schema_paths }}
- Records: {{ record_globs }}

## Two axes that fail differently

<!-- canonical:begin two-axes -->
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

Run this check after large ingestions, before releases, or when git operations or
the web browser start feeling slow. Two independent axes fail in different ways:

1. **Git and Working-Tree Weight** — tracked file count, tracked byte volume,
   and `.git` object store growth (`kg-microbe-health report --mech {{ mech_key }}`).
   Committing regenerable browser JSON or build outputs rewrites tens of
   megabytes on every seeding commit and permanently inflates `.git/objects/pack`.
2. **GitHub Pages and Client Browser Load** — deployed site total bytes, total
   file count, and the size of JSON shards fetched by the browser
   (`kg-microbe-pages audit --mech {{ mech_key }}` and
   `kg-microbe-site check --mech {{ mech_key }}`).
<!-- canonical:end two-axes -->

## Shared measurements

<!-- canonical:begin shared-measurements -->
```bash
uv run --project <claw-root> kg-microbe-health report --mech {{ mech_key }}
uv run --project <claw-root> kg-microbe-pages audit --mech {{ mech_key }}
uv run --project <claw-root> kg-microbe-site check --mech {{ mech_key }}
git count-objects -vH
```
<!-- canonical:end shared-measurements -->

## Thresholds and verdicts

<!-- canonical:begin thresholds -->
| Signal | Green | Watch | Act |
|---|---|---|---|
| Tracked repository bytes | < 500 MB | 500 MB – 1 GB | > 1 GB (GitHub warns/throttles) |
| Tracked file count | < 100k | 100k – 300k | > 300k (git status and index slow) |
| `.git` object store vs tracked bytes | < 3x tracked | 3x – 8x tracked | > 8x tracked or growing every commit from generated blobs |
| Pages total site size | Within declared budget | > 80% of budget | Breaches `page_budgets` or > 1 GB |
| Pages deployed file count | Within declared budget | > 2,000 files | > 4,000 files (Pages deploy timeout risk) |
| Single tracked file | < 25 MB | 25 – 50 MB | > 50 MB (GitHub warning / 100 MB hard block) |
<!-- canonical:end thresholds -->

## Strategy adjustments when a threshold trips

<!-- canonical:begin adjustments -->
- **Build regenerable site data in CI rather than committing it**, or keep
  committed search/detail shards strictly within the repository's declared
  `page_budgets` limits.
- **Lean index + bucketed detail shards**: keep landing-page facet summaries
  small and split per-record payloads into bounded shards so the browser never
  fetches the full corpus at once.
- **Per-source storage tiering**: one YAML per record scales well to ~100k–200k
  records; for ultra-high-volume machine-seeded sources, decide at ingest time
  whether to aggregate or index rather than minting hundreds of thousands of
  tiny files.
- **Prevent `.git` bloat before considering history rewrites**: `git gc`
  reclaims loose objects, whereas shrinking committed pack bloat requires a
  coordinated history rewrite. Always stop committing regenerable blobs first.
<!-- canonical:end adjustments -->

## Repository-specific commands and budgets

This section is {{ display_name }}'s. Document this repository's local site
build recipe, where its page budgets file lives, any shard-sizing constants, and
which directories hold regenerable build outputs versus authoritative curated
data.
