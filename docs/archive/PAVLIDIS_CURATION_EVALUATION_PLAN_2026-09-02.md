# Local analysis and application plan: Pavlidis et al. 2026

> Historical literature analysis and proposal from 2026-09-02, archived on 2026-10-08 UTC.
> Fleet membership, capability gaps, priorities, and proposed schedules below refer to
> the inspected revisions listed in the analysis. They have not been refreshed for
> the current fleet. Publishing this archive records the proposal; it does not implement
> its evaluation program or authorize live provider calls.
> Current references: [fleet manifest](../../src/kg_microbe_fleet/fleet.yaml)
> and [research-result guide](../guides/DEEP_RESEARCH_RESULTS.md).
> The full PDF and text extraction are optional, gitignored local source caches.
> The public paper is available through its [DOI](https://doi.org/10.64898/2026.07.30.741874).

Archival source-summary correction ([#586](https://github.com/CultureBotAI/culturebotai-claw/issues/586)):
the self-revision row distinguishes applied tags from accepted tags and preserves
the second-pass error breakdown. The triage row identifies development-set
cross-validation and the unavailable held-out estimate. Other observations and
proposed work retain their original review date.

## Document provenance

- Title: *Detailed curation of biological samples and experimental designs for genomics using LLM-supported agentic workflows*
- Authors: Paul Pavlidis, B. Ogan Mancarci, Amanda Maximo, Carlton Yan, and Rachel A. Schwartz
- Identifier: bioRxiv preprint `10.64898/2026.07.30.741874`, version posted 2026-08-02
- Status: preprint; not certified by peer review
- License stated in the PDF: CC-BY-ND 4.0
- Public source: [bioRxiv preprint, version 1](https://www.biorxiv.org/content/10.64898/2026.07.30.741874v1)
- Preserved local PDF: `data/pdfs/2026.07.30.741874v1.full.pdf`
- Layout-preserving text extraction: `data/pdfs/2026.07.30.741874v1.full.txt`
- PDF SHA-256: `c1ace8e94d24be4d347ae9934f68b40f288ffe5292388e6fa7ab2aadb40b81e0`
- Extracted-text SHA-256: `508c1e8169ccf337d98bcfbc673677851b96438984f5383e27c2fe597c4e2ad9`
- PDF properties: 28 pages, 3,630,975 bytes, unencrypted, no embedded JavaScript
- Extraction properties: 1,098 lines, 12,979 words, 86,904 bytes
- Analysis date: 2026-09-02

The PDF was copied without transformation. The text was extracted locally with
`pdftotext -layout`; no remote document-processing service was used. This file
is an original analysis, not a transformed edition of the paper.

## Executive interpretation

The paper's most useful contribution to the CultureBotAI system is not a new
provider or a larger model. It is an operating model for proving that an
agent-assisted curator is safe enough to use:

1. Preserve a frozen benchmark and a genuinely held-out set.
2. Separate deterministic extraction, ontology resolution, LLM judgement, and
   post-proposal review.
3. Keep exact evidence and telemetry for every proposed annotation.
4. Evaluate semantic acceptability, not just string equality.
5. Treat errors of commission and omission as different problems.
6. Route human effort using structural risk signals, not an LLM's confidence.
7. Improve the proposer and deterministic harness before adding revision loops
   or buying a stronger model.

The claw already has much of the required safety substrate: immutable plans,
checksummed inputs and source snapshots, per-claim evidence, strict semantic
validation, provider policy gates, append-only results, and validated writes.
The highest-value gap is a common **curation evaluation and review-selection
layer** shared by all Mechs.

## What the paper actually demonstrates

The following findings are measurements reported by the authors, not claims
independently reproduced here.

| Finding | Reported result | Implication for the claw and Mechs |
|---|---:|---|
| Scale and efficiency | More than 23,000 studies; near human performance at about 1/20 the cost and at least 100 times the speed; about $0.50 per study | Cost and latency belong in benchmark results, but only alongside quality and review burden. |
| Hybrid pipeline | A typical study uses about 25 LLM calls inside an extensive deterministic harness | A provider call is one stage of curation, not the curation system itself. |
| Development scale | More than 100,000 lines of Python, 24 prompt/rule files totaling about 50,000 words, and more than 3,400 tests | Durable rules, executable invariants, and regression tests matter more than prompt cleverness alone. |
| Cache/batch economics | Anthropic batch execution and prompt caching; shared content was served from cache for about 60% of calls | Add provider-neutral cost telemetry and exploit batching/caching after quality gates are stable. |
| Benchmark isolation | 400 polished development studies, 100 final studies drawn from a 2,394-study held-out pool, plus a 17,404-study context corpus | Distinguish context/prior corpora from gold and held-out evaluation records, and test for leakage. |
| Ontology priors | Historical term use improved mouse-strain resolution from 77% to 81% and cell-line resolution from 59% to 62.8% | Reuse validated fleet records as priors, but exclude the target under evaluation and always revalidate IDs and labels. |
| Ontology distrust | LLM-emitted ontology labels and URIs were not accepted without inspection and validation | Keep ontology resolution mechanical and record candidates, margins, branch checks, and final resolution provenance. |
| Uneven task quality | Factor detection recall 0.98, factor-value F1 0.62, and experiment-tag F1 0.45 against a curator ceiling near 0.55 | Report field- and task-specific metrics; a single overall score conceals the main gaps. |
| Reference fallibility | Sixteen potential factual substitutions became eight genuine agent errors after inspection; some apparent false positives were valid corrections or equivalents | Do not treat the current Mech record as unquestionable gold. Benchmark changes need adjudication and semantic equivalence. |
| Selective escalation | Of 860 arbiter verdicts, 50 (6%) were unclear, affecting 44/400 studies; 42/50 were resolved in a second pass and eight remained for review | Escalate only uncertain or high-severity items and explicitly measure human-review load. |
| Specialist decomposition | Specialist tag subagents outperformed a monolithic tag proposer | Use domain/field specialists for demonstrated omission-prone surfaces, not indiscriminate agent fan-out. |
| Weak self-revision return | First tag pass applied 248/260 tags; round two added 12 (7 correct, 3 false positives, 2 ambiguous); round three added none, despite 233/400 studies invoking extra rounds | Default to one proposal pass plus deterministic checks; require ablation evidence before adding recursive review. |
| Error triage | Exploratory development-set, dataset-grouped five-fold cross-validation: out-of-fold commission-error AUC 0.86 (95% CI 0.74–0.90); held-out 100 had too few factual errors for evaluation; LLM self-confidence AUC 0.38 | Build risk models from structural and resolver telemetry, and prohibit self-reported confidence as a promotion signal. |
| Omission dominance | About 70% of severity-weighted differences were omissions, particularly constant paper-inferred properties | Commission triage cannot solve completeness. Add explicit coverage questions and specialist omission passes. |
| Source value | Having the publication improved performance, particularly tags; supplementary material was expected to help | A research target should bind the record, authoritative database pages, primary publication, and supplements when available. |
| Model choice | Model substitutions had modest and task-dependent effects; an open model was strong on factors but weaker on tags | Optimize structure, inputs, prompts, and deterministic stages before provider/model escalation. |

These results come from mammalian transcriptomics and a site-specific curation
model. They motivate experiments in the Mechs; they do not prove the same
effect sizes will transfer to microbial knowledge engineering.

## Current-state fit and gaps

### Snapshot used for this analysis

Current GitHub `main` heads were checked on 2026-09-02:

| Repository | Main revision inspected |
|---|---|
| `culturebotai-claw` | `f2522c7acf1b95f51be973cc1bacb73b37001cdb` |
| `CultureMech` | `fc7b620e9049670ecb282e79338690dee8f0c65e` |
| `MediaIngredientMech` | `1a66fc4f5efcdcecf709e59c275d6f4fe9116448` |
| `CommunityMech` | `545d63ceccdfd83fc1acae62e5670373f83aa944` |
| `TraitMech` | `c798f47c1e45578d0d9b37e124b8f447bd80c351` |
| `ProteinTraitsMech` | `e3bd907ad3dccd107f92e6e938afec473968e61b` |
| `CellStructureMech` | `ac0daca9311303ce38a025d04376eb6bb4e5c032` |
| `HabitatMech` | `938b74119009e73a76f2ca67e1a8017d1df8f1c2` |
| `AntibioticMech` | `4593489c59b3cc46bbd2b14fa722861b3ae3cd31` |

The claw's local checkout was three commits behind the verified remote main at
analysis time. Current-state claims therefore use `origin/main` or the GitHub
revisions above, not the local working-tree `HEAD`.

### Strong foundations already present

The current claw provides:

- provider-neutral, audit-only research results;
- immutable plan, target, profile, query, and source checksums;
- explicit provider status, substitution, billing, and live-call authorization;
- separate citations and claim-specific evidence;
- evidence polarity, relevance, verification method, exact snippets, locators,
  assessors, and assessment timestamps;
- append-only terminal snapshots and explicit supersession lineage;
- proposed changes that remain separate from write authority;
- strict LinkML and semantic validation;
- `ValidatedWriteTransaction` and fleet governance primitives;
- deterministic focus profiles and provider triage;
- a vendored native Codex/OpenScientist contract with explicit Codex web search,
  a read-only sandbox, JSON-schema output, local semantic validation, atomic
  publication, credential-shape checks, and canaries.

These cover provenance, execution safety, and promotion safety well. They
should be retained.

### Material gaps

1. **No common benchmark/evaluation model.** The research schema has runs,
   evidence, findings, and proposed changes, but no domain-agnostic benchmark
   manifest, gold/adjudicated answer, error taxonomy, semantic-match verdict,
   severity, omission accounting, or evaluator version.
2. **No shared held-out evaluation runner.** There is no fleet primitive for
   group-aware splits, leakage checks, frozen prompts/configuration, confidence
   intervals, ablations, or regression gates.
3. **The execution contract is report-shaped.** Native Codex currently returns
   `report_markdown`, source title/URL pairs, and limitations. It does not itself
   require claim-level evidence links, source snapshots, proposed structured
   annotations, or useful per-stage telemetry. The richer claw result schema
   exists, but each domain runner must bridge into it consistently.
4. **No shared commission/omission risk contract.** Current deterministic
   provider triage answers “which provider fits this research stage,” not “which
   proposed assertion or record needs human review.”
5. **No fleet ontology-prior interface.** Repositories can reuse terms ad hoc,
   but there is no target-excluding, checksum-bound prior index with resolver
   candidates, scores, margins, and branch-consistency telemetry.
6. **Provider rollout drift exists.** The claw fleet manifest still marks
   CellStructureMech deep research as disabled and says it has no provider
   integration, while current CellStructureMech main contains the canonical
   contract, a cell-structure runner, template, tests, and provider docs.
7. **ProteinTraitsMech needs a conformance audit.** The fleet manifest marks
   deep research enabled, and the repository has a provider profile and Edison
   research skill, but its inspected main tree does not expose the canonical
   `deep_research_contract.py`, a native Codex/OpenScientist runner, or the
   contract tests present in the other repositories. Capability status and
   canonical dual-provider conformance are not presently the same claim.
8. **Fleet scope is ambiguous.** The canonical manifest has six members:
   CultureMech, MediaIngredientMech, CommunityMech, TraitMech,
   ProteinTraitsMech, and CellStructureMech. HabitatMech and AntibioticMech have
   relevant research infrastructure but are adjacent repositories, not current
   fleet members. Their governance status must be decided rather than assumed.
9. **CellStructureMech's small corpus limits evaluation.** A four-record seed is
   enough to exercise plumbing but not to estimate quality or regression risk.

## Recommended target architecture

Keep provider execution, scientific evidence, curation proposals, evaluation,
and promotion as five explicit layers:

```text
checksum-bound target + sources
          |
          v
provider execution contract (Codex / OpenScientist / dry-run)
          |
          v
normalized findings + evidence + proposed domain assertions
          |
          v
deterministic validation + ontology resolution + coverage checks
          |
          v
benchmark scoring + commission/omission risk + selective review
          |
          v
explicitly authorized ValidatedWriteTransaction
```

Do not overload provider selection with curation-risk selection. They answer
different questions and need different inputs, outputs, and calibration.

### New claw primitives

Add a companion evaluation contract, preferably under
`src/kg_microbe_research/schema/evaluation.yaml`, without weakening or making
historical `research.yaml` results invalid. It should define:

- `BenchmarkManifest`: benchmark ID/version, domain, inclusion criteria,
  development/context/held-out partitions, record/source checksums, split key,
  creation/adjudication lineage, and frozen status;
- `BenchmarkCase`: sanitized input skeleton, expected required-field coverage,
  gold or adjudicated assertions, source bundle, and leakage exclusions;
- `CandidateAssertion`: normalized field path, value, ontology candidate and
  resolved ID/label, evidence IDs, proposer/stage, and deterministic telemetry;
- `MatchAssessment`: exact, normalized-equivalent, acceptable-equivalent,
  broader, narrower, related-but-insufficient, conflict, or no-match, with the
  mechanical rule or named adjudicator that made the decision;
- `CurationError`: commission or omission, factual/grounding/guideline/
  structure/provenance subtype, severity, affected downstream use, and status;
- `EvaluationRun`: code/config/prompt/provider/model/input checksums, per-field
  and aggregate metrics, cost, latency, cache statistics, and ablation label;
- `RiskAssessment`: item- or record-level risk, model/rule version, features,
  calibration cohort, threshold, recommended action, and immutable outcome;
- `ReviewDecision`: keep/reject/modify/defer, rationale, reviewer, timestamp,
  evidence viewed, and adjudication lineage.

Add commands equivalent to:

```text
openclaw-cli research benchmark validate
openclaw-cli research benchmark evaluate
openclaw-cli research risk fit
openclaw-cli research risk assess
openclaw-cli research review-queue build
```

Names can change to fit the CLI, but every command should have deterministic
dry-run behavior and machine-readable output.

### Provider contract v2

Retain the current safe Codex invocation and OpenScientist credential/canary
behavior. Add a versioned structured-output profile that can require:

- atomic claims rather than report-only prose;
- source IDs/URLs and a locator for each claim;
- an exact supporting snippet where licensing and source access permit it;
- explicit contrary/insufficient evidence;
- structured limitations and unresolved questions;
- proposed domain assertions separated from narrative findings;
- stage timestamps, actual model, source counts, retry count, and reported cost;
- a deterministic bridge into `ResearchCitation`, `ResearchEvidence`,
  `ResearchFinding`, and `ProposedChange`.

URLs from provider output remain leads until independently resolved and
snapshotted. Provider success never grants write authority.

### Evaluation policy

Report at least:

- exact match;
- normalized or adjudicated acceptable match;
- ontology-aware broader/narrower/related scores;
- precision, recall, and F1 by field and assertion class;
- commission count and severity-weighted rate;
- omission count, required-field coverage, and severity-weighted rate;
- unsupported-source and invalid-ontology rates;
- severe-error recall at the chosen review threshold;
- precision at the available human-review capacity;
- review fraction, reviewer minutes, cost, latency, and cache hit rate;
- bootstrap confidence intervals and non-regression against the promoted
  baseline.

Do not promote on a single aggregate F1 or ROC AUC. For rare serious errors,
include precision-recall curves, calibration/Brier score, and the observed
false-negative count.

## Phased implementation plan

### Phase 0 — align the actual fleet and contracts (1–2 days)

**Claw**

1. Re-audit all six canonical Mechs against current `main`, using capability
   checks that distinguish “some research workflow exists” from “canonical
   Codex and OpenScientist contract is installed and tested.”
2. Update CellStructureMech's stale `deep_research` and credential capability
   declarations only after its current runner/canaries pass from a clean
   worktree.
3. Resolve ProteinTraitsMech's enabled declaration versus missing canonical
   dual-provider surface: install the canonical contract/runner/tests or narrow
   the declared capability with a factual reason.
4. Decide whether HabitatMech and AntibioticMech join the canonical fleet or
   remain governed adjacent consumers. Record the decision either way.
5. Freeze names and semantics for the benchmark partitions, error taxonomy,
   match verdicts, severity scale, and review outcomes.

**Acceptance gate**

- Fleet audit is green from clean worktrees.
- Every enabled dual-provider capability has the same pinned contract hash,
  deterministic tests, credential documentation, and offline canaries.
- No live provider call is needed for the gate.

### Phase 1 — build frozen, leak-resistant benchmark slices (about 1 week)

**Claw**

1. Implement `BenchmarkManifest` and `BenchmarkCase` validation.
2. Add deterministic partitioning by a leakage-resistant group key: source
   family, ontology branch, publication, imported database, or another
   domain-appropriate cluster—not random rows from the same source family.
3. Snapshot exact record skeletons, source inputs, prompt/rule files, provider
   profiles, schemas, and resolver indexes.
4. Add checks that held-out cases and their expected answers are absent from
   prompts, examples, generated fixtures, and target-specific priors.

**Each Mech**

1. Curate a small development slice and a separate held-out slice spanning
   common, ambiguous, incomplete-source, and structurally difficult cases.
2. Strip the answer-bearing fields to create a realistic pre-curation skeleton.
3. Have two reviewers independently assess the initial benchmark, then
   adjudicate disagreements and record acceptable alternate answers.
4. Freeze benchmark v1 before tuning prompts or runners against its held-out
   partition.

**Acceptance gate**

- All cases and sources have checksums and stable IDs.
- Context, development, and held-out partitions are disjoint by the selected
  group key.
- Leakage tests fail intentionally when a held-out answer is injected.
- Reviewer agreement and adjudication history are reported, not hidden.

### Phase 2 — improve proposals with deterministic and specialist stages (1–2 weeks)

**Claw**

1. Add a target-excluding corpus-prior index contract, with index provenance,
   term frequency, candidate score, resolver margin, ontology branch, and
   validation outcome.
2. Add the provider-contract-v2 structured claim profile and adapter into the
   existing audit result.
3. Standardize per-stage telemetry without accepting arbitrary unvalidated
   metadata.
4. Add deterministic source-bundle discovery for publication, supplement,
   source-native database record, and target record.

**Each Mech**

1. Start with deterministic parsers, normalization, identifier resolution,
   branch/cardinality checks, and prior retrieval.
2. Run one primary proposal pass.
3. Invoke specialist passes only for domain fields shown by the development
   benchmark to be omission-prone.
4. Mechanically validate every provider-emitted ID and label; preserve all
   rejected candidates and reasons as telemetry.

**Acceptance gate**

- Every proposed assertion points to claim-specific evidence.
- Every ontology assertion resolves to the expected ontology and records its
  resolver candidates/margin.
- No target contributes to its own prior during evaluation.
- An ablation quantifies the contribution of deterministic-only, prior-enabled,
  publication-enabled, and specialist stages.

### Phase 3 — semantic evaluation and trustworthy gold maintenance (about 1 week)

**Claw**

1. Implement one-to-one assertion alignment before LLM-assisted comparison.
2. Implement deterministic exact, normalization, synonym, and ontology-
   hierarchy matches.
3. Reserve an evidence-bound adjudicator for unresolved cases, followed by
   named human review when still unclear.
4. Keep benchmark corrections as new versions; never silently rewrite gold.

**Acceptance gate**

- Metrics are reproducible from frozen artifacts.
- Exact and acceptable-equivalent metrics are both reported.
- A proposed correction to gold requires evidence and dual review.
- Score changes caused by evaluator changes are distinguishable from proposer
  changes.

### Phase 4 — commission risk and omission coverage (1–2 weeks)

Build two systems, not one:

1. **Item-level commission risk** using ontology category/branch consistency,
   resolver success and margin, source quality, evidence polarity, cardinality,
   cross-field invariants, provider/model disagreement, deterministic-validator
   outcomes, and escalation history.
2. **Record-level omission coverage** using required-field checklists, source-
   available versus extracted entities, negative/unknown declarations,
   specialist coverage questions, and cross-record consistency.

Exclude free-form LLM self-confidence from promotion decisions. It may be
logged for research only and must prove incremental value in held-out data
before becoming a feature.

Use group-split cross-validation and retain a final untouched set. Choose the
review threshold against an explicit capacity and maximum tolerated severe
false-negative rate.

**Acceptance gate**

- Risk calibration is measured out of sample.
- Severe commission errors achieve the agreed review recall.
- Omission metrics improve without an unacceptable commission increase.
- Review queues include the structural reason for selection, not just a score.

### Phase 5 — selective review and guarded rollout (about 1 week)

1. Produce a static review report first: existing value, proposal, exact
   evidence/locator, ontology candidates, deterministic warnings, risk reason,
   and keep/reject/modify/defer outcome.
2. Run provider canaries and the entire benchmark in dry-run/offline mode.
3. With explicit billing authorization, run a small live canary batch for both
   native Codex and OpenScientist.
4. Compare live artifacts to schema and quality gates; do not use provider
   completion as a quality signal.
5. Promote only accepted patches through `ValidatedWriteTransaction`, with a
   final target-hash recheck and normal Mech validation.
6. Start with a reversible, review-all canary batch; move to selective review
   only after observed calibration matches the held-out estimate.

**Acceptance gate**

- Zero unreviewed writes before the canary gate is passed.
- Every accepted change is reconstructable from immutable source, result,
  assessment, patch, and validator artifacts.
- Reviewer workload and severe false negatives remain within the declared
  budget.

### Phase 6 — continuous improvement (ongoing)

- Add novel failures and adjudicated gold corrections to a new benchmark
  version, keeping the final test slice untouched until a scheduled release.
- Monitor provider/model/prompt/resolver drift independently.
- Run ablations before adding recursive self-review, extra agents, or stronger
  models.
- Once quality is stable, optimize batching, prompt caching, source caching,
  and model tier by stage.
- Track quality, review load, cost, and latency together in release reports.

## Per-repository application

### culturebotai-claw

Priority deliverables:

1. Correct the fleet/capability facts identified in Phase 0.
2. Add the companion evaluation schema, validators, CLI, fixtures, and docs.
3. Add a normalized provider-output adapter rather than expanding prose-only
   reports differently in every Mech.
4. Add benchmark packaging, leakage tests, semantic alignment, metrics,
   ablation comparison, risk calibration, and review-queue generation.
5. Extend the site/report contract with benchmark version, error breakdown,
   calibration, review fraction, cost, latency, and provider-contract pin.
6. Keep all writes behind existing transaction and authorization boundaries.

### CultureMech

- Benchmark medium identity, organism/strain compatibility, formulation,
  ingredient quantity/unit, stock solution, preparation condition, and growth
  evidence separately.
- Treat missing ingredients, volumes, pH, temperature, atmosphere, and
  preparation steps as explicit omission classes.
- Use deterministic arithmetic/unit normalization and ingredient identity
  resolution before research.
- Add specialist coverage passes for formulation completeness and organism-
  medium growth evidence only when the benchmark shows value.
- Reuse the existing research priority and researched-manifest surfaces as
  candidates for benchmark sampling, not as unquestioned gold.

### MediaIngredientMech

- Benchmark ingredient identity, synonym/hydration/stereochemistry handling,
  ontology mapping, chemical structure, role, and provenance separately.
- Record resolver candidates and margins for ChEBI and other source-native IDs;
  validate label/ID pairs mechanically.
- Add structural consistency checks between ingredient type, ontology branch,
  formula/charge/structure, and asserted role.
- Separate “same chemical,” “form/salt/hydrate,” “broader ingredient class,”
  and “functional substitute” in semantic matching.
- Evaluate omission of roles and mappings separately from incorrect roles and
  mappings.

### CommunityMech

- Benchmark composition, member roles, interactions, spatial organization,
  environmental context, causal claims, and source support separately.
- Use specialists for composition completeness, interaction/mechanism evidence,
  and environmental context rather than a single monolithic community report.
- Add graph invariants: referenced members exist, interaction endpoints and
  directions are valid, and causal edges have claim-specific evidence.
- Score partial/alternative community descriptions as explicit acceptable or
  incomplete matches rather than forcing string identity.

### TraitMech

- Sample the large existing research corpus into source-family- and ontology-
  branch-grouped benchmark slices.
- Benchmark definitions, taxonomic scope, ontology mapping, relation type,
  causal evidence, and negative evidence separately.
- Add consistency rules between trait category, ontology branch, mapping
  relation, subject taxon, and evidence type.
- Use semantic alignment to distinguish synonyms and broader/narrower traits
  from genuine mapping errors.
- Prioritize omission discovery in sparsely evidenced traits and treat existing
  research markdown as leads until normalized into claim-level evidence.

### ProteinTraitsMech

- First bring the canonical Codex/OpenScientist execution contract into factual
  alignment with its fleet capability declaration.
- Benchmark family/domain identity, hierarchy, motifs/residues, cofactors,
  reaction chemistry, structure/function claims, and causal edges separately.
- Deterministically cross-check UniProt, InterPro/Pfam, PDB/PDBe, M-CSA, Rhea,
  EC, GO, and ChEBI accessions where applicable.
- Treat residue-numbering scheme, isoform, construct, taxonomic scope, and
  family-wide generalization as high-risk structural features.
- Split held-out cases by protein family/source database to prevent near-
  duplicate leakage.

### CellStructureMech

- Correct the claw manifest's stale disabled deep-research declaration after a
  clean-worktree conformance test.
- Expand beyond the four seed records before drawing performance conclusions;
  choose records across envelope, appendage, organelle/inclusion, surface layer,
  and specialized morphological categories.
- Build at least a development slice and a separately frozen held-out slice;
  do not use all new records for prompt tuning.
- Benchmark structure identity/category, composition, localization,
  morphology, function, mechanism, taxonomic scope, and imaging/experimental
  evidence separately.
- Use specialist coverage passes for components, morphology, and function only
  after deterministic source/ontology resolution.
- Bind imaging evidence and authoritative resources to checksum-addressed
  source snapshots with figure/table locators where possible.

### HabitatMech

- Decide and record whether it becomes a canonical fleet member before relying
  on fleet-wide orchestration.
- Benchmark ENVO identity/hierarchy, habitat components, physicochemical
  conditions, process, scale, host association, and source-dataset context.
- Add branch-consistency and broader/narrower scoring for ENVO and FoodOn, with
  explicit composite-habitat handling.
- Use existing research outputs as a candidate corpus, then normalize selected
  claims and independently adjudicate gold.
- Split by source dataset and habitat family so related records cannot span
  development and held-out partitions.

### AntibioticMech

- Decide and record whether it becomes a canonical fleet member before relying
  on fleet-wide orchestration.
- Benchmark compound identity/structure, family, molecular target, mechanism,
  spectrum, resistance determinant/mechanism, producer, and clinical status
  separately.
- Use specialist passes for compound identity, target/mechanism, and resistance
  rather than a monolithic report.
- Deterministically validate chemical identity and source-native accessions;
  distinguish salts/stereoisomers/derivatives from equivalent compounds.
- Reuse the existing chemical-embedding and data-source evaluation work as
  ablation inputs, not as evidence that a method is ready for promotion.

## Priority order

### P0 — correctness of the platform

1. Reconcile CellStructureMech and ProteinTraitsMech capability declarations
   with current repository facts.
2. Decide HabitatMech and AntibioticMech governance scope.
3. Land the benchmark/evaluation contract, error taxonomy, and leakage gates.

### P1 — quality improvements with likely transfer value

1. Add ontology/corpus priors with target exclusion and resolver telemetry.
2. Add semantic alignment and field-specific benchmark metrics.
3. Build structural commission-risk rules and calibrated review queues.
4. Add required-field coverage and specialist omission passes.
5. Expand CellStructureMech while preserving a held-out slice.

### P2 — operating efficiency

1. Add static review reports or UI integration.
2. Measure provider/model ablations.
3. Optimize batching, caching, and model tier only after quality stabilizes.

Deprioritize recursive self-revision, open-ended multi-agent debate, and blanket
model upgrades until a frozen benchmark shows a material quality or review-load
benefit.

## Definition of done for the first production-quality milestone

The first milestone is complete only when:

- all in-scope repositories pass the pinned dual-provider contract and offline
  canaries from clean worktrees;
- benchmark inputs, sources, expected assertions, schemas, prompts, profiles,
  and evaluator code are checksum-bound and versioned;
- development and held-out sets are leakage-tested and group-separated;
- exact, semantic, hierarchical, commission, omission, evidence, and ontology-
  validity metrics are reported with uncertainty;
- commission risk is calibrated out of sample and does not rely on LLM
  self-confidence;
- omission coverage is measured per required field;
- every proposed assertion has source-specific evidence and every ontology ID
  is mechanically resolved;
- review capacity, severe-error recall, cost, and latency have explicit gates;
- live calls require provider and billing authorization;
- no proposed change can bypass domain validation or
  `ValidatedWriteTransaction`;
- a canary run shows that the observed review load and severe-error rate match
  the held-out estimate closely enough for the agreed rollout policy.

## Immediate next work item

Implement Phase 0 in isolated worktrees, then open one claw change that adds
the evaluation vocabulary and capability-conformance checks before modifying
domain prompts. That sequence supplies a measurement substrate first, prevents
further manifest drift, and makes every later Mech improvement testable.
