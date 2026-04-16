# Task C: Quick Start Guide

## ✅ What's Complete

1. **5 pipeline scripts created** (1,763 lines of code)
2. **Workspace directory structure** (12 directories)
3. **PDF parsing implementation** for CCAP sources
4. **Master orchestrator** with checkpoint/resume
5. **Integration test suite**
6. **Dependencies added** to pyproject.toml

## 🚀 Quick Start (5 Minutes)

### Step 1: Install Dependencies
```bash
uv sync
```

### Step 2: Run Dry-Run Test (3 media)
```bash
python scripts/batch_process_collection_media.py \
    --batch-id quick_test \
    --offset 0 \
    --batch-size 3 \
    --auto-accept-threshold 0.9 \
    --max-cost 5.0 \
    --dry-run
```

**Expected**: Pipeline runs fetch and extract stages, pauses at curate (normal).

### Step 3: Run Integration Tests
```bash
python scripts/test_collection_media_pipeline_e2e.py
```

**Expected**: Extract and validate tests pass.

## 📋 Next: Full Pilot (50 Media)

### Command
```bash
python scripts/batch_process_collection_media.py \
    --batch-id pilot_001 \
    --offset 0 \
    --batch-size 50 \
    --auto-accept-threshold 0.9 \
    --max-cost 10.0 \
    --dry-run  # Remove after dry-run succeeds
```

### Success Criteria
- >85% fetch success rate
- >80% JCM parse success
- Cost <$10
- No errors in CultureMech files

## 📚 Documentation

- **Full details**: `TASK_C_IMPLEMENTATION_COMPLETE.md`
- **Scripts**: All in `scripts/` with docstrings
- **Workspace**: `workspace/curation/collection_media/`

## ⚠️ Known: Curate Stage Requires Manual Step

The pipeline will pause at Stage 3 (curate) because it requires running MediaIngredientMech's `batch_curate.py` separately. This is expected and documented in the orchestrator output.

**To complete curate stage manually**:
1. Pipeline will output extracted unmapped ingredients
2. You'll need to convert format and run MediaIngredientMech curation
3. Copy results back and resume pipeline

Future enhancement: Automate this integration.
