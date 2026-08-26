# CultureBotAI CLAW

CultureBotAI CLAW coordinates validation, curation, and shared tooling across
the five Mech repositories: CultureMech, MediaIngredientMech (MIM),
CommunityMech, TraitMech, and ProteinTraitsMech. `src/kg_microbe_fleet/fleet.yaml` is the
canonical definition of that fleet. It contains repository-aware plugins,
file-based coordination, curation pipelines, shared Mech utilities, and fleet
CI workflows.

You do not need every repository cloned to work here — set only the roots you
use, and `openclaw-cli config validate` will report the rest as "not
configured locally" instead of failing.

## Current support status

| Surface | Status |
|---|---|
| Repository configuration and identity checks | Supported; missing or wrong roots fail closed |
| File-based repository locks | Supported; atomic, lease-owned, and expiration-aware |
| Agent and pipeline discovery | Supported |
| Agent and pipeline execution through `openclaw-cli` | Not implemented; non-dry runs fail explicitly |
| Environment-curation dry run and reports | Supported |
| Environment-curation apply mode | Disabled until a validated atomic writer exists |
| Unified ingredient-mapping apply mode | Disabled until canonical and downstream writes are transactional |
| Shared history, QC, discussions, and knowledge-gap tools | Packaged and supported |
| Historical scripts and phase reports | Retained for provenance; not part of the supported API |

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Git
- `just` for repository recipes
- An Anthropic API key only for workflows that invoke an LLM

## Setup

```bash
git clone https://github.com/CultureBotAI/culturebotai-claw.git
cd culturebotai-claw
cp .env.example .env
# Edit the repository roots in .env.
uv sync --extra dev
uv run openclaw-cli config validate
uv run openclaw-cli status
```

The external OpenClaw runtime is not a package dependency while agent and
pipeline execution is disabled. Add a compatible runtime only when implementing
that integration.

Repository roots are security boundaries. Configuration validation requires
each path to be the exact Git worktree root with the expected GitHub `origin`.
Unset variables never fall back to the current directory.

## CLI

The orchestration CLI currently supports discovery, configuration checks, and
validated dry runs:

```bash
uv run openclaw-cli agent list
uv run openclaw-cli agent run validation_agent --dry-run
uv run openclaw-cli pipeline list
uv run openclaw-cli pipeline run ingredient_curation --dry-run
uv run openclaw-cli plugin list
uv run openclaw-cli plugin test lock_manager
```

Agent and pipeline execution without `--dry-run` intentionally exits nonzero
until the OpenClaw execution integration is implemented.

## Shared Mech tools

`src/` is installed as part of this project. These equivalent module and
console-script forms are available:

```bash
uv run kg-microbe-history --help
uv run kg-microbe-governance --help
uv run kg-microbe-kgscan --help
uv run kg-microbe-qc --help
uv run kg-microbe-discussions --help

uv run python -m kg_microbe_history --help
uv run python -m kg_microbe_governance --help
uv run python -m kg_microbe_kgscan --help
uv run python -m kg_microbe_qc --help
uv run python -m kg_microbe_discussions --help
```

Canonical shared schemas, behavioral contracts, and vendored fleet checks live
under `src/kg_microbe_governance/`. The old `shared/` mirrors remain only for
the bounded Phase 1 compatibility window. See
[`docs/guides/VENDORED_GOVERNANCE.md`](docs/guides/VENDORED_GOVERNANCE.md).

## Safety model

Cross-repository code must:

1. Resolve targets through `RepositorySettings`.
2. Verify the exact worktree and expected `origin` identity.
3. Acquire the target repository lock with the context-manager API.
4. Default to dry-run and require an explicit apply action.
5. Refuse unallowlisted recipes or operations.
6. Validate staged output before replacing source data.
7. Surface partial failures and preserve recoverable artifacts.

Example lock usage:

```python
from plugins.lock_manager import LockManager

with LockManager().lock("mediaingredientmech", "publish_sssom"):
    # Perform the already-approved operation.
    ...
```

The repository-path, recipe-allowlist, and lock guarantees are enforced in
code. Approval, backup, and transaction behavior remains the responsibility of
each writer until it adopts a shared write transaction.

## Development checks

These are the pull-request gates:

```bash
uvx ruff@0.16.3 check cli plugins pipelines src tests
uv run --extra dev mypy \
  cli/main.py plugins/repository_settings.py plugins/lock_manager.py \
  plugins/git_integration.py plugins/just_runner.py \
  src/kg_microbe_history src/kg_microbe_kgscan src/kg_microbe_fleet \
  src/kg_microbe_governance/__init__.py \
  src/kg_microbe_governance/__main__.py \
  src/kg_microbe_governance/fleet_audit.py \
  src/kg_microbe_governance/artifacts/scripts/check_vendored_sync.py
uv run --extra dev python -m pytest -q \
  --cov=src --cov=cli.main --cov=plugins.repository_settings \
  --cov=plugins.lock_manager --cov=plugins/git_integration \
  --cov=plugins.just_runner --cov-report=term-missing --cov-fail-under=70
uv run --extra dev coverage report \
  --include=cli/main.py,plugins/repository_settings.py,plugins/lock_manager.py,plugins/git_integration.py,plugins/just_runner.py \
  --fail-under=60
```

Pytest intentionally collects only `tests/`. Root- and `scripts/`-level
`test_*.py` files are legacy executable diagnostics and are not CI tests.

## Repository map

```text
src/kg_microbe_agents/definitions/  packaged declarative agent definitions
cli/          openclaw-cli discovery and validation interface
pipelines/    orchestration workflows
plugins/      repository, lock, validation, ontology, and curation adapters
src/          packaged shared Mech utilities and canonical governance payloads
shared/       temporary pre-Phase-1 compatibility mirrors
scripts/      maintenance, migration, and curation commands
tests/        maintained assertion-based test suite
docs/         current guides, proposals, reviews, and historical archive
workspace/    gitignored runtime locks, tasks, reports, and caches
```

See the [documentation index](docs/README.md) for longer guides and archived
project history.
