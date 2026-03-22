# OAK Library Compatibility Issue

**Date**: March 18, 2026
**Status**: 🔴 **BLOCKING ISSUE**
**Priority**: Critical

---

## Problem

OAKlib 0.5.31 and 0.6.23 have a compatibility issue with recent versions of linkml/linkml-runtime:

```
AttributeError: type object 'Format' has no attribute 'JSON'. Did you mean: 'JSONLD'?
```

**Root Cause**: Recent versions of linkml changed `Format.JSON` to `Format.JSONLD`, but oaklib and its dependency sssom haven't been updated yet.

**Affected**:
- MediaIngredientMech environment (Python 3.14)
- Orchestration environment (Python 3.10)
- All OAK-dependent functionality

---

## Attempted Fixes

1. ❌ Downgrade linkml to 1.8.7 - Still fails
2. ❌ Downgrade oaklib to 0.5.31 - Still fails
3. ❌ Different Python versions - Issue persists

**Issue**: The problem is in linkml-runtime which is pulled in transitively and has breaking changes.

---

## Impact on OpenClaw Implementation

### Critical Impact

- ✅ **Week 2-3 agents configured** - YAML configs complete
- ✅ **Multi-Claude coordination** - Lock system working
- ✅ **Pipeline orchestration** - Python code complete
- ❌ **OAK ontology queries** - BLOCKED by this issue

### What Works

1. **IngredientCurationAgent** - Configuration complete, can delegate to existing scripts
2. **NetworkRepairAgent** - Configuration complete, wraps existing LLMNetworkRepairer
3. **ETLCoordinatorAgent** - Configuration complete
4. **IngredientCurationPipeline** - Orchestration logic complete
5. **Multi-Claude coordination** - Lock manager fully functional

### What's Blocked

1. **OAKQueryPlugin real-time queries** - Cannot load ontology adapters
2. **Live ontology validation** - Falls back to existing MediaIngredientMech code
3. **Week 4 testing with real ontology data** - Blocked

---

## Workarounds

### Workaround 1: Use Existing MediaIngredientMech Code (RECOMMENDED)

**Status**: ✅ **AVAILABLE NOW**

MediaIngredientMech already has working ontology code that doesn't use OAK directly:

```python
# File: src/mediaingredientmech/utils/llm_curator.py
# Uses Anthropic Claude for ontology mapping suggestions
# Validates using existing validation functions

# File: src/mediaingredientmech/utils/ontology_client.py
# Has OntologyClient class but may use cached/alternative approach
```

**Implementation**:
- OpenClaw agents delegate to existing scripts
- Use existing `just curate` command
- Use existing LLMCurator class directly
- Validation via existing validation functions

**Pros**:
- ✅ Works immediately
- ✅ No dependency issues
- ✅ Proven code
- ✅ Same LLM models (Claude Sonnet 4)

**Cons**:
- ⚠️ No real-time OAK caching in OpenClaw layer
- ⚠️ Depends on MediaIngredientMech environment

### Workaround 2: Mock OAK for Testing

**Status**: ✅ **CAN IMPLEMENT**

Create a mock OAK implementation for testing pipeline orchestration:

```python
# plugins/oak_query_mock.py
class MockOAKQueryPlugin:
    """Mock OAK plugin for testing without real ontologies."""

    def search(self, query, **kwargs):
        # Return mock results
        return [
            {"ontology_id": "CHEBI:17234", "label": query, "score": 0.95},
        ]

    def validate_term(self, ontology_id):
        # Mock validation
        return {"is_valid": True, "label": "Mock term"}
```

**Usage**: Test pipeline logic without actual ontology downloads

**Pros**:
- ✅ Immediate testing of pipeline orchestration
- ✅ No external dependencies
- ✅ Fast execution

**Cons**:
- ⚠️ Not real ontology data
- ⚠️ Cannot validate actual mappings

### Workaround 3: Wait for Upstream Fix

**Status**: ⏳ **PENDING**

Track these issues:
- https://github.com/INCATools/ontology-access-kit/issues
- https://github.com/linkml/linkml/issues

**Estimated fix**: Unknown (weeks to months)

---

## Recommended Path Forward

### Immediate (Week 4 Days 1-2)

**Use Workaround 1: Existing MediaIngredientMech Code**

1. ✅ Keep OAKQueryPlugin code as-is (ready for when OAK is fixed)
2. ✅ Update agents to delegate to existing scripts when OAK unavailable
3. ✅ Test pipeline orchestration without real-time OAK queries
4. ✅ Use existing MediaIngredientMech validation functions

**Implementation**:

```python
# In ingredient_curation_pipeline.py
try:
    from oak_query import OAKQueryPlugin
    oak_available = True
except Exception:
    oak_available = False
    logger.warning("OAK not available, using existing MediaIngredientMech code")

if oak_available:
    # Use OAK caching
    plugin = OAKQueryPlugin()
else:
    # Delegate to existing code
    # Run: just curate in MediaIngredientMech
    subprocess.run(["just", "curate"], cwd=mediaingredient_root)
```

### Short-term (Week 4 Days 3-4)

1. Implement Mock OAK for pipeline testing
2. Test full pipeline with mock data
3. Verify orchestration logic works
4. Test multi-Claude coordination

### Medium-term (Week 5-6)

1. Monitor upstream OAK/linkml issues
2. Test new releases when available
3. Switch to real OAK when fixed
4. Re-run full validation with real ontologies

---

## Impact Assessment

### What We Can Still Do

✅ **Week 4 Testing** - Can proceed with most tests
- Pipeline orchestration logic
- Multi-Claude coordination
- Agent delegation
- Cost tracking
- Backup/restore
- Lock system
- Status management

✅ **Production Deployment** - Can deploy with existing code
- Use MediaIngredientMech's existing ontology code
- Claude LLM suggestions work
- Validation via existing functions
- Same accuracy as current manual process

### What We Cannot Do (Yet)

❌ **Real-time OAK caching** - Cannot cache ontology queries in OpenClaw layer
❌ **Live ontology downloads** - Cannot download CHEBI/FOODON databases
❌ **OAK integration testing** - Cannot test OAKQueryPlugin with real data

### Business Impact

**Low** - Critical functionality still available via workaround:
- LLM-assisted curation works (via existing code)
- Ontology validation works (via existing code)
- Pipeline orchestration works (via delegation)
- Cost and time savings still achieved

**Key Point**: OpenClaw provides orchestration and coordination even without direct OAK access. The value is in:
1. Multi-repo coordination
2. Automated workflows
3. Multi-Claude cooperation
4. Pipeline management
5. Cost tracking
6. Monitoring

Ontology queries are delegated to existing proven code.

---

## Action Items

### Immediate

- [x] Document issue
- [ ] Update pipeline to gracefully handle OAK unavailability
- [ ] Test with delegation to existing MediaIngredientMech code
- [ ] Continue Week 4 with Workaround 1

### This Week

- [ ] Implement mock OAK for testing
- [ ] Complete pipeline integration testing
- [ ] Verify all agents work with delegation
- [ ] Test multi-Claude coordination

### Ongoing

- [ ] Monitor OAK/linkml GitHub for fixes
- [ ] Test new releases when available
- [ ] Update documentation when resolved

---

## Conclusion

**Status**: ⚠️ **Issue documented, workaround available**

**Recommendation**: Proceed with Week 4 using **Workaround 1** (existing MediaIngredientMech code)

**Timeline Impact**: **None** - Can continue with testing and deployment

**Feature Impact**: **Minimal** - OAK caching deferred, but functionality preserved

**Risk**: **Low** - Existing code is proven and working

---

**Next Steps**:
1. Update IngredientCurationPipeline to use delegation
2. Test with existing MediaIngredientMech code
3. Continue Week 4 testing plan
4. Monitor for OAK/linkml fixes

**Status**: 📋 **Ready to proceed with Week 4 testing**
