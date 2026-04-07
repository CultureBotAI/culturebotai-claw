#!/usr/bin/env python3
"""Copy compositions from referenced media to referencing media.

Resolves media that simply reference other media by copying the full
composition from the target medium. Handles simple references like
"References medium 284" without modifications.

Usage:
    python scripts/copy_referenced_compositions.py --dry-run  # Preview
    python scripts/copy_referenced_compositions.py            # Apply
"""

import argparse
import yaml
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict


def load_validation_results(validation_file: Path) -> List[Dict]:
    """Load media with reference-type validation results."""
    with open(validation_file) as f:
        data = yaml.safe_load(f)

    invalid = data.get('invalid_media', [])
    references = [m for m in invalid if 'References medium' in m.get('validation', {}).get('reason', '')]

    return references


def extract_target_medium_number(reason: str) -> Optional[str]:
    """
    Extract target medium number from validation reason.

    Examples:
        "References medium 284" -> "284"
        "References medium 168" -> "168"
    """
    match = re.search(r'References medium (\d+)', reason)
    if match:
        return match.group(1)
    return None


def build_media_index(cm_root: Path) -> Dict[str, Path]:
    """
    Build an index of JCM medium numbers to file paths.

    Returns dict mapping medium number to file path.
    """
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


def find_target_medium(medium_number: str, media_index: Dict[str, Path]) -> Optional[Path]:
    """
    Find CultureMech file for target JCM medium number using index.
    """
    return media_index.get(medium_number)


def load_media_file(file_path: Path) -> Optional[Dict]:
    """Load media YAML file."""
    try:
        with open(file_path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"  ✗ Error loading {file_path}: {e}")
        return None


def copy_composition(source_media: Dict, target_media: Dict) -> Tuple[Dict, int]:
    """
    Copy composition from source to target media.

    Returns: (updated_target, ingredient_count)
    """
    source_ingredients = source_media.get('ingredients', [])

    if not source_ingredients:
        return target_media, 0

    # Replace placeholder ingredients with copied composition
    target_media['ingredients'] = []
    for ing in source_ingredients:
        # Create a copy of the ingredient
        new_ing = ing.copy()

        # Handle nested dicts (term, concentration)
        if 'term' in new_ing and isinstance(new_ing['term'], dict):
            new_ing['term'] = new_ing['term'].copy()
        if 'concentration' in new_ing and isinstance(new_ing['concentration'], dict):
            new_ing['concentration'] = new_ing['concentration'].copy()
        if 'curation_metadata' in new_ing and isinstance(new_ing['curation_metadata'], dict):
            new_ing['curation_metadata'] = new_ing['curation_metadata'].copy()

        # Add note about being copied from reference
        if 'notes' in new_ing:
            new_ing['notes'] += f' | Copied from JCM Medium {source_media.get("media_term", {}).get("term", {}).get("id", "").replace("mediadive.medium:J", "")}'
        else:
            source_id = source_media.get('media_term', {}).get('term', {}).get('id', '')
            source_num = source_id.replace('mediadive.medium:J', '')
            new_ing['notes'] = f'Copied from referenced JCM Medium {source_num}'

        target_media['ingredients'].append(new_ing)

    # Update curation history
    if 'curation_history' not in target_media:
        target_media['curation_history'] = []

    source_id = source_media.get('id', 'UNKNOWN')
    source_name = source_media.get('name', 'UNKNOWN')

    target_media['curation_history'].append({
        'timestamp': datetime.now().isoformat(),
        'curator': 'copy_referenced_compositions',
        'action': 'RESOLVED_REFERENCE',
        'changes': f'Copied composition from referenced medium ({len(source_ingredients)} ingredients)',
        'source': source_id,
        'notes': f'Resolved reference by copying from {source_name} ({source_id})'
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


def resolve_references(
    references: List[Dict],
    cm_root: Path,
    dry_run: bool = True
) -> Dict:
    """
    Resolve all media references by copying compositions.

    Returns: Statistics dict
    """
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

    # Group references by target medium for efficiency
    by_target = defaultdict(list)
    for ref in references:
        reason = ref.get('validation', {}).get('reason', '')
        target_num = extract_target_medium_number(reason)
        if target_num:
            by_target[target_num].append(ref)

    print(f"Processing {len(references)} references to {len(by_target)} unique media...\n")

    # Build index of JCM media for fast lookup
    media_index = build_media_index(cm_root)

    # Process each target medium
    for target_num in sorted(by_target.keys()):
        refs = by_target[target_num]
        print(f"Medium {target_num} (referenced by {len(refs)} media):")

        # Find target medium file
        target_file = find_target_medium(target_num, media_index)

        if not target_file:
            print(f"  ⚠️  Target medium not found in CultureMech")
            stats['not_found'] += len(refs)
            not_found_list.extend(refs)
            for ref in refs:
                print(f"    - {ref['id']:25s} {ref['name']}")
            continue

        # Load target medium
        target_media = load_media_file(target_file)
        if not target_media:
            stats['errors'] += len(refs)
            continue

        target_ingredients = target_media.get('ingredients', [])
        if not target_ingredients:
            print(f"  ⚠️  Target medium has no ingredients: {target_file.name}")
            stats['no_composition'] += len(refs)
            continue

        print(f"  ✓ Found target: {target_file.name} ({len(target_ingredients)} ingredients)")

        # Copy composition to each referencing medium
        for ref in refs:
            ref_file_path = cm_root / ref['file']

            if not ref_file_path.exists():
                print(f"    ✗ Reference file not found: {ref_file_path}")
                stats['errors'] += 1
                continue

            # Load referencing medium
            ref_media = load_media_file(ref_file_path)
            if not ref_media:
                stats['errors'] += 1
                continue

            # Copy composition
            updated_media, ing_count = copy_composition(target_media, ref_media)

            print(f"    ✓ {ref['id']:25s} {ref['name']:40s} ({ing_count} ingredients)")

            # Save if not dry-run
            if not dry_run:
                with open(ref_file_path, 'w') as f:
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
    parser = argparse.ArgumentParser(
        description='Copy compositions from referenced media'
    )
    parser.add_argument(
        '--validation-file',
        type=Path,
        default=Path('workspace/commercial_expansions/validated_media_complete.yaml'),
        help='Path to validation results'
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

    # Load reference media
    print(f"Loading references from {args.validation_file}...")
    references = load_validation_results(args.validation_file)
    print(f"✓ Found {len(references)} reference-type media\n")

    # Resolve references
    result = resolve_references(references, args.cm_root, args.dry_run)
    stats = result['stats']

    # Print summary
    print("=" * 80)
    print("REFERENCE RESOLUTION SUMMARY")
    print("=" * 80)
    print(f"Total references: {stats['total']}")
    print(f"Resolved: {stats['resolved']}")
    print(f"Target not found: {stats['not_found']}")
    print(f"No composition in target: {stats['no_composition']}")
    print(f"Errors: {stats['errors']}")
    print()
    print(f"Total ingredients copied: {stats['total_ingredients']}")

    if stats['resolved'] > 0:
        avg_ingredients = stats['total_ingredients'] / stats['resolved']
        print(f"Average ingredients per medium: {avg_ingredients:.1f}")

    if not args.dry_run:
        print(f"\n✅ {stats['resolved']} media updated with resolved compositions")
    else:
        print(f"\n⚠️  DRY RUN - No files were modified")
        print("    Run without --dry-run to apply changes")

    # Print not found list if any
    if result['not_found']:
        print("\n" + "=" * 80)
        print(f"TARGETS NOT FOUND ({len(result['not_found'])} references)")
        print("=" * 80)
        print("These target media are not in CultureMech database:")
        by_target = defaultdict(list)
        for ref in result['not_found']:
            reason = ref.get('validation', {}).get('reason', '')
            target = extract_target_medium_number(reason)
            if target:
                by_target[target].append(ref)

        for target in sorted(by_target.keys()):
            refs = by_target[target]
            print(f"\nMedium {target} ({len(refs)} references):")
            for ref in refs:
                print(f"  - {ref['id']:25s} {ref['name']}")

    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    exit(main())
