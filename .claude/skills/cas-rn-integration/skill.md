---
name: cas-rn-integration
description: Enrich MediaIngredientMech ingredient records with CAS Registry Numbers using CultureBotHT CSV and PubChem API, and export unmapped CAS-RN ingredients for review
category: integration
requires_database: false
requires_internet: true
version: 1.0.0
tags: [cas-rn, pubchem, enrichment, mim, chemical-identity, chebi]
---

# CAS-RN Integration Skill

## Overview

Adds CAS Registry Numbers (CAS-RNs) to MediaIngredientMech ingredient YAML files
using two complementary strategies:

1. **CultureBotHT CSV match** — name-normalized lookup against `compounds_to_cas.csv`
   (1,393 compounds with CAS-RNs, no API calls required)
2. **PubChem API** — for CHEBI-mapped ingredients: CHEBI ID → PubChem CID → CAS-RN synonyms

CAS-RN is written to `chemical_properties.cas_rn` in each MIM ingredient file.

**Always run from `culturebotai-claw/` directory.**

---

## Standard Workflow

```bash
# 1. Enrich MIM with CAS-RNs (dry-run first)
python scripts/enrich_mim_cas_rn.py --dry-run --max-queries 20

# 2. Full run (PubChem queries — may take several minutes)
python scripts/enrich_mim_cas_rn.py

# 3. Export unmapped ingredients to TSV for review
just cas-export-unmapped
# Output: workspace/unmapped_cas_rn_ingredients.tsv
#         UNMAPPED_CAS_RN_INGREDIENTS.tsv (copy)

# 4. View unmapped TSV
just view-cas-tsv
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/enrich_mim_cas_rn.py` | Main enrichment — CSV + PubChem strategies |
| `scripts/export_unmapped_cas_rn_tsv.py` | Export ingredients still lacking CAS-RN |
| `scripts/fetch_cas_rn_from_culturebot_csv.py` | CSV strategy only |
| `scripts/fetch_cas_rn_from_pubchem.py` | PubChem API strategy only |
| `scripts/fetch_cas_rn_from_cactus.py` | NCI Cactus resolver (fallback) |
| `scripts/fetch_cas_rn_from_chemspider.py` | ChemSpider (requires API key) |
| `scripts/fetch_cas_rn_from_cas_common_chemistry.py` | CAS Common Chemistry API |
| `scripts/fetch_cas_rn_with_preprocessing.py` | Name normalization pre-processing helper |
| `scripts/integrate_cas_rn_from_culturebot_ht.py` | Batch integration from CultureBotHT source |

---

## Source Priority

```
1. CultureBotHT CSV   — fast, no API, covers ~1,393 common compounds
   Path: ~/CultureBotHT/CultureBotHT/data/raw/google_sheets/compounds_to_cas.csv

2. PubChem API        — needs internet; CHEBI-mapped ingredients only
   Endpoint: pubchem.ncbi.nlm.nih.gov/rest/pug

3. CAS Common Chemistry — public CAS API (rate limited)
4. NCI Cactus resolver  — fallback, lower reliability
5. ChemSpider           — requires API key (CHEMSPIDER_API_KEY env var)
```

`enrich_mim_cas_rn.py` runs strategies 1 and 2 in sequence automatically.

---

## Coverage Baseline (as of 2026-04-15)

- MIM ingredients: 1,183 total
- Have CAS-RN: **1,068** (90.3%)
- Missing CAS-RN: **115** (9.7%)

The remaining 115 are largely: complex mixtures, biological extracts (yeast extract,
peptone), buffers without unique chemical identity, and UNMAPPED ingredients that
lack a CHEBI ID (PubChem strategy requires CHEBI).

---

## Rate Limits

| Source | Rate Limit |
|--------|-----------|
| PubChem | 5 requests/sec (built-in 0.2s delay in script) |
| CAS Common Chemistry | Not documented; use conservatively |
| Cactus | ~1 req/sec recommended |
| ChemSpider | Tier-dependent on API key |

Use `--max-queries N` to limit API calls during testing:
```bash
python scripts/enrich_mim_cas_rn.py --max-queries 50
```

---

## Output Files

| File | Description |
|------|-------------|
| MIM ingredient YAML files | `chemical_properties.cas_rn` field populated in-place |
| `workspace/unmapped_cas_rn_ingredients.tsv` | Ingredients still lacking CAS-RN |
| `UNMAPPED_CAS_RN_INGREDIENTS.tsv` | Copy of above for root-level visibility |

---

## When to Rerun

- After adding new MIM ingredients (new records may now match CultureBotHT CSV)
- After CHEBI IDs are added to previously-UNMAPPED ingredients (enables PubChem lookup)
- After CultureBotHT updates their `compounds_to_cas.csv`

---

## After Completion

1. Rebuild unified mapping: `just build-unified-mapping`
   (CAS-RN column will now be populated for newly-enriched ingredients)
2. Commit MediaIngredientMech changes
3. If running FEBA enrichment next: `just feba-enrich-ontology` benefits from higher CAS-RN coverage

---

## Related Skills

- `cross-repo-sync` (this repo) — rebuild unified mapping after new CAS-RNs
- `feba-integration` (this repo) — uses CAS-RNs to look up CHEBI IDs
- `merge-ingredients` (MIM) — deduplication may be needed before CAS-RN enrichment
