# Collection Media Validation Strategy

**Date**: 2026-04-03  
**Status**: Full validation in progress (5,112 media)

---

## Discovery: Severe Data Quality Issues

### Sample Validation Results (100 media)

| Category | Count | Percentage |
|----------|-------|------------|
| **Valid media** | 2 | 2.0% |
| **References to other media** | 47 | 47.0% |
| **Not found** | 19 | 19.0% |
| **No composition table** | 32 | 32.0% |

### Key Findings

1. ✅ **CCAP PDFs are reliable** (2/2 validated successfully)
2. ❌ **JCM media have severe quality issues**:
   - Nearly half are references ("Use Medium No. X")
   - ~20% don't exist ("Nothing found")
   - ~30% exist but have no composition data

3. **Root cause**: The `identified_media.yaml` list was generated automatically and includes many invalid entries

---

## Projected Full Validation Results

**Extrapolating from 100-media sample**:

| Category | Expected Count (of 5,112) | Percentage |
|----------|---------------------------|------------|
| **Directly valid** | ~100 | 2% |
| **References (resolvable)** | ~2,400 | 47% |
| **Not found** | ~970 | 19% |
| **No composition** | ~1,640 | 32% |

**Potential after reference resolution**: ~2,500 valid media (100 direct + 2,400 resolved)

---

## Three-Phase Strategy

### Phase 1: Use Directly Valid Media ✅

**Goal**: Immediate pilot with high-quality data

**Actions**:
1. ✅ Extract ~100 directly valid media from full validation
2. ✅ Run pilot with these media
3. ✅ Expected success rate: >90% (mostly CCAP PDFs)
4. ✅ Complete end-to-end pipeline testing

**Timeline**: 1 hour  
**Expected cost**: <$5

### Phase 2: Resolve References 🔄

**Goal**: Expand dataset by resolving "Use Medium No. X" references

**Actions**:
1. ✅ Use `resolve_media_references.py` script (created)
2. 🔄 Resolve ~2,400 reference media
3. 🔄 Fetch base media + apply modifications
4. 🔄 Add resolved media to valid list
5. 🔄 Run pilot with combined dataset

**Timeline**: 2-3 hours (includes fetch time)  
**Expected cost**: ~$20-30

### Phase 3: Full Deployment 🚀

**Goal**: Process all valid + resolved media

**Actions**:
1. 🚀 Combine directly valid (~100) + resolved (~2,400) = ~2,500 media
2. 🚀 Run full curation pipeline
3. 🚀 Expected to curate ~2,000-2,500 media (vs original 5,112)
4. 🚀 Update CultureMech with curated ingredients

**Timeline**: 5-10 hours compute time  
**Expected cost**: $500-750

---

## Implementation Steps (After Validation Completes)

### Step 1: Extract Valid Media

```bash
# Parse validation results
python scripts/extract_valid_media.py \
    --input workspace/commercial_expansions/validated_media_complete.yaml \
    --output workspace/commercial_expansions/valid_media_only.yaml
```

### Step 2: Run Pilot with Valid Media

```bash
# Use only validated media
python scripts/batch_process_collection_media.py \
    --batch-id pilot_002_valid \
    --offset 0 \
    --batch-size 50 \
    --auto-accept-threshold 0.9 \
    --max-cost 10.0 \
    --input workspace/commercial_expansions/valid_media_only.yaml
```

**Expected outcome**: >90% success rate (vs 2% in pilot_001)

### Step 3: Resolve References (Sample)

```bash
# Test reference resolution on 20 references
python scripts/resolve_media_references.py \
    --input workspace/commercial_expansions/validated_media_complete.yaml \
    --output workspace/commercial_expansions/resolved_sample.yaml \
    --max-resolve 20 \
    --rate-limit 1.0
```

### Step 4: Resolve All References

```bash
# Resolve all ~2,400 references
python scripts/resolve_media_references.py \
    --input workspace/commercial_expansions/validated_media_complete.yaml \
    --output workspace/commercial_expansions/resolved_all.yaml \
    --max-resolve 2400 \
    --rate-limit 0.5
```

**Timeline**: ~20-40 minutes

### Step 5: Combine and Re-run Pilot

```bash
# Combine valid + resolved media
python scripts/combine_media_lists.py \
    --valid workspace/commercial_expansions/valid_media_only.yaml \
    --resolved workspace/commercial_expansions/resolved_all.yaml \
    --output workspace/commercial_expansions/combined_valid_media.yaml

# Run pilot with combined list
python scripts/batch_process_collection_media.py \
    --batch-id pilot_003_combined \
    --offset 0 \
    --batch-size 100 \
    --auto-accept-threshold 0.9 \
    --max-cost 20.0 \
    --input workspace/commercial_expansions/combined_valid_media.yaml
```

---

## Expected Outcomes by Phase

### Phase 1: Direct Valid Media
- **Input**: ~100 media
- **Fetch success**: >95%
- **Ingredients extracted**: ~2,000-3,000
- **Cost**: <$5
- **Benefit**: Validates infrastructure with clean data

### Phase 2: With References Resolved
- **Input**: ~2,500 media (100 + 2,400 resolved)
- **Fetch success**: >85%
- **Ingredients extracted**: ~50,000-75,000
- **Cost**: ~$500-750
- **Benefit**: Achieves 50% of original 5,112 media goal

### Phase 3: Full Deployment
- **Processed**: ~2,000-2,500 valid media
- **CultureMech files updated**: ~1,500-2,000
- **Ingredients mapped**: ~40,000-60,000
- **Total cost**: $500-750

---

## Alternative: Conservative Approach

If reference resolution proves unreliable:

1. **Use only directly valid media** (~100 media)
2. **Focus on CCAP PDFs** (highest quality)
3. **Manually curate high-value JCM media** (select 50-100 important media)
4. **Total processed**: ~150-200 media
5. **Cost**: <$50

**Trade-off**: Lower volume but higher quality

---

## Recommendations

### Immediate (Phase 1) ⭐
1. ✅ Wait for full validation to complete (~10 min remaining)
2. ✅ Extract directly valid media (~100 expected)
3. ✅ Run pilot with valid-only list
4. ✅ Validate >90% success rate

### Short-term (Phase 2) ⭐
1. ✅ Test reference resolution on 20 samples
2. ✅ If >80% success, resolve all ~2,400 references
3. ✅ Run pilot with combined list (valid + resolved)
4. ✅ Proceed to full deployment if successful

### Long-term (Phase 3)
1. 🚀 Full curation of ~2,500 validated media
2. 🚀 Update CultureMech with curated ingredients
3. 🚀 Document results and lessons learned
4. 🚀 Consider manual curation for remaining high-priority media

---

## Success Criteria

### Phase 1 (Valid Media Pilot)
- ✅ Fetch success >90%
- ✅ Parse success >90%
- ✅ Cost <$10
- ✅ Infrastructure validation complete

### Phase 2 (Reference Resolution)
- ✅ Resolution success >80%
- ✅ Combined pilot fetch success >85%
- ✅ Cost <$30

### Phase 3 (Full Deployment)
- ✅ Process >2,000 media
- ✅ Map >40,000 ingredients
- ✅ Update >1,500 CultureMech files
- ✅ Cost <$750

---

## Risk Mitigation

**Risk**: Reference resolution fails or has low quality

**Mitigation**:
- Test on 20 samples first
- Validate base media existence before resolution
- Compare resolved ingredients to expected patterns
- Manual spot-check 10% of resolutions
- Fall back to valid-only approach if <70% success

**Risk**: Even valid media have parsing issues

**Mitigation**:
- Already validated CCAP PDFs work (100% in sample)
- Can filter to CCAP-only if needed
- Estimated 50-100 CCAP media available

---

## Next Actions

**Waiting**: Full validation to complete (~10 minutes)

**Then**:
1. Parse validation results
2. Extract valid media list
3. Run Phase 1 pilot
4. Assess results and decide on Phase 2
5. Document findings

---

**Status**: Full validation running  
**ETA**: ~19:10 PM (10 minutes from now)  
**Current progress**: ~200/5112 media validated (estimated based on runtime)
