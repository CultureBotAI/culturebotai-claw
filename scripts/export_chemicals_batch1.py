#!/usr/bin/env python3
"""
Export Batch 1 chemical ingredients for Claude Code curation.

Batch 1 includes:
- Simple chemicals with clear formulas (14 items)
- Incomplete formulas needing correction (15 items)
- Water variants (3 items)
- Duplicate entries to merge (2 items)

Total: 34 items
"""

import sys
import yaml
from pathlib import Path

# Batch 1 target ingredients
BATCH_1_CHEMICALS = [
    # Simple chemicals (14)
    'CaCl2•2H2O',
    'CaSO4•2H2O',
    'CaSO4•2H2Osaturated solution',
    'KCl',
    'NaCl',
    'MgSO4•7H2O',
    'Na2SiO3•9H2O',
    'Na2EDTA•2H2O',
    'Na2HPO4•7H2O',
    'NaH2PO4•H2O',
    'NH4Cl',
    'Citric Acid•H2O',
    'Glucose',
    'Glycylglycine',

    # Incomplete formulas (15)
    'Ca',
    'H3BO',
    'KNO',
    'NaHCO',
    'KH2PO',
    'K2HPO',
    'MgCO',
    'NH4MgPO',
    'NH4NO',
    'CaCO',
    'Na2CO',
    'FE EDTA',
    'Original amount: (NH4)2HPO4(Fisher A686)',
    'Original amount: (NH4)2SO4(Fisher A 702)',
    'Ferric Ammonium Citrate',

    # Water variants (3)
    'dH2O',
    'sterile dH2O',
    'Sterile dH2O',

    # Special chemicals with duplicates (4, will dedupe to 2)
    'Sodium Thiosulfate Pentahydrate',
    'Na2Glycerophosphate.5H2O',
    'Na2glycerophosphate•5H2O',
    'Na2Glycerophosphate•5H2O',
]

def main():
    # Load unmapped ingredients
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'
    unmapped_file = mim_root / 'data/curated/unmapped_ingredients.yaml'

    with open(unmapped_file) as f:
        unmapped_data = yaml.safe_load(f)

    ingredients = unmapped_data.get('ingredients', [])

    # Extract Batch 1 items
    batch_1_items = []
    for ing in ingredients:
        name = ing.get('preferred_term', '')
        if name in BATCH_1_CHEMICALS:
            batch_1_items.append(ing)

    print(f"Found {len(batch_1_items)} out of {len(BATCH_1_CHEMICALS)} target items")

    # Create export structure
    export_data = {
        'metadata': {
            'batch_name': 'chemicals_batch_1',
            'total_terms': len(batch_1_items),
            'curation_date': '2026-03-27',
            'instructions': '''Curate using CHEBI (Chemical Entities of Biological Interest) as primary ontology.

For incomplete formulas (missing subscripts):
- Use synonyms or context to infer complete formula
- Example: KNO → KNO3 (potassium nitrate)
- Example: H3BO → H3BO3 (boric acid)

For water variants:
- All map to CHEBI:15377 (water)
- Note processing in curation notes

For duplicates:
- Identify canonical form
- Mark variants for merging
'''
        },
        'ingredients': []
    }

    # Add ingredients with curation fields
    for idx, ing in enumerate(batch_1_items, 1):
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
    output_file = Path('workspace/curation/chemicals_batch1_to_curate.yaml')
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        yaml.dump(export_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Exported to: {output_file}")
    print(f"\nNext steps:")
    print(f"1. Claude Code curates each ingredient (CHEBI mappings)")
    print(f"2. Save the curated file")
    print(f"3. Run: uv run python scripts/import_curated_ingredients.py \\")
    print(f"        --input {output_file} --threshold 0.85 --production")

if __name__ == '__main__':
    main()
