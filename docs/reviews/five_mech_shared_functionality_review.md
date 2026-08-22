# Five-Mech shared-functionality alignment review

Review updated: 2026-08-21

Repositories reviewed: CultureMech, TraitMech, MediaIngredientMech,
CommunityMech, and ProteinTraitsMech.

## Executive summary

The five repositories now expose the same deep-research architecture while
retaining the domain specialization that makes each Mech useful. Every Mech has
a committed provider profile with two custom research focuses, three-stage
discovery/synthesis/verification triage, an entity runner, schema-compliant
research capture, and provider-credit-free inspection and tests.

Alignment does **not** mean byte-identical provider implementations. TraitMech
correctly distinguishes a credential that is merely `configured` from a
provider that is locally verifiably `available`; the other Mechs retain
measured blocked-provider policy. Shared observable behavior is therefore
governed by a byte-identical contract test, while domain policy stays local.

The two concrete ProteinTraitsMech parity gaps found in the first review pass
are now implemented. Registered definition editors use schema-validated atomic
writes, and an offline corpus-internal id-to-label gate pins the exact known
mismatch set. Those remediations are recorded in
[#492](https://github.com/CultureBotAI/proteintraitsmech/issues/492) and
[#493](https://github.com/CultureBotAI/proteintraitsmech/issues/493).

No live research provider was invoked during this review or remediation. No
provider credits were spent.

## Domain-specific deep-research focus

| Mech | Default focus | Second focus | Primary curated object |
|---|---|---|---|
| CultureMech | `growth_evidence` | `formulation` | exact medium, variant, strain, and growth conditions |
| TraitMech | `causal_mechanism` | `definition_grounding` | microbial trait scope, taxon evidence, and causal edges |
| MediaIngredientMech | `identity_mapping` | `functional_roles` | chemical/formulation identity and context-specific media roles |
| CommunityMech | `ecological_mechanism` | `datasets_environment` | community membership, interactions, environment, and accessions |
| ProteinTraitsMech | `mechanism` | `family_grounding` | protein mechanism, family identity, hierarchy, and cross-resource mapping |

Each profile explicitly prioritizes its authoritative source types. Provider
scores are comparable within a stage, not across Mechs or stages.

## Alignment matrix

| Capability | Culture | Trait | Ingredient | Community | Protein |
|---|---:|---:|---:|---:|---:|
| Domain-specific provider profile | Yes | Yes | Yes | Yes | Yes |
| Discovery/synthesis/verification triage | Yes | Yes | Yes | Yes | Yes |
| Allowlists and no-paid policy | Yes | Yes | Yes | Yes | Yes |
| Credit-free shared behavior contract | Hub | Yes | Yes | Yes | Yes |
| Generic entity research runner | Yes | Yes | Yes | Yes | Yes |
| Schema-compliant result capture | Yes | Yes | Yes | Yes | Yes |
| Edison verbose provenance capture | Yes | Yes | Yes | Yes | N/A |
| Shared `Discussion` / `Dataset` schema | Yes | Yes | Yes | Yes | Yes |
| Strict closed-schema validation | Yes | Yes | Yes | Yes | Yes |
| External append-only history | Yes | Yes | Yes | Yes | Yes |
| Vendored shared-file enforcement | Hub | Yes | Yes | Yes | Yes |
| Writer classification/audit | Yes | Yes | Yes | Yes | Yes |
| Validated-write path | Yes | Yes | Yes | Yes | Yes |
| ID-to-label actionable gate | Yes | Yes | Yes | Yes | Yes |

`N/A` is intentional: ProteinTraitsMech has the generic multi-provider runner
but no Edison-specific runner/capture path.

## Provider query triage and assignment review

### What is aligned

All five provider profiles use explicit capabilities, costs, latency,
synthesis depth, source scope, limitations, and focus-specific adjustments.
Assignment proceeds stage-by-stage. The shared contract now pins:

- deterministic ranking when every raw score is negative and displayed fit is
  floored to zero;
- consistent `--allow` and `--no-paid` semantics;
- rejection of unknown capabilities before scoring;
- self-consistent provider-filtered JSON;
- exclusion of paid tiers from no-paid recommendations; and
- local-only inspection with no provider call.

### Intentional implementation differences

TraitMech reports `configured` separately from `available`. A credential is
not proof of working service or sufficient account credit, so configured
providers remain explicitly unverified even when they are routable. The other
Mechs retain a measured blocked-provider table for services known to return 402
or 500 responses. The contract governs policy outcomes without erasing this
more honest status vocabulary.

Each Mech also owns its focus definitions, capability weights, templates, and
target resolution. These must remain specialized; byte-syncing the whole
provider script would incorrectly make domain details canonical.

### Functional status

The providers are **integration-functional but not live-service-certified** by
this work. Configuration loading, aliases, status detection, policy filters,
ranking, JSON output, dry-run routing, prompt rendering, and schema-compliant
capture were tested. External provider availability, account credit, remote
service behavior, and answer quality were deliberately not tested because doing
so could spend credits. A configured credential must not be read as proof that a
provider will complete a job.

## Adversarial findings and remediation

### 1. Negative scores collapsed into alphabetical routing

Absolute fit intentionally floors negative scores at zero. Sorting only by
displayed fit therefore made all-negative stages alphabetical, losing the
least-bad ordering. Ranking now uses raw score as a deterministic tie-break
while preserving public fit semantics. A common regression test runs in every
Mech.

### 2. Edison enrichment could attribute stale same-stem artifacts

The first fix checked the task id in `agent-state.json`, but adversarial review
found that other response, citation, answer, and file sidecars could still be
left from the old task. A task mismatch now invalidates the whole set. Metadata
claims only files refreshed for the current task; failed refetches and stale
artifact listings remain unclaimed.

### 3. Vendored enforcement could silently shrink

An optional governed file selected by local existence disappears from the gate
when the file itself is deleted. Repository identity now determines whether the
Edison capture helper is required. The checker also governs its own bytes, the
provider contract, both shared schemas, and bounded curl behavior.

### 4. Provider implementations need behavioral, not byte, governance

All five public provider scripts have different Git blob identities. Some
differences are correct, but shared routing behavior previously had no fleet
gate. [CultureMech #330](https://github.com/CultureBotAI/CultureMech/issues/330)
records the finding; the new shared contract is its implementation.

### 5. ProteinTraitsMech foundation gaps were real but narrower than first reported

ProteinTraitsMech has since adopted the shared schema, history, strict
validation, evidence checks, corpus/graph CI, vendored-sync foundation,
validated atomic writes, and an actionable corpus-internal id-label gate. The
last two fixes close the concrete gaps tracked by
[#492](https://github.com/CultureBotAI/proteintraitsmech/issues/492) and
[#493](https://github.com/CultureBotAI/proteintraitsmech/issues/493), completing
the umbrella [#484](https://github.com/CultureBotAI/proteintraitsmech/issues/484).

## Tracking and resolution

| Issue | Result |
|---|---|
| [CultureMech #287](https://github.com/CultureBotAI/CultureMech/issues/287) | Correctly closed when provider files were only untracked local copies; superseded by #330 after all five became public |
| [CultureMech #288](https://github.com/CultureBotAI/CultureMech/issues/288) | Edison current-run provenance propagated |
| [CultureMech #289](https://github.com/CultureBotAI/CultureMech/issues/289) | Citation/runner contract propagated to code-owning repositories |
| [CultureMech #292](https://github.com/CultureBotAI/CultureMech/issues/292) | Stale enrichment attribution fixed |
| [CultureMech #298](https://github.com/CultureBotAI/CultureMech/issues/298) | Vendored checker is self-governed |
| [CultureMech #315](https://github.com/CultureBotAI/CultureMech/issues/315) | Negative-score ordering fixed fleet-wide |
| [CultureMech #330](https://github.com/CultureBotAI/CultureMech/issues/330) | Shared credit-free provider behavior contract implemented |
| [TraitMech #433](https://github.com/CultureBotAI/TraitMech/issues/433) | Edison regression tests and vendored governance implemented |
| [TraitMech #500](https://github.com/CultureBotAI/TraitMech/issues/500) | Task-aware enrichment implemented |
| [MediaIngredientMech #429](https://github.com/CultureBotAI/MediaIngredientMech/issues/429) | Task-aware enrichment implemented |
| [CommunityMech #673](https://github.com/CultureBotAI/CommunityMech/issues/673) | Task-aware enrichment implemented |
| [proteintraitsmech #492](https://github.com/CultureBotAI/proteintraitsmech/issues/492) | Schema-validated atomic writes and an AST-based writer audit implemented |
| [proteintraitsmech #493](https://github.com/CultureBotAI/proteintraitsmech/issues/493) | Offline corpus-internal adapter and exact-baseline CI gate implemented |

## Implementation pull requests

All pull requests below were merged after their required repository checks
passed.

| Repository | Pull requests |
|---|---|
| CultureMech | [#317](https://github.com/CultureBotAI/CultureMech/pull/317), [#329](https://github.com/CultureBotAI/CultureMech/pull/329) |
| TraitMech | [#501](https://github.com/CultureBotAI/TraitMech/pull/501) |
| MediaIngredientMech | [#418](https://github.com/CultureBotAI/MediaIngredientMech/pull/418), [#428](https://github.com/CultureBotAI/MediaIngredientMech/pull/428), [#437](https://github.com/CultureBotAI/MediaIngredientMech/pull/437) |
| CommunityMech | [#674](https://github.com/CultureBotAI/CommunityMech/pull/674) |
| ProteinTraitsMech | [#514](https://github.com/CultureBotAI/proteintraitsmech/pull/514), [#525](https://github.com/CultureBotAI/proteintraitsmech/pull/525), [#553](https://github.com/CultureBotAI/proteintraitsmech/pull/553), [#554](https://github.com/CultureBotAI/proteintraitsmech/pull/554), [#555](https://github.com/CultureBotAI/proteintraitsmech/pull/555) |

## Verification

Focused provider, contract, Edison provenance, and vendored-sync tests:

| Repository | Passing tests |
|---|---:|
| CultureMech | 51 |
| TraitMech | 42 |
| MediaIngredientMech | 38 |
| CommunityMech | 34 |
| ProteinTraitsMech | 41 |
| **Total** | **206** |

ProteinTraitsMech's validated-write remediation additionally passed 188 tests
with 2 skips, its focused AST writer-audit suite passed 52 tests, and its
id-label remediation passed 83 focused tests plus the complete corpus gate.

Ruff, shell syntax, and `git diff --check` also passed on the changed files.
All provider tests use stubs, injected environment mappings, local executable
detection, static configuration, or dry-run behavior. They do not submit a
research task.
