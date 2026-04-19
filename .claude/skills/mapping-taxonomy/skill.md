---
name: mapping-taxonomy
description: Generate a canonical reference of every mapping case the MIM ↔ kg-microbe reconciliation pipeline produces — buckets, verdicts, flags, confidence tiers, safety tiers, and the artifact each case lives in. Useful when onboarding, writing a new script, or answering "what does X status mean?"
category: documentation
requires_database: false
requires_internet: false
version: 1.0.0
tags: [mapping, taxonomy, reference, reconciliation, audit, sssom, documentation]
---

# Mapping Taxonomy Skill

## Purpose

The reconciliation pipeline produces a zoo of categorical states:
`AGREE` / `DISAGREE` / `MIM_ONLY` / `KGM_ONLY`, `MIM_WRONG` / `MIM_OK` /
`AMBIGUOUS`, `HIGH` / `MEDIUM` / `LOW` / `NONE`, `SAFE` / `RISKY`,
`MERGEABLE_DUPES` / `MIXED` / `LEGITIMATE_VARIANTS`, `CLEAN_ADD` /
`DUPLICATE` / `NOISE`, `ROUTE_TO_HYDRATE` / `ROUTE_TO_ANHYDROUS` /
`UNRESOLVED`, and a long tail of audit flags
(`DEPRECATED_CHEBI`, `LABEL_DRIFT`, `DUPLICATE`, `PREFIX_IRREGULAR`,
`CHEBI_REMOVED`, `STALE_LOCAL`…).

This skill emits a single canonical reference markdown documenting:

1. Every categorical state with its meaning
2. The script that **produces** rows with that state
3. The artifact file(s) where those rows live
4. The downstream script(s) that **consume** the state
5. A cross-reference graph of the pipeline

## When to use

- Onboarding someone into this repo
- Adding a new script and wanting to align its vocabulary with existing
  taxonomy (re-use rather than invent)
- Answering "what does bucket X mean?"
- After a major change to a classifier, to regenerate the reference
- Before writing a PR description that refers to a bucket name

## What it does

Runs `scripts/generate_mapping_taxonomy_report.py`, which:

1. Scans known producer scripts under `scripts/` for hard-coded state
   names (via structured annotations the script knows about — not
   free-form grep, to keep the output deterministic).
2. Checks which of the expected artifact files exist under
   `workspace/reports/`, `workspace/patches/`, and
   `MediaIngredientMech/mappings/` — annotates each with last-modified
   timestamp and row count.
3. Emits `workspace/reports/mapping_taxonomy.md` — a single document
   with one section per category family.

## Invocation

```bash
just mapping-taxonomy
# or directly:
python3 scripts/generate_mapping_taxonomy_report.py
```

## Output

`workspace/reports/mapping_taxonomy.md` — structure:

```
# MIM ↔ kg-microbe Mapping Case Taxonomy

## 1. Reconciliation buckets          (AGREE / DISAGREE / MIM_ONLY / KGM_ONLY / UNMAPPED_PENDING_CURATION)
## 2. Audit row flags                 (DEPRECATED_CHEBI / LABEL_DRIFT / DUPLICATE / PREFIX_IRREGULAR)
## 3. DISAGREE round-trip verdicts    (MIM_WRONG / MIM_OK / AMBIGUOUS)
## 4. P4.4 synonym-enrichment buckets (CLEAN_ADD / DUPLICATE / AMBIGUOUS / NOISE)
## 5. P4.4 hydration resolution       (ROUTE_TO_{HYDRATE,ANHYDROUS,UNKNOWN_HYDRATE} / AMBIGUOUS_TARGETS / UNRESOLVED)
## 6. Hydrate sibling proposal tiers  (HIGH / MEDIUM / LOW / NONE)
## 7. Curation queue actions          (curate-new-MIM / link-to-existing / already_in_mim)
## 8. Numeric-namespace migration     (migrate / ambiguous / orphan / keep)
## 9. Duplicate-CHEBI classification  (MERGEABLE_DUPES / MIXED / LEGITIMATE_VARIANTS)
## 10. Merge safety tiers             (SAFE / RISKY)
## 11. Label drift fix kinds          (LABEL_UPDATE / STALE_LOCAL / CHEBI_REMOVED / UNKNOWN)
## 12. Re-curation outcomes           (HIGH / MEDIUM / LOW / NONE, CURATOR_CONFIRMED_SYNONYM)
## 13. Complex-media extraction       (pure / complex_medium)
## 14. Evidence types                 (DATABASE_MATCH / LEXICAL_MATCH / CURATOR_CONFIRMED_SYNONYM …)
## 15. SSSOM predicate richness       (skos:exactMatch / closeMatch / narrowMatch / broadMatch)
## 16. Curation history action codes  (complete chronological list)
## 17. Artifact inventory             (path | producer | consumer | status)
## 18. Pipeline graph                 (which script feeds which)
```

## Dependencies

- Python 3 + pyyaml (for artifact inspection)
- No internet or DB access required — purely documents what exists

## Related skills

- `publish-sssom` — produces the canonical `ingredient_mappings.sssom.tsv`
- `synonym-review` — populates one class of audit verdicts
- `team-review-sssom` — populates `validation_method` stamps

## Files

| Path | Role |
|---|---|
| `.claude/skills/mapping-taxonomy/skill.md` | This file |
| `scripts/generate_mapping_taxonomy_report.py` | The generator |
| `workspace/reports/mapping_taxonomy.md` | Generated output |
