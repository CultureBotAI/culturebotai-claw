# Proposal: Extend kg-microbe ingredient coverage beyond CHEBI

**Status:** Draft
**Audience:** kg-microbe maintainers
**Author:** culturebotai-claw audit pipeline
**Date:** 2026-04-18

## The gap

kg-microbe's `mappings/unified_chemical_mappings.tsv.gz` is CHEBI-only by
design. That is the right scope for actual chemicals, but MIM publishes
19 mapped ingredient records that are legitimately not chemicals:

| Bucket | Ontology | Count | Examples |
|---|---|---:|---|
| Complex biological material | FOODON | 13 | Yeast extract, Beef extract, Bacto-tryptone, Casein peptone, Malt extract |
| Environmental sample | ENVO | 6 | Seawater, Vermont Soil, Green House Soil, Pasteurized Seawater |

These entries show up as `MIM_ONLY` rows in the MIM↔kg-microbe audit
(`workspace/reports/kgm_mim_audit.md`) — not because MIM is wrong, but
because kg-microbe's current data format can't represent them.

## Options

### (a) Extend `unified_chemical_mappings.tsv.gz` to allow non-CHEBI IDs

Add FOODON and ENVO to the allowed `id` prefixes. Low code change but
conflates three distinct reference ontologies in a file named
"chemical". Downstream consumers that filter `id LIKE 'CHEBI:%'` keep
working, but consumers that expect the file to be CHEBI-only for
semantic reasons break.

### (b) Add a separate `complex_ingredients.tsv.gz` artifact  *(recommended)*

Mirror kg-microbe's existing practice of one-file-per-ontology-type:
`schemas/chemicals.sssom.tsv`, `schemas/pathways.sssom.tsv`. A new
`mappings/complex_ingredients.tsv.gz` with the same column schema as
`unified_chemical_mappings.tsv.gz` — just with `FOODON:` / `ENVO:` IDs —
keeps the CHEBI boundary intact and gives consumers a clear opt-in for
non-chemical ingredients.

MIM would pre-populate it from its published SSSOM on every
`publish-sssom` run, so the file stays in sync automatically.

### (c) Accept MIM-only

Treat these 19 rows as metadata that kg-microbe doesn't need. Simplest,
but leaves knowledge graph consumers (especially anyone joining
CultureMech media recipes) without a way to resolve these ingredients
into kg-microbe nodes.

## Recommendation

**Option (b).** Lowest code change for kg-microbe (just a new file to
download and merge), preserves the CHEBI-only semantic for
`unified_chemical_mappings.tsv.gz`, and matches kg-microbe's
file-per-ontology precedent.

## The 19 MIM rows this would cover

| MIM id | Preferred term | Ontology | Target ID |
|---|---|---|---|
| MIM:Bacto-tryptone | Bacto-tryptone | FOODON | FOODON:03315719 |
| MIM:Bacto_Peptone | Bacto peptone | FOODON | FOODON:03315718 |
| MIM:Beef_Extract | Beef extract | FOODON | FOODON:03302088 |
| MIM:Casein_Peptone | Casein peptone | FOODON | FOODON:03315719 |
| MIM:Casitone | Casitone | FOODON | FOODON:03315719 |
| MIM:Cr1_Soil | CR1 Soil | ENVO | ENVO:00001998 |
| MIM:Green_House_Soil | Green House Soil | ENVO | ENVO:00001998 |
| MIM:Malt_Extract | Malt extract | FOODON | FOODON:03301056 |
| MIM:Pasteurized_Seawater | Pasteurized Seawater | ENVO | ENVO:00002149 |
| MIM:Polypeptone | Polypeptone | FOODON | FOODON:03315306 |
| MIM:Proteose_Peptone | Proteose Peptone | FOODON | FOODON:03315718 |
| MIM:Seawater | Seawater | ENVO | ENVO:00002149 |
| MIM:Soy_Peptone | Soy peptone | FOODON | FOODON:03315720 |
| MIM:Supplemented_Seawater | Supplemented Seawater | ENVO | ENVO:00002149 |
| MIM:Trypticase | Trypticase | FOODON | FOODON:03315719 |
| MIM:Trypticase_Peptone | Trypticase peptone | FOODON | FOODON:03315306 |
| MIM:Tryptone | Tryptone | FOODON | FOODON:03315719 |
| MIM:Vermont_Soil | Vermont Soil | ENVO | ENVO:00001998 |
| MIM:Yeast_Extract | Yeast extract | FOODON | FOODON:03315426 |

## Proposed next step

If kg-microbe accepts option (b), MIM can issue a PR that adds
`complex_ingredients.tsv.gz` populated from
`MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv`. The
`publish-sssom` skill would gain a secondary publish target so the file
stays in sync every release.
