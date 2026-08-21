# Soil Ontology Curation Guide

## Overview

For culture media ingredients that are soil samples or soil-based preparations, use ontology-based classification instead of free-text descriptions. This guide compares available soil ontologies and provides recommendations for CultureMech ingredient mapping.

## Soil Ontology Landscape

### Primary Recommendation: ENVO (Environment Ontology) ⭐

**Status**: OBO Foundry standard ontology
**Best for**: Microbial culture media ingredients, biological/biomedical contexts
**Format**: OWL/RDF, machine-readable
**Interoperability**: Seamlessly integrates with ChEBI, FOODON, and other OBO ontologies

**Why ENVO for CultureMech:**
- ✅ Designed for biological/environmental contexts (perfect fit for microbiology)
- ✅ Hierarchical soil classification (e.g., loam → soil)
- ✅ Widely adopted in genomics, metagenomics, environmental microbiology
- ✅ OBO Foundry member (ensures quality, interoperability)
- ✅ Already used alongside ChEBI/FOODON in your data pipeline

**Resources:**
- OBO Foundry: https://obofoundry.org/ontology/envo.html
- GitHub: https://github.com/EnvironmentOntology/envo
- Browser: https://www.ebi.ac.uk/ols/ontologies/envo

### Alternative: AGROVOC (FAO Agricultural Vocabulary)

**Status**: FAO multilingual thesaurus/vocabulary (SKOS-based linked data)
**Best for**: Agricultural contexts, soil types in farming/crop systems
**Format**: Linked Open Data (LOD), RDF/SKOS
**Coverage**: ~40,000 terms including soil types, soil functions, soil properties

**Strengths:**
- ✅ Extensive agricultural terminology
- ✅ Multilingual (40+ languages)
- ✅ Linked data compatible
- ✅ FAO standard for agricultural information systems

**Limitations for CultureMech:**
- ⚠️ Agricultural focus (not biological/microbiological)
- ⚠️ Less integration with OBO Foundry ontologies (ChEBI, FOODON)
- ⚠️ SKOS vocabulary rather than formal OWL ontology

**When to consider AGROVOC:**
- Agricultural soil samples with documented crop origin
- Cross-referencing with FAO agricultural databases
- Integration with agricultural information systems

**Resources:**
- AGROVOC Browser: https://agrovoc.fao.org/browse/agrovoc/en/
- Soil types: https://agrovoc.fao.org/browse/agrovoc/en/page/c_7204

### Secondary Option: GloSIS/WRB (World Reference Base)

**Status**: FAO Global Soil Partnership initiative
**Best for**: Detailed pedological (soil science) classifications
**Format**: OWL/RDF linked data (GloSIS), traditional classification (WRB)
**Structure**: 32 Reference Soil Groups (RSGs) + 281 qualifiers

**When to use GloSIS/WRB:**
- 🔬 Highly specific soil sample identifications needed
- 📚 Cross-referencing with soil science literature
- 🌍 Precise pedological classification required (e.g., Ferralsols, Luvisols)

**Why secondary for CultureMech:**
- ⚠️ More detailed than needed for culture media ingredients
- ⚠️ Designed for soil science, not microbiology
- ⚠️ May over-specify when simple "soil" is sufficient

**Resources:**
- FAO WRB Portal: https://www.fao.org/soils-portal/data-hub/soil-classification/world-reference-base/en/
- GloSIS Ontology: https://www.semantic-web-journal.net/system/files/swj3325.pdf
- WRB 4th Edition (2022): https://www.isric.org/explore/wrb

### Complementary: MCO (Microbial Conditions Ontology)

**Status**: Specialized ontology for microbial growth conditions
**Best for**: Overall culture media metadata, growth condition annotations
**Modules**: Integrates ChEBI (chemicals), MicrO (phenotypic characters)

**Use case:**
- Annotating complete culture media formulations (not individual ingredients)
- Linking growth conditions to microbial phenotypes
- Metadata about incubation, temperature, pH, etc.

**Resources:**
- Paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC7963087/

---

## Verdict: Which is "Best" for Soil?

**It depends on your use case:**

| Use Case | Best Ontology | Reason |
|----------|---------------|--------|
| **Microbial culture media** (our case) | **ENVO** ⭐ | Integrates with ChEBI/FOODON, OBO Foundry standard, biological focus |
| **Pedological research** | **GloSIS/WRB** | 32 RSGs + 281 qualifiers, international soil science standard |
| **Agricultural systems** | **AGROVOC** | Agricultural vocabulary, FAO standard, multilingual |
| **Soil properties/processes** | **Research ontologies** | Specialized for soil physics, chemistry, biology |

### For CultureMech: ENVO is Best ✅

**Why ENVO wins for culture media ingredients:**
1. **Integration**: Works seamlessly with ChEBI (chemicals) and FOODON (food materials) already in your pipeline
2. **Biological context**: Designed for biological/biomedical applications (not agriculture or soil science)
3. **OBO Foundry**: Quality-controlled, interoperable with 100+ life science ontologies
4. **Sufficient granularity**: Has specific terms (greenhouse soil, peat soil, agricultural soil) without over-specifying
5. **Community adoption**: Standard in genomics, metagenomics, environmental microbiology

**When to use alternatives:**
- **AGROVOC xref**: When soil has documented agricultural origin
- **GloSIS/WRB xref**: When pedological classification is in source database
- **Both ENVO + xrefs**: Best practice for maximum interoperability

### Comparison: ENVO vs GloSIS vs AGROVOC

| Criterion | ENVO | GloSIS/WRB | AGROVOC |
|-----------|------|------------|---------|
| **Biological integration** | ✅✅✅ | ⚠️ | ⚠️ |
| **Soil detail** | ✅✅ | ✅✅✅ | ✅✅ |
| **OBO Foundry** | ✅ | ❌ | ❌ |
| **Microbiology focus** | ✅ | ❌ | ❌ |
| **Interoperability** | ✅✅✅ | ✅✅ | ✅✅ |
| **For culture media** | **Best** | Overkill | Agricultural only |

---

## Recommended Approach: Hybrid ENVO-Primary Strategy

**Default workflow:**
1. **Use ENVO** for all soil ingredients as primary ontology
2. **Add xref to GloSIS/WRB** if specific pedological classification is known
3. **Add notes** explaining context (e.g., "agricultural soil from Vermont")

**Example:**
```yaml
- ontology_id: ENVO:00002229
  preferred_term: agricultural soil
  xrefs:
    - id: WRB:Luvisol  # If known from source
    - id: GloSIS:...   # If detailed classification available
  notes: "Vermont agricultural soil, likely farm field origin"
```

## ENVO Soil Classification Hierarchy

### Primary Soil Types

| ENVO ID | Term | Use For |
|---------|------|---------|
| `ENVO:00001998` | soil | Generic soil (fallback only) |
| `ENVO:00005802` | greenhouse soil | Greenhouse/glasshouse cultivation soil |
| `ENVO:00002229` | agricultural soil | Farm or crop field soil |
| `ENVO:00002259` | peat soil | High organic matter, wetland-derived |
| `ENVO:00002260` | forest soil | Woodland/forest floor soil |
| `ENVO:00005755` | garden soil | Cultivated garden soil |
| `ENVO:01001357` | potting soil | Commercial potting mix |
| `ENVO:00002018` | sediment | For aquatic/marine sediments |

### Soil by Composition

| ENVO ID | Term | Description |
|---------|------|-------------|
| `ENVO:00002256` | sandy soil | High sand content |
| `ENVO:00002257` | loamy soil | Balanced sand/silt/clay |
| `ENVO:00002258` | clay soil | High clay content |
| `ENVO:00002259` | peat soil | High organic matter |

### Processed/Modified Soils

| ENVO ID | Term | Use For |
|---------|------|---------|
| `ENVO:01001357` | potting soil | Sterilized/amended commercial mix |
| `ENVO:02000039` | sterilized soil | Autoclaved or heat-treated |

## Curation Examples for CultureMech Soil Terms

### Current Unmapped Terms (ENVO-Primary Approach)

| Term | Primary (ENVO) | Secondary (GloSIS/WRB) | Confidence | Rationale |
|------|----------------|------------------------|------------|-----------|
| **Green House Soil** | ENVO:00005802<br>greenhouse soil | Optional: WRB RSG if known | 0.95 | Exact ENVO match, perfect fit |
| **Peat Medium** | ENVO:00002259<br>peat soil | WRB:Histosol (organic soil) | 0.90 | Explicit "peat" mention |
| **Vermont Soil** | ENVO:00002229<br>agricultural soil | WRB RSG if documented | 0.75 | Contextual inference (Vermont = agricultural) |
| **CR1 Soil** | ENVO:00001998<br>soil | Add WRB xref if source known | 0.70 | CR1 = sample ID, origin unknown |
| **Soil+Seawater Medium** | ENVO:00002018<br>marine sediment | WRB:Fluvisol (if coastal) | 0.75 | Composite material → sediment |
| **Soilwater: GR+ Medium** | ENVO:00001998<br>soil | Investigate GR+ protocol | 0.60 | GR+ undefined, needs source check |
| **Soilwater: GR- Medium** | ENVO:00001998<br>soil | Investigate GR- protocol | 0.60 | GR- undefined, needs source check |

### Decision Tree for Soil Classification

```
Is it explicitly named? (e.g., "greenhouse", "peat", "agricultural")
├─ YES → Use specific ENVO term (e.g., ENVO:00005802)
│   └─ Add WRB xref if pedological classification is documented
└─ NO → Is there contextual information? (location, source, composition)
    ├─ YES → Infer appropriate ENVO term (e.g., Vermont → agricultural)
    │   └─ Add note explaining inference
    └─ NO → Use generic ENVO:00001998 (soil)
        └─ Mark for future refinement when source is identified
```

## Best Practices

### 1. Prioritize Specificity
- Always use the most specific ENVO term available
- Generic `ENVO:00001998` (soil) should be last resort

### 2. Check Source Context
- Look for mentions in CultureMech source databases
- Geographic origin may indicate soil type (e.g., Vermont → agricultural)
- Collection site (greenhouse, forest, farm) guides classification

### 3. Composite Materials
- **Soil + Seawater** → Consider `ENVO:00002018` (sediment) or `ENVO:01000018` (mudflat)
- **Peat + Water** → `ENVO:00002259` (peat soil)
- **Sterilized Soil** → `ENVO:02000039` (sterilized soil)

### 4. Confidence Scoring
- **0.95-1.0**: Explicit match (e.g., "greenhouse soil" → ENVO:00005802)
- **0.85-0.94**: Strong contextual evidence
- **0.70-0.84**: Reasonable inference from limited info
- **<0.70**: Insufficient info, use generic or mark for manual review

## Integration with Other Ontologies

### Complementary Ontologies for Culture Media

**ChEBI** (Chemical Entities of Biological Interest)
- Use for: Chemical compounds in soil (minerals, salts)
- Example: Soil containing calcium carbonate → ENVO:soil + CHEBI:3311

**FOODON** (Food Ontology)
- Use for: Agricultural products, food-derived materials
- Example: Compost from food waste → FOODON terms

**PCO** (Population and Community Ontology)
- Use for: Soil microbial communities
- Example: Soil microbiome composition

**ENVO Environmental Processes**
- Use for: Soil treatments and processing
- Examples: autoclaved soil, pasteurized soil, sterilized soil

### Cross-Ontology Example
```yaml
ingredient:
  name: "Autoclaved greenhouse soil"
  ontology_mappings:
    - ontology_id: ENVO:00005802
      label: greenhouse soil
      ontology_source: ENVO
      relationship: is_a
    - ontology_id: ENVO:02000039
      label: sterilized soil
      ontology_source: ENVO
      relationship: has_quality
```

## Key Research Findings (2026)

### ENVO in Biological Contexts
- ENVO is specifically designed for "contextualising biological and biomedical entities"
- Provides hierarchical classification enabling queries (e.g., loam as subclass of soil)
- Widely used in genomics, metagenomics, and environmental microbiology projects
- Interoperates with 100+ OBO Foundry ontologies

### WRB/GloSIS Development
- WRB 4th edition released 2022 with 32 Reference Soil Groups
- GloSIS web ontology implements WRB as OWL/RDF linked data
- Uses SOSA (Sensor, Observation, Sample, Actuator), SKOS, GeoSPARQL standards
- Enables soil information exchange as linked data

### Microbial Culture Media Ontology
- MCO (Microbial Conditions Ontology) provides framework for growth conditions
- Integrates ChEBI modules for chemical composition
- Formal relations between media and chemical composition

## Additional Resources

### ENVO
- OBO Foundry: https://obofoundry.org/ontology/envo.html
- Browser: https://www.ebi.ac.uk/ols/ontologies/envo
- GitHub: https://github.com/EnvironmentOntology/envo
- Paper: https://pubmed.ncbi.nlm.nih.gov/27664130/

### GloSIS/WRB
- FAO Portal: https://www.fao.org/soils-portal/data-hub/soil-classification/world-reference-base/en/
- GloSIS Ontology Paper: https://www.semantic-web-journal.net/system/files/swj3325.pdf
- WRB 2022: https://www.isric.org/explore/wrb

### MCO
- Paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC7963087/

## Notes for Automated Curation

When implementing LLM-based or rule-based curation:

```python
# Primary ENVO mapping rules
soil_rules = {
    "greenhouse": "ENVO:00005802",   # greenhouse soil
    "glasshouse": "ENVO:00005802",
    "peat": "ENVO:00002259",         # peat soil
    "garden": "ENVO:00005755",       # garden soil
    "potting": "ENVO:01001357",      # potting soil
    "forest": "ENVO:00002260",       # forest soil
    "woodland": "ENVO:00002260",
    "agricultural": "ENVO:00002229",  # agricultural soil
    "farm": "ENVO:00002229",
    "cropland": "ENVO:00002229",
}

# Composite and processed materials
composite_rules = {
    ("soil", "seawater"): "ENVO:00002018",   # marine sediment
    ("soil", "water"): "ENVO:00002042",       # sediment suspension
    ("sterilized", "soil"): "ENVO:02000039", # sterilized soil
    ("autoclaved", "soil"): "ENVO:02000039",
}

# Contextual inference (location-based)
location_context = {
    "vermont": "ENVO:00002229",      # agricultural soil (Vermont = farms)
    "desert": "ENVO:01001357",       # arid soil
    "wetland": "ENVO:00002259",      # peat soil
}

def map_soil_term(term, context=None):
    """
    Map soil term to ENVO ID using hierarchical rules.

    Returns: (envo_id, confidence_score, notes)
    """
    term_lower = term.lower()

    # Direct keyword match (high confidence)
    for keyword, envo_id in soil_rules.items():
        if keyword in term_lower:
            return (envo_id, 0.95, f"Direct match: {keyword}")

    # Composite match (medium confidence)
    for (key1, key2), envo_id in composite_rules.items():
        if key1 in term_lower and key2 in term_lower:
            return (envo_id, 0.80, f"Composite: {key1} + {key2}")

    # Context-based inference (medium-low confidence)
    if context:
        for location, envo_id in location_context.items():
            if location in context.lower():
                return (envo_id, 0.75, f"Contextual inference from: {location}")

    # Fallback to generic soil (low confidence)
    return ("ENVO:00001998", 0.70, "Generic soil - needs manual review")
```

---

## Summary and Recommendations

### For CultureMech Ingredient Mapping:

**✅ DO:**
- Use **ENVO as primary ontology** for all soil ingredients
- Prioritize specific ENVO terms (greenhouse soil, peat soil) over generic "soil"
- Add **notes explaining reasoning** for contextual inferences
- Include **WRB/GloSIS xrefs** when pedological classification is documented
- Set **confidence scores** based on evidence quality (0.95+ for exact matches, 0.70-0.84 for inferences)

**❌ DON'T:**
- Use WRB as primary ontology (it's for soil science, not microbiology)
- Skip ENVO entirely (it's the OBO Foundry standard for biological contexts)
- Use generic ENVO:00001998 (soil) when more specific terms are available
- Guess WRB classifications without documented evidence

### Quality Tiers:

| Confidence | Evidence | Example | ENVO Term | WRB Xref |
|-----------|----------|---------|-----------|----------|
| **0.95-1.0** | Explicit name | "Greenhouse Soil" | ENVO:00005802 | Optional |
| **0.85-0.94** | Strong context | "Peat Medium" | ENVO:00002259 | If known |
| **0.70-0.84** | Weak inference | "Vermont Soil" | ENVO:00002229 | If known |
| **<0.70** | Insufficient info | "CR1 Soil" | ENVO:00001998 | Review needed |

### When to Add WRB/GloSIS Cross-References:

- ✓ When source database provides WRB classification
- ✓ When literature/publication references specific soil type
- ✓ When collaboration with soil scientists requires it
- ✗ When guessing based on location alone
- ✗ When ENVO term is sufficient for microbiology use case

### Next Steps:

1. **Re-curate existing soil terms** with specific ENVO IDs (not generic soil)
2. **Add structured notes** explaining classification rationale
3. **Flag for review** any terms with confidence <0.75
4. **Investigate GR+/GR- protocols** to determine appropriate classification
5. **Check source databases** (DSMZ, ATCC, etc.) for original soil descriptions

---

*Last updated: March 2026 based on ENVO, GloSIS, WRB 2022, and MCO research*
