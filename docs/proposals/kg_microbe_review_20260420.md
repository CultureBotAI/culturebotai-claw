# kg-microbe Review (SSSOM-first, chemical-mappings-mim-priority)
_Generated 2026-04-21 16:08:38 by `scripts/generate_kg_microbe_review.py`._

Row-level diff of MIM's published SSSOM vs kg-microbe's consolidated SSSOM (`unified_ingredient_mappings.sssom.tsv.gz`) on the `chemical-mappings-mim-priority` branch.

## Scope
- MIM published SSSOM: **613** rows (`KG-Microbe/MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv`)
- kg-microbe consolidated SSSOM, `MIM:*` subjects only: **1104** rows
- Legacy `MediaIngredientMech:*` subjects in kg-microbe SSSOM: **1019**

## Diff summary
| Class | Rows | Suggested kg-microbe action |
|---|---:|---|
| `IN_SYNC` | 462 | None — consolidator will idempotently reproduce |
| `CHEBI_DIVERGED` | 2 | Rerun consolidator after refreshing MIM SSSOM input |
| `LABEL_DRIFTED` | 149 | Verify priority-11 `mediaingredientmech_reviewed` wins the name tiebreaker |
| `MISSING_IN_KGM` | 0 | Rerun consolidator — MIM SSSOM not picked up |
| `MIM_ONLY_NON_CHEBI` | 0 | Accept `complex_ingredients.tsv.gz` companion artifact |
| `STALE_IN_KGM` | 491 | Rerun consolidator — MIM dropped these |
| `MIM_LEGACY_IN_KGM` | 1019 | Should be zero after this branch merges |

## kg-microbe source tag distribution (on `MIM:*` rows)
Sanity check that `mediaingredientmech_reviewed` dominates, as priority-11 intends.

| Source tag | Rows |
|---|---:|
| `mediaingredientmech_reviewed` | 1104 |
| `culturebotai_reviewed` | 1045 |
| `chebi_xrefs` | 868 |
| `mediadive_compounds` | 812 |
| `primary_mappings[kegg_compound]` | 472 |
| `primary_mappings[chemicals_sssom]` | 104 |
| `primary_mappings[bacdive_api]` | 80 |
| `bacdive_metabolites` | 43 |
| `bacdive_antibiotics[manual_pre-2026]` | 42 |
| `primary_mappings[bacdive_metabolite]` | 41 |
| `metatraits_special_chemicals[corrected_2026-04-08]` | 15 |
| `metatraits_special_chemicals` | 14 |
| `metatraits_chemical_synonyms[manual_2026-04-07]` | 12 |
| `metatraits_chemical_mappings` | 5 |
| `primary_mappings[madin_etal_manual]` | 4 |

## CHEBI_DIVERGED (showing 2 of 2)

| MIM subject | MIM object | kg-microbe object | Note |
|---|---|---|---|
| `MIM:Fructose` | `CHEBI:28757` — fructose | `CHEBI:28645` — Fructose | MIM object_id=CHEBI:28757, kg-microbe object_id=CHEBI:28645 |
| `MIM:Vitamin_B12` | `CHEBI:176843` — vitamin B12 | `CHEBI:17439` — Cyanocobalamin | MIM object_id=CHEBI:176843, kg-microbe object_id=CHEBI:17439 |

## LABEL_DRIFTED (showing 25 of 149)

| MIM subject | MIM object | kg-microbe object | Note |
|---|---|---|---|
| `MIM:3_N_morpholinopropanesulfonic_acid` | `CHEBI:44115` — 3-(N-morpholino)propanesulfonic acid | `CHEBI:44115` — MOPS buffer | expected '3-(N-morpholino)propanesulfonic acid' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'MOPS buffer' |
| `MIM:Alcl3` | `CHEBI:30115` — aluminium trichloride hexahydrate | `CHEBI:30115` — AlCl3 x 6 H2O | expected 'aluminium trichloride hexahydrate' (narrow/broad rule: CHEBI canonical label stays); kg-microbe has 'AlCl3 x 6 H2O' |
| `MIM:Alk_So42` | `CHEBI:86465` — potassium aluminium sulfate dodecahydrate | `CHEBI:86465` — AlK(SO4)2 x 12 H2O | expected 'potassium aluminium sulfate dodecahydrate' (narrow/broad rule: CHEBI canonical label stays); kg-microbe has 'AlK(SO4)2 x 12 H2O' |
| `MIM:Beta_Lactose` | `CHEBI:36218` — beta-lactose | `CHEBI:36218` — lactose | expected 'Beta-Lactose' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'lactose' |
| `MIM:Betaine_X_H2o` | `CHEBI:17750` — glycine betaine | `CHEBI:17750` — Betaine | expected 'Betaine x H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'Betaine' |
| `MIM:Cacl2` | `CHEBI:91243` — calcium chloride hexahydrate | `CHEBI:91243` — CaCl2 x 6 H2O | expected 'calcium chloride hexahydrate' (narrow/broad rule: CHEBI canonical label stays); kg-microbe has 'CaCl2 x 6 H2O' |
| `MIM:Cacl22h2o_2` | `CHEBI:86158` — calcium chloride dihydrate | `CHEBI:86158` — CaCl2 x 2 H2O | expected 'CaCl22H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CaCl2 x 2 H2O' |
| `MIM:Cacl2_X_7_H2o` | `CHEBI:3312` — calcium dichloride | `CHEBI:3312` — CaCl2 | expected 'CaCl2 x 7 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CaCl2' |
| `MIM:Cadmium_Nitrate` | `CHEBI:77732` — cadmium nitrate | `CHEBI:77732` — Ca(NO3)2 | expected 'cadmium nitrate' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'Ca(NO3)2' |
| `MIM:Calcium_Chloride` | `CHEBI:86158` — calcium chloride dihydrate | `CHEBI:86158` — CaCl2 x 2 H2O | expected 'Calcium Chloride' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CaCl2 x 2 H2O' |
| `MIM:Casamino_Acids` | `CHEBI:78020` — heptacosanoate | `CHEBI:78020` — Casamino acid | expected 'Casamino acids' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'Casamino acid' |
| `MIM:Casein_Peptone` | `FOODON:03315719` — mammalian milk protein (hydrolyzed) | `FOODON:03315719` — Bacto-tryptone | expected 'Casein peptone' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'Bacto-tryptone' |
| `MIM:Casitone` | `FOODON:03315719` — mammalian milk protein (hydrolyzed) | `FOODON:03315719` — Bacto-tryptone | expected 'Casitone' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'Bacto-tryptone' |
| `MIM:Caso4` | `CHEBI:32583` — calcium sulfate dihydrate | `CHEBI:32583` — CaSO4 x 2 H2O | expected 'calcium sulfate dihydrate' (narrow/broad rule: CHEBI canonical label stays); kg-microbe has 'CaSO4 x 2 H2O' |
| `MIM:Caso4_X_7_H2o` | `CHEBI:31346` — calcium sulfate | `CHEBI:31346` — CaSO4 | expected 'CaSO4 x 7 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CaSO4' |
| `MIM:Cecl3_X_7_H2o` | `CHEBI:35458` — cerium trichloride | `CHEBI:35458` — CeCl3 | expected 'CeCl3 x 7 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CeCl3' |
| `MIM:Co_No32` | `CHEBI:86214` — cobalt dinitrate hexahydrate | `CHEBI:86214` — Co(NO3)2 x 6 H2O | expected 'cobalt dinitrate hexahydrate' (narrow/broad rule: CHEBI canonical label stays); kg-microbe has 'Co(NO3)2 x 6 H2O' |
| `MIM:Cocl2_X_2_H2o` | `CHEBI:35696` — cobalt dichloride | `CHEBI:35696` — CoCl2 | expected 'CoCl2 x 2 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CoCl2' |
| `MIM:Cocl2_X_4_H2o` | `CHEBI:35696` — cobalt dichloride | `CHEBI:35696` — CoCl2 | expected 'CoCl2 x 4 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CoCl2' |
| `MIM:Cocl2_X_6_H2o` | `CHEBI:35696` — cobalt dichloride | `CHEBI:35696` — CoCl2 | expected 'CoCl2 x 6 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CoCl2' |
| `MIM:Coenzyme_A` | `CHEBI:15346` — coenzyme A | `CHEBI:15346` — Coenzym A | expected 'Coenzyme A' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'Coenzym A' |
| `MIM:Coso4_X_7_H2o` | `CHEBI:53470` — cobalt(2+) sulfate | `CHEBI:53470` — CoSO4 | expected 'CoSO4 x 7 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CoSO4' |
| `MIM:Cucl2` | `CHEBI:86318` — copper(II) chloride dihydrate | `CHEBI:86318` — CuCl2 x 2 H2O | expected 'copper(II) chloride dihydrate' (narrow/broad rule: CHEBI canonical label stays); kg-microbe has 'CuCl2 x 2 H2O' |
| `MIM:Cucl2_X_6_H2o` | `CHEBI:49553` — copper(II) chloride | `CHEBI:49553` — CuCl2 | expected 'CuCl2 x 6 H2O' (priority-11 rule: MIM subject_label → kg-microbe object_label); kg-microbe has 'CuCl2' |
| `MIM:Cuso4` | `CHEBI:91246` — copper(II) sulfate hexahydrate | `CHEBI:91246` — CuSO4 x 6 H2O | expected 'copper(II) sulfate hexahydrate' (narrow/broad rule: CHEBI canonical label stays); kg-microbe has 'CuSO4 x 6 H2O' |

## STALE_IN_KGM (showing 20 of 491)

| kg-microbe MIM subject | kg-microbe object |
|---|---|
| `MIM:Sodium_Ascorbate` | `CHEBI:113451` — Na-ascorbate |
| `MIM:Sodium_Ascorbate_2` | `CHEBI:113451` — Na-ascorbate |
| `MIM:Sodium_Ascorbate_3` | `CHEBI:113451` — Na-ascorbate |
| `MIM:Sodium_Benzoate` | `CHEBI:113455` — Na-benzoate |
| `MIM:Sodium_Benzoate_2` | `CHEBI:113455` — Na-benzoate |
| `MIM:Sodium_Caproate` | `CHEBI:114126` — Na-caproate |
| `MIM:Disodium_Fumarate` | `CHEBI:115156` — Disodium fumarate |
| `MIM:Na-fumarate` | `CHEBI:115156` — Disodium fumarate |
| `MIM:Sodium_Fumarate` | `CHEBI:115156` — Disodium fumarate |
| `MIM:Sodium_Fumarate_2` | `CHEBI:115156` — Disodium fumarate |
| `MIM:D-galactose_2` | `CHEBI:12936` — D-Galactose |
| `MIM:Sodium_selenite_pentahydrate` | `CHEBI:131361` — Na2SeO3 x 5 H2O |
| `MIM:Mnso45h2o` | `CHEBI:131524` — MnSO4 x 5 H2O |
| `MIM:Dipotassium_Hydrogen_Phosphate` | `CHEBI:131527` — Dipotassium hydrogen phosphate |
| `MIM:Dipotassium_Phosphate` | `CHEBI:131527` — Dipotassium hydrogen phosphate |
| `MIM:Dipotassium_Phosphate_2` | `CHEBI:131527` — Dipotassium hydrogen phosphate |
| `MIM:Pyridoxamine-hcl` | `CHEBI:131531` — Pyridoxamine hydrochloride |
| `MIM:Pyridoxamine-hcl_2` | `CHEBI:131531` — Pyridoxamine hydrochloride |
| `MIM:Pyridoxamine_Dihydrochloride_2` | `CHEBI:131532` — Pyridoxamine Dihydrochloride |
| `MIM:Na2-~DF-glycerolphosphate` | `CHEBI:132089` — Na2-ß-glycerolphosphate |

## MIM_LEGACY_IN_KGM (showing 10 of 1019)

Any `MediaIngredientMech:<id>` subject in kg-microbe's SSSOM should have been rewritten to `MIM:<slug>` on this branch. Remaining rows indicate the consolidator needs another pass.

| kg-microbe subject | kg-microbe object |
|---|---|
| `MediaIngredientMech:000722` | `CHEBI:1` — CHEBI:1 |
| `MediaIngredientMech:000688` | `CHEBI:103822` — Phenyl acetic acid |
| `MediaIngredientMech:000399` | `CHEBI:113246` — Pyruvic acid sodium salt |
| `MediaIngredientMech:000914` | `CHEBI:113373` — Na-3-hydroxybutyrate |
| `MediaIngredientMech:000454` | `CHEBI:113451` — Na-ascorbate |
| `MediaIngredientMech:000514` | `CHEBI:113451` — Na-ascorbate |
| `MediaIngredientMech:000887` | `CHEBI:113451` — Na-ascorbate |
| `MediaIngredientMech:001044` | `CHEBI:113451` — Na-ascorbate |
| `MediaIngredientMech:000379` | `CHEBI:113455` — Na-benzoate |
| `MediaIngredientMech:000520` | `CHEBI:113455` — Na-benzoate |

## Recommended contribution scope
Based on this diff, candidate commits for the `chemical-mappings-mim-priority` branch:

1. **Rerun consolidator** to absorb the 0 `MISSING_IN_KGM` + 2 `CHEBI_DIVERGED` + 491 `STALE_IN_KGM` rows and drop 1019 `MIM_LEGACY_IN_KGM` rows.
2. **Priority-11 tiebreaker audit** — 149 rows where kg-microbe's `object_label` differs from MIM's. If MIM is priority-11, its label should win; if it doesn't, the consolidator has a tiebreaker bug.
3. **Accept `complex_ingredients.tsv.gz`** — the FOODON/ENVO companion artifact covering the MIM_ONLY_NON_CHEBI rows.
4. **Surface MIM curator provenance** — MIM SSSOM's `source` column embeds `MIM:curator=<name>` tags that currently flatten to `mediaingredientmech_reviewed` in kg-microbe. A small consolidator enhancement could preserve the curator attribution.

---

_Review complete._
