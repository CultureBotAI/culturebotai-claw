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
- CellStructureMech (`CELLSTRUCTUREMECH_ROOT`)

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
- `kg_microbe_patches`: a ledger for generated, not-yet-applied patch sets.
  Records each run's fingerprint so a set returning unchanged is reported as an
  unapplied backlog with an age, and warns when a generated artifact predates
  its inputs. It tracks; applying a patch means changing another repository.
- `kg_microbe_consistency`: a read-only cross-record scanner. Groups records
  that plausibly denote the same substance and reports where a curated field
  disagrees. `--propose` additionally emits correct-by-analogy proposals, but
  only for the one unambiguous shape: an ontology-grounded record beside a
  registry or placeholder fallback for the same substance. Two competing
  ontology terms are surfaced and never resolved -- there is no basis in the
  data for picking a winner. `--shape embedded-ingredients` reads corpora that
  hold many grounded entries per document, such as CultureMech media, and a
  disagreement involving an `LLM_ASSISTED` grounding is counted separately:
  that record is internally consistent, so id-label correspondence cannot see
  it. Nothing is ever written to a corpus.
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
- A claw-governed standalone Mech execution contract for native, explicitly
  web-enabled Codex calls with schema plus semantic output validation, and
  non-billing Codex/OpenScientist canaries. It remains separate from
  `kg_microbe_research`, which does not execute providers.
- The assertion-based suite under `tests/` and fleet workflows under `.github/`.

Experimental or disabled:

- `.github/workflows/label-correspondence-reusable.yaml` until a Mech calls it.
  A `workflow_call` workflow is only executed by a caller, so claw's own CI can
  check its shape and nothing more. TraitMech is the canary (#180); the other
  four adopt it only after that run passes for real.

- `openclaw-cli agent run` and `pipeline run` execution without `--dry-run`.
- Environment-curation apply mode; it raises until an atomic validated writer exists.
- Unified ingredient-mapping apply mode; it raises until all YAML writes are transactional.
- Provider command construction and *execution inside `kg_microbe_research`*,
  including an executable mock provider. The package decides whether a call is
  permitted; it does not make one. The separately vendored Mech execution
  contract is supported, but runners must still consult the policy gate before
  any live provider call.
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
  src/kg_microbe_consistency src/kg_microbe_patches \
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
uv run kg-microbe-consistency --help
uv run kg-microbe-research --help
uv run kg-microbe-history --help
uv run kg-microbe-governance --help
uv run kg-microbe-kgscan --help
uv run kg-microbe-qc --help
uv run kg-microbe-discussions --help
uv run kg-microbe-skills --help
uv run kg-microbe-sources --help
```

`kg-microbe-sources check --mech X` validates that Mech's `download.yaml`
source catalogue. A source is a group of one or more file blocks: `name`,
`license` and `seeder` are the source's obligations, met by any block in it,
while `url` and `status` are each block's own, and a multi-file source must say
which file each block describes. Restrictive or unresolved licences are
surfaced as warnings, since carrying licence provenance is what the catalogue
is for. A Mech that declares `source_catalogue: disabled` reports the recorded
reason and exits zero, rather than reading as a missing file.

`kg_microbe_sources.fetch` downloads one source release: bounded retries, then
size/digest/prefix/content validation, then an atomic replace with a provenance
sidecar. The transport is injectable, so the interesting behaviour is testable
offline; `curl` is only the default. `verify(path)` reads a file back against
its sidecar, which is what makes a torn promotion detectable rather than
believed.

`kg-microbe-corpus report --mech X` walks that Mech's `record_globs` and reports
record and byte counts per glob plus how each declared field is populated, as
deterministic JSON two releases can be diffed. Which fields are tabulated is the
`corpus_statistics` capability's `fields` setting -- the domain part -- and every
declared field is checked against its own corpus by a test, because a field no
record carries reports as a data problem rather than a wrong declaration. An
unreadable record is named and exits nonzero, since it is excluded from every
count above it.

`kg-microbe-pages audit --mech X` measures a built site against the budgets that
repository declares -- total bytes, file count, and per-group totals and largest
members, where a group is a glob the Mech names. A site with too few files fails
before any size limit, because an empty site is under all of them. The limits
live in the Mech; only the mechanism is here.

`kg-microbe-health report --mech X` (or `--mech claw`) reports what a repository
costs to carry: tracked files and bytes, where the weight sits by top-level
directory and by extension, and the largest tracked files. Measured from git, so
a working tree's caches and build output cannot change the answer.

`kg_microbe_graph.audit` checks a causal graph's structure: dangling edges,
duplicate node ids, orphan nodes, fragmentation, and reachability from a
declared anchor type. These are properties of a graph rather than of a schema,
so enum membership, evidence and CURIE shapes stay in each Mech. Connectivity is
undirected -- a mechanism written effect-to-cause is the same mechanism.

`kg-microbe-writers audit` lists every script that writes a YAML record and
what it declares about doing it. A writer is detected five ways -- `yaml.dump`,
a dump written to a path, the Mech's own save helper, an in-place edit of a
globbed YAML, and a write to a path built from a `.yaml` name. Each Mech's
`audit_writers.py` implements a different subset, which is why they disagree;
the shared rule is the union, and `--why` reports which technique found a row.

`kg-microbe-site check` judges a built site: a title, a declared language, alt
text, headings that do not skip a level, references that resolve, and no
dependency on a third party to render. `site_path` is the set of pages to check
and `published_root` is what a site-absolute reference means and how far a
relative one may climb; they differ when a repository checks part of what it
publishes. Run it on build output. On template
sources it reports pages the build has not created yet and unrendered
expressions as dangling references, which is the check being run one step too
early rather than a defect. A repository declares a deliberate CDN through
`allowed_hosts` in its `site_contract` capability.

`kg-microbe-skills check` validates every path and sibling-skill reference in
`.claude/`. It judges a reference against the repository it belongs to, and
reports what it could not resolve rather than calling it broken: `missing` and
`ambiguous` fail the command, `unverifiable` does not. A skill whose bare paths
are relative to another repository declares `reference-root:` in its
frontmatter -- a repository name, or `mech` for a path that exists in every
Mech. `kg-microbe-skills catalogue` lists every skill with its scope -- `claw`,
`fleet` (resolves the repositories it acts on from the manifest), or `domain`
(scientific policy for one corpus) -- plus the canonical templates and, from
the capability each declares, which Mechs need an adapter.
`kg-microbe-skills render --skill X --mech Y` prints one. It prints; installing
an adapter into a Mech checkout is a downstream mutation and goes through the
cross-repository checklist as its own change.

Existence is decided by git, not the filesystem, so the verdict is the same on
a laptop and in CI: tracked is fine, gitignored counts as a generated artifact,
and neither means no clone of that repository has it. It reads backticked
prose and shell code fences; a `cd` inside a fence moves the paths that follow,
including through a `${VAR:-default}` fallback. Non-shell fences are not read,
because they carry literal data the path rules would misread.

## Change conventions

- Add regression tests under `tests/` for every repaired failure mode.
- Return nonzero from CLI failures; printing an error is not sufficient.
- Do not swallow partial failures into a successful report.
- Use timezone-aware UTC timestamps.
- Serialize a downstream record with `kg_microbe_write.dump_record(mech_key, …)`,
  never a local `yaml.safe_dump`. The emit options live in the manifest and are
  declared only where they were measured to round-trip that Mech's corpus
  byte-for-byte; two Mechs have no such option set and the call refuses rather
  than reformatting their records (#187).
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
