---
name: fleet-maintenance-cycle
description: "Run the recurring read-only fleet development and repository maintenance cycle (--tier fast for local offline hygiene, stale content, test/CI config, and governance checks; --tier full to add GitHub Pages freshness, local page_budgets/site_contract audits, CI run telemetry, and fleet CRUD inventories). Produces a unified report without mutating any repository."
category: cross-repo
requires_database: false
requires_internet: false
version: 1.0.0
tags: [fleet, maintenance, hygiene, stale-content, testing, ci, pages, governance, read-only]
---

# Fleet Development and Repository Maintenance Cycle

Run the unified maintenance cycle from the `culturebotai-claw` root:

```bash
uv run python scripts/fleet_maintenance_cycle.py --tier fast
uv run python scripts/fleet_maintenance_cycle.py --tier full
just fleet-maintenance --tier fast
```

## Purpose

Orchestrate the fleet's development and repository maintenance checks in a single deterministic, read-only pass with two execution tiers:

### `--tier fast` (Default — Offline, <30s)

1. **Git, Worktree, Branch, Stash, Lock & Temp Hygiene** (`/fleet-worktree-and-temp-hygiene`, `scripts/fleet_git_and_temp_hygiene.py`):
   - Audits `/tmp/`, `/private/tmp`, and `$TMPDIR` for provenance-sensitive helper scripts (`PROVENANCE_PROMOTE_REQUIRED`), temp checkouts, and 4-day reaper risks.
   - Audits `workspace/` in `claw` for registered vs orphan worktrees and read-only lock lease statuses (`ACTIVE`, `DEAD_PID`, `EXPIRED`, `ORPHAN_GUARD`, `MALFORMED`).
   - Audits `claw`, all 14 manifest-declared Mechs, `CultureBotAI.github.io`, and `kg-microbe` for dirty trees, stashes, prunable worktrees, non-default local branches, and sibling-shadow checkouts.
2. **Stale Content, Code, Data, Writer & Patch Audit** (`/fleet-stale-content-audit`, `scripts/fleet_stale_content_audit.py`):
   - Measures tracked repository weight (`kg-microbe-health report`) and `.git` object store size (`git count-objects -v`).
   - Flags legacy `test_*.py` files outside `tests/`, orphan `.pyc` files, unreferenced scripts, ungoverned YAML writers (`kg-microbe-writers audit`), corpus record counts (`kg-microbe-corpus report`), and unapplied patch sets in `workspace/patches/patch_ledger.json`.
3. **Static Test, Coverage Floor, Typecheck & Workflow Audit** (`/fleet-test-and-ci-status`, `scripts/fleet_test_ci_status.py`):
   - Tabulates test files, AST test function counts, skip/xfail markers, coverage floors, `mypy`/`ruff` configuration, and untyped `src/kg_microbe_*` packages.
4. **Governance & Skill Drift Checks**:
   - Runs `scripts/apply_cron_profile.py --check-active`, `scripts/update_governed_workflow_pins.py --check`, and `kg_microbe_skills check`.
   - Checks the reusable Mech baseline source inventory and reports consumer adoption/drift; use `onboard-mech` and the [baseline guide](../../../docs/guides/MECH_TEMPLATE.md) for scoped update PRs.
5. **Local Pages Budgets & Site Contract Audits**:
   - Runs `kg_microbe_pages.budgets.audit` and `kg_microbe_site.contract.check_site` across locally built Mech sites (`scripts/fleet_pages_status.py --with-local-audits`).

### `--tier full` (Online + Full Metadata Inventory)

Includes every check in `--tier fast` plus:

6. **Remote GitHub Pages Freshness & Companion X-Mech Suite Parity** (`/github-pages-status`, `scripts/fleet_pages_status.py --with-local-audits`):
   - Verifies deployment status, served-path freshness vs `main`, and HTTP reachability across all Mech Pages sites and `CultureBotAI/CultureBotAI.github.io`.
7. **GitHub Actions CI Telemetry** (`scripts/fleet_test_ci_status.py --with-ci-runs`):
   - Queries `gh api` for default-branch pass rates, median/p90 workflow durations, queue delays, Pages build durations, and failing workflows on `main`.
8. **Fleet-Wide CRUD Inventory Summary** (`/fleet-repo-crud-cleanup`, `scripts/repo_crud_inventory.py --all-fleet`):
   - Sweeps `claw` and all configured Mechs for regenerable cache and build clutter candidates and reports total candidate counts and bytes.

## Options

```bash
uv run python scripts/fleet_maintenance_cycle.py --tier fast
uv run python scripts/fleet_maintenance_cycle.py --tier full
uv run python scripts/fleet_maintenance_cycle.py --tier fast --run-pytest
uv run python scripts/fleet_maintenance_cycle.py --tier fast --write-report workspace/reports/fleet_maintenance.md
uv run python scripts/fleet_maintenance_cycle.py --tier full --json --write-report workspace/reports/fleet_maintenance.json
```

## Boundaries

`scripts/fleet_maintenance_cycle.py` is strictly **read-only** (unless `--write-report` is explicitly passed to save the report file). It never deletes files, modifies repositories, acquires or breaks locks, or triggers GitHub workflows. When findings require remediation, present the prioritized findings and obtain explicit user approval before mutating any repository or external surface.
