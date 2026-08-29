# CLAUDE.md

This file is the repository-specific operating guide for coding agents. The
code and tests are authoritative if an older guide or archived report differs.

## Fact-based answers only

Never state a comparison, count, status, or historical claim without having
verified it in the current conversation via a tool call (`gh`, `git`, `grep`,
`Read`, etc.). "I recall," "this is typically the case," or a prior summary
are not verification — code, issue/PR state, and downstream Mech repos change
between turns and across concurrent sessions.

- Prefer a live check over memory: `gh api`/`gh pr view`/`gh issue view` over
  a remembered issue list; `git log`/`git blame` over a recalled commit; a
  fresh `Read` over trusting an earlier read of the same file.
- A downstream Mech's local checkout can lag its `origin/main` significantly
  (observed directly in this repo's own sessions) — verify against `gh api`
  or a fresh `git fetch`, not the working tree on disk, before asserting what
  a Mech currently contains.
- If a claim can't be verified this session, say so ("I did not check X" /
  "I don't know") instead of presenting a plausible guess as fact.
- Re-verify rather than repeat: restating an earlier claim in this same
  conversation without re-checking it is exactly the failure mode this rule
  exists to prevent.

## Purpose and boundaries

CultureBotAI CLAW coordinates work across five downstream Mech repositories.
`src/kg_microbe_fleet/fleet.yaml` is the canonical list; do not re-declare it
in code. Read it through `kg_microbe_fleet.load_fleet_manifest()`. It lives
inside the package rather than in `conf/` so installed commands retain the
manifest when no source checkout is present:

- CultureMech (`CULTUREMECH_ROOT`)
- MediaIngredientMech, canonically abbreviated MIM
  (`MEDIAINGREDIENTMECH_ROOT`)
- CommunityMech (`COMMUNITYMECH_ROOT`)
- TraitMech (`TRAITMECH_ROOT`)
- ProteinTraitsMech (`PROTEINTRAITSMECH_ROOT`) — note the GitHub slug is
  lowercase `proteintraitsmech`

You do not need every Mech cloned. `openclaw-cli config validate` reports an
unset root as "not configured locally" rather than a failure; pass
`--require-all-repositories` where the whole fleet is expected. An unconfigured
repository remains unusable — every access path still fails closed.

Each Mech declares its capabilities in the manifest as `enabled`, `disabled`,
or `not_applicable`; the latter two require a recorded reason. Consult the
declaration rather than assuming a capability applies fleet-wide.

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
- `kg_microbe_write`: the shared `ValidatedWriteTransaction` -- stage every
  change, validate the complete set, then replace atomically with a recovery
  journal. Nothing is written until `commit(apply=True)`; a dry run still
  validates. It does not resolve repositories, take locks, or decide
  authorization: `RepositorySettings` and `LockManager` own those, and it
  refuses to write outside the root it is handed.
- `kg_microbe_research`: the shared provider catalogue, focus-profile
  validation, deterministic triage, execution-policy gate, packaged LinkML
  result schema, strict result validator, and append-only dry-run scaffolder.
  It makes no provider health probe or provider call and performs no provider
  network access. Values read from recognised credential environment variables
  are checked only for non-emptiness and are never emitted or retained.
- Packaged canonical vendored-artifact manifest and identity-validated,
  dry-run-first synchronization.
- The assertion-based suite under `tests/` and fleet workflows under `.github/`.

Experimental or disabled:

- `openclaw-cli agent run` and `pipeline run` execution without `--dry-run`.
- Environment-curation apply mode; it raises until an atomic validated writer exists.
- Unified ingredient-mapping apply mode; it raises until all YAML writes are transactional.
- Provider command construction and *execution*, including an executable mock
  provider. `kg_microbe_research` decides whether a call is permitted; it does
  not make one. None of the Mech runners consults this gate yet. Four
  runners still execute live by default; ProteinTraitsMech is dry-run-first.
- Provider executors, domain adapters, historical-result migrations, and the
  five migrated Mech runners.
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
  plugins/git_integration.py plugins/just_runner.py \
  src/kg_microbe_history src/kg_microbe_kgscan src/kg_microbe_fleet \
  src/kg_microbe_research src/kg_microbe_write \
  src/kg_microbe_governance/__init__.py \
  src/kg_microbe_governance/__main__.py \
  src/kg_microbe_governance/fleet_audit.py \
  src/kg_microbe_governance/artifacts/scripts/check_vendored_sync.py
uv run --extra dev python -m pytest -q \
  --cov=src --cov=cli.main --cov=plugins.repository_settings \
  --cov=plugins.lock_manager --cov=plugins.git_integration \
  --cov=plugins.just_runner --cov-report=term-missing --cov-fail-under=70
uv run --extra dev coverage report \
  --include=cli/main.py,plugins/repository_settings.py,plugins/lock_manager.py,plugins/git_integration.py,plugins/just_runner.py \
  --fail-under=60
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

## Research provider safety

A live research call may consume a quota or incur a charge. It must satisfy
three independent policy conditions:

1. **Live execution.** `authorize(...)` returns a dry run unless `apply=True`.
2. **Usage authorization.** Billing/quota classification is independent of the
   relative cost tier used for ranking. Every provider not explicitly marked
   `free` (including `metered` or `unknown`) additionally needs an explicit
   acknowledgement or a cost ceiling that admits its relative cost tier.
3. **Plan agreement.** The provider must be represented in the immutable plan
   returned by `plan_stage(...)`. Explicitly naming any eligible fallback
   instead of the recommendation, or making another triage/allowlist choice,
   requires a recorded override reason.

An override can explain a manual triage or allowlist choice; it never waives
`--no-paid`, the usage-authorization gate, a cost ceiling, or provider status.

A blocked, unavailable, or merely configured provider is refused whatever the
caller passes. Configuration is not verified availability: a non-empty
credential or discovered local CLI/package can yield only `configured`. For an
external provider, only explicitly injected, previously obtained
`AvailabilityEvidence` can yield `available`. The catalogue-only `mock` remains
a `stub` until its executable implementation lands. `KNOWN_BLOCKED` records
measured failures and outranks both configuration and injected evidence.

The installed CLI accepts prior evidence only through
`--availability-evidence PATH`. `load_availability(...)` strictly validates its
versioned JSON: every entry records status, reason, timezone-aware check/expiry
times, source, and a configuration-context label; expiry must be after the
check, no more than 24 hours later, and still in the future. Expiry is rechecked
on every lookup and immediately before an existing plan can authorize
execution. This is an explicit trusted-caller boundary, not a cryptographic
attestation or a check that the current secret matches the recorded context.
Never put credential values in an evidence file. Programmatic callers and tests
can inject non-expiring, ephemeral evidence with `StaticAvailability`.

`--no-paid` excludes every provider whose billing class is not explicitly
`free`, regardless of its relative cost tier. Because `mock` is currently the
only `free` provider and is never recommended, the flag cannot presently be
satisfied by any profile or configuration. The filter still runs -- `--no-paid`
remains a hard exclusion that no override waives -- but an empty result now
says why, in the `triage` JSON as `no_paid_unsatisfiable` and inside the
`authorize` refusal, instead of reporting a bare "recommends None" that reads
as a misconfigured profile (#152). The check reads the catalogue, so
classifying any routable provider as `free` retires the message with no code
change. Bound relative cost with `--max-cost` instead.

The `kg-microbe-research authorize` command evaluates policy only and never
invokes a provider. Its exit codes are the machine-readable half of the
contract:

| Exit | Meaning |
|---:|---|
| 0 | live execution authorized |
| 2 | a policy refusal, and nothing else |
| 3 | a permitted dry run |
| 1 | malformed or unsatisfiable input: unknown subcommand, missing or bad argument, unknown focus/stage, unknown provider in `--allow`, unreadable profile, `--no-paid` that no provider can satisfy |

Argparse exits 2 for a usage error by default, which would collide with a
policy refusal, so the parser is overridden to exit 1 (#153). A malformed
allowlist raises `PolicyInputError`, deliberately outside the `PolicyError`
hierarchy, so a caller reading exit 2 as "policy said no" never sees a typo.
`--json` still emits the same refusal payload for a malformed request; only the
exit code distinguishes it, so machine callers lose nothing.

`kg-microbe-research scaffold-result` saves a schema-valid `DRY_RUN` bundle with
an evaluation row for every catalogue provider at every stage, policy-eligible
assignments, and embedded checksum-bound profile and target input bytes.
`validate-result` checks its closed LinkML shape, lifecycle, references, profile
replay, paths, and artifact bytes. Raw `COMPLETED` capture uses `NOT_ASSESSED`;
assessed claims require named per-claim `ResearchEvidence` against independent
source snapshots. Assessment lineage is checksum-bound and preserves the raw
plan, status, runs, citations, and artifacts. The POSIX public result writer is
append-only and has no overwrite mode. Neither command calls a provider. A
saved `ResearchPlan` has `authority: audit_only`; never deserialize it into
execution authority.
Rebuild and authorize a fresh in-memory triage plan immediately before any
future provider call. See `docs/guides/DEEP_RESEARCH_RESULTS.md`.

Never call a provider to test this code. The package contains no provider health
probe or provider-call path, and every contract in `tests/` is offline and
deterministic. Inject local configuration with `environ` and `StaticProbe`, and
inject prior functional evidence separately with `StaticAvailability` or the
strict cached-evidence loader.

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
src/kg_microbe_agents/definitions/  packaged YAML agent definitions; declaration is not execution
cli/          discovery, status, plugin checks, and configuration validation
plugins/      validated repository adapters and coordination primitives
pipelines/    curation/orchestration workflows with explicit support status
src/          installed kg_microbe_* libraries, CLIs, and canonical governance payloads
scripts/      maintenance and migration scripts; audit before treating as supported
tests/        the only default pytest collection root
docs/         current index, guides, proposals, reviews, and archive
workspace/    gitignored runtime state
```

Key shared console scripts:

```bash
uv run kg-microbe-research --help
uv run kg-microbe-history --help
uv run kg-microbe-governance --help
uv run kg-microbe-kgscan --help
uv run kg-microbe-qc --help
uv run kg-microbe-discussions --help
```

## Change conventions

- Add regression tests under `tests/` for every repaired failure mode.
- Return nonzero from CLI failures; printing an error is not sufficient.
- Do not swallow partial failures into a successful report.
- Use timezone-aware UTC timestamps.
- Use atomic creation/replacement for locks and curated data. For a writer that
  touches more than one file, prefer `ValidatedWriteTransaction` over a
  per-record write loop: writing as you go means a failure part-way through
  leaves an unknown subset of the corpus modified.
- Preserve unrelated user changes and generated artifacts.
- Prefer `uv run python` over machine-specific interpreter paths.
- Keep README user-facing; put agent-only constraints here; put detailed design
  rationale in `docs/proposals/` or `docs/guides/`.

## Prompts and review workflow

- `src/kg_microbe_governance/artifacts/prompts/backlog-loop-goal.md` is the
  canonical hand-over prompt for the native `/goal` and the source vendored to
  each Mech.
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
