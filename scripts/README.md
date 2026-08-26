# Script support policy

The public reusable CLIs live under `src/` and are installed as console
scripts. Files in this directory are repository-maintenance commands, not a
stable Python API.

## Workflow-supported scripts

Workflow support is narrower than a single "CI-supported" category:

- `.github/workflows/governance-fleet-audit.yaml` invokes the installed
  `kg-microbe-governance fleet-audit` command from trusted claw base/main
  against the manifest-derived Mech main checkouts; downstream pins are
  unanimous authenticated data, not executable audit code. It does not
  delegate to a compatibility script in this directory.
- `.github/workflows/id-label-canon.yaml` runs the three canonical packaged
  behavioral suites directly under `src/kg_microbe_governance/artifacts/`.
- `validate_evidence_references.py` is executed by the scheduled,
  manually-dispatched, and post-merge cross-repository workflow. Its failure
  fails that workflow, but it is not a pull-request gate.
- `inventory_unmapped_ingredients.py` is executed by the same cross-repository
  workflow, but currently runs as advisory (`|| true`). Its findings do not
  fail the workflow.
- `generate_kg_microbe_review.py` is named in that workflow's push path filter
  but is not executed by the workflow. Use the `just kg-microbe-review` recipe.
- `apply_cron_profile.py` is not executed by a workflow. It is an operator tool
  exposed through `just cron-profiles` and `just cron-profile`.

Changes to these scripts require focused tests under `tests/` and must preserve
their documented command-line interface. Do not describe a script as a
pull-request gate unless a `pull_request` workflow executes it without an
error-swallowing condition.

## Operator-supported scripts

Scripts referenced by a current `justfile` recipe are operator tools. Their
recipe is the supported entry point; run its dry-run form first when one
exists. A recipe that writes another repository must satisfy the mutation
checklist in `CLAUDE.md`.

## Maintenance and migration scripts

Every remaining script is maintenance/migration code. Treat it as one-off
until it has all of the following:

- argparse `--help` describing inputs and outputs;
- a dry-run default for writes;
- validated repository targets and locking for cross-repository access;
- assertion-based tests under `tests/`;
- an entry in the justfile or CI.

Files named `test_*.py` here are legacy executable diagnostics and are not
collected by pytest. Migrate useful coverage into `tests/`; do not add new test
modules under `scripts/`.

Historical scripts should remain in Git until a separate deletion review
confirms that no just recipe, workflow, or guide references them.
