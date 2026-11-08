# Workflow evidence examples

These are illustrative, schema-valid empty outcomes, not live completion claims.
Run from the CLAW checkout with its environment:

```bash
PYTHONPATH=src python -m kg_microbe_workflows validate-evidence \
  src/kg_microbe_workflows/examples/reviews/workflow/example-run/cycle-000001/stage-04/revision-0001/evidence.yaml \
  --root src/kg_microbe_workflows/examples
```

The `example-run` files retain their original v1 parent numbering and bytes:
for stage 5 supply stage 4's evidence.yaml with `--previous`; stage 6 freezes the
actual machine-readable `INFRA_TASKS.md` snapshot. Under parent v2 these keys
are stages 5, 6 and 7. Historical evidence is never renumbered. Nonempty resolution examples
and rejection cases are maintained in `tests/test_workflow_contract.py`.

The v2 `open_issue_triage` example is an explicit empty frozen inventory:

```bash
uv run python -m kg_microbe_workflows validate-evidence \
  src/kg_microbe_workflows/examples/reviews/workflow/example-triage-run/cycle-000001/stage-01/revision-0001/evidence.yaml \
  --root src/kg_microbe_workflows/examples
```

Its `issue_inventory.json` is the exact supervisor-frozen JSON. The other JSON
artifacts contain `groups`, `plans` and `dispositions` arrays matching the
manifest's `issue_triage` data. Severity assessments retain the original labels
and record the assigned severity label separately. A blocked critical/high
issue produces `outcome: blocked` with its prerequisite and holds closure.
The shared budget records one start/end window and both actors' work intervals;
parallel time is not added together or granted separately to each actor.
Nonempty and failing cases are in `tests/test_issue_triage_contract.py`.

Copy the structure, replace identity and source revision, create actual evidence,
then calculate exact SHA-256 values. Never reuse example claims or checksums.
`source_revision` describes the source reviewed before committing the report;
the final closure receipt separately binds the commit containing the report.

For every additional output kind in the active cycle's immutable effective
workflow, repeat `--required-output KIND`; for example
`--required-output supporting --required-output validation`. Without these flags
the CLI checks the canonical minimum outputs, not a customized active policy.

Revision 1 has no `supersedes_evidence`. Every revision greater than 1 must pin
the exact preceding revision with `supersedes_evidence: {path: ..., sha256: ...}`.
Keep `previous_evidence` separately pinned to the same frozen stage/cycle source
when revising a report. Carry unresolved IDs forward and retain all older files.
