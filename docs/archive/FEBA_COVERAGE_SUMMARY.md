# FEBA Ingredients Coverage Summary

**Date**: 2026-04-06  
**Total FEBA Media**: 380 formulations  
**Total Unique FEBA Ingredients**: 347

---

## Coverage Comparison

| Metric | With Coverage | Without Coverage | Percentage |
|--------|---------------|------------------|------------|
| **Ontology Term ID** (CHEBI/FOODON/etc.) | 164 | 183 | **47.3%** |
| **CAS Registry Number** | 311 | 36 | **89.6%** |

---

## Key Findings

### 1. CAS-RN Coverage is Much Higher (89.6%)

**311/347 ingredients (89.6%)** have CAS Registry Numbers

**Sources**:
- CultureMech media files: 224 (64.6%)
- MediaIngredientMech database: 132 (38.0%)
- Notation variant mapping: +39
- Resolvable resolution: +8

**Why higher**: CAS-RN is easier to obtain from chemical databases (PubChem, CACTUS) using compound names, even without formal ontology mappings.

---

### 2. Ontology Coverage is Lower (47.3%)

**164/347 ingredients (47.3%)** have ontology term IDs in CultureMech media files

**By Ontology Source**:
- **CHEBI**: 153 (93.3% of mapped) - Chemical Entities of Biological Interest
- **FOODON**: 10 (6.1% of mapped) - Food Ontology
- **UBERON**: 1 (0.6% of mapped) - Uber-anatomy ontology

**Why lower**: Ontology mapping requires manual curation or high-confidence automated matching to structured ontologies. Many ingredients have CAS-RN but lack formal ontology term assignments.

---

## Gap Analysis

### Ingredients with CAS-RN but No Ontology ID

**147 ingredients (42.4%)** have CAS-RN but no ontology term ID

**Examples**:
- 4-Aminobenzoic acid (CAS: 150-13-0) - No CHEBI ID assigned
- 3-(N-morpholino)propanesulfonic acid (CAS: 1132-61-2) - No CHEBI ID
- Gases: #N2, #Ar, #N2O - Have CAS-RN, missing ontology IDs

**Reason**: These ingredients were found in CAS databases but haven't been mapped to CHEBI/FOODON terms in the CultureMech files.

---

### Ingredients with Ontology ID but No CAS-RN

**0 ingredients** - All 164 ingredients with ontology IDs also have CAS-RN

**Finding**: This suggests good ontology→CAS-RN conversion, likely because:
- CHEBI and FOODON often include CAS-RN references
- Ontology-mapped ingredients are well-characterized compounds
- Previous CAS-RN integration phases successfully enriched ontology-mapped ingredients

---

### Ingredients with Neither

**36 ingredients (10.4%)** have neither ontology ID nor CAS-RN

**Categories**:
- Complex biological materials: Beef extract, Peptone, Casitone (15 ingredients)
- Resolvable but not yet mapped: Difficult hydrated salts, ambiguous compounds (21 ingredients)

**Status**: These are the same 36 ingredients identified in `FEBA_UNCOVERED_INGREDIENTS.tsv`

---

## Examples by Coverage Status

### ✅ Full Coverage (Ontology + CAS-RN) - 164 ingredients

```
Ingredient                 | Ontology ID    | CAS-RN      
---------------------------|----------------|-------------
Acetic Acid               | CHEBI:15366    | 64-19-7     
Agar                      | CHEBI:2509     | 9002-18-0   
Ammonium Chloride         | CHEBI:31206    | 12125-02-9  
D-Glucose                 | CHEBI:42758    | 50-99-7     
Sodium chloride           | CHEBI:26710    | 7647-14-5   
```

---

### ⚠️ CAS-RN Only (No Ontology) - 147 ingredients

```
Ingredient                           | CAS-RN      | Ontology
-------------------------------------|-------------|----------
4-Aminobenzoic acid                 | 150-13-0    | Missing
#N2 (nitrogen)                      | 7727-37-9   | Missing
#Ar (argon)                         | 7440-37-1   | Missing
magnesium chloride hexahydrate      | 616-575-1   | Missing
pyridoxine HCl                      | 58-56-0     | Missing
```

---

### ❌ No Coverage - 36 ingredients

```
Ingredient                      | CAS-RN  | Ontology
--------------------------------|---------|----------
Beef extract                   | None    | None
Peptone                        | None    | None
Casitone                       | None    | None
Iron(III) chloride hexahydrate | None    | None
manganese(II) sulfate dihydrate| None    | None
```

---

## Recommendations

### 1. Enrich Ontology Mappings (Priority: HIGH)

**Target**: 147 ingredients with CAS-RN but no ontology ID

**Approach**:
- Use CAS-RN to lookup CHEBI IDs via ChEBI web services
- Use PubChem compound IDs to find CHEBI cross-references
- Manual curation for high-frequency ingredients (used in >10 media)

**Expected gain**: +100-120 ontology mappings → 75-80% ontology coverage

**Example workflow**:
```python
# For each ingredient with CAS-RN but no ontology ID:
# 1. Query ChEBI API with CAS-RN
# 2. If found, add term.id and term.label to media files
# 3. Update MediaIngredientMech with ontology mapping
```

---

### 2. Accept Current CAS-RN Coverage (89.6%)

**Recommendation**: Current CAS-RN coverage (89.6%) is excellent

**Reason**:
- Exceeds typical chemical database coverage (60-70%)
- Remaining 36 are either unmappable (15) or require manual effort (21)
- Further gains diminishing returns

---

### 3. Document Unmappable Ingredients

**Target**: 15 complex biological materials, 2 media components

**Action**: Add metadata to indicate inherent unmappability
```yaml
data_quality_flags:
  - has_unmapped_ingredients
  - complex_biological_material  # New flag
  - no_single_cas_rn_exists      # New flag
```

---

## Priority Actions

### High Priority: Enrich Ontology Mappings

**Steps**:
1. Extract 147 ingredients with CAS-RN but no ontology ID
2. Query ChEBI API using CAS-RN
3. Add CHEBI IDs to CultureMech media files
4. Update MediaIngredientMech ontology mappings
5. Remove `has_unmapped_ingredients` flag from resolved media

**Estimated effort**: 4-6 hours (mostly automated with manual verification)  
**Expected outcome**: 75-80% ontology coverage for FEBA ingredients

---

### Medium Priority: Complete CAS-RN Coverage

**Steps**:
1. Manual lookup for 3 RESOLVABLE_HIGH ingredients
2. Resolve difficult hydrated salts (Iron(III) chloride hexahydrate, etc.)
3. Update with CAS-RN

**Estimated effort**: 1-2 hours manual work  
**Expected outcome**: 91-92% CAS-RN coverage

---

### Low Priority: Document Unmappables

**Steps**:
1. Add data quality flags for 15 complex biological materials
2. Document in media YAML files why unmappable
3. Create reference documentation

**Estimated effort**: 1 hour  
**Expected outcome**: Clear documentation of unmappable ingredients

---

## Summary Statistics

| Metric | Count | Percentage |
|--------|-------|------------|
| **Total FEBA ingredients** | 347 | 100% |
| **Full coverage** (Ontology + CAS-RN) | 164 | 47.3% |
| **CAS-RN only** | 147 | 42.4% |
| **Ontology only** | 0 | 0% |
| **No coverage** | 36 | 10.4% |

---

## Comparison to Overall Project

| Repository | Ontology Coverage | CAS-RN Coverage |
|------------|-------------------|-----------------|
| **FEBA ingredients** | 47.3% (164/347) | 89.6% (311/347) |
| **All MediaIngredientMech** | ~100% (1,113/1,113) | 67.0% (746/1,113) |

**Note**: MediaIngredientMech shows ~100% ontology mapping because the database only tracks ingredients that have been curated and mapped. FEBA media files in CultureMech may reference ingredients not yet in MediaIngredientMech.

---

## Files Generated

- **workspace/feba_ontology_coverage_report.yaml** - Detailed analysis
- **workspace/feba_ontology_unmapped_ingredients.txt** - 183 ingredients without ontology IDs
- **FEBA_COVERAGE_SUMMARY.md** - This document

---

## Next Steps

**If you want to improve ontology coverage**:
1. Run ChEBI enrichment script (to be created)
2. Query ChEBI API for 147 ingredients with CAS-RN
3. Update CultureMech media files with CHEBI IDs
4. Target: 75-80% ontology coverage

**If you want to focus on CAS-RN**:
1. Manual lookup for 3 remaining RESOLVABLE_HIGH
2. Target: 91-92% CAS-RN coverage

**Current recommendation**: Accept current coverage levels (47% ontology, 90% CAS-RN) as both are substantial for research purposes.

---

**Generated**: 2026-04-06  
**Author**: Claude Opus 4.6  
**Related**: FEBA_CAS_RN_MAPPING_COMPLETE.md
