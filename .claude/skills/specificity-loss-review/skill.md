---
name: specificity-loss-review
description: Detect MIM mappings where the ontology term is more general than the named ingredient (e.g. "Vermont Soil" → ENVO:00001998 "soil"). Surface candidates for minting `kgmicrobe.ingredient:<slug>` custom terms that subclass the parent ontology term, preserving ingredient-level specificity in MIM-side data while keeping the parent reference for downstream KG consumers via skos:narrowMatch.
category: curation
requires_database: false
requires_internet: false
version: 1.0.0
tags: [mim, ontology, specificity, custom-terms, kgmicrobe, dismech]
---

# Specificity-Loss Review Skill

## The problem

When MIM resolves "Vermont Soil" or "Pasteurized Seawater" or "Beef
Heart Infusion", the available ontology terms are usually the parent
class (`ENVO:00001998` *soil*, `ENVO:00002149` *seawater*,
`FOODON:00004410` *beef heart*). Mapping the specific ingredient to
the parent is *not wrong* — `Vermont Soil` *is* a kind of soil — but
it's a **loss of specificity**: a downstream consumer that joins on
`ENVO:00001998` can no longer distinguish "Vermont soil" (a particular
sample) from "soil" in general.

The fix:

1. **Mint** a `kgmicrobe.ingredient:<slug>` custom term as the new
   primary identifier for the MIM record.
2. **Retain** the parent ontology term as a `skos:narrowMatch`
   relationship in the published SSSOM (the kg-microbe term IS
   narrower than the parent).
3. **Append** a row to the custom-ingredients reference TSV recording
   the parent relationship explicitly. Downstream KGX consumers
   convert this into a subclass edge.

The MIM record now says, simultaneously:
- This ingredient is `kgmicrobe.ingredient:vermont_soil` (precise)
- It is a kind of `ENVO:00001998` (parent)

## Two-step workflow

### Step 1 — Detect (`scripts/detect_specificity_loss.py`)

Walks every MIM `mapped/` record where the primary identifier is a
real ontology term (CHEBI/FOODON/ENVO/etc.; not a placeholder).
Compares the ingredient `preferred_term` tokens against the
ontology label tokens (after dropping function-word stops). Flags
records where label tokens are a strict subset of name tokens.

For each flagged row, categorizes the qualifier loss:

| Category | Curator advice |
|---|---|
| `GEOGRAPHIC_OR_PROPER` | **Mint** — proper-noun adjective (Vermont, Bayan) is real specificity |
| `TREATMENT` | Review — sometimes degenerate (sterilized water = water), sometimes meaningful (filtered seawater ≠ seawater) |
| `STEREO` | Usually keep — stereo loss for media context is acceptable |
| `HYDRATE` | Usually keep — hydrate form rarely changes media-as-ingredient identity |
| `BRAND` | Usually keep — brand-stripped already |
| `FORMULATION_OR_QUALIFIER` | Review — concentration / role / form qualifiers; case-by-case |
| `DESCRIPTIVE_QUALIFIER` | Review — generic descriptors |

```bash
just detect-specificity-loss
```

Outputs:

- `workspace/reports/specificity_loss_review.tsv` — per-row data
- `workspace/reports/specificity_loss_review.md` — bucketed summary

### Step 2 — Mint (`scripts/mint_kgm_ingredient.py`)

Curator marks the TSV (add an `action` column with values `mint`,
`keep`, or blank) and runs:

```bash
just mint-kgm-ingredient --slug Vermont_Soil          # one-off
just mint-kgm-ingredient --from-tsv workspace/reports/specificity_loss_review.tsv  # batch
```

For each minted record the script:

1. Sets the YAML's `identifier` to `kgmicrobe.ingredient:<slug>`.
2. Updates `ontology_mapping`:
   - `ontology_id` and `ontology_label` retain the parent ontology term
   - `mapping_quality: NARROW_MATCH` (the MIM term is narrower)
3. Appends a `CURATOR_JUDGMENT` evidence entry citing the parent
   relationship.
4. Appends a `curation_history` entry (action: `MINT_KGM_INGREDIENT`).
5. Appends a row to
   `MediaIngredientMech/data/custom/kgmicrobe_ingredients.tsv` with:

```
kgm_id                              preferred_term  parent_ontology_id  parent_ontology_label  relation         created_by  created_at  notes
kgmicrobe.ingredient:vermont_soil   Vermont Soil    ENVO:00001998       soil                   rdfs:subClassOf  ...         ...         ...
```

This file is the **canonical registry** of MIM custom terms. It's
read by:
- Downstream KGX emitters (kg-microbe consolidator) — they convert
  the `parent_ontology_id` column into a `biolink:subclass_of` edge
  in the unified mapping graph.
- Search tools / browsers — to display the parent-child relationship
  in per-ingredient pages.

## SSSOM emission

After minting, `just build-sssom` emits one row per minted record:

```
subject_id            predicate            object_id      object_label
MIM:Vermont_Soil      skos:narrowMatch     ENVO:00001998  soil
```

(The SSSOM subject keeps its `MIM:<slug>` form for cross-repo
stability; the `kgmicrobe.ingredient:<slug>` is the YAML identifier
and the canonical KG-side node id.)

The `skos:narrowMatch` predicate is the key signal: any consumer
that joined "ENVO:00001998 = soil" with "Vermont Soil" expecting
identity will now see they're related-but-not-identical.

## When to mint vs when to keep

**Mint** when the qualifier represents a **real biological,
geographic, or formulation distinction** that downstream consumers
should be able to disambiguate:

- Geographic source: Vermont Soil, Bayan Obo Tailings
- Specific samples: Green House Soil, Iberian Pit Lake
- Branded formulations with reproducibility implications:
  Bacto Tryptic Soy Broth (Difco) vs (Oxoid)
- Composite formulations: Iron (as FeCl3 in EDTA), Trace Element
  Solution SL-10

**Keep** when the qualifier is a degenerate variant:

- Stereo prefixes: (R)-3-hydroxybutyrate (parent CHEBI is racemate)
- Hydrate forms: monohydrate / pentahydrate
- Numbered series of the same substance: Proteose Peptone No. 2
- Concentration qualifiers without recipe implications:
  "(0.70 M stock)"

## Relationship to existing skills

| Skill | Role |
|---|---|
| `complex-ingredient-resolver` | Source of FOODON/ENVO/MICRO/etc. mappings; many of its STRONG_MEDIUM hits are good mint candidates |
| `unmapped-inventory` | Doesn't reach already-mapped records; this skill complements by reviewing the mapped/ tier |
| `team-review-sssom` | Audit-grade per-row check; flags `LABEL_MISMATCH` independently of specificity loss |
| `mapping-taxonomy` | Canonical reference for verdict / quality vocabularies including NARROW_MATCH |

## Files

| Path | Role |
|---|---|
| `.claude/skills/specificity-loss-review/skill.md` | This file |
| `scripts/detect_specificity_loss.py` | Step 1 — detector |
| `scripts/mint_kgm_ingredient.py` | Step 2 — mint helper |
| `MediaIngredientMech/data/custom/kgmicrobe_ingredients.tsv` | Canonical custom-terms registry |
| `workspace/reports/specificity_loss_review.{tsv,md}` | Per-record report |

## Dependencies

- Python 3 + `pyyaml`
- No internet, no DB

## Notes on the parent-relation choice

The custom-ingredients TSV's `relation` column defaults to
`rdfs:subClassOf` (the kg-microbe term IS-A subclass of the parent
ontology term). For downstream graph emitters that prefer biolink,
this maps to `biolink:subclass_of`. The SSSOM uses
`skos:narrowMatch` because SSSOM is a mapping vocabulary, not an
asserted-classification vocabulary — the relationship semantics are
equivalent in this context (narrowMatch ≡ "the subject is narrower
than the object").

## Future enhancements

- **Auto-detect "obvious mints"** — when the qualifier is in the
  GEOGRAPHIC_OR_PROPER bucket AND the parent is in ENVO, auto-mint
  without curator confirmation. (Currently all minting is opt-in.)
- **Sibling-resolution** — when minting, search the parent term's
  children in the ontology to see if a more specific term already
  exists. (E.g., before minting kgmicrobe.ingredient:rabbit_blood,
  check if NCIT or BTO has a "rabbit blood" specialization.)
- **Bulk apply from curator-marked TSV** — already supported via
  `--from-tsv`; document a TSV-marking convention in this skill.
