#!/usr/bin/env python3
"""Extract valid media from validation results.

Filters validated_media_complete.yaml to extract only valid media with composition data,
formatting output for use with batch_process_collection_media.py pipeline.

Usage:
    python scripts/extract_valid_media.py \
        --input workspace/commercial_expansions/validated_media_complete.yaml \
        --output workspace/commercial_expansions/valid_media_only.yaml
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime


def extract_valid_media(input_file: Path, output_file: Path) -> int:
    """
    Extract valid media from validation results.

    Args:
        input_file: Path to validated_media_complete.yaml
        output_file: Path to output valid_media_only.yaml

    Returns:
        Number of valid media extracted
    """
    # Load validation results
    print(f"Loading validation results from {input_file}")
    with open(input_file) as f:
        data = yaml.safe_load(f)

    metadata = data.get('metadata', {})
    valid_media = data.get('valid_media', [])
    invalid_media = data.get('invalid_media', [])

    print(f"Found {len(valid_media)} valid media")
    print(f"Found {len(invalid_media)} invalid media")
    print()

    if not valid_media:
        print("⚠️  No valid media found in validation results")
        return 0

    # Process valid media for pipeline format
    processed_media = []

    for media in valid_media:
        # Remove validation metadata (not needed for pipeline)
        media_clean = media.copy()
        media_clean.pop('validation', None)

        # Add has_placeholder flag for expand stage
        media_clean['has_placeholder'] = True

        processed_media.append(media_clean)

    # Count by source type
    ccap_count = sum(1 for m in processed_media if m.get('supplier') == 'CCAP')
    jcm_count = sum(1 for m in processed_media if m.get('supplier') == 'JCM')
    other_count = len(processed_media) - ccap_count - jcm_count

    print(f"Breakdown by source:")
    print(f"  - CCAP PDFs: {ccap_count}")
    print(f"  - JCM media: {jcm_count}")
    if other_count > 0:
        print(f"  - Other: {other_count}")
    print()

    # Create output structure
    output_data = {
        'metadata': {
            'scan_date': datetime.now().isoformat(),
            'total_identified': len(processed_media),
            'high_priority': len(processed_media),
            'source': 'Filtered from validated_media_complete.yaml',
            'validation_date': metadata.get('validation_date'),
            'original_total': metadata.get('total_validated'),
            'filter_criteria': 'valid=True, has composition data'
        },
        'high_priority': processed_media
    }

    # Save output
    with open(output_file, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"✓ Saved {len(processed_media)} valid media to {output_file}")

    return len(processed_media)


def main():
    parser = argparse.ArgumentParser(
        description='Extract valid media from validation results'
    )
    parser.add_argument(
        '--input',
        type=Path,
        default=Path('workspace/commercial_expansions/validated_media_complete.yaml'),
        help='Input validation results YAML'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/commercial_expansions/valid_media_only.yaml'),
        help='Output valid media YAML'
    )

    args = parser.parse_args()

    # Extract valid media
    count = extract_valid_media(args.input, args.output)

    # Summary
    print("\n" + "=" * 80)
    print("EXTRACTION SUMMARY")
    print("=" * 80)
    print(f"Valid media extracted: {count}")

    if count > 0:
        print(f"\n✅ Ready for pilot run")
        print(f"\nNext command:")
        print(f"python scripts/batch_process_collection_media.py \\")
        print(f"    --batch-id pilot_002_validated \\")
        print(f"    --batch-size {count} \\")
        print(f"    --input {args.output}")
    else:
        print(f"\n⚠️  No valid media to process")

    return 0


if __name__ == '__main__':
    exit(main())
