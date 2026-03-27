# ENVO Term Sourcing and Environmental Information Integration Guide

## Overview

This document explains how to source high-quality ENVO (Environment Ontology) terms and integrate environmental information across the CultureBotAI-CLAW multi-repository system (CultureMech, MediaIngredientMech, CommunityMech).

## Current Architecture

### OAK Integration (Ontology Access Kit)

The system has a centralized **OAKQueryPlugin** (`plugins/oak_query.py`) that wraps the MediaIngredientMech OntologyClient with caching:

```python
from plugins.oak_query import OAKQueryPlugin

# Cached ontology queries with 24-hour TTL
plugin = OAKQueryPlugin(config={
    "cache_ttl": 86400,
    "enabled_ontologies": ["CHEBI", "FOODON", "ENVO", "NCIT", "MESH", "UBERON"]
})

# Search for ENVO terms
results = plugin.search(
    query="peatland",
    sources=["ENVO"],
    max_results=10
)
```

### OAK Architecture

**Under the hood**, the plugin uses OAK adapters (from `oaklib`):

- **Source**: `sqlite:obo:envo` (OBO foundry ENVO ontology)
- **Adapter methods**:
  - `basic_search(query)` - Full-text search for terms
  - `label(curie)` - Get label for a term ID
  - `definition(curie)` - Get definition
  - `entity_aliases(curie)` - Get synonyms

### MediaIngredientMech OntologyClient

Located at: `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech/src/mediaingredientmech/utils/ontology_client.py`

```python
from mediaingredientmech.utils.ontology_client import OntologyClient, OntologyCandidate

# Create client with specific sources
client = OntologyClient(sources=["ENVO"])

# Search for terms
candidates = client.search(
    query="hot spring",
    sources=["ENVO"],
    max_results=10
)

# Validate a specific term
adapter = client._get_adapter("ENVO")
label = adapter.label("ENVO:01000339")  # "hot spring"
definition = adapter.definition("ENVO:01000339")
```

## Sourcing ENVO Terms: Best Practices

### 1. Manual ENVO Browser Lookup

**Primary source**: [ENVO Browser at EBI OLS](https://www.ebi.ac.uk/ols/ontologies/envo)

**How to find terms**:
1. Go to https://www.ebi.ac.uk/ols/ontologies/envo
2. Search by environment name (e.g., "peatland", "marine sediment", "hot spring")
3. Verify the label and definition match your need
4. Copy the ENVO ID (format: `ENVO:NNNNNNN` or `ENVO:NNNNNNNN`)

**Example ENVO terms for microbial environments**:

| Environment | ENVO ID | Label | Use Case |
|-------------|---------|-------|----------|
| Peatland | ENVO:00000044 | peatland | Peat bog, Sphagnum bacteria |
| Soil | ENVO:00002982 | soil | General soil bacteria |
| Sea water | ENVO:00002149 | sea water | Marine bacteria, ocean |
| Hydrothermal vent | ENVO:01000030 | hydrothermal vent | Thermophilic deep-sea bacteria |
| Hot spring | ENVO:01000339 | hot spring | Thermophilic bacteria |
| Hypersaline lake | ENVO:00002044 | hypersaline lake | Halophilic bacteria |
| Lake | ENVO:00000023 | lake | Freshwater lake bacteria |
| River | ENVO:00000022 | river | Freshwater river bacteria |
| Marine sediment | ENVO:03000003 | marine sediment | Benthic marine bacteria |
| Permafrost | ENVO:00000134 | permafrost | Cold-adapted soil microbes |
| Gut environment | ENVO:00002151 | gut environment | Gut microbiome bacteria |
| Rhizosphere | ENVO:02000065 | rhizosphere | Plant root-associated bacteria |

### 2. Programmatic Term Lookup

**Via OAKQueryPlugin** (recommended for batches):

```python
from plugins.oak_query import OAKQueryPlugin

plugin = OAKQueryPlugin()

# Search with variants (handles typos/synonyms)
results = plugin.search_with_variants(
    queries=["peatland", "peat bog", "sphagnum bog"],
    sources=["ENVO"],
    max_results=5
)

for result in results:
    print(f"{result['ontology_id']}: {result['label']}")
    print(f"  Definition: {result['definition']}")
    print(f"  Score: {result['score']}")
```

**Validation** (for known IDs):

```python
# Validate that a term exists
validation = plugin.validate_term("ENVO:00000044")
if validation['is_valid']:
    print(f"✓ {validation['label']}")
    print(f"  {validation['definition']}")
else:
    print(f"✗ Term not found")
```

### 3. Citation and Provenance

**Current system pattern**: Each environment reference includes:

1. **preferred_term** - Human-readable name
2. **term.id** - ENVO CURIE (the official identifier)
3. **term.label** - The official ENVO label (from ontology)
4. **notes** (optional) - Additional context or citations

**Example** (from schema proposal):

```yaml
source_environment:
  - preferred_term: peatland
    term:
      id: ENVO:00000044
      label: peatland
    notes: "Designed for acidophilic bacteria from northern boreal peatlands (pH 3.5-4.5)"
```

**For environmental_context** (MediaIngredientMech), add:
- **relevance** - Why the ingredient is relevant (NATURAL_SOURCE, REQUIRED_FOR_ORGANISM, SELECTIVE_AGENT, ENVIRONMENT_MIMIC, COMMONLY_USED)
- **environment_label** - For readability

```yaml
environmental_context:
  - environment_term: "ENVO:00000044"
    environment_label: peatland
    relevance: NATURAL_SOURCE
    notes: "Major component of peat organic matter; supports humic acid-degrading bacteria"
```

## Cross-Repository Integration

### Schema Fields

**CultureMech** (`source_environment` field on MediaRecipe):
- Links environments to **media recipes**
- Captures: "This medium is designed for organisms from environment X"
- Type: `SourceEnvironmentDescriptor` (Descriptor/Term pattern)

**MediaIngredientMech** (`environmental_context` field on MappedIngredient):
- Links environments to **ingredients**
- Captures: "This ingredient is relevant to environment X for reason Y"
- Type: `EnvironmentContext` (flat class with enum)

**CommunityMech** (`environment_term` field on Community/Isolate):
- Links environments to **microbial communities**
- Captures: "This community originates from environment X"

### Integration Query Example

Find ingredients suitable for cultivating organisms from a specific environment:

```
1. Query CultureMech: media with source_environment = ENVO:00000044 (peatland)
2. Extract ingredients from those media
3. Query MediaIngredientMech: ingredients with environmental_context ENVO:00000044
4. Cross-reference and rank by relevance
5. Build environment-specific ingredient catalog
```

## Automated ENVO Term Sourcing: Recommended Workflows

### 1. During Media Recipe Curation

When processing a media recipe without a source_environment:

```python
from plugins.oak_query import OAKQueryPlugin

def enrich_media_with_environment(media_record, organism_name=None):
    """Add ENVO terms to media based on organism or literature context."""

    plugin = OAKQueryPlugin()

    # Strategy 1: Search by organism habitat
    if organism_name:
        habitat_clues = infer_habitat_from_organism(organism_name)
        for clue in habitat_clues:
            results = plugin.search(clue, sources=["ENVO"], max_results=3)
            if results:
                best_result = results[0]
                return {
                    "preferred_term": best_result['label'],
                    "term": {
                        "id": best_result['ontology_id'],
                        "label": best_result['label']
                    }
                }

    # Strategy 2: Manual lookup
    # Fall back to asking curator for environment context
    return None
```

### 2. During Ingredient Curation

When discovering that an ingredient has environmental relevance:

```python
def add_environmental_context_to_ingredient(ingredient,
                                            environment_name,
                                            relevance_type):
    """Link ingredient to environment with specific relevance."""

    plugin = OAKQueryPlugin()

    # Search for the environment
    results = plugin.search(environment_name, sources=["ENVO"], max_results=1)

    if results:
        result = results[0]
        return {
            "environment_term": result['ontology_id'],
            "environment_label": result['label'],
            "relevance": relevance_type,
            "notes": f"Sourced from {result['label']} environment"
        }

    return None
```

### 3. Batch Environmental Metadata Extraction

The system includes an **environment coverage dashboard** (`scripts/environment_coverage_dashboard.py`) that:

1. Scans CommunityMech for `environment_term` fields
2. Scans CultureMech for `source_environment` fields
3. Scans MediaIngredientMech for `environmental_context` fields
4. Generates reports on:
   - Which environments are well-covered
   - Which environments need more resources
   - Cross-repository environment alignment

**Usage**:

```bash
python scripts/environment_coverage_dashboard.py --format json --output report.json
```

## ENVO Term Validation

### ID Format

ENVO IDs must match the pattern: **`^ENVO:\d{7,8}$`**

Valid examples:
- `ENVO:00000044` (7 digits)
- `ENVO:01000030` (8 digits)

Invalid examples:
- `ENVO:123` (too few digits)
- `envo:00000044` (lowercase prefix)
- `ENVO_00000044` (underscore instead of colon)

### Validation via OAKQueryPlugin

```python
plugin = OAKQueryPlugin()

# Validate multiple terms
terms = ["ENVO:00000044", "ENVO:01000030", "ENVO:invalid"]

for term_id in terms:
    result = plugin.validate_term(term_id)
    if result['is_valid']:
        print(f"✓ {term_id}: {result['label']}")
    else:
        print(f"✗ {term_id}: {result.get('error', 'Unknown error')}")
```

## Caching Strategy

The OAKQueryPlugin uses **3-level caching**:

1. **Memory cache** - Fast in-process cache (24-hour TTL default)
2. **Disk cache** - Persistent JSON files in `.cache/oak_queries/`
3. **OAK adapter** - Direct ontology queries (slowest)

**Configuration**:

```python
plugin = OAKQueryPlugin(config={
    "cache_ttl": 86400,  # 24 hours
    "cache_dir": "/path/to/workspace/.cache/oak_queries"
})

# Clear expired cache
plugin.clear_cache(older_than_seconds=86400)

# Get cache statistics
stats = plugin.get_cache_stats()
print(f"Cached entries: {stats['memory_cache_entries']}")
print(f"Cache size: {stats['disk_cache_size_mb']}MB")
```

## Environment Variable Configuration

**Required for ENVO sourcing**:

```bash
# .env file
MEDIAINGREDIENTMECH_ROOT=/path/to/MediaIngredientMech
OPENCLAW_WORKSPACE=./workspace  # Cache location
```

## Troubleshooting

### Issue: OAK adapter fails to load

**Symptom**: `OAK unavailable for query, returning empty`

**Cause**: OAK/oaklib installation issue or network connectivity

**Solution**:
```bash
# Verify oaklib installation
python -c "from oaklib import get_adapter; print('OK')"

# Reinstall if needed
pip install oaklib
```

### Issue: ENVO term not found

**Possible causes**:
1. ID format incorrect (check pattern)
2. Term was removed from ENVO
3. Typo in term name

**Solution**:
1. Verify ID format: `ENVO:NNNNNNN` or `ENVO:NNNNNNNN`
2. Check [ENVO Browser](https://www.ebi.ac.uk/ols/ontologies/envo) for correct ID
3. Use `search()` method to find similar terms

### Issue: Cache growing too large

**Symptom**: `.cache/oak_queries/` uses significant disk space

**Solution**:
```python
plugin = OAKQueryPlugin()
plugin.clear_cache(older_than_seconds=604800)  # Remove entries > 7 days old
```

## References

### Official Resources

- **ENVO Ontology**: https://github.com/EnvironmentOntology/envo
- **EBI OLS (Term Browser)**: https://www.ebi.ac.uk/ols/ontologies/envo
- **OAK (Ontology Access Kit)**: https://github.com/INCATools/ontology-access-kit

### In This Codebase

- **OAK Plugin**: `plugins/oak_query.py`
- **OntologyClient**: `../MediaIngredientMech/src/mediaingredientmech/utils/ontology_client.py`
- **Schema Proposals**:
  - CultureMech: `workspace/schema_proposals/culturemech_source_environment_REFINED.yaml`
  - MediaIngredientMech: `workspace/schema_proposals/mediaingredientmech_environmental_context_REFINED.yaml`
- **Coverage Analysis**: `scripts/environment_coverage_dashboard.py`

### Test Examples

- MediaIngredientMech ontology tests: `../MediaIngredientMech/tests/test_ontology_lookup.py`
- Mock OLS/OAK integration patterns (search, label lookup, alias retrieval)

## Next Steps for Implementation

1. **Implement CultureMech source_environment field** (schema modification)
2. **Implement MediaIngredientMech environmental_context field** (schema + relevance enum)
3. **Create ENVO term lookup utilities** for batch curation workflows
4. **Add validation rules** for ENVO ID format and term existence
5. **Build environment-aware queries** across all three repositories
6. **Integrate with ingredient/media curation pipelines** for automated enrichment
7. **Create curation workflows** that leverage environment metadata for discovery

## Summary

The system is designed to support **reliable, citations-enabled ENVO term sourcing** through:

- **OAK integration** for programmatic term lookup and validation
- **Caching** to reduce API calls and improve performance
- **Schema design** that keeps environment metadata with rich context (preferred term, official label, relevance, notes)
- **Cross-repository coordination** via shared ENVO term CURIEs
- **Coverage dashboards** to identify well-resourced and under-resourced environments

All ENVO sourcing should verify terms via the [EBI OLS browser](https://www.ebi.ac.uk/ols/ontologies/envo) before adding to records, and include proper citations through the `notes` field where relevant.
