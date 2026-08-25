# Retired multi-Claude architecture proposal

This March 2026 proposal is retired. It instructed an orchestrator to hold a
repository lock while a downstream Claude session performed edits. The current
fail-closed hooks correctly block those edits, so that workflow is internally
inconsistent and must not be used.

Use [MULTI_CLAUDE_COORDINATION.md](MULTI_CLAUDE_COORDINATION.md) for the
supported local-machine coordination contract. In particular:

- resolve every target from the packaged fleet manifest;
- give concurrent writers isolated branches and worktrees;
- hold a repository or global lease only for a short shared metadata
  transition, and release it before a hook-bearing worker edits or commits;
- treat task and status files as advisory state rather than write permission;
  and
- remember that local file leases do not coordinate another machine or CI.

Historical implementation notes remain under `docs/archive/`; they are not
supported operational instructions.
