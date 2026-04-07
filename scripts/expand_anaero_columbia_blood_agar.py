#!/usr/bin/env python3
"""Expand Anaero Columbia Agar with rabbit blood.

This medium uses Columbia Agar base (similar to Oxoid CM331) with rabbit blood,
prepared for anaerobic incubation. Since the specific BD-BBL "Anaero Columbia Agar"
product is not available, we use standard Columbia Agar Base composition.
"""

import yaml
from pathlib import Path
from datetime import datetime


def load_columbia_base_composition(composition_file: Path) -> list:
    """Load Columbia Agar Base composition."""
    with open(composition_file) as f:
        data = yaml.safe_load(f)
    return data['constituents']


def create_ingredients_list(constituents: list) -> list:
    """Create ingredients list with Columbia base + rabbit blood."""
    ingredients = []

    # Add Columbia base constituents
    for constituent in constituents:
        ingredient = {
            'preferred_term': constituent['name'],
            'concentration': constituent.get('concentration', {}),
            'notes': f"From Columbia Agar Base (for anaerobic use); {constituent.get('notes', '')}",
            'source': 'Columbia Agar Base (Oxoid CM331 equivalent)'
        }

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

    # Add rabbit blood additive
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
        'notes': 'Added aseptically after autoclaving and cooling to 45-50°C; 5% final concentration for anaerobic cultivation',
        'source': 'Blood additive for anaerobic Columbia Agar'
    }
    ingredients.append(blood_ingredient)

    return ingredients


def expand_medium(constituents: list, cm_root: Path, dry_run: bool = True) -> bool:
    """Expand the Anaero Columbia Agar medium."""

    medium_info = {
        'id': 'CultureMech:003036',
        'file': 'data/normalized_yaml/bacterial/anaero_columbia_agar_with_rabbit_blood.yaml'
    }

    file_path = cm_root / medium_info['file']

    if not file_path.exists():
        print(f"✗ File not found: {file_path}")
        return False

    print(f"\nProcessing: {medium_info['id']}")
    print(f"  File: {file_path.name}")
    print(f"  Base: Columbia Agar Base (for anaerobic use)")
    print(f"  Blood: 5% rabbit blood")

    if dry_run:
        print(f"  [DRY RUN] Would add {len(constituents) + 1} ingredients (7 base + 1 blood)")
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
        'curator': 'expand_anaero_columbia_blood_agar',
        'action': 'EXPANDED_COMMERCIAL_PRODUCT',
        'changes': f"Replaced placeholder with Columbia Agar Base composition + 5% rabbit blood ({len(ingredients)} ingredients)",
        'source': 'Columbia Agar Base + rabbit blood',
        'notes': 'BD-BBL Anaero Columbia Agar product not found in current catalogs; using standard Columbia Agar Base composition. Anaerobic cultivation achieved through incubation conditions rather than medium composition differences.'
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
    import argparse

    parser = argparse.ArgumentParser(description='Expand Anaero Columbia Blood Agar')
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--composition',
        type=Path,
        default=Path('workspace/commercial_expansions/columbia_agar_base_composition.yaml'),
        help='Path to Columbia Agar Base composition file'
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
    print(f"Loading Columbia Agar Base composition from {args.composition}...")
    constituents = load_columbia_base_composition(args.composition)
    print(f"✓ Loaded {len(constituents)} constituents\n")

    print("Expanding Anaero Columbia Blood Agar...")
    print("=" * 80)

    success = expand_medium(constituents, args.cm_root, args.dry_run)

    # Print summary
    print("\n" + "=" * 80)
    print("ANAERO COLUMBIA BLOOD AGAR EXPANSION SUMMARY")
    print("=" * 80)
    if success:
        print("✅ Anaero Columbia Blood Agar expanded")
        if not args.dry_run:
            print(f"   Base: Columbia Agar Base (7 ingredients)")
            print(f"   Blood: Rabbit blood (1 ingredient)")
            print(f"   Total: {len(constituents) + 1} ingredients")
            print(f"   Note: Anaerobic conditions achieved via incubation environment")
        else:
            print("⚠️  DRY RUN - No files were modified")
    else:
        print("✗ Failed to expand medium")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
