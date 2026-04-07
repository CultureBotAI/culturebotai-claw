#!/usr/bin/env python3
"""Mark media with unavailable source information.

For media where the source database/supplier has no composition information,
update them with appropriate flags and notes indicating data unavailability.
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime


def mark_unavailable_media(media_list: list, cm_root: Path, dry_run: bool = True) -> dict:
    """Mark media as having unavailable source information."""

    stats = {
        'total': len(media_list),
        'updated': 0,
        'already_marked': 0,
        'errors': 0
    }

    for medium in media_list:
        try:
            file_path = cm_root / medium['file']

            if not file_path.exists():
                print(f"✗ File not found: {medium['id']} - {file_path}")
                stats['errors'] += 1
                continue

            # Load media
            with open(file_path) as f:
                media = yaml.safe_load(f)

            # Check if already marked
            flags = media.get('data_quality_flags', {})
            if isinstance(flags, dict) and flags.get('source_information_unavailable'):
                print(f"  ⊙ {medium['id']:25s} Already marked")
                stats['already_marked'] += 1
                continue

            print(f"  ✓ {medium['id']:25s} {medium['name']}")

            if not dry_run:
                # Update ingredients to have a clear note
                if 'ingredients' in media and len(media['ingredients']) > 0:
                    placeholder = media['ingredients'][0]
                    if 'preferred_term' in placeholder and 'PLACEHOLDER' in placeholder.get('preferred_term', ''):
                        placeholder['preferred_term'] = 'Composition information not available'
                        placeholder['notes'] = f"Source database has no composition information for this medium. Reason: {medium.get('description', 'Not found')}"

                # Update curation history
                if 'curation_history' not in media:
                    media['curation_history'] = []

                media['curation_history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'curator': 'mark_unavailable_media',
                    'action': 'MARKED_UNAVAILABLE',
                    'changes': 'Marked as source_information_unavailable',
                    'notes': f"Source database has no composition data. Category: {medium.get('type', 'UNKNOWN')}. {medium.get('description', '')}"
                })

                # Update data quality flags
                if 'data_quality_flags' not in media:
                    media['data_quality_flags'] = {}
                elif isinstance(media['data_quality_flags'], list):
                    old_flags = media['data_quality_flags']
                    media['data_quality_flags'] = {flag: True for flag in old_flags}

                media['data_quality_flags']['source_information_unavailable'] = True
                media['data_quality_flags']['incomplete_composition'] = True

                # Save
                with open(file_path, 'w') as f:
                    yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            stats['updated'] += 1

        except Exception as e:
            print(f"✗ Error processing {medium['id']}: {e}")
            stats['errors'] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description='Mark media with unavailable source information')
    parser.add_argument(
        '--scan-file',
        type=Path,
        default=Path('workspace/curation/option_c_remaining_scan.yaml'),
        help='Path to scan results file'
    )
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

    # Load scan results
    print(f"Loading scan results from {args.scan_file}...")
    with open(args.scan_file) as f:
        scan_data = yaml.safe_load(f)

    # Collect all non-recoverable media
    unavailable_media = []

    # Empty/Not found (33 media)
    unavailable_media.extend(scan_data.get('empty', []))

    # Commercial - not recoverable (Eiken)
    for medium in scan_data.get('commercial', []):
        if not medium.get('recoverable', False):
            unavailable_media.append(medium)

    # Unknown format
    unavailable_media.extend(scan_data.get('unknown', []))

    print(f"✓ Found {len(unavailable_media)} media to mark\n")

    # Breakdown
    empty_count = len(scan_data.get('empty', []))
    commercial_count = sum(1 for m in scan_data.get('commercial', []) if not m.get('recoverable', False))
    unknown_count = len(scan_data.get('unknown', []))

    print(f"Breakdown:")
    print(f"  - Empty/Not found: {empty_count}")
    print(f"  - Commercial (unavailable): {commercial_count}")
    print(f"  - Unknown format: {unknown_count}")
    print()

    print("=" * 80)
    print("MARKING MEDIA WITH UNAVAILABLE SOURCE INFORMATION")
    print("=" * 80)

    stats = mark_unavailable_media(unavailable_media, args.cm_root, args.dry_run)

    # Print summary
    print("\n" + "=" * 80)
    print("MARK UNAVAILABLE SUMMARY")
    print("=" * 80)
    print(f"Total media: {stats['total']}")
    print(f"Updated: {stats['updated']}")
    print(f"Already marked: {stats['already_marked']}")
    print(f"Errors: {stats['errors']}")

    if not args.dry_run:
        print(f"\n✅ {stats['updated']} media marked as source_information_unavailable")
    else:
        print(f"\n⚠️  DRY RUN - No files were modified")

    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    exit(main())
