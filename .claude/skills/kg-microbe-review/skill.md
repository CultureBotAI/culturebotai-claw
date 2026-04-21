---
name: kg-microbe-review
description: Review kg-microbe's chemical-mappings-mim-priority branch against the current MIM published SSSOM. Diffs the two SSSOM artifacts row-by-row, surfaces rows where MIM's canonical data didn't propagate, and produces a report listing concrete commits we can contribute to chemical-mappings-mim-priority.
category: cross-repo
requires_database: false
requires_internet: false
version: 2.0.0
tags: [kg-microbe, sssom, mim, review, diff, pr-prep, chemical-mappings-mim-priority]
---

# kg-microbe Review Skill

## Purpose

Since kg-microbe has moved to SSSOM-first on the
`chemical-mappings-mim-priority` branch, the authoritative kg-microbe
mapping product is now
`mappings/unified_ingredient_mappings.sssom.tsv.gz` — emitted by
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
  └─ ingredient_mappings.sssom.tsv    VS    └─ unified_ingredient_mappings.sssom.tsv.gz
     (current: ~613 rows)                      (current: ~596k rows, of which ~640 are MIM:*)
```

The comparison is keyed by `subject_id` when it's a MIM CURIE.
kg-microbe may have additional rows for kg-microbe-only provenance
(`kgm.name:*`, `kgmicrobe.compound:*`, etc.) — those are out of
scope for this diff but noted in the review's "not-in-MIM context"
section.

## Diff classifications

| Class | Meaning | Suggested kg-microbe action |
|---|---|---|
| `IN_SYNC` | MIM row's (CHEBI, object_label) match kg-microbe's | None — rerun of consolidator will idempotently reproduce |
| `CHEBI_DIVERGED` | Both sides have the MIM subject but differ on object_id | Investigate: did MIM just change CHEBI? If yes, rerun consolidator |
| `LABEL_DRIFTED` | Same CHEBI but kg-microbe's object_label ≠ MIM's object_label | Priority-11 rule should force MIM label — check consolidator pipeline |
| `MISSING_IN_KGM` | MIM has the row; kg-microbe's SSSOM does not | Rerun consolidator (or MIM SSSOM wasn't picked up yet) |
| `STALE_IN_KGM` | kg-microbe's SSSOM has a `MIM:*` subject that MIM's current SSSOM does not | Rerun consolidator — MIM dropped/merged the record |
| `MIM_LEGACY_IN_KGM` | kg-microbe still references `MediaIngredientMech:<id>` legacy | Rerun consolidator — the migration should drop these |

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
  `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe`
  on the `chemical-mappings-mim-priority` branch

## Files

| Path | Role |
|---|---|
| `.claude/skills/kg-microbe-review/skill.md` | This file |
| `scripts/generate_kg_microbe_review.py` | The diff generator |
| `workspace/reports/kg_microbe_review.md` | Generated report |

## Related

- `mapping-taxonomy` — canonical reference for every mapping state
- `publish-sssom` — the MIM side of the handoff
- `cross-repo-sync` — the broader sync pipeline
