#!/usr/bin/env python3
"""Expand Columbia Blood Agar media with Oxoid CM331 base composition.

Specifically handles media that reference "Oxoid CM331" in preparation steps.
Adds CM331 constituents plus blood additive.
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List


# Media IDs from Option C Phase 1 analysis
COLUMBIA_BLOOD_AGAR_MEDIA = [
    {
        'id': 'CultureMech:002614',
        'file': 'data/normalized_yaml/bacterial/columbia_blood_agar_with_5_sheep_blood.yaml',
        'blood_type': 'sheep blood',
        'blood_percent': '5',
        'blood_term': 'UBERON:0000178',  # blood
        'blood_label': 'blood'
    },
    {
        'id': 'CultureMech:002579',
        'file': 'data/normalized_yaml/bacterial/columbia_blood_agar_with_10_horse_blood.yaml',
        'blood_type': 'horse blood',
        'blood_percent': '10',
        'blood_term': 'UBERON:0000178',
        'blood_label': 'blood'
    },
    {
        'id': 'CultureMech:002933',
        'file': 'data/normalized_yaml/bacterial/columbia_blood_agar_with_5_rabbit_blood.yaml',
        'blood_type': 'rabbit blood',
        'blood_percent': '5',
        'blood_term': 'UBERON:0000178',
        'blood_label': 'blood'
    },
    {
        'id': 'CultureMech:002640',
        'file': 'data/normalized_yaml/bacterial/columbia_blood_agar_with_5_horse_blood.yaml',
        'blood_type': 'horse blood',
        'blood_percent': '5',
        'blood_term': 'UBERON:0000178',
        'blood_label': 'blood'
    }
]


def load_cm331_composition(composition_file: Path) -> List[Dict]:
    """Load Oxoid CM331 composition from YAML file."""
    with open(composition_file) as f:
        data = yaml.safe_load(f)

    return data['constituents']


def create_ingredients_list(cm331_constituents: List[Dict], blood_info: Dict) -> List[Dict]:
    """Create full ingredients list: CM331 base + blood."""
    ingredients = []

    # Add CM331 base constituents
    for constituent in cm331_constituents:
        ingredient = {
            'preferred_term': constituent['name'],
            'concentration': constituent.get('concentration', {}),
            'notes': f"From Oxoid CM331 (Columbia Agar Base); {constituent.get('notes', '')}",
            'source': 'Oxoid CM331'
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

    # Add blood additive
    blood_ingredient = {
        'preferred_term': f"Defibrinated {blood_info['blood_type']}",
        'term': {
            'id': blood_info['blood_term'],
            'label': blood_info['blood_label']
        },
        'concentration': {
            'value': blood_info['blood_percent'],
            'unit': 'PERCENT_V_V'
        },
        'curation_metadata': {
            'mapping_quality': 'MANUAL',
            'confidence_score': 1.0,
            'curation_date': datetime.now().isoformat(),
            'ontology_source': 'UBERON'
        },
        'notes': f"Added aseptically after autoclaving and cooling to 45-50°C; {blood_info['blood_percent']}% final concentration",
        'source': 'Blood additive to CM331 base'
    }
    ingredients.append(blood_ingredient)

    return ingredients


def expand_medium(medium_info: Dict, cm331_constituents: List[Dict], cm_root: Path, dry_run: bool = True) -> bool:
    """Expand a single Columbia Blood Agar medium."""
    file_path = cm_root / medium_info['file']

    if not file_path.exists():
        print(f"✗ File not found: {file_path}")
        return False

    print(f"\nProcessing: {medium_info['id']}")
    print(f"  File: {file_path.name}")
    print(f"  Blood: {medium_info['blood_percent']}% {medium_info['blood_type']}")

    if dry_run:
        print(f"  [DRY RUN] Would add {len(cm331_constituents) + 1} ingredients (7 CM331 + 1 blood)")
        return True

    # Load media file
    with open(file_path) as f:
        media = yaml.safe_load(f)

    # Create ingredients list
    ingredients = create_ingredients_list(cm331_constituents, medium_info)

    # Replace placeholder
    media['ingredients'] = ingredients

    # Update curation history
    if 'curation_history' not in media:
        media['curation_history'] = []

    media['curation_history'].append({
        'timestamp': datetime.now().isoformat(),
        'curator': 'expand_columbia_blood_agar',
        'action': 'EXPANDED_COMMERCIAL_PRODUCT',
        'changes': f"Replaced placeholder with Oxoid CM331 composition + {medium_info['blood_percent']}% {medium_info['blood_type']} ({len(ingredients)} ingredients)",
        'source': 'Oxoid CM331 + blood additive',
        'notes': f"Commercial product expansion: Columbia Agar Base (CM331) with {medium_info['blood_type']}"
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
    parser = argparse.ArgumentParser(description='Expand Columbia Blood Agar media')
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
        help='Path to CM331 composition file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing files'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    # Load CM331 composition
    print(f"Loading Oxoid CM331 composition from {args.composition}...")
    cm331_constituents = load_cm331_composition(args.composition)
    print(f"✓ Loaded {len(cm331_constituents)} CM331 constituents\n")

    print(f"Expanding {len(COLUMBIA_BLOOD_AGAR_MEDIA)} Columbia Blood Agar media...")
    print("=" * 80)

    stats = {
        'total': len(COLUMBIA_BLOOD_AGAR_MEDIA),
        'success': 0,
        'failed': 0
    }

    for medium_info in COLUMBIA_BLOOD_AGAR_MEDIA:
        if expand_medium(medium_info, cm331_constituents, args.cm_root, args.dry_run):
            stats['success'] += 1
        else:
            stats['failed'] += 1

    # Print summary
    print("\n" + "=" * 80)
    print("COLUMBIA BLOOD AGAR EXPANSION SUMMARY")
    print("=" * 80)
    print(f"Total media: {stats['total']}")
    print(f"Successful: {stats['success']}")
    print(f"Failed: {stats['failed']}")

    if not args.dry_run and stats['success'] > 0:
        print(f"\n✅ {stats['success']} Columbia Blood Agar media expanded")
        print("   Base: Oxoid CM331 (7 ingredients)")
        print("   Additive: Blood (1 ingredient)")
        print("   Total per medium: 8 ingredients")
    elif args.dry_run:
        print(f"\n⚠️  DRY RUN - No files were modified")

    return 0 if stats['failed'] == 0 else 1


if __name__ == '__main__':
    exit(main())
