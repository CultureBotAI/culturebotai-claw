---
name: kg-microbe-review
description: Review kg-microbe's chemical-mappings-mim-priority branch against the current MIM published SSSOM. Diffs the two SSSOM artifacts row-by-row, surfaces rows where MIM's canonical data didn't propagate, and produces a report listing concrete commits we can contribute to chemical-mappings-mim-priority.
category: cross-repo
requires_database: false
requires_internet: false
version: 2.0.0
tags: [kg-microbe, sssom, mim, review, diff, pr-prep, chemical-mappings-mim-priority]
reference-root: kg-microbe
---

# kg-microbe Review Skill

## Purpose

Since kg-microbe has moved to SSSOM-first on the
`chemical-mappings-mim-priority` branch, the authoritative kg-microbe
mapping product is now
`mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz` — emitted by
`scripts/consolidate_chemical_mappings.py` with a documented
**priority system** where `mediaingredientmech_reviewed` sits at
priority 11 (highest). The legacy flat TSV
(`unified_chemical_mappings.tsv.gz`) is being phased out.

This skill prepares a **contribution-focused review**: it diffs MIM's
published SSSOM against kg-microbe's consolidated SSSOM and lists
exactly what kg-microbe's chemical-mappings-mim-priority branch should
pick up on its next consolidator run — plus anything we can
contribute upstream directly.

## Scope of the review

```
  MediaIngredientMech/mappings/              kg-microbe/mappings/
  └─ ingredient_mappings.sssom.tsv    VS    └─ kgmicrobe_unified_entity_mappings.sssom.tsv.gz
     (current: ~613 rows)                      (current: ~596k rows, of which ~640 are MIM:*)
```

**Comparison is keyed on `object_id`**, not on `subject_id`.
kg-microbe's consolidator collapses MIM:* subjects into entity-anchored
xref rows (`cas:50-99-7 → CHEBI:17234` carrying `mediaingredientmech_*`
in the `source` column). A subject-anchored diff would mis-report
1300+ correctly-propagated rows as missing; the object-anchored diff
matches the consolidator's actual data model.

## Diff classifications

### Primary diff: MIM SSSOM vs kg-microbe `kgmicrobe_unified_entity_mappings.sssom.tsv.gz`

| Class | Meaning | Suggested kg-microbe action |
|---|---|---|
| `IN_SYNC` | kg-microbe has ≥1 row with this MIM-asserted `object_id` AND `mediaingredientmech_*` in `source` | None — consolidator absorbed it via xref propagation |
| `IN_SYNC_SUBJECT_PRESERVED` | kg-microbe still keys this MIM:* subject as a row, and the object matches MIM's | None — residual subject preserved (typically standalone ENVO/MICRO with no other xrefs) |
| `DIVERGED_OBJECT` | MIM:* subject preserved in kg-microbe but with a different `object_id` than MIM asserts | Investigate: typical cases are MICRO vs FOODON (peptone family), or MIM-minted `kgmicrobe.ingredient:*` collapsed to ENVO parent (Vermont Soil) |
| `PROVENANCE_LOST` | Object exists in kg-microbe but no row tags `mediaingredientmech_*` | Rerun consolidator OR audit its source-merge logic |
| `OBJECT_NOT_IN_KGM` | MIM-asserted `object_id` absent from kg-microbe's SSSOM entirely | True backlog — consolidator hasn't ingested this object |
| `REGISTRY_LANDED` | MIM registry row (object = `kgmicrobe.{ingredient,compound}:*`); CURIE has its own subject row in kg-microbe | None — registry CURIE materialised |
| `REGISTRY_NOT_LANDED` | Same shape but no kg-microbe row for that CURIE | Informational — happens when MIM mints a registry CURIE without a canonical CHEBI anchor for the consolidator to synthesise around |
| `STALE_IN_KGM` | kg-microbe still has a `MIM:*` subject row that MIM's current SSSOM does not | Rerun consolidator — MIM dropped/merged the record |
| `MIM_LEGACY_IN_KGM` | Any `MediaIngredientMech:*` subjects remaining | Rerun consolidator — namespace migration should drop these |

### Secondary diff: kg-microbe metatraits chemical mappings vs MIM

The review additionally checks two **out-of-SSSOM** files in
`kg-microbe/mappings/canonical/`:

- `chemical_mappings.tsv` — trait → CHEBI for carbon/nitrogen substrates
- `special_chemical_mappings.tsv` — trait_pattern → ontology overrides

| Class | Meaning | Suggested action |
|---|---|---|
| `IN_MIM_AGREE` | kg-microbe's CHEBI is already a primary ID in MIM | None |
| `IN_MIM_DIVERGE` | Same chemical name in MIM but with a different CHEBI | Manual review — pick the right one (often charge-state / hydration variants like glucose vs D-glucopyranose) |
| `MISSING_IN_MIM` | Chemical not in MIM — candidate for `import-ingredients` skill | Add to MIM (it has a CHEBI/FOODON/ENVO ID, so HIGH-confidence) |

**Out-of-scope** (no chemistry overlap with MIM): `enzyme_mappings.tsv`,
`enzyme_name_to_go.tsv`, `pathway_mappings.tsv`,
`phenotype_mappings.tsv`, `metpo_alias_mappings.tsv`. These are not
reviewed because MIM's mandate is ingredient/chemical mappings, not
enzymes/pathways/phenotypes.

## Invocation

```bash
just kg-microbe-review                  # default: writes workspace/reports/kg_microbe_review.md
# or:
python3 scripts/generate_kg_microbe_review.py [--branch chemical-mappings-mim-priority]
```

Output: `workspace/reports/kg_microbe_review.md` — structured for
sharing with a kg-microbe reviewer and for deriving the PR scope.

## When to use

- Before opening a PR to `chemical-mappings-mim-priority`
- After running `just publish-sssom` on the MIM side
- When kg-microbe's consolidator produces output that doesn't match
  MIM's intent — this script identifies the drift precisely
- For periodic sanity checks of the cross-repo sync

## Contribution scope (what we could PR)

Based on the current branch state (commits like `9b3f760d`
"Regenerate unified mappings from refreshed MIM SSSOM") — the
likely contribution surfaces are:

1. **Additional source tagging in the SSSOM `source` column** —
   surface MIM-specific curation tags (e.g. `MIM:curator=<name>`)
   for better provenance (currently they're flattened to just
   `mediaingredientmech_reviewed`).
2. **Consolidator enhancement** — if `object_formula` / `object_category`
   are missing for any MIM row that MIM's YAML specifies, a small
   patch to `consolidate_chemical_mappings.py` could propagate them.
3. **Test fixtures** — the review report's `MISSING_IN_KGM` and
   `STALE_IN_KGM` rows double as regression-test inputs.
4. **MIM SSSOM schema compatibility** — if we add columns to MIM's
   SSSOM (e.g. `validation_method`), kg-microbe's consolidator may
   need corresponding handling.

## Dependencies

- Python 3 + pyyaml
- No internet or DB access required
- Access to the kg-microbe repo at
  the checkout `KGMICROBE_ROOT` names, `../kg-microbe` by default
  on the `chemical-mappings-mim-priority` branch

## Files

| Path | Role |
|---|---|
| `.claude/skills/kg-microbe-review/SKILL.md` | This file |
| `scripts/generate_kg_microbe_review.py` | The diff generator |
| `workspace/reports/kg_microbe_review.md` | Generated report |

## Related

- `mapping-taxonomy` — canonical reference for every mapping state
- `publish-sssom` — the MIM side of the handoff
- `cross-repo-sync` — the broader sync pipeline
