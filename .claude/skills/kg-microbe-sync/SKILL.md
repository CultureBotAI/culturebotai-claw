---
name: kg-microbe-sync
description: Snapshot the kg-microbe data files claw scripts depend on into workspace/kgm_snapshot/, capturing the current local kg-microbe state without `git pull`. Provides reproducible audit boundaries, fallback when KGM_ROOT is unset, and a clear "as of when" reference for the cross-repo backlog inventory.
category: cross-repo
requires_database: false
requires_internet: false
version: 1.0.0
tags: [kg-microbe, sync, snapshot, vendor, dependency, mim, cross-repo]
reference-root: kg-microbe
---

# kg-microbe Sync Skill

## Purpose

Several claw scripts read kg-microbe data files in place via the
`KGMICROBE_ROOT` env var (defaulting to `../kg-microbe`):

- `scripts/inventory_unmapped_ingredients.py` — reads
  `kg-microbe/docs/metatraits/unmapped_compounds.tsv` and
  `kg-microbe/mappings/mediadive_unmapped_ingredients_to_curate.tsv`
- `scripts/generate_kg_microbe_review.py` — reads
  `kg-microbe/mappings/culturebotai_reviewed_ingredients.tsv`,
  `complex_ingredients.tsv.gz`, etc.

Reading in place is convenient but creates a few problems:

1. **Reproducibility** — re-running the same script against an
   evolving kg-microbe checkout produces different results without
   any record of *what changed* on the kg-microbe side.
2. **Audit boundaries** — when an inventory shows different numbers
   than yesterday, was it because MIM curation moved or because
   kg-microbe data refreshed?
3. **Portability** — if `KGMICROBE_ROOT` is missing, scripts fail.

This skill captures a **snapshot** of the kg-microbe files into
`workspace/kgm_snapshot/`, with a JSON manifest recording per-file
sha256 + mtime + the kg-microbe git HEAD at snapshot time.

The snapshot is **gitignored** (lives under `workspace/`) — it's a
local audit boundary, not a vendored dependency that ships with the
repo.

## Files snapshotted

| Source path (in `kg-microbe/`) | Why claw cares |
|---|---|
| `mappings/culturebotai_reviewed_ingredients.tsv` | kg-microbe-side review state for cross-repo verification |
| `mappings/mediadive_unmapped_ingredients_to_curate.tsv` | mediadive-side unmapped backlog (input to unmapped-inventory) |
| `mappings/complex_ingredients.tsv.gz` | shared complex-ingredient registry (already vendored at workspace/reports/, redundantly) |
| `mappings/kgmicrobe_proposal_placeholders.tsv` | proposed-but-not-minted kgmicrobe.* CURIE registry |
| `mappings/manual_mapping_audit_report.tsv` | kg-microbe-side audit |
| `docs/metatraits/unmapped_compounds.tsv` | metatraits placeholder backlog (input to unmapped-inventory) |

The list is in `scripts/sync_kgm_dependencies.py::DEPS`. To add a new
dependency, append `(rel_path, why)` and re-run.

## Run it

```bash
just sync-kgm
# Or directly:
python3 scripts/sync_kgm_dependencies.py
# Dry-run (no copies, report only):
python3 scripts/sync_kgm_dependencies.py --dry-run
```

Output:
- `workspace/kgm_snapshot/<filename>` — copied source files, preserving
  filename
- `workspace/kgm_snapshot/manifest.json` — per-file sha256 + mtime +
  kg-microbe git HEAD at snapshot time + claw timestamp

## When to refresh

| Trigger | Action |
|---|---|
| Before running `just inventory-unmapped` for an audit pass | `just sync-kgm` first |
| After a kg-microbe consolidator run that touched the dependency files | re-snapshot |
| When investigating a backlog drift across days | check `manifest.json`'s sha256 against current kg-microbe state |
| Periodic (weekly, monthly) — for clean audit-trail | re-snapshot |

The script is idempotent: files unchanged since last snapshot stay
unchanged (same mtime preserved by `shutil.copy2`).

## Why not git pull?

This skill explicitly does NOT `git pull` kg-microbe — that would
fetch remote changes the user might not want. The contract is:

> Use the **current local** kg-microbe files. Whatever's on disk is
> what we trust. Don't reach for remote state.

If you want to pull remote changes, do `cd kg-microbe && git pull`
manually first, then run `just sync-kgm`.

## Manifest format

Each file in `manifest.json::files` has:
```json
{
  "source_relative": "mappings/culturebotai_reviewed_ingredients.tsv",
  "source_absolute": "/.../kg-microbe/mappings/...",
  "snapshot_path": "workspace/kgm_snapshot/...",
  "source_size": 362801,
  "source_mtime": "2026-04-17T22:10:00+00:00",
  "source_sha256": "584fe95a0f02...",
  "purpose": "kg-microbe-side review state for cross-repo verification"
}
```

Top-level fields:
- `kgm_root`: absolute path of the kg-microbe checkout used
- `kgm_git_head`: full SHA of kg-microbe HEAD at snapshot time
- `snapshot_taken_at`: ISO 8601 UTC

Diffing two manifests across snapshots tells you exactly what changed
on the kg-microbe side between two audit moments.

## Files

| Path | Role |
|---|---|
| `.claude/skills/kg-microbe-sync/SKILL.md` | This file |
| `scripts/sync_kgm_dependencies.py` | The snapshotter |
| `workspace/kgm_snapshot/` | Snapshot output (gitignored) |
| `workspace/kgm_snapshot/manifest.json` | Per-file provenance |

## Dependencies

- Python 3 + stdlib (no extras)
- A kg-microbe checkout at `$KGMICROBE_ROOT` (default `../kg-microbe`)

## Related skills

- `unmapped-inventory` — primary consumer of the snapshotted unmapped
  / mediadive TSVs
- `kg-microbe-review` — secondary consumer; reads
  `culturebotai_reviewed_ingredients.tsv` and
  `complex_ingredients.tsv.gz`
- `cross-repo-sync` — broader propagation pipeline; this skill is its
  upstream half (capture kg-microbe state) where `cross-repo-sync` is
  the downstream half (push MIM state to consumers)

## Out of scope

- **Updating kg-microbe** — kg-microbe is downstream of MIM in the
  publish graph; we don't write *into* kg-microbe via this skill.
  Use the consolidator inside the kg-microbe checkout for that.
- **Checking-out a specific kg-microbe branch / commit** — use
  `cd kg-microbe && git checkout <ref>` first.
- **Vendoring under data/ or docs/** — committed-to-claw vendoring
  would inflate the repo and create rotation churn. The
  `workspace/kgm_snapshot/` location is intentionally gitignored.
