---
name: fleet-test-and-ci-status
description: "Audit test suite counts, skip/xfail markers, coverage floors, mypy and ruff parity, governed workflow pins, local pytest durations, and GitHub Actions pass rates and runtimes across claw and the manifest-defined Mech fleet. Read-only."
category: cross-repo
requires_database: false
requires_internet: false
version: 1.0.0
tags: [fleet, testing, ci, coverage, mypy, ruff, workflows, telemetry, read-only]
---

# Fleet Test Suite and CI Telemetry Status

Run the read-only test and CI auditor from the `culturebotai-claw` root:

```bash
uv run python scripts/fleet_test_ci_status.py
just fleet-test-ci-status
```

## Purpose

Report the parameters, coverage gates, and runtime health of tests and CI across `claw` and every manifest-declared Mech:

1. **Test Inventory (`tests/`)**:
   - Counts `test_*.py` files, AST-parsed `test_*` functions, and `pytest.mark.skip`, `pytest.skip`, and `pytest.mark.xfail` markers without importing or executing test modules.
2. **Coverage Floor, Typecheck (`mypy`), and Lint (`ruff`) Parity**:
   - Extracts `--cov-fail-under` and `--fail-under` thresholds from CI workflows and `Justfile`.
   - Checks whether `ruff` and `mypy` are configured in CI and `Justfile`.
   - In `claw`, compares `src/kg_microbe_*` packages on disk against the `mypy` targets in `.github/workflows/tests.yaml` and flags any omitted package (`UNTYPED_SRC_PACKAGES`).
3. **Workflow Triggers & Governed Workflow Pins**:
   - Inspects `.github/workflows/*.y*ml` for trigger coverage (`push`, `pull_request`, `schedule`, `workflow_dispatch`, `workflow_call`) and checks whether `pull_request` triggers carry path filters that could skip test execution on code or schema edits.
   - Verifies governed workflow pin alignment in `src/kg_microbe_governance/vendored_artifacts.json` via `scripts/update_governed_workflow_pins.py`.
4. **Optional Live Local Pytest Benchmark (`--run-pytest`)**:
   - Executes `pytest -q --durations=5` in each selected repository, capturing passed/failed/skipped counts, wall-clock duration (`wall_seconds`), and the 5 slowest test cases.
5. **Optional GitHub Actions Telemetry (`--with-ci-runs`)**:
   - Queries `gh api` for recent workflow runs per repository and computes:
     - Default-branch pass rate (`pass_rate`, surfaced as `LOW_CI_PASS_RATE` when `< 80%`)
     - Median and p90 time-to-completion (`median_duration_sec`, `p90_duration_sec`)
     - Queue delay (`median_queue_sec`)
     - Pages build/deploy workflow duration (`pages_median_duration_sec`).

## Options

```bash
uv run python scripts/fleet_test_ci_status.py --mech all
uv run python scripts/fleet_test_ci_status.py --mech claw --run-pytest
uv run python scripts/fleet_test_ci_status.py --with-ci-runs
uv run python scripts/fleet_test_ci_status.py --with-ci-runs --runs-limit 30 --json
```

## Interpreting findings

- **`UNTYPED_SRC_PACKAGES`**:
  A `src/kg_microbe_*` package exists on disk in `claw` but is missing from the `mypy` target list in `.github/workflows/tests.yaml`, `AGENTS.md`, and `README.md`. Keep all three synchronized (`tests/test_fleet_manifest.py`).
- **`NO_TESTS` / `PYTEST_NOT_IN_CI`**:
  A configured repository has zero `test_*.py` files under `tests/` (`NO_TESTS`) or does not run `pytest` in any GitHub Actions workflow (`PYTEST_NOT_IN_CI`).
- **`PYTEST_FAILED` / `LOW_CI_PASS_RATE`**:
  A local `--run-pytest` invocation failed (`PYTEST_FAILED`) or recent default-branch GitHub Actions runs have a `< 80%` pass rate (`LOW_CI_PASS_RATE`). Inspect with `gh run list -R <owner/repo> --branch main` and `gh run view`.

## Boundaries

This skill and `scripts/fleet_test_ci_status.py` are strictly **read-only**. They never rerun workflows, modify `.github/workflows/`, or alter test files.
