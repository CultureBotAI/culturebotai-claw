# Documentation index

The repository root contains only the two entry documents:

- [`README.md`](../README.md) — supported user-facing setup and commands.
- [`CLAUDE.md`](../CLAUDE.md) — repository-specific instructions for coding agents.

Current design work lives in [`proposals/`](proposals/). Cross-repository and
domain guidance lives in [`guides/`](guides/). Historical implementation,
session, phase, and completion reports are retained in [`archive/`](archive/)
for provenance; they do not describe the supported interface.

Other maintained references:

- [`AUTONOMOUS_LOOPS.md`](AUTONOMOUS_LOOPS.md) — goal-loop workflow guidance.
- [`shared/history/README.md`](../shared/history/README.md) — append-only history layer.
- [`shared/idlabel/README.md`](../shared/idlabel/README.md) — vendored ID/label checks.

Generated reports belong under the gitignored `workspace/reports/`, not in the
documentation tree.
