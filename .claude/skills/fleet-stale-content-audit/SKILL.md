---
name: fleet-stale-content-audit
description: "Audit tracked repository weight, .git object bloat, legacy root test_*.py diagnostics outside tests/, orphan .pyc files, unreferenced scripts, ungoverned YAML writers, corpus record counts, backlog document age, and unapplied patch sets across claw and the manifest-defined Mech fleet. Read-only."
category: cross-repo
requires_database: false
requires_internet: false
version: 1.0.0
tags: [fleet, stale-content, health, writers, patches, corpus, audit, read-only]
---

# Fleet Stale Content, Code, and Data Audit

Run the read-only stale-content auditor from the `culturebotai-claw` root:

```bash
uv run python scripts/fleet_stale_content_audit.py
just fleet-stale-audit
```

## Purpose

Detect stale or drifting code, data, and repository weight across `claw` and every manifest-declared Mech in one deterministic offline report:

1. **Tracked Repository Weight & `.git` Object Store Size**:
   - Calls `kg_microbe_health.repository.measure` (`kg-microbe-health report`) to tabulate tracked file counts, tracked bytes, top directories by bytes, and the largest tracked files.
   - Measures `.git` object store size (`git count-objects -v`) and computes the `git_to_tracked_ratio` to spot historical binary or generated-file bloat in `<repo>/.git/objects/pack` that was deleted from HEAD but still slows clones and fetches.
2. **Legacy Diagnostics & Orphan Bytecode**:
   - Flags `test_*.py` or `*_test.py` files tracked outside `tests/` (legacy executable diagnostics that `pytest` does not collect).
   - Counts orphan `.pyc` files in `__pycache__` whose `.py` source no longer exists (which can cause stale import behavior).
3. **Unreferenced Scripts & Ungoverned YAML Writers**:
   - Cross-references `scripts/*.py` and `scripts/*.sh` against `Justfile`, `.github/workflows/`, `src/`, `tests/`, `docs/`, and `.claude/` to list scripts with zero static references (review candidates, never auto-delete targets).
   - Runs `kg_microbe_writers.audit` (`kg-microbe-writers audit`) for Mechs enabling `writer_audit` to count governed vs ungoverned YAML record writers (`UNGOVERNED_YAML_WRITERS`).
4. **Corpus Counts & Backlog Freshness**:
   - Counts YAML corpus records via `kg_microbe_corpus.statistics.list_records` for Mechs enabling `corpus_statistics`.
   - Checks the last-commit age of `NEXT_TASKS.md` and `INFRA_TASKS.md`.
5. **Unapplied Patch Ledger & Untracked Patch Files**:
   - Inspects `workspace/patches/ledger.json` (`kg_microbe_patches.ledger`) and scans `workspace/patches/` for untracked `.json`/`.yaml`/`.patch`/`.diff` artifacts (`UNTRACKED_PATCH_FILES`), reporting age and whether upstream inputs have advanced since generation.

## Options

```bash
uv run python scripts/fleet_stale_content_audit.py --mech all
uv run python scripts/fleet_stale_content_audit.py --mech culturemech
uv run python scripts/fleet_stale_content_audit.py --mech claw
uv run python scripts/fleet_stale_content_audit.py --json
```

## Interpreting findings

- **`LEGACY_TESTS_OUTSIDE_TESTS_DIR`**:
  Either migrate the diagnostic into `tests/` with real assertions or rename/retire it via a reviewed PR so it does not masquerade as part of the test suite.
- **`UNGOVERNED_YAML_WRITERS`**:
  A script in a Mech writes YAML corpus records without routing through the Mech's validated writer / curation-history helper. Inspect with `uv run kg-microbe-writers audit --mech <mech> --why`.
- **`UNREFERENCED_SCRIPTS`**:
  Zero static references is a **review hint**, not proof that a script is dead (it may be a historical migration script or an operator CLI). Always run an ignore-independent search (`rg -uu`) and check git log provenance before proposing retirement.
- **`UNAPPLIED_PATCH_BACKLOG` / `UNTRACKED_PATCH_FILES`**:
  Generated patches sitting in `workspace/patches/` that have not been applied to their target repository or recorded in `workspace/patches/ledger.json`.

## Boundaries

This skill and `scripts/fleet_stale_content_audit.py` are strictly **read-only**. Retiring a tracked file, migrating a legacy test, or applying a patch set requires a branch and PR under the standard repository and cross-repository checklists.
