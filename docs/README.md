# Documentation index

The repository root contains only the two entry documents:

- [`README.md`](../README.md) — supported user-facing setup and commands.
- [`CLAUDE.md`](../CLAUDE.md) — repository-specific instructions for coding agents.

Current design work lives in [`proposals/`](proposals/). Cross-repository and
domain guidance lives in [`guides/`](guides/). Historical implementation,
session, phase, and completion reports are retained in [`archive/`](archive/)
for provenance; they do not describe the supported interface.

Other maintained references:

- [`guides/VENDORED_GOVERNANCE.md`](guides/VENDORED_GOVERNANCE.md) — canonical
  shared-artifact manifest, synchronization, rollout, and rollback.
- [`guides/CURATION_HISTORY.md`](guides/CURATION_HISTORY.md) — append-only
  curation-history schema, CLI, vendoring, and enforcement model.
- [`guides/DEEP_RESEARCH_RESULTS.md`](guides/DEEP_RESEARCH_RESULTS.md) — strict,
  append-only deep-research result capture shared by all five Mechs.
- [`AUTONOMOUS_LOOPS.md`](AUTONOMOUS_LOOPS.md) — goal-loop workflow guidance.
- [`src/kg_microbe_governance/artifacts/`](../src/kg_microbe_governance/artifacts/) —
  canonical ID/label implementation and behavioral contracts.

Generated reports belong under the gitignored `workspace/reports/`, not in the
documentation tree.
