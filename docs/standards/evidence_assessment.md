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
