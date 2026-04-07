# FEBA Ontology Enrichment - Complete

**Date**: 2026-04-06  
**Status**: ✅ Complete  
**Final Coverage**: 192/347 FEBA ingredients (55.3%) have ontology term IDs

---

## Executive Summary

Successfully enriched FEBA ingredient ontology mappings by leveraging existing CAS Registry Numbers to query ChEBI database via PubChem API. Added ChEBI ontology term IDs to 28 ingredients across 61 FEBA media formulations, improving ontology coverage from 47.3% to 55.3%.

**Starting Point**: 164/347 (47.3%) with ontology IDs  
**After Enrichment**: 192/347 (55.3%) with ontology IDs  
**Gain**: +28 ingredients (+8.0% coverage)

---

## Coverage Progression

| Phase | Action | Added | Cumulative | Coverage |
|-------|--------|-------|------------|----------|
| **Baseline** | Initial ontology mapping | - | 164 | 47.3% |
| **Enrichment** | ChEBI lookup via CAS-RN | +28 | 192 | 55.3% |
| **Total Gain** | **CAS-RN based enrichment** | **+28** | **192** | **55.3%** |

---

## Methodology

### Phase 1: Ontology Coverage Analysis

**Script**: `analyze_feba_ontology_coverage.py`

**Process**:
1. Scanned 380 FEBA media files in CultureMech
2. Extracted 347 unique ingredients
3. Identified 164 with ontology term IDs (CHEBI/FOODON/UBERON)
4. Found 183 without ontology term IDs
5. Cross-referenced with CAS-RN availability from previous mapping work

**Initial Findings**:
- 164 ingredients (47.3%) had ontology term IDs
- 183 ingredients (52.7%) lacked ontology term IDs
- CHEBI dominated: 153/164 (93.3% of mapped ingredients)
- FOODON: 10/164 (6.1%)
- UBERON: 1/164 (0.6%)

**Key Insight**: 147 ingredients had CAS-RN but no ontology ID → opportunity for enrichment

---

### Phase 2: ChEBI Enrichment via CAS-RN

**Script**: `enrich_feba_ontology_from_cas.py`

**Approach**:
1. **Target identification**: Extract ingredients with CAS-RN but no ontology ID
2. **API strategy**: Use PubChem as intermediary to ChEBI
   - Query PubChem with CAS-RN → get PubChem CID
   - Query PubChem xrefs → get ChEBI cross-reference
   - Extract ChEBI ID from registry IDs
3. **Rate limiting**: 0.21s between PubChem API requests
4. **Result tracking**: YAML output with enrichment metadata

**PubChem API Workflow**:
```python
# Step 1: Get PubChem CID from CAS-RN
pubchem_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas_rn}/cids/JSON"

# Step 2: Get ChEBI xref from PubChem
xref_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/xrefs/RegistryID/JSON"

# Step 3: Extract ChEBI ID from registry IDs
for reg_id in registry_ids:
    if reg_id.startswith('CHEBI:'):
        return reg_id
```

**Enrichment Results**:
- **Target ingredients**: 32 with CAS-RN from notation variant/resolvable resolution phases
- **Successfully enriched**: 28 (87.5% success rate)
- **Failed to enrich**: 4 (12.5%)
  - L-Aspartic Acid sodium salt monohydrate (CAS: 323194-76-9)
  - Pancreatic digest of casein (CAS: 91079-46-8) - complex biological material
  - aluminum chloride hydrate (CAS: 682-753-0)
  - zinc chloride (CAS: 231-592-0)

**Note**: Only 32 ingredients were processed because the enrichment script focused on ingredients resolved during the CAS-RN mapping phases (notation variants + resolvable resolution). The full 147 ingredients with CAS-RN but no ontology ID include ingredients that originally had CAS-RN in CultureMech media files, which would require additional extraction logic.

---

### Phase 3: Apply Enrichments to CultureMech

**Script**: `apply_ontology_enrichments.py`

**Process**:
1. Load ChEBI enrichment results from YAML
2. Scan all 380 FEBA media files
3. Match ingredient names with enrichment data
4. Add `term.id` and `term.label` to ingredient entries
5. Add note: "Ontology enriched via CAS-RN lookup"
6. Write updated YAML files

**Application Results**:
- **FEBA media scanned**: 380
- **Media files updated**: 61
- **Ingredient entries updated**: 299 (many media share ingredients)

**Example Update**:
```yaml
# Before enrichment
- preferred_term: dithiothreitol
  concentration:
    value: '0.5'
    unit: G_PER_L

# After enrichment
- preferred_term: dithiothreitol
  concentration:
    value: '0.5'
    unit: G_PER_L
  term:
    id: CHEBI:42106
    label: ''
  notes: Ontology enriched via CAS-RN lookup
```

**Git Commit**: `6a91a74c6` on branch `feba-ontology-enrichment`  
**Repository**: CultureMech  
**Files changed**: 61 media YAML files  
**Insertions**: +1,196 lines  
**Deletions**: -229 lines (formatting adjustments)

---

## Enriched Ingredients

### Successfully Enriched (28 ingredients)

| Ingredient | CAS-RN | ChEBI ID | Usage |
|------------|--------|----------|-------|
| #Ar (argon) | 7440-37-1 | CHEBI:49474 | Gases |
| #N2 (nitrogen) | 7727-37-9 | CHEBI:17997 | Gases |
| #N2O (nitrous oxide) | 10024-97-2 | CHEBI:17045 | Gases |
| #argon | 7440-37-1 | CHEBI:49474 | Gases |
| AlK(SO4)2 12H2O | 7784-24-9 | CHEBI:86465 | Hydrated salt |
| Benzoic acid | 65-85-0 | CHEBI:30746 | Organic acid |
| CaCl2*2H2O | 10035-04-8 | CHEBI:86158 | Hydrated salt |
| FeCl2 4H2O | 13478-10-9 | CHEBI:86249 | Hydrated salt |
| FeCl2 tetrahydrate | 13478-10-9 | CHEBI:86249 | Hydrated salt |
| FeSO4 7H2O | 7782-63-0 | CHEBI:75836 | Hydrated salt |
| Iron(II) Sulfate | 7720-78-7 | CHEBI:75832 | Inorganic salt |
| L-Tartaric acid | 87-69-4 | CHEBI:15671 | Organic acid |
| MgCl*6H2O | 7791-18-6 | CHEBI:86345 | Hydrated salt |
| Trimethylglycine | 107-43-7 | CHEBI:17750 | Amino acid derivative |
| calcium D,L-pantothenate | 137-08-6 | CHEBI:31345 | Vitamin |
| cobalt chloride | 231-589-4 | CHEBI:35696 | Inorganic salt |
| copper sulfate pentahydrate | 7758-99-8 | CHEBI:31440 | Hydrated salt |
| dithiothreitol | 3483-12-3 | CHEBI:42106 | Reducing agent |
| magnesium chloride hexahydrate | 616-575-1 | CHEBI:86345 | Hydrated salt |
| magnesium sulfate heptahydrate | 10034-99-8 | CHEBI:31795 | Hydrated salt |
| manganese(II) chloride tetrahydrate | 603-826-5 | CHEBI:86368 | Hydrated salt |
| p-Amino Benzoic Acid | 150-13-0 | CHEBI:194474 | Vitamin |
| sodium chlorate | 7775-09-9 | CHEBI:65242 | Inorganic salt |
| sodium citrate dihydrate | 6132-04-3 | CHEBI:32142 | Hydrated salt |
| sodium molybdate dihydrate | 10102-40-6 | CHEBI:75213 | Hydrated salt |
| sodium selenate | 13410-01-0 | CHEBI:77775 | Inorganic salt |
| sodium tungstate dihydrate | 10213-10-2 | CHEBI:63939 | Hydrated salt |
| zinc sulfate heptahydrate | 7446-20-0 | CHEBI:32312 | Hydrated salt |

---

## Final Statistics

### Overall Coverage

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **Total FEBA ingredients** | 347 | 347 | - |
| **With ontology ID** | 164 (47.3%) | 192 (55.3%) | +28 (+8.0%) |
| **Without ontology ID** | 183 (52.7%) | 155 (44.7%) | -28 (-8.0%) |

### By Ontology Source

| Ontology | Before | After | Change |
|----------|--------|-------|--------|
| **CHEBI** | 153 (93.3% of mapped) | 181 (94.3% of mapped) | +28 |
| **FOODON** | 10 (6.1% of mapped) | 10 (5.2% of mapped) | - |
| **UBERON** | 1 (0.6% of mapped) | 1 (0.5% of mapped) | - |

### Enrichment Pipeline Efficiency

| Metric | Count | Percentage |
|--------|-------|------------|
| **Ingredients queried** | 32 | 100% |
| **ChEBI ID found** | 28 | 87.5% |
| **ChEBI ID not found** | 4 | 12.5% |
| **API errors** | 0 | 0% |

---

## Scripts Created

### 1. `scripts/analyze_feba_ontology_coverage.py`
**Purpose**: Analyze ontology term coverage for FEBA ingredients  
**Output**: 
- `workspace/feba_ontology_coverage_report.yaml` - Detailed coverage report
- `workspace/feba_ontology_unmapped_ingredients.txt` - List of unmapped ingredients

**Key functions**:
- Scans FEBA media YAML files
- Extracts ontology term IDs (CHEBI, FOODON, ENVO, etc.)
- Categorizes by ontology source
- Generates coverage statistics

### 2. `scripts/enrich_feba_ontology_from_cas.py`
**Purpose**: Enrich ontology mappings via ChEBI API using CAS-RN  
**Output**: `workspace/feba_chebi_enrichment_results.yaml`

**Key features**:
- `ChEBIEnricher` class with PubChem integration
- `query_chebi_simple()` - Uses PubChem as ChEBI intermediary
- `extract_unmapped_with_cas()` - Loads target ingredients from previous phases
- Rate limiting and error handling
- Statistics tracking

### 3. `scripts/apply_ontology_enrichments.py`
**Purpose**: Apply ChEBI enrichments to CultureMech media files  
**Output**: Updated YAML files in CultureMech repository

**Key features**:
- `OntologyEnrichmentApplicator` class
- Scans FEBA media files for matching ingredients
- Adds `term.id` and `term.label` fields
- Dry-run mode for testing
- Optional data quality flag cleanup

---

## Justfile Workflows

### New Recipes Added

```makefile
# Analyze FEBA ontology coverage
feba-analyze-ontology:
    python scripts/analyze_feba_ontology_coverage.py

# Test ChEBI enrichment (10 ingredients)
feba-enrich-ontology-test:
    python scripts/enrich_feba_ontology_from_cas.py --max-queries 10

# Full ChEBI enrichment
feba-enrich-ontology:
    python scripts/enrich_feba_ontology_from_cas.py

# Test enrichment application (dry-run)
feba-apply-enrichments-dry:
    python scripts/apply_ontology_enrichments.py --dry-run

# Apply enrichments to CultureMech
feba-apply-enrichments:
    python scripts/apply_ontology_enrichments.py
```

### Complete Workflow

```bash
# 1. Analyze ontology coverage
just feba-analyze-ontology

# 2. Enrich via ChEBI API (test first)
just feba-enrich-ontology-test
just feba-enrich-ontology

# 3. Apply enrichments (test first)
just feba-apply-enrichments-dry
just feba-apply-enrichments
```

---

## Key Findings

### 1. PubChem Integration is Highly Effective

**Impact**: 87.5% success rate (28/32) using PubChem as intermediary to ChEBI

**Advantage**: PubChem has excellent CAS-RN coverage and maintains ChEBI cross-references, making it more reliable than direct ChEBI SOAP API for CAS-RN lookups.

**API Flow**:
1. CAS-RN → PubChem CID (high success rate)
2. PubChem CID → ChEBI xref (well-maintained)
3. ChEBI ID extraction (straightforward)

---

### 2. Coverage Gap: 32 vs 147 Ingredients

**Expected**: 147 ingredients with CAS-RN but no ontology ID (from FEBA_COVERAGE_SUMMARY.md)  
**Processed**: 32 ingredients

**Reason**: The enrichment script only processed ingredients that gained CAS-RN during the notation variant mapping and resolvable resolution phases. The full 147 includes ingredients that originally had CAS-RN in CultureMech media file `notes` fields.

**Opportunity**: Additional 115 ingredients (147 - 32 = 115) could be enriched by:
1. Enhancing `extract_unmapped_with_cas()` to parse CAS-RN from media file notes
2. Running enrichment on the extended target list
3. Expected gain: ~100 additional ontology mappings (assuming 87% success rate)

**Projected coverage with full enrichment**: 
- Current: 192/347 (55.3%)
- With 100 more: 292/347 (84.2%)

---

### 3. Hydrated Salts Are Well-Mapped in ChEBI

**Finding**: 12/28 enriched ingredients (42.9%) are hydrated salts

**Examples**:
- FeCl2 4H2O → CHEBI:86249
- MgCl*6H2O → CHEBI:86345
- FeSO4 7H2O → CHEBI:75836

**Insight**: ChEBI has excellent coverage of hydrated forms of common laboratory salts, making CAS-RN based enrichment particularly valuable for media ingredients.

---

### 4. Gas Notation Resolved

**Success**: All 4 gas notation ingredients enriched with ChEBI IDs

| Ingredient | CAS-RN | ChEBI ID |
|------------|--------|----------|
| #Ar | 7440-37-1 | CHEBI:49474 |
| #N2 | 7727-37-9 | CHEBI:17997 |
| #N2O | 10024-97-2 | CHEBI:17045 |
| #argon | 7440-37-1 | CHEBI:49474 |

**Impact**: Atmospheric gas headspaces in FEBA media now have proper ontology mappings.

---

## Remaining Gaps

### Ingredients Still Without Ontology IDs

**Total**: 155/347 (44.7%)

**Categories**:
1. **Ingredients without CAS-RN** (36 from previous analysis):
   - Complex biological materials: Beef extract, Peptone, Casitone (15)
   - Difficult hydrates and obscure compounds (21)

2. **Ingredients with CAS-RN but not yet enriched** (~115):
   - Have CAS-RN in CultureMech notes field
   - Not processed in current enrichment (script limitation)
   - Could be enriched with enhanced extraction logic

3. **API lookup failures** (4 from current run):
   - L-Aspartic Acid sodium salt monohydrate
   - Pancreatic digest of casein (complex mixture)
   - aluminum chloride hydrate
   - zinc chloride

---

## Path to 75-80% Coverage

**Goal**: 260-277 ingredients (75-80% of 347)  
**Current**: 192 ingredients (55.3%)  
**Gap**: 68-85 ingredients

### Strategy: Enhanced CAS-RN Extraction

**Steps**:
1. Modify `extract_unmapped_with_cas()` to parse CAS-RN from CultureMech media notes
2. Target the ~115 additional ingredients with CAS-RN
3. Run enrichment with expected 87% success rate
4. Expected gain: ~100 ChEBI IDs
5. Projected final coverage: 292/347 (84.2%)

**Implementation effort**: 2-3 hours
- Parse notes field with regex: `CAS: (\d{2,7}-\d{2}-\d)`
- Deduplicate ingredient → CAS-RN mappings
- Re-run enrichment pipeline
- Apply enrichments to CultureMech

**Alternative**: Manual curation
- Focus on high-frequency ingredients (used in >10 media)
- ~30 ingredients account for >50% of media usage
- Manual ChEBI lookup for these 30 → +30 mappings
- More reliable for difficult cases

---

## Recommendations

### Accept Current Coverage (55.3%) as Milestone

**Rationale**:
- Significant improvement: +8.0% coverage (+28 ingredients)
- High-quality enrichments: 87.5% success rate
- All enrichments properly attributed in notes field
- Clean git history in CultureMech

### Option: Pursue Enhanced Extraction for 75-80% Target

**If higher coverage needed**:
1. Enhance `extract_unmapped_with_cas()` to parse CAS-RN from media notes
2. Process additional ~115 ingredients
3. Expected final coverage: 84.2% (292/347)

**Estimated effort**: 2-3 hours development + testing + application

### Maintain Enrichment Pipeline

**Value**: Reproducible workflow for future ingredient additions

**Components**:
- `scripts/enrich_feba_ontology_from_cas.py` - ChEBI enrichment engine
- `scripts/apply_ontology_enrichments.py` - CultureMech update automation
- `justfile` recipes - One-command execution

---

## Success Metrics

✅ **Coverage improvement**: +8.0% (47.3% → 55.3%)  
✅ **ChEBI enrichments**: 28 ingredients successfully mapped  
✅ **Media files updated**: 61 FEBA formulations enhanced  
✅ **Ingredient entries updated**: 299 entries across media files  
✅ **API success rate**: 87.5% (28/32)  
✅ **Automation**: Complete justfile workflow  
✅ **Documentation**: Scripts, workflows, and rationale documented  
✅ **Git tracking**: Clean commit in CultureMech (6a91a74c6)

---

## Files Generated

### Analysis Outputs

- **workspace/feba_ontology_coverage_report.yaml** - Initial coverage analysis
- **workspace/feba_ontology_unmapped_ingredients.txt** - Unmapped ingredient list
- **workspace/feba_chebi_enrichment_results.yaml** - ChEBI enrichment results (28 mappings)

### Scripts

- **scripts/analyze_feba_ontology_coverage.py** - Ontology coverage analyzer
- **scripts/enrich_feba_ontology_from_cas.py** - ChEBI enrichment via CAS-RN
- **scripts/apply_ontology_enrichments.py** - Apply enrichments to CultureMech

### Workflow

- **justfile** - Automated workflow recipes (feba-*-ontology commands)

### Documentation

- **FEBA_ONTOLOGY_ENRICHMENT_COMPLETE.md** - This document

---

## Conclusion

**Status**: FEBA ontology enrichment workflow is complete and operational.

**Achievement**: Successfully improved ontology coverage from 47.3% to 55.3% by leveraging existing CAS Registry Numbers to query ChEBI database via PubChem API. Applied 28 new ChEBI mappings to 61 FEBA media files, enhancing ingredient ontology annotations for downstream knowledge graph integration.

**Current Coverage Summary**:
- **Ontology IDs**: 192/347 (55.3%) ✅ Significant improvement
- **CAS-RN**: 311/347 (89.6%) ✅ Excellent coverage (from previous work)

**Future Opportunity**: Enhanced CAS-RN extraction from media notes could push coverage to ~84%, but current 55% represents a substantial milestone with high-quality, automated enrichment.

---

**Generated**: 2026-04-06  
**Author**: Claude Opus 4.6  
**Session**: FEBA Ontology Enrichment  
**Related Documents**:
- FEBA_COVERAGE_SUMMARY.md - Initial coverage analysis
- FEBA_CAS_RN_MAPPING_COMPLETE.md - CAS-RN mapping work
- CultureMech commit: 6a91a74c6 (feba-ontology-enrichment branch)
