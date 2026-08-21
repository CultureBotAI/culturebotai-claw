# Script support policy

The public reusable CLIs live under `src/` and are installed as console
scripts. Files in this directory are repository-maintenance commands, not a
stable Python API.

## CI-supported scripts

These are invoked directly by GitHub workflows and are pull-request gates:

- `audit_idlabel_fleet.sh`
- `validate_evidence_references.py`
- `inventory_unmapped_ingredients.py`
- `generate_kg_microbe_review.py`
- `apply_cron_profile.py`

Changes to them require focused tests under `tests/` and must preserve their
documented command-line interface.

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
