# Claim evidence assessments across the Mech fleet

## Investigation and decision

[EcoMech's TraitMech integration notes](https://github.com/diatomsRcool/ecomech/blob/5d3f55467f3caaa6e88eb7f33037e4a8103873a7/docs/traitmech_integration.md)
identify two useful dimensions of primary claim evidence:

- `supports`: SUPPORT, REFUTE, PARTIAL, NO_EVIDENCE or WRONG_STATEMENT.
- `evidence_source`: the study or data-source type behind that evidence.

The [actual upstream schema](https://github.com/diatomsRcool/ecomech/blob/5d3f55467f3caaa6e88eb7f33037e4a8103873a7/src/ecomech/schema/ecomech.yaml)
requires both. The fleet adopts the meanings and vocabularies while preserving
its existing requiredness. A previously valid record remains valid; newly
introduced fields are optional and have no default. Existing citations are not
backfilled or automatically classified.

`supports` assesses the citation **against its attached claim**. It is independent
of confidence, evidence quality and curation method. NO_EVIDENCE means the source
does not establish the claim, not that an experiment found no effect. PARTIAL
requires explaining which part or conditions are supported. A publication may
support one claim and refute another.

`evidence_source` distinguishes field studies, mesocosms, laboratory studies,
computational evidence, meta-analyses, reviews, remote sensing, long-term
monitoring, expert opinion and other known types. The fleet also retains
CommunityMech's IN_VITRO and IN_VIVO and adds DATABASE for database assertions.
A PMID or DOI does not establish a study type; LLM-assisted curation is not
COMPUTATIONAL evidence unless the cited scientific evidence is computational.

## Baseline and implementation

Checked against the published main branches on 2026-09-17:

| Mech | Primary evidence classes | Existing support assessment | Change |
| --- | --- | --- | --- |
| CultureMech | EvidenceItem | Required, all five values | Add optional source type |
| MediaIngredientMech | MappingEvidence; ComponentEvidence | Optional on MappingEvidence | Add source types to both; optional support on ComponentEvidence |
| CommunityMech | EvidenceItem | Required, all five values | Extend existing required source enum without removing its values |
| TraitMech | EvidenceItem | Absent | Add both optionally |
| ProteinTraitsMech | EvidenceItem | Absent | Add both optionally |
| AntibioticMech | EvidenceItem | Absent | Add both optionally |
| CellStructureMech | EvidenceItem | Absent | Add both optionally |
| HabitatMech | EvidenceItem | Absent | Add both optionally |
| NaturalProductMech | EvidenceItem | Absent | Add both optionally |
| TaxonMech | EvidenceItem | Absent | Add both optionally |

The machine-readable agreement is [evidence_assessment.yaml](evidence_assessment.yaml).
Its class keys cover the canonical fleet manifest. Existing support enums are
reused, including the shared SupportLevelEnum; downstream vendored schemas are
unchanged. Each repository has local usage documentation and closed-schema tests
for valid assessments, invalid values, old payloads and requiredness.

## Deliberately separate provenance

The shared `SupportingReference.evidence_source` already means **quotation
location**, such as `abstract` or `full_text`. CLAW's KG scanner emits `abstract`.
That free-text field remains unchanged; applying the new enum there would reject
existing references and conflate two meanings. Tests explicitly retain `abstract`.

ProteinTraitsMech's `GroundingEvidence.evidence_source` identifies a grounding
source. TaxonMech's strain/genome provenance identifies typed link evidence.
Those classes are outside this primary-claim assessment contract. Existing
`source`, `evidence_type`, `retrieved_on`, citation identifiers and curation
provenance remain available for their original purposes.

## Rollout boundary

This is a schema and model rollout, not scientific reassessment. No record's
support is inferred, no citation is promoted to positive evidence, and no
scientific records or graph assertions are changed. Curators should fill these
fields only after reading the source in the context of its attached claim.
Omission remains unassessed. Consumers must check the assessment before treating
a citation as positive support; the number of citations is not a support score.

## Implementation PRs and validation

The implementation is staged in the following PRs; opening a PR does not mean
it has been merged or deployed.

| Repository | PR | Local validation |
| --- | --- | --- |
| culturemech | [#481](https://github.com/CultureBotAI/CultureMech/pull/481) | 39 assessment tests; 6 generated-artifact tests; all 15,878 records pass strict validation and unique ID checks |
| mediaingredientmech | [#692](https://github.com/CultureBotAI/MediaIngredientMech/pull/692) | 138 assessment and schema tests pass |
| communitymech | [#937](https://github.com/CultureBotAI/CommunityMech/pull/937) | 39 assessment tests including generated-model serialization pass |
| traitmech | [#973](https://github.com/CultureBotAI/TraitMech/pull/973) | 41 assessment/validator/writer tests and all 630 records pass strict validation; Pydantic roundtrip passes |
| proteintraitsmech | [#714](https://github.com/CultureBotAI/proteintraitsmech/pull/714) | 51 assessment/validator tests and Pydantic roundtrip pass |
| antibioticmech | [#401](https://github.com/CultureBotAI/AntibioticMech/pull/401) | 35 assessment/writer tests pass; 1 corpus-dependent test skipped |
| cellstructuremech | [#1126](https://github.com/CultureBotAI/CellStructureMech/pull/1126) | 49 assessment/writer tests pass; 1 corpus-dependent test skipped |
| habitatmech | [#337](https://github.com/CultureBotAI/HabitatMech/pull/337) | 35 assessment/writer tests and schema history validation pass; 1 corpus-dependent test skipped |
| naturalproductmech | [#165](https://github.com/CultureBotAI/NaturalProductMech/pull/165) | 39 assessment/writer tests pass |
| taxonmech | [#73](https://github.com/CultureBotAI/TaxonMech/pull/73) | 68 tests pass; 13 baseline failures reproduced; 1 corpus-dependent test skipped |

Across the ten repositories, **311 new assessment tests pass**. They cover all
allowed values, existing requiredness, omission without defaults, invalid inputs,
closed-schema rejection of unknown fields and compatibility with shared quote
locations. CultureMech and CommunityMech also exercise the tracked generated
models for every source type. Generated artifacts use each repository's locked
LinkML toolchain. TraitMech and ProteinTraitsMech Pydantic models were generated
for smoke checks without committing ignored build outputs.

A whole-schema comparison against each checkout's original main commit verifies
that removing the intended additions yields the original schema exactly.
No vendored shared schema or scientific record changed. Ruff and whitespace
checks pass. Corpus-dependent skips reflect intentionally sparse test checkouts;
this is not a claim that every full fleet corpus gate ran locally.

TaxonMech's 13 unrelated failures reproduce against its untouched baseline
`be6b63fad5d5ff9cb9629d4332bbaf6e721e9c83`. Its strain/genome fixtures use
`1970-01-01T00:00:00Z`, which the existing `^20[0-9]{2}-` timestamp pattern rejects.
All new claim-evidence tests pass. These historical-date tests and the shared
timestamp contract are outside this change.

CultureMech's ontology-label gate checked the normalized records successfully
and initially reported one missing required generated SSSOM product. Regenerating
that product yielded 1,915 mapping rows. Re-running the same maintained validator
on the previously missing SSSOM target passed (1,820 canonical matches, 2 accepted
exceptions and 2,008 non-ontology identifiers skipped by configured policy).
The normalized record check reported 53 existing non-blocking plausibility
warnings. The generated mapping artifact remains ignored and uncommitted.
