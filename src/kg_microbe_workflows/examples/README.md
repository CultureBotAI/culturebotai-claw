# Workflow evidence examples

These are illustrative, schema-valid empty outcomes, not live completion claims.
Run from the CLAW checkout with its environment:

```bash
PYTHONPATH=src python -m kg_microbe_workflows validate-evidence \
  src/kg_microbe_workflows/examples/reviews/workflow/example-run/cycle-000001/stage-04/revision-0001/evidence.yaml \
  --root src/kg_microbe_workflows/examples
```

For stage 5 supply stage 4's evidence.yaml with `--previous`. Stage 6 freezes the
actual machine-readable `INFRA_TASKS.md` snapshot. Nonempty resolution examples
and rejection cases are maintained in `tests/test_workflow_contract.py`.

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
