# Phase 2 Pilot Test - Next Steps

**Date**: March 20, 2026
**Status**: Step 1 (Dry-Run) ✅ Complete | Step 2 (Verification) ✅ Complete | Step 3 (Actual Run) ⏳ Ready

---

## Current Status

✅ **Infrastructure Complete**:
- Multi-Claude coordination system operational
- Lock manager working correctly
- Status tracking functional
- Pipeline orchestration ready
- Dry-run test successful

---

## Issue Identified

The Phase 2 test plan (PHASE2_PILOT_TEST.md) specifies testing with **11 ingredients from KM2 Cell-Free Medium**:

**High Priority (Mappable)**:
1. Na2HPO4·12H2O - Expected: CHEBI:86155
2. azlocillin - Expected: CHEBI:2955
3. flucloxacillin - Expected: CHEBI:5114

**Complex**:
4. Brain Heart Infusion (BHI)
5. PPLO (Pleuropneumonia-like organisms broth)
6. Pig serum
7. Horse serum

**Solutions**:
8-11. NaOH solutions, antibiotic solutions

**However**: MediaIngredientMech currently has **17 different unmapped ingredients**, primarily:
- Commercial products (Bacto Soytone, 32 occurrences)
- Proteins (Casein, 13 occurrences; Catalase, 26 occurrences)
- These were *previously mapped* but unmapped during quality reviews

The KM2 ingredients are NOT in MediaIngredientMech's current unmapped list, likely because:
- Last import from CultureMech was ~11 days ago (March 9)
- KM2 ingredients may have been added more recently
- Or they need to be explicitly extracted and imported

---

## Options for Completing Pilot Test

### Option A: Test with Existing 17 Unmapped Ingredients ⚠️

**Pros**:
- Ready to run immediately
- Tests the curation pipeline end-to-end
- Real-world test case (complex ingredients)

**Cons**:
- Complex commercial products and proteins
- Low expected auto-acceptance rate (30-50%)
- May require extensive manual review
- High cost for limited success ($0.50-$1.00 for 30-50% acceptance)
- Not testing with the specific ingredients from the test plan

**Command**:
```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
.venv/bin/python run_pilot_test.py \
  --batch-size 5 \
  --auto-accept-threshold 0.9
```

### Option B: Import Latest from CultureMech First ✅ (Recommended)

**Workflow**:
1. Run `just import-data` in MediaIngredientMech to get latest ingredients
2. Check if KM2 ingredients appear in unmapped list
3. Run curation on small batch (3-5 ingredients)
4. Evaluate results

**Pros**:
- Gets latest data from CultureMech
- May include the KM2 ingredients we want to test
- More aligned with original test plan
- Better chance of testing mappable chemicals

**Cons**:
- Import step adds time (~5 minutes)
- Import may change existing data
- Still no guarantee KM2 ingredients are unmapped

**Commands**:
```bash
# Step 1: Import latest from CultureMech
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech
just import-data

# Step 2: Check what's unmapped now
head -100 data/curated/unmapped_ingredients.yaml

# Step 3: Run curation with orchestration
cd ../culturebotai-claw
.venv/bin/python run_pilot_test.py \
  --batch-size 5 \
  --auto-accept-threshold 0.9
```

### Option C: Manual Extraction of KM2 Ingredients

**Workflow**:
1. Read KM2 medium file from CultureMech
2. Extract the 11 unmapped ingredients
3. Create a focused import for just those ingredients
4. Run curation on that batch

**Pros**:
- Tests exactly what the test plan specifies
- High expected auto-acceptance (simple chemicals)
- Best demonstration of the system

**Cons**:
- Requires custom extraction script
- More development work
- Outside scope of "orchestration-only" mode

### Option D: Update Test Plan to Match Reality

**Workflow**:
1. Update PHASE2_PILOT_TEST.md to reflect actual available ingredients
2. Run test with existing 17 unmapped ingredients
3. Document that KM2 ingredients are not currently unmapped

**Pros**:
- Realistic test
- No additional prep work
- Tests actual use case

**Cons**:
- Deviates from original test plan
- Lower success metrics

---

## Recommendation

**Choose Option B**: Import latest data, then run small batch curation

**Rationale**:
1. Dry-run successful ✅
2. Infrastructure proven ✅
3. Import step is safe (non-destructive)
4. Gets us closest to original test plan
5. Can assess actual available ingredients after import
6. Conservative batch size (5) limits cost

**Timeline**:
- Import data: ~5 minutes
- Check unmapped list: ~1 minute
- Run curation (batch_size=5): ~5-10 minutes
- Review results: ~10 minutes
- **Total**: ~25 minutes

**Expected Cost**: $0.30-$0.50

**Risk**: Low (backups available, dry-run successful)

---

## Alternative: Minimal Test First

If you want to minimize risk, run a **single-ingredient test** first:

```bash
.venv/bin/python run_pilot_test.py \
  --batch-size 1 \
  --auto-accept-threshold 0.9
```

**Benefits**:
- Ultra-low cost (~$0.05-$0.10)
- Ultra-fast (~2 minutes)
- Validates full live pipeline
- Can scale up after success

---

## Lock Coordination Test

To test multi-Claude coordination (optional):

**Terminal 1**:
```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
.venv/bin/python run_pilot_test.py --batch-size 3
# This will hold lock for ~5 minutes
```

**Terminal 2** (while running):
```bash
# Check lock exists
ls /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace/locks/

# View lock details
cat /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace/locks/mediaingredientmech.lock

# Try to run check_lock.py manually
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
python scripts/check_lock.py mediaingredientmech "test operation"
# Should return exit code 1 (blocked)
```

Expected: Lock blocks concurrent operations ✅

---

## Summary

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| A: Test existing 17 | Ready now | Complex ingredients, low acceptance | ⚠️ Fallback |
| B: Import then test | Latest data, aligned with plan | Adds import step | ✅ Recommended |
| C: Manual extract | Tests exact plan | Requires custom work | ❌ Out of scope |
| D: Update plan | Realistic | Deviates from plan | ⚠️ Fallback |

**Recommended**: **Option B** - Import latest data from CultureMech, then run small batch (5 ingredients)

---

## Next Commands

### To proceed with Option B (Recommended):

```bash
# 1. Import latest from CultureMech
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech
just import-data

# 2. Check what unmapped ingredients are now available
head -100 data/curated/unmapped_ingredients.yaml | grep -A 3 "preferred_term:"

# 3. Run pilot test with small batch
cd ../culturebotai-claw
.venv/bin/python run_pilot_test.py \
  --batch-size 5 \
  --auto-accept-threshold 0.9

# 4. Review results
cat workspace/reports/pilot_tests/pilot_test_*.yaml | tail -20
```

### To proceed with Option A (Test existing immediately):

```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
.venv/bin/python run_pilot_test.py \
  --batch-size 5 \
  --auto-accept-threshold 0.9
```

### To proceed with minimal test first:

```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
.venv/bin/python run_pilot_test.py \
  --batch-size 1 \
  --auto-accept-threshold 0.9
```

---

**Decision point**: Choose option and execute corresponding commands.

**Status**: ⏳ Awaiting next action - pilot test infrastructure ready and validated.
