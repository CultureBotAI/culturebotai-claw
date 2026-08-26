# Mech general-functionality standardization plan

Plan saved: 2026-08-24

Repository inventory reviewed: 2026-08-22

Implementation status updated: 2026-08-25. Phases 0 and 1 are complete; the
current-state inventory below remains the baseline that motivated the program.

Repositories: CultureMech, TraitMech, MediaIngredientMech, CommunityMech,
ProteinTraitsMech, and culturebotai-claw

## Executive decision

`culturebotai-claw` should become the canonical home for functionality that is
general across Mechs. Each Mech should retain only its domain data, schema
extensions, research focuses, prompt content, target resolution, and thin
adapters to the shared functionality.

The present fleet does not meet that model. Claw is a partial control plane:
some shared tools are packaged there, some are passive mirrors of CultureMech,
and substantial general behavior is duplicated independently in the five Mechs.
Even the definition of the fleet varies between three, four, and five Mechs.

Standardization does not mean making every Mech use every feature. A capability
may be explicitly `not_applicable` with a machine-readable reason. For example,
record-level knowledge-gap scanning is not currently applicable to the
ontology-derived ProteinTraitsMech corpus. The goal is one implementation and
an explicit capability declaration, not artificial feature parity.

No live research provider needs to be called while implementing or testing this
plan. Provider integration must be verified with static configuration, mocks,
fixtures, injected environments, and dry-run command construction.

## Current-state summary

| Surface | Distribution today | Claw status | Standardization verdict |
|---|---|---|---|
| Fleet repository registry | Different code paths know three, four, or five Mechs | Core repository settings and CLI know only three | One canonical five-Mech manifest is required |
| Deep-research provider triage | Five separate provider scripts and five domain profiles | Missing | Centralize provider catalogue, ranking, policy, and execution |
| Deep-research result storage | Markdown reports plus provider-specific metadata YAML | No shared result schema | Add schema-governed plans, runs, citations, artifacts, and results |
| Entity research runners | One per Mech, with repeated provider/credential/command logic | Missing | Shared runner plus domain adapters |
| Paid-call safety | Four runners are live-by-default; ProteinTraitsMech requires `--apply` | No fleet policy | Dry-run by default; explicit live and paid authorization |
| Source-fetch skill | Present in all five, with divergent variants | Missing | Canonical parameterized skill and fetch contract |
| Open-issue review skill | Present in all five, with repo-name differences | Missing | Canonical skill driven by the fleet manifest |
| Next-task/backlog skill | Present in four | Missing | Canonical skill with per-repo backlog paths |
| Schema-gap audit | Multiple overlapping skills across four Mechs | Conceptual reference only | One executable framework plus schema adapters |
| ID/label validation | Operational in all five | Passive mirror and fleet audit | Make claw authoritative for implementation and contract |
| Strict validation | Implemented separately in all five | Missing | Shared validation protocol with domain profiles |
| Validated atomic writes | Capability exists in all five through different APIs | Shared transaction missing | One write transaction and writer registry |
| Writer audit | Five distinct scripts | Missing | Shared writer contract and audit engine |
| History | Vendored schema in five; scaffolders vary | Packaged shared CLI and schema mirror | Retain central CLI; make schema authority explicit |
| QC, discussions, and knowledge-gap tools | Four Mechs consume claw packages | Packaged | Keep central; add profile schemas and capability declarations |
| Claude coordination hooks | Present in three; two hard-code a machine path and fail open | Missing | Generate portable hooks from claw configuration |
| CI workflows | Similar concerns, different files and job composition | No reusable workflow library | Add reusable workflows with thin local callers |
| Page/browser infrastructure | Similar site features, multiple implementations | Some shared browser/QC code | Extract common rendering, theme, and budget contracts |
| Source inventory/ingestion | Most developed in ProteinTraitsMech | Missing | General source-manifest and ingestion framework |
| Corpus statistics/scalability | Individual skills in CultureMech or ProteinTraitsMech | Missing | General profiling and scalability tools |

## Principal findings

### 1. There is no single fleet definition

Claw's core repository settings, packaged
`kg_microbe_config/openclaw_config.yaml`, CLI status command, and several
declarative agents list only CultureMech, MediaIngredientMech, and CommunityMech.
The cross-Mech synchronization skill includes TraitMech but not
ProteinTraitsMech. Fleet PR and vendored audits know all five.

This is a systemic correctness problem. Every shared tool independently naming
repositories guarantees future omissions.

### 2. Claw's current governance direction conflicts with the target model

The current shared-file documentation intentionally calls claw a passive mirror
and treats CultureMech as the canonical fetch hub. That was a deliberate prior
decision, so moving authority is a governance migration rather than a file copy.

Because claw is now the intended public orchestration and shared-component
repository, new general functionality should originate here. Existing canonical
sets should migrate only with explicit pins, compatibility checks, and a
coordinated fleet rollout.

### 3. Deep research is structurally aligned but operationally duplicated

All five Mechs expose the same broad architecture:

- a provider catalogue with capabilities, cost, latency, source scope, and
  limitations;
- focus-specific discovery, synthesis, and verification scoring;
- provider allowlists and no-paid filtering;
- a domain-specific entity resolver and prompt;
- a shared behavioral contract test; and
- dry-run or mocked tests that do not spend provider credits.

However, every Mech carries its own provider implementation. Provider aliases,
credential handling, command construction, status vocabulary, JSON rendering,
and error behavior have already drifted. Triage also stops at a recommendation:
the entity runners accept a manually supplied provider and do not enforce the
triage decision or its no-paid policy.

### 4. Research artifacts are not governed by a shared schema

The committed research products are primarily Markdown, sometimes accompanied
by an Edison-style `*-meta.yaml`. There is no shared `ResearchPlan`,
`ResearchRun`, `ResearchCitation`, `ResearchArtifact`, or `ResearchResult`
class, and the metadata YAML is not validated against a common schema.

Schema validation of a later curated Mech record does not make the research
artifact itself schema-compliant. The two contracts must be distinct:

1. the research run and its evidence/provenance are schema-valid; and
2. any proposed domain change is validated against the target Mech schema before
   it can be applied.

### 5. Provider execution safety is inconsistent

CultureMech, TraitMech, MediaIngredientMech, and CommunityMech execute a provider
unless the caller supplies `--dry-run`. ProteinTraitsMech defaults to dry-run
and requires `--apply` for a possibly billed call.

The central runner should adopt the safer behavior and additionally require an
explicit paid-provider acknowledgement or budget ceiling. A credential being
configured must remain distinct from a provider being functionally certified.

### 6. Shared skills are copied rather than parameterized

The strongest general-skill candidates are:

- `fetch-source` — all five;
- `review-open-issues` — all five;
- `next-tasks` — four;
- `schema-gap-analysis` / `audit-schema-gaps` — overlapping implementations;
- `id-label-correspondence` — general engine but incomplete skill coverage;
- `generate-schema-artifacts` — only CommunityMech;
- `stats-report` — only CultureMech;
- `scalability-check`, `data-sources`, `ingest-source`, and
  `review-record-samples` — only ProteinTraitsMech; and
- instruction-reference integrity and PR-sanity checks — isolated to individual
  Mechs.

Repo names, paths, schemas, and commands should be profile data. The method,
safety rules, output contract, and tests should live in claw.

### 7. Write safety has five implementations and no common transaction

All five Mechs now have some combination of strict validation, writer audits,
and validated writes. Four use package-level `write_validated.py` variants;
ProteinTraitsMech uses a richer `record_io.py` path. Claw itself states that
backup and transaction behavior remains each writer's responsibility.

This leaves the most important mutation boundary outside the shared control
plane. The common API should provide validation-before-replace, atomic replace,
backup/recovery metadata, locking, dry-run diffs, and a writer registry.

### 8. Hooks and workflows are both incomplete and inconsistent

Only CultureMech, MediaIngredientMech, and CommunityMech carry Claude
coordination hooks. MediaIngredientMech and CommunityMech embed a user-specific
absolute path and fail open when the lock checker errors; CultureMech uses an
environment variable and fails closed. TraitMech and ProteinTraitsMech have no
equivalent hooks.

All five run strict validation, but the workflow files are different. History,
label correspondence, vendored sync, page generation, documentation freshness,
instruction-reference checks, PR sanity, and scalability budgets are composed
differently or present in only one repo.

Claw should own reusable workflows and hook templates. Each Mech should contain
only a small caller or generated wrapper with domain-specific inputs.

## Target ownership model

### Claw owns

- the canonical five-Mech fleet and capability manifest;
- shared LinkML schemas and configuration schemas;
- provider catalogue, triage, execution policy, and research-run capture;
- validated atomic write transactions and writer auditing;
- shared QC, history, discussions, knowledge-gap, source-fetch, statistics,
  and scalability engines;
- canonical general skills and hook templates;
- reusable GitHub workflows and fleet contract tests;
- generic browser, graph-layout, and site-quality components; and
- generators/synchronizers for thin Mech-facing adapters.

### Each Mech owns

- its domain record schema and corpus;
- domain-specific research focuses and source priorities;
- prompt content and template variables;
- target resolution and record summarization;
- domain validation extensions;
- domain-specific curation skills; and
- a thin capability profile and adapters to claw APIs.

### Explicit non-goals

- Do not force non-applicable features onto a Mech.
- Do not make domain schemas or research prompts byte-identical.
- Do not certify live provider availability by spending credits in CI.
- Do not require a sibling source checkout at runtime once claw is packaged;
  use a pinned package, reusable workflow, or deliberately vendored artifact.
- Do not migrate every historical one-off script into the supported API.

## Proposed claw structure

```text
conf/
  fleet.yaml
  schemas/
    fleet-profile.yaml
    provider-profile.yaml
    qc-profile.yaml
    knowledge-gap-profile.yaml
    discussions-profile.yaml
  research-profiles/
    culturemech.yaml
    traitmech.yaml
    mediaingredientmech.yaml
    communitymech.yaml
    proteintraitsmech.yaml

src/
  kg_microbe_fleet/
  kg_microbe_research/
  kg_microbe_curation/
  kg_microbe_validation/
  kg_microbe_sources/
  kg_microbe_history/
  kg_microbe_qc/
  kg_microbe_kgscan/
  kg_microbe_discussions/
  kg_microbe_web/
  kg_microbe_governance/
    artifacts/
      schema/
        mech_shared.yaml
        history.yaml
      scripts/
      tests/
      prompts/
```

The exact package boundaries can be adjusted during implementation, but there
must be one source of truth for each general contract.

## Implementation roadmap

### Phase 0 — Establish the fleet contract

> **Implementation note (Phase 0, landed).** The manifest ships as
> `src/kg_microbe_fleet/fleet.yaml`, not `conf/fleet.yaml` as written below.
> Existing installed commands need the manifest in the wheel; a root `conf/`
> file is absent after installation. Consumers load one manifest snapshot at
> command time and inject it into repository settings. Only the location
> changed; the contract is as specified. Package paths, primary schema paths,
> and canonical record globs were verified against all five local Mech checkouts
> on 2026-08-25 and are included in each profile. Repository settings, packaged
> configuration and agents, CLI queries/status, fleet audits, general skills,
> capability-scoped workflows, and coordination-hook installation now consume
> this contract. Source-distribution-to-wheel smoke tests prove the manifest,
> configuration, and agents work without the source checkout. All acceptance
> tests are deterministic and provider-credit-free. Domain research focuses
> remain Phase 2 profile data rather than fleet-identity metadata.

1. Add `conf/fleet.yaml` with all five Mechs, their GitHub identities,
   environment variables, package/schema locations, record globs, and declared
   capabilities.
2. Model capability status as `enabled`, `disabled`, or `not_applicable`, with a
   required reason for the latter two.
3. Update `RepositorySettings`, the packaged `openclaw_config.yaml`, CLI status,
   agents, fleet audits, and skills to consume the manifest.
4. Add a test that fails when code hard-codes a divergent fleet list.
5. Update claw metadata and documentation to describe all five Mechs.

Acceptance criteria:

- every fleet-facing command discovers exactly the same five repositories;
- no supported component contains an independent Mech list; and
- ProteinTraitsMech appears in core configuration and status output.

### Phase 1 — Move shared-schema and vendored governance to claw

> **Implementation note (Phase 1, completed 2026-08-25).** Authority migration
> used two claw commits around a coordinated five-Mech rollout. The bootstrap
> packages one strict artifact manifest, the converged canonical payloads, an
> identity-validated dry-run/apply synchronizer, and a dependency-free pinned
> checker while `fleet.yaml` was explicitly in `transition`. The synchronizer
> proves that the requested claw SHA contains the installed manifest and bytes
> before writing it as a pin. All five Mechs now pin bootstrap merge
> `a8f7c94d8d5ccfa0ed430e4d3c5d0dbf63af2416` through CultureMech #340,
> MediaIngredientMech #472, CommunityMech #683, TraitMech #516, and
> ProteinTraitsMech #564. The local five-worktree audit verified exact committed
> `origin/main` roots, bound that SHA to the installed manifest/payload bytes,
> and compared every pin, file, and Git mode directly with each `HEAD` tree.
> The final claw commit therefore switches to `authoritative`, forbids a Mech
> hub, repoints the history package and ID-label behavioral job to canonical
> packaged assets, and removes the compatibility mirrors. The migration avoided
> circular/self pins and never called a research provider.

1. Make claw canonical for `mech_shared.yaml`, `history.yaml`, shared validator
   code, shared behavioral tests, and the backlog-loop contract.
2. Preserve commit pins so public Mech CI can consume immutable claw revisions.
3. Replace CultureMech-hub assumptions in vendored checks with claw canonical
   references.
4. Provide a single manifest and sync command for all governed artifacts.
5. Roll out the new pin to all five Mechs in coordinated PRs.
6. Retire the old CultureMech authority only after the fleet audit passes
   against claw.
7. Migrate claw's remaining operational `shared/history` and `shared/idlabel`
   consumers before removing those compatibility paths: history defaults/help,
   package data, tests/workflow/docs; ID-label workflow working directory,
   Pytest/Ruff exclusions, and fleet audit script; mirror tests; all three
   `shared/{history,idlabel,spoke}` trees; and the root skill/backlog contract
   copies. Add a no-reference/no-reintroduction guard for retired paths.

Acceptance criteria:

- claw contains every canonical shared artifact;
- each Mech consumes an immutable claw revision;
- no circular or self-referential pin remains; and
- the fleet audit checks committed missing files, byte drift, and Git modes,
  including when ignore or index flags hide working-tree state.

All Phase 1 acceptance criteria passed. The recorded pre-flip audit used clean
detached worktrees at CultureMech `0422968004b99c91ed356d6ee4e38b7e93f371d5`,
MediaIngredientMech `82694054f5bbf74b5392bf8858c9962c2152a35a`,
CommunityMech `ba596731b23b799f4baca96984ceb8f0d56874fe`, TraitMech
`3ee94eeec831d98d2a2cc1ebe2368fe3fa122f69`, and ProteinTraitsMech
`a70ff8f5564b77a50963daafaacc2dde013eb1a2`; it reported 14, 14, 14,
14, and 13 applicable artifacts respectively.

### Phase 2 — Build the shared deep-research subsystem

> **Implementation note (Phase 2, provider subsystem landed).** `kg_microbe_research`
> now owns the provider catalogue, focus-profile validation, deterministic
> triage, and the execution policy; each Mech keeps its own
> `conf/deep_research_provider.yaml`. Verified against `origin/main` in all five
> repositories on 2026-08-25: every Mech carried its own
> `scripts/deep_research_provider.py` (614-688 lines, five distinct hashes,
> ~3,280 lines total). The two closest pairs differ only in comments, so the
> divergence is copy drift rather than domain need — but it is not only
> cosmetic: CultureMech and ProteinTraitsMech reject a non-numeric capability
> weight, stage weight, or provider adjustment, MediaIngredientMech and
> CommunityMech accept them and fail later inside scoring, and TraitMech has
> dropped `credential_status` altogether. The shared loader takes the strictest
> behaviour of each and is verified to accept all five committed profiles
> unchanged, so adoption is not a data migration.
>
> Items 1, 4, and 5 are implemented. Availability is injected through `environ`
> and a `LocalProbe`, so no test depends on the developer's PATH and no test
> touches the network. Items 2, 3, 6, and 7 — the LinkML research schema, the
> schema-compliant run record, the adapter protocol, and converting the five
> runners — are deliberately left to follow-up work; this lands the contract
> they consume. Until then the five runners still execute live by default, so
> the safety fix is available but not yet enforced at their call sites.

1. Create `kg_microbe_research` with:
   - provider definitions and aliases;
   - capability, source-scope, cost, and latency vocabulary;
   - credential/configured/available/blocked status separation;
   - focus-profile validation;
   - deterministic stage ranking and assignment;
   - allowlist and no-paid policy enforcement;
   - command construction for supported provider integrations; and
   - mock/dry-run providers for tests.
2. Add a LinkML research schema containing at least:
   - `ResearchQuestion`;
   - `ResearchPlan` and stage assignments;
   - `ResearchRun` and provider status;
   - `ResearchCitation` and evidence snippets;
   - `ResearchArtifact` with checksums and paths;
   - `ResearchFinding` with support level;
   - `ProposedChange`; and
   - `ResearchResult`.
3. Store the rendered query, canonical provider, focus, target identity, config
   hash, timestamps, cost/budget, task identifier, status, citations, and output
   checksums in the schema-compliant record.
4. Require dry-run by default. Live execution requires `--apply`; paid execution
   additionally requires an explicit paid acknowledgement or budget ceiling.
5. Connect execution to an immutable triage plan so a manually supplied
   provider cannot bypass policy silently.
6. Add a common adapter protocol for resolving a domain target, rendering prompt
   variables, and validating proposed changes.
7. Convert each Mech runner into a thin adapter and retain its two custom focus
   profiles.

Acceptance criteria:

- all provider and assignment tests pass without network calls;
- all saved metadata validates against `research.yaml`;
- no command spends credits without two explicit decisions: live execution and
  paid-provider authorization;
- each Mech can render a complete dry-run plan and result skeleton; and
- provider behavior is governed centrally while domain focus remains local.

### Phase 3 — Centralize validated writes and writer audits

1. Define a `ValidatedWriteTransaction` API with:
   - exact target resolution;
   - repository identity and lock checks;
   - proposed diff generation;
   - schema and domain validation before replacement;
   - atomic replacement;
   - backup/recovery metadata; and
   - explicit apply authorization.
2. Define a writer registry that declares every in-place editor, its target
   classes, validation profile, and derived artifacts.
3. Generalize the strongest AST/runtime writer-audit checks from the Mechs.
4. Add adapter hooks for repositories whose serialization requirements differ.
5. Migrate writers incrementally; block new unmanaged in-place writers in CI.

Acceptance criteria:

- every registered writer uses the shared transaction or has a reviewed,
  time-bounded exception;
- invalid output never replaces source data;
- interrupted writes are recoverable; and
- claw can audit all five writer registries without modifying a repository.

### Phase 4 — Centralize general skills and hooks

1. Add canonical claw skills for source fetching, issue review, next tasks,
   schema-gap auditing, ID/label validation, schema-artifact generation,
   corpus statistics, sample review, and scalability checks.
2. Parameterize repo names, paths, commands, labels, and output locations from
   `fleet.yaml` or a Mech capability profile.
3. Retain thin domain-specific skills only where scientific policy differs.
4. Add a skill-reference checker that validates every local path, command, and
   sibling-skill reference.
5. Create portable pre/post edit and commit hooks generated from the fleet
   profile.
6. Remove hard-coded machine paths and choose one documented fail-closed policy
   for configured coordination.

Acceptance criteria:

- one canonical general skill can be rendered for each applicable Mech;
- generated adapters pass the shared skill-frontmatter and reference tests;
- hooks work from arbitrary checkout locations; and
- missing configured lock infrastructure cannot silently fail open.

### Phase 5 — Provide reusable CI workflows

Create reusable claw workflows for:

- strict schema validation;
- curation-history validation;
- ID/label correspondence;
- vendored/shared-component drift;
- skill and instruction-reference integrity;
- page generation and artifact freshness;
- PR check presence and sanity;
- documentation freshness; and
- repository/page-size budgets.

Each Mech should keep a small caller workflow passing its profile, paths, Python
versions, and optional domain jobs. Consolidating workflows must not erase
domain-specific gates such as concentration plausibility or community-network
quality.

Acceptance criteria:

- common job logic exists only in claw;
- every applicable Mech calls the same pinned reusable workflow;
- capability-disabled jobs are reported explicitly rather than silently
  skipped; and
- a fleet audit verifies workflow pins and required callers.

### Phase 6 — Consolidate general web, source, and quality functionality

1. Extract a shared site shell, navigation, accessibility contract, asset
   policy, and page-budget checks.
2. Consolidate reusable browser export, graph layout, UMAP/dimensionality, and
   KGX export primitives while retaining domain adapters.
3. Define a common source manifest and robust fetch API based on the strongest
   existing fetch-source implementation.
4. Generalize source ingestion, licence/provenance recording, corpus statistics,
   record sampling, and scalability reporting.
5. Keep domain acceptance rules and source-specific parsers in their Mechs.

Acceptance criteria:

- common site behavior and budgets are tested once centrally;
- data-source provenance follows one schema;
- fetches are retry-bounded, validated, and atomically promoted; and
- every Mech can produce comparable corpus and repository-health reports.

### Phase 7 — Remove superseded copies and enforce convergence

1. Mark old local implementations deprecated before removal.
2. Provide compatibility wrappers for one release window where needed.
3. Remove duplicate general implementations after every Mech uses the pinned
   claw component.
4. Add a fleet test that rejects reintroduction of governed duplicate code.
5. Update the shared-functionality review and architecture documentation.

Acceptance criteria:

- general code has one canonical implementation;
- Mech repositories contain only profiles, adapters, wrappers, and domain code;
- all five repositories pass their full local checks and the claw fleet audit;
  and
- rollback instructions exist for each migrated subsystem.

## Suggested issue decomposition

1. **Create canonical five-Mech fleet manifest and capability model**
2. **Make claw authoritative for shared schemas and vendored contracts**
3. **Implement shared deep-research provider catalogue and triage engine**
4. **Add schema-compliant ResearchPlan/ResearchRun/ResearchResult capture**
5. **Require explicit apply and paid authorization for provider execution**
6. **Convert five entity research runners to shared core plus adapters**
7. **Implement shared validated-write transaction and writer registry**
8. **Centralize general Claude skills and generate Mech adapters**
9. **Replace hard-coded coordination hooks with claw-managed hooks**
10. **Publish reusable strict/history/id-label/vendored workflows**
11. **Standardize skill references, PR sanity, docs freshness, and budgets**
12. **Extract common browser, graph, source-ingestion, and corpus-health tools**
13. **Remove superseded Mech copies and add anti-duplication fleet gates**

These issues should be implemented in order where dependencies require it.
In particular, the fleet manifest and governance decision should land before
new components are propagated, and the research artifact schema should land
before the five runners are migrated.

## Verification strategy

All shared components require three layers of tests:

1. **Unit contracts in claw** — deterministic, offline, and provider-credit-free.
2. **Adapter contracts in every Mech** — load the real profile/schema and render
   or validate representative records without network calls.
3. **Fleet integration audit** — verify pins, capability declarations, workflow
   callers, generated adapters, and absence of unmanaged duplicate code.

For provider functionality, testing a configured credential is not sufficient
evidence that a service is operational. CI should certify integration behavior,
not remote account credit, service uptime, or answer quality. Optional live
smoke tests must remain manual, budget-capped, and disabled by default.

## Definition of done

The standardization program is complete when:

- claw has one authoritative inventory of all five Mechs;
- every general component is implemented and tested in claw;
- each Mech declares whether the component is enabled or not applicable;
- domain differences are expressed through validated profiles and adapters;
- deep-research plans and results are schema-compliant;
- provider calls are dry-run and no-paid by default;
- shared writes are validated, atomic, locked, and recoverable;
- CI and skills consume pinned claw contracts;
- fleet audits detect missing, divergent, or reintroduced duplicate components;
  and
- no provider credits are spent by the standard test suite.
