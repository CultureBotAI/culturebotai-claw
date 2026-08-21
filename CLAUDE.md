# CLAUDE.md

This file is the repository-specific operating guide for coding agents. The
code and tests are authoritative if an older guide or archived report differs.

## Purpose and boundaries

CultureBotAI CLAW coordinates work across three downstream repositories:

- CultureMech (`CULTUREMECH_ROOT`)
- MediaIngredientMech, canonically abbreviated MIM
  (`MEDIAINGREDIENTMECH_ROOT`)
- CommunityMech (`COMMUNITYMECH_ROOT`)

This repository owns orchestration, cross-repository safety primitives, shared
Mech utilities, fleet checks, and curation support. Do not edit a downstream
repository directly from an ad hoc path. Resolve and verify it through the
orchestration layer.

## Supported versus experimental surfaces

Supported:

- `RepositorySettings` fail-closed path and Git identity validation.
- `LockManager` atomic, lease-owned file coordination.
- Plugin and agent discovery and validated CLI dry runs.
- Packaged history, QC dashboard, discussion-browser, and knowledge-gap tools.
- The assertion-based suite under `tests/` and fleet workflows under `.github/`.

Experimental or disabled:

- `openclaw-cli agent run` and `pipeline run` execution without `--dry-run`.
- Environment-curation apply mode; it raises until an atomic validated writer exists.
- Unified ingredient-mapping apply mode; it raises until all YAML writes are transactional.
- Legacy root diagnostics, one-off migration scripts, and archived phase workflows.

Never describe an experimental path as implemented merely because a YAML agent
definition, configuration section, or placeholder method exists.

## Setup and checks

```bash
cp .env.example .env       # first checkout only; edit repository roots
uv sync --extra dev
uv run openclaw-cli config validate

uvx ruff@0.16.3 check cli plugins pipelines src tests
uv run --extra dev mypy \
  cli/main.py plugins/repository_settings.py plugins/lock_manager.py \
  src/kg_microbe_history src/kg_microbe_kgscan
uv run --extra dev python -m pytest -q \
  --cov=src --cov-report=term-missing --cov-fail-under=70
```

Pytest collects only `tests/`. A root or `scripts/` file named `test_*.py` is a
legacy executable diagnostic unless it is deliberately migrated into `tests/`
with assertions.

## Mandatory cross-repository mutation checklist

Before any downstream write:

1. Run `openclaw-cli config validate` and resolve the target through
   `RepositorySettings`; never default a missing root to `.`.
2. Confirm the target is the exact expected worktree and GitHub `origin`.
3. Inspect branch, staged changes, unstaged changes, and untracked files.
4. Obtain user approval when the operation changes downstream data, schemas,
   Git state, or published artifacts.
5. Acquire the repository lock with `LockManager.lock(...)`.
6. Run the operation in dry-run mode first when available.
7. Stage output, validate it, then replace destination files atomically.
8. Report modified files, validation results, partial failures, and recovery path.

Use the context manager so exceptions cannot skip release:

```python
from plugins.lock_manager import LockManager

with LockManager().lock("culturemech", "operation_name"):
    perform_approved_write()
```

Do not use manual acquire/release pairs in new code. Never force-release another
lease as routine error recovery.

## Configuration rules

- Start from `.env.example`; do not commit `.env` or credentials.
- Repository paths must be explicit, absolute for automation, and free of
  unresolved `${...}` expressions.
- Repository-aware plugins must consume `RepositorySettings`, not call
  `os.getenv` independently.
- Command/recipe allowlists deny by default.
- Runtime artifacts belong under `OPENCLAW_WORKSPACE` (default `./workspace`).
- The path, identity, allowlist, and lock controls are enforced. Do not claim
  that approval, backups, or transactional writes are centrally enforced for a
  writer unless its code and tests demonstrate that behavior.

## Current architecture

```text
agents/       YAML agent definitions; declaration is not execution
cli/          discovery, status, plugin checks, and configuration validation
plugins/      validated repository adapters and coordination primitives
pipelines/    curation/orchestration workflows with explicit support status
src/          installed kg_microbe_* shared libraries and CLIs
shared/       history schema, ID/label checks, and spoke sync manifests
scripts/      maintenance and migration scripts; audit before treating as supported
tests/        the only default pytest collection root
docs/         current index, guides, proposals, reviews, and archive
workspace/    gitignored runtime state
```

Key shared console scripts:

```bash
uv run kg-microbe-history --help
uv run kg-microbe-kgscan --help
uv run kg-microbe-qc --help
uv run kg-microbe-discussions --help
```

## Change conventions

- Add regression tests under `tests/` for every repaired failure mode.
- Return nonzero from CLI failures; printing an error is not sufficient.
- Do not swallow partial failures into a successful report.
- Use timezone-aware UTC timestamps.
- Use atomic creation/replacement for locks and curated data.
- Preserve unrelated user changes and generated artifacts.
- Prefer `uv run python` over machine-specific interpreter paths.
- Keep README user-facing; put agent-only constraints here; put detailed design
  rationale in `docs/proposals/` or `docs/guides/`.

## Prompts and review workflow

- `prompts/backlog-loop-goal.md` is a hand-over prompt for the native `/goal`.
  Do not recreate a project command named `/goal`.
- `.claude/workflows/dynamic-review.js` is the version-controlled source for
  `/dynamic-review`. It reports to the session by default and posts PR comments
  only when explicitly requested.
- `.claude/commands/curate.md` coordinates the curation stages and must stop for
  confirmation before downstream mutations.

## Documentation

Start at [`docs/README.md`](docs/README.md). Historical completion, phase, and
session reports live under `docs/archive/` and are never a source of current
operating truth.
