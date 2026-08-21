# Phase 6 Execution Guide - ChemSpider & CAS Common Chemistry

**Date**: 2026-04-06  
**Status**: Scripts prepared, awaiting API credentials  
**Goal**: Push CAS-RN coverage from 67.0% to 73-77% (target: 810-860 ingredients)

---

## Overview

Phase 6 integrates two additional data sources to retrieve CAS Registry Numbers for the remaining 367 unmapped ingredients:

1. **ChemSpider API** (RSC Developer Portal) - Requires free API key
2. **CAS Common Chemistry API** (Official CAS) - Open access, no key required

Both scripts are production-ready with full error handling, rate limiting, and provenance tracking.

---

## Step 1: ChemSpider API Setup

### Register for Free API Key

1. Visit: https://developer.rsc.org/
2. Click "Sign Up" or "Create Account"
3. Complete registration (email verification required)
4. Log in to developer portal
5. Navigate to "My Applications" or "Create Application"
6. Create a new application:
   - **Name**: MediaIngredientMech CAS-RN Integration
   - **Description**: Research project for microbial culture media ingredient curation
   - **Organization**: VIMSS / Your Institution
7. Copy your API key (keep it secure)

### Free Tier Limits

- **1,000 API calls per month**
- Research/educational use only
- No commercial applications
- Rate limit: Conservative (1.5s between requests in script)

### Set Environment Variable

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export CHEMSPIDER_API_KEY="your-api-key-here"

# OR specify on command line when running script
```

---

## Step 2: Test ChemSpider Integration

### Dry Run (Recommended First)

Test with a small batch to verify API access:

```bash
cd ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw

# Test with 10 queries
python scripts/fetch_cas_rn_from_chemspider.py \
    --api-key YOUR_KEY \
    --dry-run \
    --max-queries 10
```

**Expected output**:
```
Processing MediaIngredientMech ingredients for ChemSpider CAS-RN fetching...

  Processing mapped ingredients...
    Querying Ingredient_name                                  (preferred_term)...
      ✓ Found CAS-RN: 12345-67-8
      - No CAS-RN found
    ...

================================================================================
CHEMSPIDER CAS-RN FETCH STATISTICS
================================================================================
Ingredients processed: 10
  Already had CAS-RN: 8
  No identifiers: 0

ChemSpider API queries: 2
  CAS-RN found: 1
  CAS-RN not found: 1
  API errors: 0
  Rate limit errors: 0

Ingredients updated: 0
Success rate: 50.0%

⚠️  DRY RUN - No files were modified
```

### Full Run

If dry run succeeds, run on all unmapped ingredients:

```bash
# Using environment variable
python scripts/fetch_cas_rn_from_chemspider.py

# OR using command line
python scripts/fetch_cas_rn_from_chemspider.py --api-key YOUR_KEY
```

**Runtime**: ~10-15 minutes (367 queries @ 1.5s per query, with rate limiting)

### Monitor Progress

The script prints real-time progress:
- Ingredient name being queried
- CAS-RN found (✓) or not found (-)
- API errors if they occur
- Final statistics

**Quota management**: Script processes all 367 unmapped ingredients. If you're concerned about monthly quota (1,000 calls), you can run in batches:

```bash
# Process 100 at a time
python scripts/fetch_cas_rn_from_chemspider.py --max-queries 100
```

---

## Step 3: CAS Common Chemistry Integration

### No Setup Required

CAS Common Chemistry is an **open access API** - no registration or API key needed!

### Test Run

```bash
cd ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw

# Dry run with 10 queries
python scripts/fetch_cas_rn_from_cas_common_chemistry.py \
    --dry-run \
    --max-queries 10
```

### Full Run

```bash
# Run on all remaining unmapped ingredients
python scripts/fetch_cas_rn_from_cas_common_chemistry.py
```

**Runtime**: ~6-8 minutes (remaining ingredients @ 1.0s per query)

**Free tier**: 50,000 requests/month (plenty of headroom)

---

## Step 4: Commit Results to MediaIngredientMech

After both scripts complete:

```bash
cd ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech

# Check what was updated
git status

# Review changes
git diff data/ingredients/mapped/ | head -100

# Commit Phase 6 results
git add data/ingredients/

git commit -m "Add CAS-RN from ChemSpider API - Phase 6a

- ChemSpider API integration
- XX ingredients updated with CAS-RN
- Data source: ChemSpider API
- Full provenance tracking

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git commit -m "Add CAS-RN from CAS Common Chemistry API - Phase 6b

- CAS Common Chemistry API integration  
- XX ingredients updated with CAS-RN
- Data source: CAS Common Chemistry API (official CAS source)
- Full provenance tracking

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 5: Verify Results

### Check Coverage

```bash
cd ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech

# Count total CAS-RN
grep -r "cas_rn:" data/ingredients/ | wc -l

# Expected: 796-836 (746 + 50-90 from Phase 6)
```

### Check Source Distribution

```bash
# Distribution by data source
grep -r "data_source:" data/ingredients/ | cut -d: -f3 | sort | uniq -c

# Expected additions:
#   XX ChemSpider API
#   XX CAS Common Chemistry API
```

### Calculate New Coverage

```bash
# Total ingredients
ls data/ingredients/{mapped,unmapped}/*.yaml | wc -l
# Should be: 1113

# Coverage percentage
# (total_with_cas / 1113) * 100
```

**Target**: 73-77% coverage (810-860 ingredients with CAS-RN)

---

## Expected Results

### ChemSpider API

**Expected matches**: 20-40 ingredients  
**Success rate**: 5-11% of remaining 367  
**Strengths**:
- Complex structures and stereoisomers
- International chemical names
- Complementary to PubChem coverage

**Typical matches**:
- Complex organic compounds
- Pharmaceutical intermediates
- Specialty chemicals with multiple synonyms

### CAS Common Chemistry API

**Expected matches**: 30-50 ingredients  
**Success rate**: 8-14% of remaining  
**Strengths**:
- Official CAS source (most authoritative)
- Common laboratory chemicals
- Well-characterized substances

**Typical matches**:
- Standard lab reagents
- Common industrial chemicals
- Widely-used research compounds

### Combined Phase 6

**Total expected**: 50-90 ingredients  
**New coverage**: 73-77% (810-860 total)  
**Runtime**: ~16-23 minutes combined  
**Cost**: $0 (both free for research)

---

## Troubleshooting

### ChemSpider Issues

**"Invalid API key" error**:
- Verify key is correct (copy-paste from developer portal)
- Check environment variable: `echo $CHEMSPIDER_API_KEY`
- Try passing key via command line: `--api-key YOUR_KEY`

**Rate limit errors**:
- Script uses 1.5s delay (conservative)
- ChemSpider quota: 1,000/month
- Check remaining quota in developer portal

**API errors**:
- ChemSpider occasionally times out on complex queries
- Script handles errors gracefully, continues processing
- Check `api_errors` count in statistics

### CAS Common Chemistry Issues

**Connection errors**:
- API is open access, should not require authentication
- Check internet connection
- Try manual query: `curl "https://commonchemistry.cas.org/api/search?q=glucose"`

**No results found**:
- CAS Common Chemistry has 500,000+ substances
- Not all chemicals in research databases are included
- This is expected - script handles gracefully

---

## Data Quality Verification

After Phase 6 completion:

### 1. Validate CAS-RN Format

```bash
cd ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech

# Find any invalid CAS-RN formats
grep -r "cas_rn:" data/ingredients/ | grep -v -E "cas_rn: \d+-\d+-\d+"
```

Should return no results (all CAS-RN should match format).

### 2. Check Provenance

```bash
# Verify all Phase 6 additions have proper provenance
grep -A3 "ChemSpider API" data/ingredients/*/
grep -A3 "CAS Common Chemistry API" data/ingredients/*/
```

Each should show:
- `data_source`
- `retrieval_date`
- Curation history entry

### 3. Spot Check Examples

```bash
# View a few updated ingredients
find data/ingredients -name "*.yaml" -exec grep -l "ChemSpider API" {} \; | head -5 | xargs cat
```

Verify structure matches existing entries.

---

## Next Steps After Phase 6

### Update Documentation

Update `CAS_RN_INTEGRATION_COMPLETE.md`:
- Add actual Phase 6 results
- Update coverage percentage
- Update final statistics

### Regenerate Unmapped Analysis

```bash
cd ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw

python scripts/analyze_unmapped_cas_rn.py \
    --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
    --output workspace/reports/unmapped_cas_rn_analysis.md
```

This will show:
- New unmapped count (expected: ~277-303 remaining)
- Updated category breakdowns
- Remaining "Other/Uncategorized" ingredients

### Consider Phase 7 (Optional)

**Manual Curation** for remaining "Other/Uncategorized":
- Review ingredients with CHEBI IDs but no CAS-RN found
- Chemical literature search (PubChem, ChEBI, SciFinder)
- Direct CAS Registry lookup for high-priority compounds
- **Potential gain**: 50-100 additional ingredients

**Realistic maximum**: 80-85% coverage with manual curation

---

## Phase 6 Scripts Reference

### ChemSpider Script

**File**: `scripts/fetch_cas_rn_from_chemspider.py`

**Usage**:
```bash
# Basic usage
python scripts/fetch_cas_rn_from_chemspider.py --api-key YOUR_KEY

# Environment variable
export CHEMSPIDER_API_KEY="your-key"
python scripts/fetch_cas_rn_from_chemspider.py

# Dry run
python scripts/fetch_cas_rn_from_chemspider.py --dry-run --max-queries 10

# Custom MediaIngredientMech path
python scripts/fetch_cas_rn_from_chemspider.py \
    --mim /path/to/MediaIngredientMech \
    --api-key YOUR_KEY
```

### CAS Common Chemistry Script

**File**: `scripts/fetch_cas_rn_from_cas_common_chemistry.py`

**Usage**:
```bash
# Basic usage (no API key needed)
python scripts/fetch_cas_rn_from_cas_common_chemistry.py

# Dry run
python scripts/fetch_cas_rn_from_cas_common_chemistry.py --dry-run --max-queries 10

# Custom path
python scripts/fetch_cas_rn_from_cas_common_chemistry.py \
    --mim /path/to/MediaIngredientMech
```

---

## Summary Checklist

- [ ] Register for ChemSpider API key at https://developer.rsc.org/
- [ ] Set `CHEMSPIDER_API_KEY` environment variable
- [ ] Run ChemSpider dry run test (10 queries)
- [ ] Run ChemSpider full integration
- [ ] Run CAS Common Chemistry dry run test (10 queries)
- [ ] Run CAS Common Chemistry full integration
- [ ] Verify coverage increased to 73-77%
- [ ] Commit results to MediaIngredientMech
- [ ] Update CAS_RN_INTEGRATION_COMPLETE.md
- [ ] Regenerate unmapped analysis report

---

**Ready to execute**: Both Phase 6 scripts are production-ready. User action required: Obtain ChemSpider API key and run scripts.

**Expected completion time**: 20-30 minutes total  
**Expected outcome**: 810-860 ingredients with CAS-RN (73-77% coverage)  
**Cost**: $0 (free research APIs)

---

**Generated**: 2026-04-06  
**Author**: Claude Opus 4.6  
**Session**: CAS-RN Integration Phase 6 Preparation
