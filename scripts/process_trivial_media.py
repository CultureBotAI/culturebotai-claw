#!/usr/bin/env python3
"""Process trivial media (water, simple solutions) from Option C Phase 1.

Usage:
    python scripts/process_trivial_media.py --dry-run
    python scripts/process_trivial_media.py
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime


TRIVIAL_MEDIA = {
    'CultureMech:003010': {
        'file': 'data/normalized_yaml/bacterial/distilled_water.yaml',
        'name': 'distilled_water',
        'composition': {
            'description': 'Autoclaved distilled water',
            'ingredients': [
                {
                    'preferred_term': 'water',
                    'term': {
                        'id': 'CHEBI:15377',
                        'label': 'water'
                    },
                    'curation_metadata': {
                        'mapping_quality': 'MANUAL',
                        'confidence_score': 1.0,
                        'curation_date': datetime.now().isoformat(),
                        'ontology_source': 'CHEBI'
                    },
                    'notes': 'Autoclaved distilled water (trivial medium)',
                    'source': 'JCM Medium 664'
                }
            ]
        }
    }
}


def update_trivial_medium(medium_id: str, cm_root: Path, dry_run: bool = True) -> bool:
    """Update a trivial medium file with its simple composition."""

    if medium_id not in TRIVIAL_MEDIA:
        print(f"✗ Unknown trivial medium: {medium_id}")
        return False

    medium_data = TRIVIAL_MEDIA[medium_id]
    file_path = cm_root / medium_data['file']

    if not file_path.exists():
        print(f"✗ File not found: {file_path}")
        return False

    print(f"\nProcessing: {medium_id} ({medium_data['name']})")
    print(f"  File: {file_path}")
    print(f"  Description: {medium_data['composition']['description']}")

    if dry_run:
        print(f"  [DRY RUN] Would add {len(medium_data['composition']['ingredients'])} ingredient(s)")
        return True

    # Load existing file
    with open(file_path) as f:
        media = yaml.safe_load(f)

    # Update description
    media['description'] = medium_data['composition']['description']

    # Replace placeholder ingredients
    media['ingredients'] = medium_data['composition']['ingredients']

    # Update curation history
    if 'curation_history' not in media:
        media['curation_history'] = []

    media['curation_history'].append({
        'timestamp': datetime.now().isoformat(),
        'curator': 'process_trivial_media',
        'action': 'EXPANDED_TRIVIAL',
        'changes': f"Replaced placeholder with trivial composition ({len(medium_data['composition']['ingredients'])} ingredient)",
        'notes': 'Trivial medium (simple composition) - manually curated'
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
    media['data_quality_flags']['curation_method'] = 'manual_trivial'
    media['data_quality_flags']['trivial_medium'] = True

    # Save
    with open(file_path, 'w') as f:
        yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  ✓ Updated with {len(medium_data['composition']['ingredients'])} ingredient(s)")
    return True


def main():
    parser = argparse.ArgumentParser(description='Process trivial media')
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing files'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    print(f"Processing {len(TRIVIAL_MEDIA)} trivial media...")
    print("=" * 80)

    stats = {
        'total': len(TRIVIAL_MEDIA),
        'success': 0,
        'failed': 0
    }

    for medium_id in TRIVIAL_MEDIA.keys():
        if update_trivial_medium(medium_id, args.cm_root, args.dry_run):
            stats['success'] += 1
        else:
            stats['failed'] += 1

    # Print summary
    print("\n" + "=" * 80)
    print("TRIVIAL MEDIA PROCESSING SUMMARY")
    print("=" * 80)
    print(f"Total: {stats['total']}")
    print(f"Successful: {stats['success']}")
    print(f"Failed: {stats['failed']}")

    if not args.dry_run and stats['success'] > 0:
        print(f"\n✅ {stats['success']} trivial media updated")
    elif args.dry_run:
        print(f"\n⚠️  DRY RUN - No files were modified")

    return 0 if stats['failed'] == 0 else 1


if __name__ == '__main__':
    exit(main())
