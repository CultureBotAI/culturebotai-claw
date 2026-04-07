#!/usr/bin/env python3
"""Convert extracted unmapped ingredients to MediaIngredientMech collection format.

Usage:
    python scripts/convert_to_mim_format.py \
        --input workspace/curation/collection_media/extracted/pilot_002_validated_unmapped.yaml \
        --output workspace/curation/collection_media/extracted/pilot_002_mim_format.yaml
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime


def convert_to_mim_format(input_file: Path, output_file: Path) -> int:
    """
    Convert extracted unmapped ingredients to MediaIngredientMech collection format.

    Returns: Number of ingredients converted
    """
    # Load extracted ingredients
    print(f"Loading extracted ingredients from {input_file}")
    with open(input_file) as f:
        data = yaml.safe_load(f)

    unmapped = data.get('unmapped_ingredients', [])
    print(f"Found {len(unmapped)} unmapped ingredients\n")

    # Convert to MediaIngredientMech collection format
    ingredients = []

    for i, ing in enumerate(unmapped, 1):
        ingredient = {
            'ontology_id': f'UNMAPPED_{i:04d}',
            'identifier': f'UNMAPPED_{i:04d}',
            'preferred_term': ing['preferred_term'],
            'synonyms': [
                {
                    'synonym_text': syn,
                    'synonym_type': 'RAW_TEXT',
                    'source': 'CultureMech_CollectionMedia'
                }
                for syn in ing.get('synonyms', [])
            ],
            'mapping_status': 'UNMAPPED',
            'occurrence_statistics': {
                'total_occurrences': ing['occurrence_count'],
                'media_count': len(set(ing.get('media_sources', []))),
                'sample_media': ing.get('media_sources', [])[:10]
            },
            'curation_history': [
                {
                    'timestamp': datetime.now().isoformat(),
                    'curator': 'extract_unmapped_ingredients',
                    'action': 'IMPORTED',
                    'changes': 'Imported from collection media extraction',
                    'source': 'CultureMech_CollectionMedia'
                }
            ],
            'notes': f'Extracted from {len(set(ing.get("media_sources", [])))} collection media files'
        }

        # Add sample concentrations if available
        if ing.get('sample_concentrations'):
            sample_conc = ing['sample_concentrations'][0]
            ingredient['notes'] += f' | Example concentration: {sample_conc["value"]} {sample_conc["unit"]}'

        ingredients.append(ingredient)

    # Create MediaIngredientMech collection format
    output_data = {
        'generation_date': datetime.now().isoformat(),
        'total_count': len(ingredients),
        'mapped_count': 0,
        'unmapped_count': len(ingredients),
        'source': 'CultureMech Collection Media (CCAP/JCM)',
        'ingredients': ingredients
    }

    # Save output
    with open(output_file, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"✓ Converted {len(ingredients)} ingredients")
    print(f"✓ Saved to {output_file}")

    return len(ingredients)


def main():
    parser = argparse.ArgumentParser(
        description='Convert extracted ingredients to MediaIngredientMech format'
    )
    parser.add_argument(
        '--input',
        type=Path,
        required=True,
        help='Input extracted unmapped YAML'
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Output MediaIngredientMech collection YAML'
    )

    args = parser.parse_args()

    # Convert
    count = convert_to_mim_format(args.input, args.output)

    # Summary
    print("\n" + "=" * 80)
    print("CONVERSION SUMMARY")
    print("=" * 80)
    print(f"Ingredients converted: {count}")
    print(f"\n✅ Ready for MediaIngredientMech batch curation")
    print(f"\nNext command:")
    print(f"cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech")
    print(f"python scripts/batch_curate.py \\")
    print(f"    --batch-size 150 \\")
    print(f"    --auto-accept-threshold 0.9 \\")
    print(f"    --data-path ../culturebotai-claw/{args.output} \\")
    print(f"    --sources CHEBI,FOODON,ENVO,UBERON")

    return 0


if __name__ == '__main__':
    exit(main())
