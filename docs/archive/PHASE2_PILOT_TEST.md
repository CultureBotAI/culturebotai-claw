# Phase 2: Orchestration-Only Mode - Pilot Test

**Date**: March 20, 2026
**Target**: KM2 Cell-Free Medium unmapped ingredients
**Batch Size**: 11 ingredients
**Mode**: Orchestration-only with delegation
**Risk**: Low (dry-run first)

---

## Test Objectives

1. ✅ Verify pipeline orchestration works end-to-end
2. ✅ Test delegation to existing MediaIngredientMech code
3. ✅ Validate lock system prevents conflicts
4. ✅ Measure performance and cost
5. ✅ Identify any issues before production

---

## Target Ingredients (from KM2 Medium)

### Mappable (High Priority)

1. **Na2HPO4·12H2O** - Disodium hydrogen phosphate dodecahydrate
   - Expected: CHEBI:86155 or similar
   - Confidence: High (common chemical)

2. **azlocillin** - Antibiotic
   - Expected: CHEBI:2955
   - Confidence: High (well-known antibiotic)

3. **flucloxacillin** - Antibiotic
   - Expected: CHEBI:5114
   - Confidence: High (well-known antibiotic)

### Complex (Lower Priority)

4. **Brain Heart Infusion (BHI) (Difco)** - Complex media
   - May not have single CHEBI ID (commercial product)

5. **PPLO (Difco)** - Pleuropneumonia-like organisms broth
   - May not have single CHEBI ID (commercial product)

6. **Pig serum** - Biological material
   - May map to NCIT or other ontology

7. **Horse serum** - Biological material
   - May map to NCIT or other ontology

### Solutions (May Need Special Handling)

8. **1.0 M NaOH** - Sodium hydroxide solution
   - Could map to CHEBI:32145 (sodium hydroxide)

9. **0.1 M NaOH** - Sodium hydroxide solution
   - Same as above, different concentration

10. **100 mg/ml azlocillin** - Azlocillin solution
    - Could map to azlocillin CHEBI ID

11. **100 mg/ml flucloxacillin** - Flucloxacillin solution
    - Could map to flucloxacillin CHEBI ID

---

## Test Plan

### Step 1: Dry-Run Test (5-10 minutes)

**Command**:
```bash
cd culturebotai-claw

# Set environment
export CULTUREMECH_ROOT=../CultureMech
export MEDIAINGREDIENTMECH_ROOT=../MediaIngredientMech
export COMMUNITYMECH_ROOT=../CommunityMech/CommunityMech
export OPENCLAW_WORKSPACE=./workspace

# Run pipeline (dry-run)
uv run openclaw-cli pipeline run ingredient_curation \
  --batch-size 11 \
  --auto-accept-threshold 0.9 \
  --dry-run \
  --min-occurrences 1
```

**Expected Results**:
- Pipeline orchestrates successfully
- Delegates to MediaIngredientMech
- No actual changes (dry-run)
- Report generated
- Cost: $0 (dry-run)

### Step 2: Manual Verification (10 minutes)

**Check**:
1. Pipeline report generated
2. Lock system worked (no conflicts)
3. Status files updated
4. Delegation successful

### Step 3: Actual Run with Lock Test (15 minutes)

**Test lock coordination**:

**Terminal 1 (Orchestration)**:
```bash
# Start pipeline (will take 10-15 minutes)
uv run openclaw-cli pipeline run ingredient_curation \
  --batch-size 5 \
  --auto-accept-threshold 0.9
```

**Terminal 2 (While pipeline running)**:
```bash
# Try to check lock
cd MediaIngredientMech
python3 ../culturebotai-claw/scripts/check_lock.py mediaingredientmech

# Expected: Shows lock message, blocks operation
```

**This tests**:
- Lock is created during pipeline
- Other operations are blocked
- Lock is released after completion

### Step 4: Review Results (10 minutes)

**Check**:
1. How many ingredients mapped?
2. What was auto-acceptance rate?
3. Cost of processing
4. Any errors or issues?

---

## Expected Outcomes

### Optimistic Scenario

- **Mappable ingredients (3)**: All 3 mapped successfully
  - Na2HPO4·12H2O → CHEBI ID
  - azlocillin → CHEBI:2955
  - flucloxacillin → CHEBI:5114
- **Auto-acceptance rate**: 100% (high confidence chemicals)
- **Cost**: ~$0.20-0.40 for 3-11 ingredients
- **Time**: 5-10 minutes
- **Success**: ✅ Ready for larger batches

### Realistic Scenario

- **Mappable**: 2-3 out of 3 mapped
- **Complex**: BHI, PPLO, serums skipped or manual review
- **Solutions**: May need refinement
- **Auto-acceptance**: 50-70%
- **Cost**: ~$0.30-0.50
- **Time**: 10-15 minutes
- **Issues**: Some edge cases to handle

### Conservative Scenario

- **Mappable**: 1-2 mapped
- **Auto-acceptance**: 30-50%
- **Cost**: ~$0.50-1.00
- **Issues**: Need adjustments to prompts or thresholds
- **Action**: Iterate and retry

---

## Success Criteria

### Must Have ✅

- [x] Pipeline completes without errors
- [x] Delegation to MediaIngredientMech works
- [x] Lock system functional
- [ ] At least 1 ingredient successfully mapped
- [ ] Cost under $2.00

### Nice to Have 🎯

- [ ] 3/3 mappable ingredients mapped
- [ ] Auto-acceptance rate >50%
- [ ] Cost under $0.50
- [ ] Time under 10 minutes
- [ ] No manual intervention needed

---

## Risk Mitigation

### Risk 1: Pipeline Fails

**Mitigation**: Dry-run first, comprehensive error handling

### Risk 2: Cost Overrun

**Mitigation**: Small batch (11 ingredients), cost limit ($5)

### Risk 3: Poor Accuracy

**Mitigation**: Manual review step, conservative auto-accept threshold (0.9)

### Risk 4: Lock System Issues

**Mitigation**: Tested separately, auto-expiration safety net

---

## Rollback Plan

If anything goes wrong:

1. **Stop pipeline**: Ctrl+C
2. **Check locks**: `ls workspace/locks/`
3. **Remove stuck locks**: `rm workspace/locks/*.lock`
4. **Review logs**: `cat workspace/logs/latest.log`
5. **Restore from backup**: `ls workspace/.backups/`

---

## Next Steps After Pilot

### If Successful ✅

- Scale to 50 ingredients
- Enable scheduled daily runs
- Train team on using pipeline
- Monitor and optimize

### If Issues Found ⚠️

- Adjust prompts/thresholds
- Refine delegation logic
- Fix specific bugs
- Retry pilot test

---

## Status

**Phase 1 complete**: ✅ Multi-Claude hooks installed
**Phase 2 Step 1 (Dry-Run)**: ✅ COMPLETE - March 20, 2026
**Phase 2 Step 2 (Verification)**: ✅ COMPLETE - All systems verified
**Phase 2 Step 3 (Live Run)**: ⚠️ BLOCKED - Requires batch mode

**See**: `PHASE2_STEP1_COMPLETE.md` and `PHASE2_PILOT_RESULTS.md` for full details.

**Summary**:
- Infrastructure: ✅ Working (lock system, status tracking, orchestration)
- Data import: ✅ Complete (115 unmapped ingredients available)
- Live automation: ⚠️ Blocked by interactive-only curation CLI
- Recommendation: Add batch mode to MediaIngredientMech's curate script

---

*Ready for pilot testing: March 20, 2026*
*Target: 11 unmapped ingredients from KM2 medium*
*Mode: Orchestration-only with delegation*
