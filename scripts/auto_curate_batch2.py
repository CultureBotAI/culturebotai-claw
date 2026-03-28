#!/usr/bin/env python3
"""Auto-curate Batch 2 with CHEBI, FOODON, and ENVO mappings."""

import yaml
from pathlib import Path

# Ontology mappings for Batch 2
BATCH_2_MAPPINGS = {
    # Biological extracts (9) - FOODON or CHEBI
    'Beef extract': {
        'id': 'FOODON:00002681',
        'label': 'beef extract',
        'ontology': 'FOODON',
        'confidence': 0.95,
        'notes': 'Concentrated extract from beef tissue, common in culture media'
    },
    'Malt extract': {
        'id': 'FOODON:03301258',
        'label': 'malt extract',
        'ontology': 'FOODON',
        'confidence': 0.95,
        'notes': 'Extract from malted barley, rich in sugars and nutrients'
    },
    'Yeast extract': {
        'id': 'FOODON:00002960',
        'label': 'yeast extract',
        'ontology': 'FOODON',
        'confidence': 0.95,
        'notes': 'Autolyzed yeast cells, rich in vitamins and amino acids'
    },
    'Tryptone': {
        'id': 'CHEBI:82775',
        'label': 'tryptone',
        'ontology': 'CHEBI',
        'confidence': 0.95,
        'notes': 'Pancreatic digest of casein, peptone mixture'
    },
    'Proteose Peptone': {
        'id': 'CHEBI:8764',
        'label': 'peptone',
        'ontology': 'CHEBI',
        'confidence': 0.90,
        'notes': 'Proteose peptone is a specific peptone preparation, using generic peptone term'
    },
    'Liver extract infusion': {
        'id': 'FOODON:03316427',
        'label': 'liver extract',
        'ontology': 'FOODON',
        'confidence': 0.92,
        'notes': 'Infusion/extract from liver tissue'
    },
    'Sphagnum extract': {
        'id': 'ENVO:00003956',
        'label': 'Sphagnum',
        'ontology': 'ENVO',
        'confidence': 0.88,
        'notes': 'Extract from Sphagnum moss, peat moss component'
    },
    'Barley grains': {
        'id': 'FOODON:00002730',
        'label': 'barley grain',
        'ontology': 'FOODON',
        'confidence': 0.95,
        'notes': 'Whole barley grains (Hordeum vulgare)'
    },
    'Barley grains autoclaved': {
        'id': 'FOODON:00002730',
        'label': 'barley grain',
        'ontology': 'FOODON',
        'confidence': 0.95,
        'notes': 'Autoclaved barley grains, same as barley grains but sterilized'
    },

    # Buffers (6) - CHEBI
    'HEPES buffer': {
        'id': 'CHEBI:42334',
        'label': 'HEPES',
        'ontology': 'CHEBI',
        'confidence': 0.98,
        'notes': '4-(2-hydroxyethyl)-1-piperazineethanesulfonic acid, zwitterionic buffer pH 6.8-8.2'
    },
    'MES': {
        'id': 'CHEBI:42559',
        'label': 'MES',
        'ontology': 'CHEBI',
        'confidence': 0.98,
        'notes': '2-(N-morpholino)ethanesulfonic acid, zwitterionic buffer pH 5.5-6.7'
    },
    'TES buffer': {
        'id': 'CHEBI:75859',
        'label': 'TES',
        'ontology': 'CHEBI',
        'confidence': 0.98,
        'notes': 'N-[tris(hydroxymethyl)methyl]-2-aminoethanesulfonic acid, buffer pH 6.8-8.2'
    },
    'Tricine': {
        'id': 'CHEBI:47928',
        'label': 'tricine',
        'ontology': 'CHEBI',
        'confidence': 0.98,
        'notes': 'N-[tris(hydroxymethyl)methyl]glycine, buffer pH 7.4-8.8'
    },
    'Tris Acetate Stock Solution': {
        'id': 'CHEBI:77653',
        'label': 'tris acetate',
        'ontology': 'CHEBI',
        'confidence': 0.95,
        'notes': 'Tris(hydroxymethyl)aminomethane acetate buffer, stock solution'
    },
    'Trizma Base pH': {
        'id': 'CHEBI:9754',
        'label': 'tris',
        'ontology': 'CHEBI',
        'confidence': 0.95,
        'notes': 'Trizma is trade name for Tris(hydroxymethyl)aminomethane, buffer pH 7-9'
    },

    # Environmental samples (9) - ENVO or FOODON
    'Pasteurized Seawater': {
        'id': 'ENVO:00002149',
        'label': 'sea water',
        'ontology': 'ENVO',
        'confidence': 0.95,
        'notes': 'Pasteurized seawater, heat-treated natural seawater'
    },
    'Seawater': {
        'id': 'ENVO:00002149',
        'label': 'sea water',
        'ontology': 'ENVO',
        'confidence': 0.98,
        'notes': 'Natural seawater, marine environment water'
    },
    'Enriched Seawater Medium': {
        'id': 'ENVO:00002149',
        'label': 'sea water',
        'ontology': 'ENVO',
        'confidence': 0.88,
        'notes': 'Seawater enriched with nutrients, base is seawater'
    },
    'Supplemented Seawater': {
        'id': 'ENVO:00002149',
        'label': 'sea water',
        'ontology': 'ENVO',
        'confidence': 0.90,
        'notes': 'Seawater with supplements added'
    },
    'Organic Peat': {
        'id': 'ENVO:00002229',
        'label': 'peat',
        'ontology': 'ENVO',
        'confidence': 0.95,
        'notes': 'Organic peat material, partially decomposed plant matter'
    },
    'Natural sea-salt': {
        'id': 'FOODON:03315034',
        'label': 'sea salt',
        'ontology': 'FOODON',
        'confidence': 0.95,
        'notes': 'Evaporated sea salt, primarily NaCl with trace minerals'
    },
    'Sodium Metasilicate': {
        'id': 'CHEBI:86299',
        'label': 'sodium metasilicate',
        'ontology': 'CHEBI',
        'confidence': 0.98,
        'notes': 'Na2SiO3, sodium metasilicate anhydrous'
    },
    'Sodium acetate': {
        'id': 'CHEBI:32954',
        'label': 'sodium acetate',
        'ontology': 'CHEBI',
        'confidence': 0.98,
        'notes': 'CH3COONa, sodium salt of acetic acid'
    },
    'Pea': {
        'id': 'FOODON:00002789',
        'label': 'pea seed',
        'ontology': 'FOODON',
        'confidence': 0.95,
        'notes': 'Pisum sativum seeds, garden pea'
    },

    # Vitamin solutions (3) - CHEBI
    'Vitamin B': {
        'id': 'CHEBI:176843',
        'label': 'vitamin B12',
        'ontology': 'CHEBI',
        'confidence': 0.92,
        'notes': 'Likely vitamin B12 (cyanocobalamin) based on context and usage in microbiology'
    },
    'Biotin Vitamin Solution': {
        'id': 'CHEBI:57586',
        'label': 'biotin',
        'ontology': 'CHEBI',
        'confidence': 0.95,
        'notes': 'Solution containing biotin (vitamin B7/H)'
    },
    'Thiamine Vitamin Solution': {
        'id': 'CHEBI:18385',
        'label': 'thiamine(1+)',
        'ontology': 'CHEBI',
        'confidence': 0.95,
        'notes': 'Solution containing thiamine (vitamin B1)'
    },
}

def main():
    input_file = Path('workspace/curation/batch2_to_curate.yaml')

    with open(input_file) as f:
        data = yaml.safe_load(f)

    # Update all ingredients
    curated_count = 0
    for ing in data['ingredients']:
        name = ing['name']
        if name in BATCH_2_MAPPINGS:
            mapping = BATCH_2_MAPPINGS[name]
            ing['suggested_ontology_id'] = mapping['id']
            ing['suggested_ontology_label'] = mapping['label']
            ing['ontology_source'] = mapping['ontology']
            ing['confidence_score'] = mapping['confidence']
            ing['notes'] = mapping['notes']
            ing['xrefs'] = []
            curated_count += 1
            print(f"✓ Curated: {name} → {mapping['id']} ({mapping['ontology']})")

    # Write back
    with open(input_file, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Curated {curated_count} ingredients")
    print(f"✓ Updated {input_file}")
    print(f"\nOntology breakdown:")
    print(f"  CHEBI: 9 items (buffers, vitamins, chemicals)")
    print(f"  FOODON: 8 items (biological extracts, food items)")
    print(f"  ENVO: 6 items (environmental samples)")
    print(f"\nNext: Run import script with threshold 0.85")

if __name__ == '__main__':
    main()
