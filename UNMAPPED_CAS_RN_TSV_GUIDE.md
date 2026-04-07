# Unmapped CAS-RN Ingredients TSV Guide

**File**: `UNMAPPED_CAS_RN_INGREDIENTS.tsv`  
**Generated**: 2026-04-06  
**Total Ingredients**: 367 (33% of 1,113 total)

---

## Overview

This TSV file contains all 367 MediaIngredientMech ingredients that lack CAS Registry Numbers after automated integration (Phases 1-6). Ingredients are categorized by unmappability reason and prioritized for manual curation.

---

## TSV Structure

### Columns (12 total)

| Column | Description | Example Values |
|--------|-------------|----------------|
| **priority** | Curation priority | HIGH, MEDIUM, LOW, UNMAPPABLE |
| **category** | Unmappability reason | Hydrated Salts (x notation), Stock Solutions/Mixtures, etc. |
| **preferred_term** | Primary ingredient name | CaCl2 x 2 H2O, Sodium chloride |
| **ontology_id** | Mapped ontology ID | CHEBI:86158, FOODON:00001234, (empty) |
| **ontology_label** | Ontology term label | CaCl2 x 2 H2O |
| **ontology_source** | Source ontology | CHEBI, FOODON, ENVO, (empty) |
| **mapping_status** | Mapping status | MAPPED, UNMAPPED, UNKNOWN |
| **has_chebi_id** | Has ChEBI ID (boolean) | True, False |
| **synonym_count** | Number of synonyms | 0-25 |
| **synonyms** | First 3 synonyms (pipe-separated) | Synonym1\|Synonym2\|Synonym3 |
| **filename** | YAML filename | Cacl2_X_2_H2o.yaml |
| **file_path** | Relative path from MediaIngredientMech root | data/ingredients/mapped/Cacl2_X_2_H2o.yaml |

### Sorting

TSV is sorted by:
1. **Priority** (HIGH → MEDIUM → LOW → UNMAPPABLE)
2. **Category** (alphabetical)
3. **Preferred term** (alphabetical)

---

## Category Breakdown

### 1. Hydrated Salts (x notation) - 99 ingredients (27.0%)

**Priority**: HIGH  
**Description**: Hydrated salts using "x" notation (e.g., "CaCl2 x 2 H2O")  
**Mappability**: High - requires "x" notation preprocessing

**Examples**:
- CaCl2 x 2 H2O (CHEBI:86158)
- CuSO4 x 5 H2O (CHEBI:31440)
- FeSO4 x 7 H2O (CHEBI:86161)

**Approach**:
- Convert "x" notation to standard hydrate form
- "CaCl2 x 2 H2O" → "Calcium chloride dihydrate"
- Requires formula → name lookup or manual mapping

**Potential**: Phase 7 preprocessing could resolve 50-80 of these

---

### 2. Other/Uncategorized - 166 ingredients (45.2%)

**Priority**: MEDIUM  
**Description**: Mapped ingredients with ChEBI IDs but no CAS-RN found in any API  
**Mappability**: Moderate - requires manual lookup or specialized sources

**Examples**:
- 2-Mercaptoethanesulfonate (CHEBI:17905)
- Catalase (CHEBI:4056)
- Cellobiose (CHEBI:35156)

**ChEBI Coverage**: 166/166 (100%) have ChEBI IDs

**Approach**:
- Manual lookup in ChEBI web interface
- Direct CAS Registry search (if access available)
- SciFinder or Reaxys (if institutional access)
- Chemical literature review

**Potential**: Manual curation could resolve 100-150

---

### 3. Stock Solutions/Mixtures - 53 ingredients (14.4%)

**Priority**: UNMAPPABLE  
**Description**: Multi-component mixtures, media, or stock solutions  
**Mappability**: Unmappable - no single CAS-RN exists

**Examples**:
- Trace Metals Solution
- Phosphate Buffer Stock Solution
- BG-11 Trace Metals Solution
- P-II Metal Solution

**Approach**: Document as unmappable, no CAS-RN possible

---

### 4. Abbreviations - 16 ingredients (4.4%)

**Priority**: MEDIUM  
**Description**: Abbreviated names or incomplete formulas  
**Mappability**: Moderate - may be typos or need expansion

**Examples**:
- FE EDTA
- H3BO (incomplete, should be H3BO3)
- K2HPO (incomplete, should be K2HPO4)
- NH4NO (incomplete, should be NH4NO3)

**Approach**:
- Expand abbreviations
- Complete chemical formulas
- Check for typos in source data

**Potential**: 5-10 resolvable with formula completion

---

### 5. Complex Notation - 14 ingredients (3.8%)

**Priority**: MEDIUM  
**Description**: Special characters (•, unusual symbols) not handled by Phase 5  
**Mappability**: Moderate - needs additional preprocessing

**Examples**:
- CaCl2•2H2O (bullet notation)
- Na2glycerophosphate•5H2O
- Citric Acid•H2O

**Approach**: Extend Phase 5 preprocessing to handle bullet (•) notation

**Potential**: 10-12 resolvable with extended preprocessing

---

### 6. Natural Products - 11 ingredients (3.0%)

**Priority**: UNMAPPABLE  
**Description**: Environmental samples, natural extracts  
**Mappability**: Unmappable - variable composition

**Examples**:
- Seawater
- Organic Peat
- Vermont Soil
- Sphagnum extract

**Approach**: Document as unmappable, no CAS-RN possible

---

### 7. Placeholders/Errors - 4 ingredients (1.1%)

**Priority**: UNMAPPABLE  
**Description**: Data quality issues, placeholders  
**Mappability**: Unmappable - fix source data

**Examples**:
- "See source for composition"
- "Original amount: (NH4)2HPO4(Fisher A686)"
- CHEBI:1 (invalid placeholder)

**Approach**: Remove or replace with correct data

---

### 8. Commercial Products - 3 ingredients (0.8%)

**Priority**: LOW  
**Description**: Brand-name products, proprietary formulations  
**Mappability**: Low - requires MSDS lookup

**Examples**:
- Bacto Middlebrook 7H10 agar
- Bacto Soytone
- Marine agar 2216

**Approach**: Contact manufacturers, review MSDS/specification sheets

---

### 9. Incomplete Formulas - 1 ingredient (0.3%)

**Priority**: LOW  
**Description**: Chemical formulas missing subscripts  
**Mappability**: Low - check source data

**Example**: KF (potassium fluoride - actually has CAS-RN, may be data issue)

---

## Priority Guide

### HIGH Priority (99 ingredients, 27.0%)

**Definition**: Best candidates for automated or semi-automated resolution  
**Category**: Hydrated Salts (x notation)  
**Approach**: Develop Phase 7 preprocessing script  
**Effort**: 2-4 hours development  
**Expected gain**: 50-80 CAS-RN

**Recommendation**: Start here if pursuing additional coverage

---

### MEDIUM Priority (196 ingredients, 53.4%)

**Definition**: May benefit from manual curation  
**Categories**: Other/Uncategorized, Abbreviations, Complex Notation  
**Approach**: Manual lookup in chemical databases  
**Effort**: 10-20 hours manual work  
**Expected gain**: 100-150 CAS-RN

**Recommendation**: 
1. Focus on high-frequency ingredients (used in >10 media)
2. Prioritize ingredients with ChEBI IDs (easier lookup)
3. Stop when marginal value diminishes

---

### LOW Priority (4 ingredients, 1.1%)

**Definition**: Low value for effort required  
**Categories**: Commercial Products, Incomplete Formulas  
**Approach**: MSDS review, source data correction  
**Effort**: 2-5 hours  
**Expected gain**: 2-4 CAS-RN

**Recommendation**: Only pursue if specific products are critical

---

### UNMAPPABLE (68 ingredients, 18.5%)

**Definition**: No single CAS-RN exists by nature  
**Categories**: Stock Solutions/Mixtures, Natural Products, Placeholders/Errors  
**Approach**: Document as unmappable, do not pursue  
**Expected gain**: 0 CAS-RN

**Recommendation**: Skip - inherently unmappable

---

## Usage Workflows

### Workflow 1: Phase 7 "x" Notation Preprocessing (2-4 hours)

**Target**: 99 HIGH priority hydrated salts

**Steps**:
1. Filter TSV: `grep "^HIGH" UNMAPPED_CAS_RN_INGREDIENTS.tsv`
2. Extract unique compound formulas (before "x")
3. Build formula → chemical name mapping table
4. Develop preprocessing script to convert "x" notation
5. Re-query PubChem/CACTUS with converted names
6. Update MediaIngredientMech with results

**Expected**: 50-80 CAS-RN added (5-7% additional coverage)

---

### Workflow 2: Manual Curation (10-20 hours)

**Target**: 196 MEDIUM priority ingredients

**Steps**:
1. Filter TSV: `grep "^MEDIUM" UNMAPPED_CAS_RN_INGREDIENTS.tsv`
2. Filter for ChEBI IDs: `awk -F'\t' '$8=="True"'`
3. Sort by synonym_count (more synonyms = easier to find)
4. Manual lookup:
   - ChEBI web interface: https://www.ebi.ac.uk/chebi/
   - PubChem web search: https://pubchem.ncbi.nlm.nih.gov/
   - CAS Common Chemistry: https://commonchemistry.cas.org/
5. Create manual_cas_rn_mappings.csv
6. Import with provenance: "Manual curation from ChEBI/PubChem"

**Expected**: 100-150 CAS-RN added (9-13% additional coverage)

---

### Workflow 3: Focus on High-Frequency Ingredients

**Target**: Ingredients used in many media recipes

**Steps**:
1. Cross-reference with CultureMech usage frequency
2. Identify ingredients appearing in >10 media
3. Prioritize manual lookup for these
4. Document as "High-priority for manual curation"

**Rationale**: Maximizes impact per hour of manual work

---

### Workflow 4: Export Subsets

```bash
# HIGH priority only
grep "^HIGH" UNMAPPED_CAS_RN_INGREDIENTS.tsv > high_priority_cas_rn.tsv

# MEDIUM priority with ChEBI IDs
awk -F'\t' '$1=="MEDIUM" && $8=="True"' UNMAPPED_CAS_RN_INGREDIENTS.tsv > medium_with_chebi.tsv

# Hydrated salts only
grep "Hydrated Salts" UNMAPPED_CAS_RN_INGREDIENTS.tsv > hydrated_salts_x_notation.tsv

# Other/Uncategorized with ChEBI
awk -F'\t' '$2=="Other/Uncategorized" && $8=="True"' UNMAPPED_CAS_RN_INGREDIENTS.tsv > other_with_chebi.tsv
```

---

## Statistics

### Coverage Analysis

| Status | Count | Percentage |
|--------|-------|------------|
| **Has CAS-RN** | 746 | 67.0% |
| **Lacks CAS-RN** | 367 | 33.0% |
| **Total** | 1,113 | 100% |

### Unmapped Breakdown

| Priority | Count | % of Unmapped | Potential Gain |
|----------|-------|---------------|----------------|
| HIGH | 99 | 27.0% | 50-80 (Phase 7) |
| MEDIUM | 196 | 53.4% | 100-150 (manual) |
| LOW | 4 | 1.1% | 2-4 |
| UNMAPPABLE | 68 | 18.5% | 0 |

### ChEBI Coverage

- **With ChEBI IDs**: 268/367 (73.0%)
- **Without ChEBI IDs**: 99/367 (27.0%)

Ingredients with ChEBI IDs are easier to curate manually (authoritative source for lookup).

---

## Realistic Coverage Projections

| Approach | Additional CAS-RN | New Coverage | Effort |
|----------|-------------------|--------------|--------|
| **Current (Phase 1-6)** | 746 | 67.0% | ✅ Complete |
| **+ Phase 7 (x notation)** | 50-80 | 72-74% | 2-4 hours |
| **+ Manual curation (selective)** | 100-150 | 78-81% | 10-20 hours |
| **+ Commercial MSDS** | 2-4 | 80-83% | 2-5 hours |
| **Absolute maximum** | ~200 | ~85% | 15-30 hours |

**Remaining 15% (170 ingredients)** are inherently unmappable (stock solutions, natural products, placeholders).

---

## Recommendations

### For 70-75% Coverage (Moderate Effort)

**Approach**: Phase 7 preprocessing only  
**Effort**: 2-4 hours development  
**Gain**: +50-80 CAS-RN (5-7%)  
**Target category**: Hydrated Salts (x notation)

**Steps**:
1. Extract 99 HIGH priority ingredients
2. Develop "x" notation → hydrate name conversion
3. Re-query PubChem/CACTUS with converted names
4. Update MediaIngredientMech

---

### For 75-80% Coverage (Significant Effort)

**Approach**: Phase 7 + selective manual curation  
**Effort**: 12-24 hours total  
**Gain**: +150-230 CAS-RN (14-21%)  
**Target categories**: HIGH + high-frequency MEDIUM

**Steps**:
1. Complete Phase 7 (hydrated salts)
2. Filter MEDIUM priority by:
   - Has ChEBI ID (easier lookup)
   - High synonym count (more search options)
   - High media frequency (max impact)
3. Manual lookup top 50-100 ingredients
4. Stop when marginal value < effort

---

### Current Recommendation (Accept 67%)

**Rationale**:
- 67% exceeds initial 60-70% target
- 746 ingredients have authoritative CAS-RN
- Remaining 367 are documented and categorized
- Further work has diminishing returns

**Use TSV for**:
- Documentation of unmappable ingredients
- Future reference if specific ingredients become critical
- Potential Phase 7+ development if needed

---

## Regenerating TSV

If MediaIngredientMech is updated:

```bash
cd ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw

# Regenerate TSV
python scripts/export_unmapped_cas_rn_tsv.py \
    --mim ~/Documents/.../MediaIngredientMech \
    --output workspace/unmapped_cas_rn_ingredients.tsv

# Copy to project root
cp workspace/unmapped_cas_rn_ingredients.tsv UNMAPPED_CAS_RN_INGREDIENTS.tsv
```

---

## Related Documents

- **CAS_RN_INTEGRATION_COMPLETE.md** - Complete project documentation
- **PHASE_6_RESULTS.md** - Phase 6 testing analysis
- **UNMAPPED_CAS_RN_ANALYSIS.md** - Detailed unmappable categories analysis
- **scripts/export_unmapped_cas_rn_tsv.py** - TSV generation script
- **scripts/analyze_unmapped_cas_rn.py** - Category analysis tool

---

**Generated**: 2026-04-06  
**Author**: Claude Opus 4.6  
**TSV File**: UNMAPPED_CAS_RN_INGREDIENTS.tsv (368 rows)  
**Status**: Complete and ready for manual curation workflows
