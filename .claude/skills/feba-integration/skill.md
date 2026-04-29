---
name: feba-integration
description: Full FEBA (Functional Enrichment via CHEBI and Biological Annotation) pipeline — enrich CultureMech FEBA media ingredients with CHEBI IDs via CAS-RN lookup, create MIM records, and apply back to CultureMech
category: integration
requires_database: false
requires_internet: true
version: 1.0.0
tags: [feba, chebi, cas-rn, enrichment, culturemech, mim, ontology, pipeline]
---

# FEBA Integration Skill

## Overview

The FEBA integration pipeline enriches CultureMech ingredient records that lack CHEBI
ontology mappings by:

1. Identifying FEBA-sourced ingredients that are missing CAS-RN or CHEBI coverage
2. Mapping FEBA notation variants (e.g. `Fe(III) citrate` → CAS-RN)
3. Querying ChEBI API to get CHEBI IDs from CAS-RNs
4. Applying enriched CHEBI IDs back to CultureMech media files
5. Creating new MIM ingredient records for newly-mapped ingredients

**Always run from the `culturebotai-claw/` directory.**

---

## Pipeline Steps & Dependencies

```
feba-extract-uncovered          → workspace/feba_uncovered_report.yaml
         ↓
feba-map-variants               → workspace/feba_notation_mapping_results.yaml
         ↓
feba-classify                   → workspace/feba_mappability_classification.yaml
         ↓
feba-resolve-high               → workspace/feba_resolvable_resolution_results.yaml
         ↓
feba-generate-tsv               → FEBA_UNCOVERED_INGREDIENTS.tsv
         ↓                         (for human review)
feba-analyze-ontology           → workspace/feba_ontology_coverage_report.yaml
         ↓
feba-enrich-ontology            → workspace/feba_chebi_enrichment_results.yaml
         ↓
feba-apply-enrichments          → CultureMech media files updated in-place
         ↓
feba-update-mim                 → MIM ingredient files updated
         ↓
feba-create-mim-ingredients     → new MIM ingredient YAML files created
```

---

## Justfile Recipes

### Analysis Phase

```bash
# 1. Find FEBA ingredients with no CAS-RN coverage
just feba-extract-uncovered

# 2. Map FEBA notation variants to standard CAS-RN forms
just feba-map-variants

# 3. Classify ingredients by mappability (HIGH/MEDIUM/LOW/UNMAPPABLE)
just feba-classify

# 4. Resolve HIGH-priority resolvable ingredients
just feba-resolve-high

# 5. Generate TSV for human review
just feba-generate-tsv

# Or run all analysis steps at once:
just feba-analyze
```

### Ontology Enrichment Phase

```bash
# 6. Analyze ontology term coverage in CultureMech FEBA media
just feba-analyze-ontology

# 7. Test enrichment (10 ingredients only — check before full run)
just feba-enrich-ontology-test

# 7. Full enrichment via ChEBI API (may take several minutes)
just feba-enrich-ontology

# 8. Apply enrichments to CultureMech — dry-run first
just feba-apply-enrichments-dry
just feba-apply-enrichments

# 9. Update MIM with enrichment results — dry-run first
just feba-update-mim-dry
just feba-update-mim

# 10. Create new MIM ingredient records — dry-run first
just feba-create-mim-ingredients-dry
just feba-create-mim-ingredients
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/extract_feba_uncovered_ingredients.py` | Find FEBA ingredients missing CAS-RN/CHEBI |
| `scripts/map_feba_notation_variants.py` | Map notation variants to canonical CAS-RN |
| `scripts/classify_feba_mappability.py` | Score each ingredient HIGH/MEDIUM/LOW/UNMAPPABLE |
| `scripts/resolve_feba_resolvable.py` | Resolve HIGH (and optionally MEDIUM) priority items |
| `scripts/generate_feba_uncovered_tsv.py` | Export TSV for review |
| `scripts/analyze_feba_ontology_coverage.py` | Audit CHEBI term presence in FEBA media |
| `scripts/enrich_feba_ontology_from_cas.py` | Query ChEBI API; produce enrichment results YAML |
| `scripts/apply_ontology_enrichments.py` | Write CHEBI IDs into CultureMech media YAML files |
| `scripts/update_mim_with_enrichments.py` | Update existing MIM records with new CHEBI IDs |
| `scripts/create_mim_ingredients_from_enrichments.py` | Create new MIM YAML files for new ingredients |

---

## Workspace File Map

| File | Produced by | Consumed by |
|------|-------------|-------------|
| `workspace/feba_uncovered_ingredients.txt` | feba-extract-uncovered | feba-map-variants |
| `workspace/feba_uncovered_report.yaml` | feba-extract-uncovered | feba-classify, feba-generate-tsv |
| `workspace/feba_notation_mapping_results.yaml` | feba-map-variants | feba-classify, feba-enrich-ontology |
| `workspace/feba_mappability_classification.yaml` | feba-classify | feba-resolve-high/medium/all |
| `workspace/feba_resolvable_resolution_results.yaml` | feba-resolve-high | feba-enrich-ontology |
| `workspace/feba_ontology_coverage_report.yaml` | feba-analyze-ontology | feba-enrich-ontology |
| `workspace/feba_chebi_enrichment_results.yaml` | feba-enrich-ontology | feba-apply-enrichments, feba-update-mim, feba-create-mim-ingredients |
| `FEBA_UNCOVERED_INGREDIENTS.tsv` | feba-generate-tsv | human review |

---

## Internet Requirements

`feba-enrich-ontology` queries the **ChEBI API** (`www.ebi.ac.uk/chebi`). Requires internet.
The test recipe (`feba-enrich-ontology-test`) limits queries to 10 ingredients.

---

## When to Rerun

- New FEBA media imported into CultureMech that lack ontology mappings
- After `cas-rn-integration` adds new CAS-RNs that can now resolve FEBA ingredients
- Periodically when ChEBI database is updated with new compound entries

---

## After Completion

After running the full FEBA pipeline:
1. Run `just build-unified-mapping` to rebuild the unified mapping with new CHEBIs
2. Run `just sync-mim-to-culturemech` to propagate any new CHEBIs to other CultureMech media
3. Commit both CultureMech and MIM repos

---

## Related Skills

- `cross-repo-sync` (this repo) — run after FEBA to propagate enrichments
- `cas-rn-integration` (this repo) — adds CAS-RNs that feed the FEBA enrichment step
- `map-media-ingredients` (MIM) — manual curation path for ingredients FEBA can't resolve
