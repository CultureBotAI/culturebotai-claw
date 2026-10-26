# Documentation index

The repository root contains only the two entry documents:

- [`README.md`](../README.md) — supported user-facing setup and commands.
- [`CLAUDE.md`](../CLAUDE.md) — repository-specific instructions for coding agents.

Current design work lives in [`proposals/`](proposals/). Cross-repository and
domain guidance lives in [`guides/`](guides/). Historical implementation,
session, phase, and completion reports are retained in [`archive/`](archive/)
for provenance; they do not describe the supported interface.

Other maintained references:

- [`guides/EMBEDDING_SETS.md`](guides/EMBEDDING_SETS.md) — PaCMAP projections,
  applicable text, chemical, protein, graph and future sets, and the fleet adoption plan.
- [`guides/PYTHON_RUNTIME.md`](guides/PYTHON_RUNTIME.md) — the shared Python 3.13
  runtime, single-version CI, and requirements for compatibility exceptions.
- [`guides/MECH_SITE_FEATURES.md`](guides/MECH_SITE_FEATURES.md) — the X-Mech
  website feature set every published site is expected to provide, reference
  implementations, verified sibling routes, and candidate catalogue features.
- [`guides/MECH_STANDARD.md`](guides/MECH_STANDARD.md) — the measured Mech
  standard: universal requirements, declared-decision capabilities, and
  domain-specific work; what a new Mech adopts, and in what order
- [`guides/VENDORED_GOVERNANCE.md`](guides/VENDORED_GOVERNANCE.md) — canonical
  shared-artifact manifest, synchronization, rollout, and rollback.
- [`guides/CURATION_HISTORY.md`](guides/CURATION_HISTORY.md) — append-only
  curation-history schema, CLI, vendoring, and enforcement model.
- [`guides/RECORD_REVIEWS.md`](guides/RECORD_REVIEWS.md) — shared structured
  record reviews, evidence-linked findings, fleet triage, and planning inputs.
- [`guides/MECH_SESSION_WORKFLOWS.md`](guides/MECH_SESSION_WORKFLOWS.md) — bind
  existing agy sessions, track goals, and verify PR closure before advancing.
- [`guides/MECH_WORKFLOW_CONTRACT.md`](guides/MECH_WORKFLOW_CONTRACT.md) — shared
  LinkML/YAML six-goal cycle, local adaptations, versioned reviews, and
  issue-linked infrastructure work.
- [`guides/DEEP_RESEARCH_RESULTS.md`](guides/DEEP_RESEARCH_RESULTS.md) — strict,
  append-only deep-research result capture shared by every Mech.
- [`AUTONOMOUS_LOOPS.md`](AUTONOMOUS_LOOPS.md) — goal-loop workflow guidance.
- [`src/kg_microbe_governance/artifacts/`](../src/kg_microbe_governance/artifacts/) —
  canonical ID/label implementation and behavioral contracts.

Operational scratch reports belong under the gitignored `workspace/reports/`,
not in the documentation tree. Versioned goal-review evidence follows the
repository paths defined by the workflow contract.
