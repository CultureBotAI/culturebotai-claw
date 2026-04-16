---
name: cross-repo-sync
description: Sync identifiers, CHEBI mappings, and KG-Microbe node matches across CultureMech, MediaIngredientMech, and the unified ingredient mapping — the standard integration pipeline
category: integration
requires_database: false
requires_internet: false
version: 1.0.0
tags: [sync, integration, chebi, kg-microbe, unified-mapping, culturemech, mim, cross-repo]
---

# Cross-Repo Sync Skill

## Overview

Maintains consistency across the three downstream repos by running a standard
sequence of scripts that:

1. Build a unified ingredient mapping (CultureMech names × MIM records)
2. Backfill CHEBI IDs from MIM into CultureMech ingredient `term.id` fields
3. Match CultureMech media and MIM ingredients to KG-Microbe graph nodes

**Always run from the `culturebotai-claw/` directory.**

---

## Standard Sync Sequence

Run these in order after any significant MIM or CultureMech update:

```bash
# Step 1 — rebuild the unified mapping (required input for step 2)
just build-unified-mapping

# Step 2 — preview CHEBI backfill
just sync-mim-to-culturemech-dry

# Step 2 — apply CHEBI backfill to CultureMech
just sync-mim-to-culturemech

# Step 3 — re-match CultureMech media to KG-Microbe nodes
just match-culturemech

# Step 3 — re-match MIM ingredients to KG-Microbe CHEBI nodes
just match-mim
```

Or to run all KG matches at once:
```bash
just match-all
```

---

## Scripts

| Justfile Recipe | Script | What it does |
|----------------|--------|--------------|
| `build-unified-mapping` | `scripts/build_unified_ingredient_mapping.py` | Join all CultureMech ingredient names with MIM records; output: `workspace/unified_ingredient_mapping.tsv` |
| `sync-mim-to-culturemech[-dry]` | `scripts/sync_mim_to_culturemech.py` | Backfill CHEBI IDs from unified mapping into CultureMech `term.id` / `chebi_term.id` fields |
| `match-culturemech[-dry]` | `scripts/match_culturemech_to_kg.py` | Match CultureMech media → `mediadive.medium:XXX` KG nodes; populates `kg_microbe_match` field |
| `match-mim[-dry]` | `scripts/match_mim_to_kg.py` | Match MIM ingredients → CHEBI KG nodes; populates `kg_microbe_node_id` field |

---

## Key Output Files

| File | Description |
|------|-------------|
| `workspace/unified_ingredient_mapping.tsv` | 3,853 rows: every CultureMech ingredient name with CHEBI, CAS-RN, KG node IDs |
| `workspace/unified_ingredient_mapping.yaml` | Summary with status breakdown and top 50 fully-mapped ingredients |

---

## Coverage Baseline (as of 2026-04-15)

After last full sync:
- Unified mapping: 3,853 unique CultureMech ingredient names
- Have CHEBI ID: **1,212** (31%)
- Have CAS-RN: **1,107** (28%)
- Have KG-Microbe node ID: **775** (20%)
- Matched to MIM record: **1,185** (30%)
- CultureMech media with KG match: **489**
- MIM ingredients with KG node: **704**

---

## When to Rerun

| Event | Steps needed |
|-------|-------------|
| New MIM ingredients added (mapped with CHEBI) | Steps 1 → 2 → 3 |
| New CultureMech media added | Steps 1 → 3 (match-culturemech) |
| New CAS-RNs added to MIM | Step 1 only (rebuild unified mapping) |
| KG-Microbe graph updated (new embeddings release) | Step 3 only |

---

## Sync Rules (what `sync_mim_to_culturemech.py` does)

- Ingredient with **no `term.id`** → sets `term.id` to CHEBI from MIM
- Ingredient with **FOODON/other `term.id`** → adds `chebi_term.id` (preserves FOODON in `term.id`)
- Ingredient already with **`CHEBI:` `term.id`** → skipped

---

## Troubleshooting

**Unified mapping file missing:**
```bash
just build-unified-mapping
# Requires both CultureMech and MIM repos to exist at expected paths
```

**Low CHEBI coverage after sync:**
- Check `workspace/unified_ingredient_mapping.tsv` — column `mapping_status`
- `UNMAPPED`: ingredient is in MIM but lacks CHEBI (needs manual curation in MIM)
- `UNMATCHED_IN_MIM`: name not found in MIM at all (add to MIM or check spelling)

**KG match failures:**
- Verify embeddings file exists in `CultureMech/data/embeddings/`
- CHEBI nodes must exist in the KG graph; new CHEBI IDs may lag by one KG release

---

## Related Skills

- `build-unified-mapping` (MediaIngredientMech) — same workflow, documented from MIM side
- `feba-integration` (this repo) — FEBA enrichment that feeds new CHEBIs into MIM, then rerun cross-repo-sync
- `cas-rn-integration` (this repo) — adds CAS-RNs to MIM, then rebuild unified mapping
- `match-kg-microbe` (CultureMech) — per-recipe KG matching from within CultureMech
