#!/usr/bin/env python3
"""Expand Lowenstein-Jensen Medium with BD 220908 composition.

Handles medium that references "BD 220908" in preparation steps.
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List


LOWENSTEIN_JENSEN_MEDIUM = {
    'id': 'CultureMech:003059',
    'file': 'data/normalized_yaml/bacterial/lowenstein_jensen_medium.yaml'
}


def load_composition(composition_file: Path) -> List[Dict]:
    """Load BD 220908 composition from YAML file."""
    with open(composition_file) as f:
        data = yaml.safe_load(f)

    return data['constituents']


def create_ingredients_list(constituents: List[Dict]) -> List[Dict]:
    """Convert constituents to CultureMech ingredient format."""
    ingredients = []

    for constituent in constituents:
        ingredient = {
            'preferred_term': constituent['name'],
            'notes': f"From BD 220908 (Lowenstein-Jensen Medium); {constituent.get('notes', '')}",
            'source': 'BD 220908'
        }

        # Add concentration or amount
        if 'concentration' in constituent:
            ingredient['concentration'] = constituent['concentration']
        elif 'amount' in constituent:
            ingredient['notes'] = f"{constituent['amount']}; " + ingredient['notes']

        # Add ontology term
        if 'ontology_id' in constituent:
            ingredient['term'] = {
                'id': constituent['ontology_id'],
                'label': constituent['ontology_label']
            }
            ingredient['curation_metadata'] = {
                'mapping_quality': 'MANUAL',
                'confidence_score': 1.0,
                'curation_date': datetime.now().isoformat(),
                'ontology_source': constituent['ontology_source']
            }

        ingredients.append(ingredient)

    return ingredients


def expand_medium(constituents: List[Dict], cm_root: Path, dry_run: bool = True) -> bool:
    """Expand the Lowenstein-Jensen medium."""
    file_path = cm_root / LOWENSTEIN_JENSEN_MEDIUM['file']

    if not file_path.exists():
        print(f"✗ File not found: {file_path}")
        return False

    print(f"\nProcessing: {LOWENSTEIN_JENSEN_MEDIUM['id']}")
    print(f"  File: {file_path.name}")
    print(f"  Product: BD 220908 (Lowenstein-Jensen Medium)")

    if dry_run:
        print(f"  [DRY RUN] Would add {len(constituents)} ingredients")
        return True

    # Load media file
    with open(file_path) as f:
        media = yaml.safe_load(f)

    # Create ingredients list
    ingredients = create_ingredients_list(constituents)

    # Replace placeholder
    media['ingredients'] = ingredients

    # Update curation history
    if 'curation_history' not in media:
        media['curation_history'] = []

    media['curation_history'].append({
        'timestamp': datetime.now().isoformat(),
        'curator': 'expand_lowenstein_jensen',
        'action': 'EXPANDED_COMMERCIAL_PRODUCT',
        'changes': f"Replaced placeholder with BD 220908 composition ({len(ingredients)} ingredients)",
        'source': 'BD 220908 (Lowenstein-Jensen Medium)',
        'notes': 'Commercial product expansion: BD Lowenstein-Jensen Medium ready-to-use slants'
    })

    # Update data quality flags
    if 'data_quality_flags' not in media:
        media['data_quality_flags'] = {}
    elif isinstance(media['data_quality_flags'], list):
        old_flags = media['data_quality_flags']
        media['data_quality_flags'] = {flag: True for flag in old_flags}

    media['data_quality_flags']['incomplete_composition'] = False
    media['data_quality_flags']['has_ontology_mappings'] = True
    media['data_quality_flags']['ingredients_curated'] = True
    media['data_quality_flags']['commercial_product'] = True

    # Save
    with open(file_path, 'w') as f:
        yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  ✓ Expanded with {len(ingredients)} ingredients")
    return True


def main():
    parser = argparse.ArgumentParser(description='Expand Lowenstein-Jensen Medium')
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--composition',
        type=Path,
        default=Path('workspace/commercial_expansions/lowenstein_jensen_composition.yaml'),
        help='Path to BD 220908 composition file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing files'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    # Load composition
    print(f"Loading BD 220908 composition from {args.composition}...")
    constituents = load_composition(args.composition)
    print(f"✓ Loaded {len(constituents)} constituents\n")

    print("Expanding Lowenstein-Jensen Medium...")
    print("=" * 80)

    success = expand_medium(constituents, args.cm_root, args.dry_run)

    # Print summary
    print("\n" + "=" * 80)
    print("LOWENSTEIN-JENSEN EXPANSION SUMMARY")
    print("=" * 80)
    if success:
        print("✅ Lowenstein-Jensen Medium expanded")
        if not args.dry_run:
            print(f"   Product: BD 220908")
            print(f"   Ingredients: {len(constituents)}")
        else:
            print("⚠️  DRY RUN - No files were modified")
    else:
        print("✗ Failed to expand medium")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
