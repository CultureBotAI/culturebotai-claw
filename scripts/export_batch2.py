#!/usr/bin/env python3
"""
Export Batch 2 ingredients for Claude Code curation.

Batch 2 includes:
- Biological extracts (9 items)
- Buffers (6 items)
- Environmental samples (9 items)
- Vitamin solutions (3 items)

Total: 27 items
"""

import sys
import yaml
from pathlib import Path

# Batch 2 target ingredients
BATCH_2_INGREDIENTS = [
    # Biological extracts (9)
    'Beef extract',
    'Malt extract',
    'Yeast extract',
    'Tryptone',
    'Proteose Peptone',
    'Liver extract infusion',
    'Sphagnum extract',
    'Barley grains',
    'Barley grains autoclaved',

    # Buffers (6)
    'HEPES buffer',
    'MES',
    'TES buffer',
    'Tricine',
    'Tris Acetate Stock Solution',
    'Trizma Base pH',

    # Environmental samples (9)
    'Pasteurized Seawater',
    'Seawater',
    'Enriched Seawater Medium',
    'Supplemented Seawater',
    'Organic Peat',
    'Natural sea-salt',
    'Sodium Metasilicate',
    'Sodium acetate',
    'Pea',

    # Vitamin solutions (3)
    'Vitamin B',
    'Biotin Vitamin Solution',
    'Thiamine Vitamin Solution',
]

def main():
    # Load unmapped ingredients
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'
    unmapped_file = mim_root / 'data/curated/unmapped_ingredients.yaml'

    with open(unmapped_file) as f:
        unmapped_data = yaml.safe_load(f)

    ingredients = unmapped_data.get('ingredients', [])

    # Extract Batch 2 items
    batch_2_items = []
    for ing in ingredients:
        name = ing.get('preferred_term', '')
        if name in BATCH_2_INGREDIENTS:
            batch_2_items.append(ing)

    print(f"Found {len(batch_2_items)} out of {len(BATCH_2_INGREDIENTS)} target items")

    # Create export structure
    export_data = {
        'metadata': {
            'batch_name': 'batch_2_biological_buffers_environmental',
            'total_terms': len(batch_2_items),
            'curation_date': '2026-03-27',
            'instructions': '''Curate using appropriate ontologies:

- Biological extracts: FOODON or CHEBI
- Buffers: CHEBI
- Environmental samples: ENVO (seawater, peat) or FOODON (food items)
- Vitamin solutions: CHEBI (specific vitamin terms)

For complex extracts, use FOODON when available, CHEBI as fallback.
'''
        },
        'ingredients': []
    }

    # Add ingredients with curation fields
    for idx, ing in enumerate(batch_2_items, 1):
        stats = ing.get('occurrence_statistics', {})

        export_data['ingredients'].append({
            'id': idx,
            'name': ing.get('preferred_term', 'Unknown'),
            'synonyms': ing.get('synonyms', []),
            'total_occurrences': stats.get('total_occurrences', 0),
            'sources': ing.get('sources', []),

            # Fields to fill in during curation
            'suggested_ontology_id': None,
            'suggested_ontology_label': None,
            'ontology_source': None,
            'confidence_score': None,
            'notes': None,
            'xrefs': [],
        })

    # Write output
    output_file = Path('workspace/curation/batch2_to_curate.yaml')
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        yaml.dump(export_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Exported to: {output_file}")
    print(f"\nNext steps:")
    print(f"1. Claude Code curates each ingredient")
    print(f"2. Save the curated file")
    print(f"3. Run: uv run python scripts/import_curated_ingredients.py \\")
    print(f"        --input {output_file} --threshold 0.85 --production")

if __name__ == '__main__':
    main()
