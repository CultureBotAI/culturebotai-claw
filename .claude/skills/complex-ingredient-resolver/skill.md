---
name: complex-ingredient-resolver
description: Multi-ontology cascading resolver for heuristic-complex MIM ingredients (yeast extract, peptone, soil, manure, milk, etc.). Searches FOODON → ENVO → CHEBI → NCIT via EBI OLS REST and OAK CHEBI sqlite. Re-scores fuzzy matches via token-subset analysis (label tokens ⊆ name tokens) to suppress single-word false positives. Auto-applies HIGH-confidence label/synonym-exact hits and STRONG_MEDIUM token-contained fuzzy hits; surfaces the rest for curator review.
category: curation
requires_database: false
requires_internet: true
version: 1.0.0
tags: [mim, foodon, envo, chebi, ncit, ols, oak, complex-ingredient, food, environmental, dismech]
---

# Complex Ingredient Resolver Skill

## Purpose

The `unmapped-inventory` skill identifies a "heuristic-complex" bucket
of ingredient names (yeast extract, peptone, soil, brain heart
infusion, cow's milk, etc.) — substances that can't be mapped to a
single CHEBI compound because they're food/environmental/biological
mixtures. This skill resolves them.

Because no single ontology covers every complex-ingredient class, the
resolver runs a **cascading search** across four ontologies, in
priority order:

```
   FOODON  ⇢  ENVO   ⇢  CHEBI  ⇢  NCIT
   (food)     (env)     (chem)    (clinical/pharma)
```

Each hit is classified and then **re-scored** to filter false
positives that pure OLS fuzzy-top matching would let through.

## OLS + OAK in this skill (per-tool roles)

This skill — like `synonym-review`, `ingredient-mapping`, and
`evidence-reference-validation` — relies on the same two ontology
infrastructures used across the claw repo:

| Tool | Used for | Where |
|---|---|---|
| **EBI OLS REST API** (`/api/search`) | Live label / synonym / fuzzy search across FOODON, ENVO, CHEBI, NCIT | `scripts/foodon_pass.py::ols_search` |
| **OAK** (`oaklib`) + local CHEBI sqlite (`~/.data/oaklib/chebi.db`) | Offline structure metadata (formula, SMILES, InChI) for CHEBI-mapped ingredients | `scripts/backfill_chebi_chemistry.py` |

The cascading resolver in this skill uses **OLS** (live, multi-ontology
coverage); the `evidence-reference-validation` and `ingredient-mapping`
skills use **both OLS and OAK** depending on the operation. The general
principle in claw scripts:

- **OLS for discovery / search** — fast, no local DB to maintain,
  covers every ontology in EBI's index.
- **OAK for offline batch operations** — chemistry structure backfill,
  CAS-RN xref index, deterministic local validation.

Both pipelines are caching-aware: OLS calls accumulate in
`workspace/cache/ols_cas_cache.json` (used by `import-ingredients`),
and OAK lookups read directly from the local sqlite (no network).

## Match scoring

`scripts/foodon_pass.py::score_fuzzy_match` re-scores any OLS
"fuzzy-top" result (the top non-exact hit) using token-subset analysis:

```
STRONG     label tokens ⊆ name tokens AND label has ≥ 2 non-stop tokens
ACCEPTABLE name tokens ⊆ label tokens AND name has ≥ 2 non-stop tokens
WEAK       neither subset holds — only partial overlap (likely wrong)
```

The `≥ 2 tokens` floor is the key tightening: it blocks matches like
"B-glucan from yeast" → FOODON:03411345 *yeast* (the label is too
generic), while keeping "Cow's milk" → FOODON:02020891 *cow milk*
(the label has two contentful tokens that both appear in the name).

A small stop-token list excludes function words ("of", "and", "from")
and ingredient-form words that aren't discriminating ("powder",
"solution", "extract", "broth", "agar"). Tweak the list at the top
of `foodon_pass.py` if a specific domain term is causing
over/under-matching.

## Pipeline

```
   ┌──────────────────────────────────────────────────────────┐
   │  Stage 1 — Harvest                                       │
   │   `just inventory-unmapped`                              │
   │   Filters distinct names matching _COMPLEX_RE            │
   │   (yeast/peptone/extract/soil/manure/...)                │
   │   ≈ 99 names today (stable across recent runs)           │
   └────────────────────────┬─────────────────────────────────┘
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Stage 2 — Cascading OLS search                          │
   │   FOODON → ENVO → CHEBI → NCIT                           │
   │   Stop on first label-exact / synonym-exact (= HIGH)     │
   │   Else: take FOODON fuzzy-top, re-score                  │
   └────────────────────────┬─────────────────────────────────┘
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Stage 3 — Apply or report                                │
   │   --apply              writes HIGH + STRONG_MEDIUM        │
   │   --apply --high-only  writes HIGH only (safer default)   │
   │   no flag              dry-run; report-only              │
   └────────────────────────┬─────────────────────────────────┘
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Stage 4 — Move applied YAMLs from unmapped/ → mapped/    │
   │   git mv per upgraded record                              │
   │   (handled in user workflow, not the script)              │
   └────────────────────────┬─────────────────────────────────┘
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Stage 5 — Republish SSSOM                                │
   │   `just build-sssom && just publish-sssom`                │
   │   New rows under FOODON / ENVO / NCIT show up             │
   └──────────────────────────────────────────────────────────┘
```

## Run it

```bash
# 1) Make sure the inventory is fresh
just inventory-unmapped

# 2) Dry-run + report (default)
just foodon-pass

# 3) Apply HIGH only — safe; only label/synonym-exact hits
just foodon-pass -- --apply --high-only

# 4) Apply HIGH + STRONG_MEDIUM (most aggressive)
just foodon-pass -- --apply

# 5) After apply, move upgraded YAMLs to mapped/ (handled per-record;
#    see the apply step in the user workflow)
```

Outputs:

- `workspace/reports/foodon_pass.tsv` — per-name verdicts
- `workspace/reports/foodon_pass.md` — bucketed report (HIGH /
  STRONG_MEDIUM / MEDIUM / WEAK_MEDIUM / NO_HIT)

## Verdicts

| Verdict | Match origin | Trust | Action |
|---|---|---|---|
| `HIGH` | label-exact or synonym-exact in FOODON / ENVO / CHEBI / NCIT | Highest | Auto-apply (`--apply`) |
| `STRONG_MEDIUM` | OLS fuzzy-top, label tokens ⊆ name tokens, label ≥ 2 tokens | High | Auto-apply (`--apply` without `--high-only`) |
| `MEDIUM` | OLS fuzzy-top, name tokens ⊆ label tokens, name ≥ 2 tokens | Medium | Curator review |
| `WEAK_MEDIUM` | OLS fuzzy-top, only partial overlap | Low | Skip (likely wrong) |
| `NO_HIT` | No match in any of the four cascading ontologies | n/a | Leave as `kgmicrobe.compound:` placeholder; consider MICRO ontology (deferred) |

## Real-world results (2026-05-01 first run)

Out of 99 heuristic-complex distinct names:

- **9 records upgraded automatically** (6 FOODON HIGH from prior pass +
  3 ENVO HIGH this pass: Garden Soil, Sludge, Soil; 6 STRONG_MEDIUM
  from prior pass: Beef Brain Powder, Beef Heart Infusion, Cooked
  Meat Medium, Cow's Milk, Ground Beef, Dry Cow-manure)
- **2 MEDIUM** for curator review (Infusion from Potatoes, Sea water
  — name is more specific than the label)
- **76 WEAK_MEDIUM** — fuzzy hits filtered out as likely wrong
- **7 NO_HIT** — Peptone, Proteose peptone, Trypticase peptone, Bacto
  Tryptone, Universal peptone, Marine broth 2216, Anaerobe Basal
  Broth CM0957. These would be cleanly mapped via the **MICRO**
  ontology (`MICRO:0000178` is "peptone") but MICRO requires adding
  a new prefix to the SSSOM curie_map — deferred.

## Known false positives

- `Dry cow-manure` originally matched FOODON:00004411 (*dry cow*) as
  STRONG_MEDIUM — wrong sense (a non-lactating cow, not manure).
  Manually corrected to `ENVO:00003031` (animal manure). This is the
  edge case the token-subset rule can't handle: "dry cow" is a valid
  English subphrase of "dry cow-manure" but means something
  completely different. Curator review of `STRONG_MEDIUM` is
  recommended despite the heuristic tightening.

## When to use

- After `just inventory-unmapped` shows new heuristic-complex names
  in MIM `unmapped/`
- When CHEBI/NCIT-only resolution leaves yeast extracts / peptones /
  soils unmapped
- Quarterly to re-check after FOODON / ENVO ontology updates
- When debugging a "this is a complex ingredient and shouldn't be
  CHEBI" curator question

## What this skill does NOT do

- Backfill chemical structure (use `evidence-curation` for evidence,
  `import-ingredients` for full source-driven mapping, the dedicated
  CHEBI-chemistry backfill script for formulas)
- Move YAMLs from unmapped/ to mapped/ — that's a manual `git mv`
  step in the user workflow (so curators see the move in commit
  diffs)
- Validate that the chosen FOODON/ENVO term is the *best* possible
  match — only that it's substring-correct. Curator review remains
  the source of truth for "is this the right term".

## Files

| Path | Role |
|---|---|
| `.claude/skills/complex-ingredient-resolver/skill.md` | This file |
| `scripts/foodon_pass.py` | The resolver driver |
| `workspace/reports/unmapped_inventory.tsv` | Input — distinct heuristic-complex names |
| `workspace/reports/foodon_pass.{tsv,md}` | Output — per-name verdicts |

## Dependencies

- Python 3 + `pyyaml`
- Internet access for EBI OLS4 (`https://www.ebi.ac.uk/ols4/api/search`)
- (For chemistry backfill on the same records: `~/.data/oaklib/chebi.db`,
  used by the separate `backfill_chebi_chemistry.py` script — out of
  scope for this resolver.)

## Related skills

- `unmapped-inventory` — produces the heuristic-complex bucket this
  skill consumes
- `ingredient-mapping` — the broader source→resolver→emit pipeline;
  uses OLS+OAK in similar ways
- `evidence-reference-validation` — Phase 1 anti-hallucination gate
- `synonym-review` — uses both OLS and OAK to cross-check ingredient
  synonyms post-publish
- `mapping-taxonomy` — canonical reference for verdict vocabulary

## Deferred / future enhancements

- **MICRO ontology cascade** — `MICRO:0000178` ("peptone") would
  cleanly cover the 7 NO_HIT peptone variants. Requires adding the
  `MICRO:` prefix to `MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv`'s
  `curie_map` and to `scripts/build_mim_ingredient_sssom.py`'s
  supported-prefix list. Modest schema extension.
- **MeSH cascade** — `mesh:C030846` is "Bacto-peptone"; `mesh:C018135`
  is "proteose-peptone". Same pattern as MICRO — needs prefix
  registration.
- **Curator-marked-TSV apply pass** — for the MEDIUM bucket, a tiny
  follow-up script reads a curator-marked TSV and writes per-row
  YAMLs.
