#!/usr/bin/env python3
"""Resolve Option C Phase 1 reference media by copying compositions.

Handles media that reference other JCM media (e.g., "Use Medium No. 284").
Similar to copy_referenced_compositions.py but for Option C Phase 1 media.

Usage:
    python scripts/resolve_option_c_references.py --dry-run
    python scripts/resolve_option_c_references.py
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def load_reference_media(reference_file: Path) -> list:
    """Load reference media from YAML file."""
    with open(reference_file) as f:
        data = yaml.safe_load(f)

    return data['reference_media']


def build_media_index(cm_root: Path) -> dict:
    """Build index of JCM medium numbers to file paths."""
    print("Building media index...")
    data_dir = cm_root / 'data' / 'normalized_yaml'
    index = {}

    for yaml_file in data_dir.rglob('*.yaml'):
        try:
            with open(yaml_file) as f:
                media = yaml.safe_load(f)

            if not media:
                continue

            media_term_id = media.get('media_term', {}).get('term', {}).get('id', '')

            # Extract JCM medium number
            if media_term_id.startswith('mediadive.medium:J'):
                medium_num = media_term_id.replace('mediadive.medium:J', '')
                index[medium_num] = yaml_file

        except Exception:
            continue

    print(f"✓ Indexed {len(index)} JCM media\n")
    return index


def build_id_index(cm_root: Path) -> dict:
    """Build index of CultureMech IDs to file paths."""
    print("Building ID index...")
    data_dir = cm_root / 'data' / 'normalized_yaml'
    index = {}

    for yaml_file in data_dir.rglob('*.yaml'):
        try:
            with open(yaml_file) as f:
                media = yaml.safe_load(f)

            if media and media.get('id'):
                index[media['id']] = yaml_file
        except:
            continue

    print(f"✓ Indexed {len(index)} CultureMech IDs\n")
    return index


def copy_composition(source_media: dict, target_media: dict, modifications: str = None) -> tuple:
    """
    Copy composition from source to target media.

    Args:
        source_media: Source medium with ingredients
        target_media: Target medium to update
        modifications: Optional description of modifications from reference

    Returns: (updated_target, ingredient_count)
    """
    source_ingredients = source_media.get('ingredients', [])

    if not source_ingredients:
        return target_media, 0

    # Deep copy ingredients
    target_media['ingredients'] = []
    for ing in source_ingredients:
        new_ing = ing.copy()

        # Handle nested dicts
        if 'term' in new_ing and isinstance(new_ing['term'], dict):
            new_ing['term'] = new_ing['term'].copy()
        if 'concentration' in new_ing and isinstance(new_ing['concentration'], dict):
            new_ing['concentration'] = new_ing['concentration'].copy()
        if 'curation_metadata' in new_ing and isinstance(new_ing['curation_metadata'], dict):
            new_ing['curation_metadata'] = new_ing['curation_metadata'].copy()

        # Add provenance note
        source_id = source_media.get('media_term', {}).get('term', {}).get('id', '')
        source_num = source_id.replace('mediadive.medium:J', '') if source_id else 'UNKNOWN'

        if modifications:
            note_text = f"Copied from referenced JCM Medium {source_num} with modifications: {modifications}"
        else:
            note_text = f"Copied from referenced JCM Medium {source_num}"

        if 'notes' in new_ing:
            new_ing['notes'] += f" | {note_text}"
        else:
            new_ing['notes'] = note_text

        target_media['ingredients'].append(new_ing)

    # Update curation history
    if 'curation_history' not in target_media:
        target_media['curation_history'] = []

    source_id = source_media.get('id', 'UNKNOWN')
    source_name = source_media.get('name', 'UNKNOWN')

    target_media['curation_history'].append({
        'timestamp': datetime.now().isoformat(),
        'curator': 'resolve_option_c_references',
        'action': 'RESOLVED_REFERENCE',
        'changes': f'Copied composition from referenced medium ({len(source_ingredients)} ingredients)',
        'source': source_id,
        'notes': f'Resolved reference by copying from {source_name} ({source_id})' + (f' with modifications: {modifications}' if modifications else '')
    })

    # Update data quality flags
    if 'data_quality_flags' not in target_media:
        target_media['data_quality_flags'] = {}
    elif isinstance(target_media['data_quality_flags'], list):
        old_flags = target_media['data_quality_flags']
        target_media['data_quality_flags'] = {flag: True for flag in old_flags}

    target_media['data_quality_flags']['resolved_reference'] = True
    target_media['data_quality_flags']['incomplete_composition'] = False

    return target_media, len(source_ingredients)


def resolve_references(references: list, cm_root: Path, dry_run: bool = True) -> dict:
    """Resolve all reference media by copying compositions."""
    stats = {
        'total': len(references),
        'resolved': 0,
        'not_found': 0,
        'no_composition': 0,
        'errors': 0,
        'total_ingredients': 0
    }

    resolved_list = []
    not_found_list = []

    # Group by target
    by_target = defaultdict(list)
    for ref in references:
        target_num = ref['references']
        by_target[target_num].append(ref)

    print(f"Processing {len(references)} references to {len(by_target)} unique media...\n")

    # Build indexes
    media_index = build_media_index(cm_root)
    id_index = build_id_index(cm_root)

    # Process each target
    for target_num in sorted(by_target.keys(), key=lambda x: int(x)):
        refs = by_target[target_num]
        print(f"Medium {target_num} (referenced by {len(refs)} media):")

        # Find target medium
        target_file = media_index.get(target_num)

        if not target_file:
            print(f"  ⚠️  Target medium not found in CultureMech")
            stats['not_found'] += len(refs)
            not_found_list.extend(refs)
            for ref in refs:
                print(f"    - {ref['id']:25s} {ref['name']}")
            continue

        # Load target
        with open(target_file) as f:
            target_media = yaml.safe_load(f)

        if not target_media:
            stats['errors'] += len(refs)
            continue

        target_ingredients = target_media.get('ingredients', [])
        if not target_ingredients:
            print(f"  ⚠️  Target has no ingredients: {target_file.name}")
            stats['no_composition'] += len(refs)
            continue

        print(f"  ✓ Found target: {target_file.name} ({len(target_ingredients)} ingredients)")

        # Copy to each referencing medium
        for ref in refs:
            ref_file = id_index.get(ref['id'])

            if not ref_file:
                print(f"    ✗ Reference file not found: {ref['id']}")
                stats['errors'] += 1
                continue

            # Load referencing medium
            with open(ref_file) as f:
                ref_media = yaml.safe_load(f)

            if not ref_media:
                stats['errors'] += 1
                continue

            # Copy composition
            updated_media, ing_count = copy_composition(target_media, ref_media)

            print(f"    ✓ {ref['id']:25s} {ref['name']:50s} ({ing_count} ingredients)")

            # Save if not dry-run
            if not dry_run:
                with open(ref_file, 'w') as f:
                    yaml.dump(updated_media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            stats['resolved'] += 1
            stats['total_ingredients'] += ing_count
            resolved_list.append({
                'ref': ref,
                'target': target_media.get('id'),
                'ingredients': ing_count
            })

        print()

    return {
        'stats': stats,
        'resolved': resolved_list,
        'not_found': not_found_list
    }


def main():
    parser = argparse.ArgumentParser(description='Resolve Option C reference media')
    parser.add_argument(
        '--reference-file',
        type=Path,
        default=Path('workspace/curation/option_c_reference_media.yaml'),
        help='Path to reference media file'
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

    # Load references
    print(f"Loading references from {args.reference_file}...")
    references = load_reference_media(args.reference_file)
    print(f"✓ Found {len(references)} reference media\n")

    # Resolve
    result = resolve_references(references, args.cm_root, args.dry_run)
    stats = result['stats']

    # Print summary
    print("=" * 80)
    print("REFERENCE RESOLUTION SUMMARY")
    print("=" * 80)
    print(f"Total references: {stats['total']}")
    print(f"Resolved: {stats['resolved']}")
    print(f"Target not found: {stats['not_found']}")
    print(f"No composition: {stats['no_composition']}")
    print(f"Errors: {stats['errors']}")
    print()
    print(f"Total ingredients copied: {stats['total_ingredients']}")

    if stats['resolved'] > 0:
        avg = stats['total_ingredients'] / stats['resolved']
        print(f"Average ingredients per medium: {avg:.1f}")

    if not args.dry_run:
        print(f"\n✅ {stats['resolved']} media updated")
    else:
        print(f"\n⚠️  DRY RUN - No files were modified")

    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    exit(main())
