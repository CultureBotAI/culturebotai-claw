#!/usr/bin/env python3
"""Expand Blood Agar with BD-Difco Blood Agar Base composition.

Handles medium that references "Blood agar base (BD-Difco)" in preparation steps.
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List


BLOOD_AGAR_MEDIUM = {
    'id': 'CultureMech:003056',
    'file': 'data/normalized_yaml/bacterial/blood_agar.yaml'
}


def load_composition(composition_file: Path) -> List[Dict]:
    """Load BD-Difco Blood Agar Base composition from YAML file."""
    with open(composition_file) as f:
        data = yaml.safe_load(f)

    return data['constituents']


def create_ingredients_list(constituents: List[Dict]) -> List[Dict]:
    """Convert constituents to CultureMech ingredient format."""
    ingredients = []

    # Add base constituents
    for constituent in constituents:
        ingredient = {
            'preferred_term': constituent['name'],
            'notes': f"From BD-Difco Blood Agar Base (211037); {constituent.get('notes', '')}",
            'source': 'BD BBL 211037'
        }

        # Add concentration
        if 'concentration' in constituent:
            ingredient['concentration'] = constituent['concentration']

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

    # Add blood additive (5% rabbit blood per JCM preparation)
    blood_ingredient = {
        'preferred_term': 'Defibrinated rabbit blood',
        'term': {
            'id': 'UBERON:0000178',
            'label': 'blood'
        },
        'concentration': {
            'value': '5',
            'unit': 'PERCENT_V_V'
        },
        'curation_metadata': {
            'mapping_quality': 'MANUAL',
            'confidence_score': 1.0,
            'curation_date': datetime.now().isoformat(),
            'ontology_source': 'UBERON'
        },
        'notes': 'Added aseptically after autoclaving and cooling to 45°C; 5% final concentration',
        'source': 'Blood additive per JCM preparation'
    }
    ingredients.append(blood_ingredient)

    return ingredients


def expand_medium(constituents: List[Dict], cm_root: Path, dry_run: bool = True) -> bool:
    """Expand the Blood Agar medium."""
    file_path = cm_root / BLOOD_AGAR_MEDIUM['file']

    if not file_path.exists():
        print(f"✗ File not found: {file_path}")
        return False

    print(f"\nProcessing: {BLOOD_AGAR_MEDIUM['id']}")
    print(f"  File: {file_path.name}")
    print(f"  Product: BD-Difco Blood Agar Base (211037)")
    print(f"  Blood: 5% rabbit blood")

    if dry_run:
        print(f"  [DRY RUN] Would add {len(constituents) + 1} ingredients (5 base + 1 blood)")
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
        'curator': 'expand_blood_agar',
        'action': 'EXPANDED_COMMERCIAL_PRODUCT',
        'changes': f"Replaced placeholder with BD-Difco Blood Agar Base composition + 5% rabbit blood ({len(ingredients)} ingredients)",
        'source': 'BD BBL 211037 + rabbit blood',
        'notes': 'Commercial product expansion: BD-Difco Blood Agar Base (Infusion Agar) with rabbit blood'
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
    parser = argparse.ArgumentParser(description='Expand Blood Agar medium')
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--composition',
        type=Path,
        default=Path('workspace/commercial_expansions/bd_difco_blood_agar_base_composition.yaml'),
        help='Path to BD-Difco Blood Agar Base composition file'
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
    print(f"Loading BD-Difco Blood Agar Base composition from {args.composition}...")
    constituents = load_composition(args.composition)
    print(f"✓ Loaded {len(constituents)} constituents\n")

    print("Expanding Blood Agar medium...")
    print("=" * 80)

    success = expand_medium(constituents, args.cm_root, args.dry_run)

    # Print summary
    print("\n" + "=" * 80)
    print("BLOOD AGAR EXPANSION SUMMARY")
    print("=" * 80)
    if success:
        print("✅ Blood Agar medium expanded")
        if not args.dry_run:
            print(f"   Product: BD-Difco Blood Agar Base (211037)")
            print(f"   Base ingredients: {len(constituents)}")
            print(f"   Blood additive: 1 (5% rabbit blood)")
            print(f"   Total: {len(constituents) + 1} ingredients")
        else:
            print("⚠️  DRY RUN - No files were modified")
    else:
        print("✗ Failed to expand medium")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
