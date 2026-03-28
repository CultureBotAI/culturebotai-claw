#!/usr/bin/env python3
"""Remove COMPLEX formulation entries from MediaIngredientMech.

These entries were created to represent complex media and stock solutions,
but should remain exclusively in CultureMech. MediaIngredientMech should
only contain single chemical/biological ingredients.
"""

import yaml
from pathlib import Path
from datetime import datetime

def remove_complex_from_mim(mim_root: Path, dry_run: bool = True):
    """Remove COMPLEX entries from MediaIngredientMech mapped_ingredients.yaml."""
    mapped_file = mim_root / 'data/curated/mapped_ingredients.yaml'

    print(f"Loading {mapped_file}...")

    with open(mapped_file) as f:
        data = yaml.safe_load(f)

    original_count = len(data['ingredients'])
    print(f"Original count: {original_count} ingredients")

    # Filter out COMPLEX entries
    remaining = []
    removed = []

    for ing in data['ingredients']:
        ontology_id = ing.get('ontology_id', '')

        if ontology_id.startswith('MediaIngredientMech:COMPLEX_'):
            removed.append({
                'id': ontology_id,
                'name': ing.get('preferred_term', 'unknown'),
                'occurrences': ing.get('occurrence_statistics', {}).get('total_occurrences', 0)
            })
        else:
            remaining.append(ing)

    print(f"\nRemoved {len(removed)} COMPLEX entries:")
    for entry in removed[:10]:  # Show first 10
        print(f"  - {entry['id']}: {entry['name']} ({entry['occurrences']} occurrences)")

    if len(removed) > 10:
        print(f"  ... and {len(removed) - 10} more")

    print(f"\nRemaining: {len(remaining)} ingredients")

    # Update metadata
    if 'metadata' not in data:
        data['metadata'] = {}

    data['metadata']['total_ingredients'] = len(remaining)
    data['metadata']['last_update'] = datetime.utcnow().isoformat()
    data['metadata']['complex_entries_removed'] = {
        'timestamp': datetime.utcnow().isoformat(),
        'count': len(removed),
        'reason': 'Complex formulations moved to CultureMech-only architecture'
    }

    data['ingredients'] = remaining

    if not dry_run:
        # Write back
        with open(mapped_file, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"\n✓ Updated {mapped_file}")
    else:
        print(f"\n⚠️  DRY RUN - No changes made")

    return len(removed), len(remaining)

def remove_complex_from_canonical(workspace: Path, dry_run: bool = True):
    """Remove COMPLEX entries from canonical store."""
    canonical_file = workspace / 'canonical_ingredients/mapped_ingredients.yaml'

    if not canonical_file.exists():
        print(f"\n⚠️  Canonical store not found: {canonical_file}")
        return 0, 0

    print(f"\nLoading {canonical_file}...")

    with open(canonical_file) as f:
        data = yaml.safe_load(f)

    if not data or 'ingredients' not in data:
        print("No ingredients found in canonical store")
        return 0, 0

    original_count = len(data['ingredients'])

    # Filter out COMPLEX entries
    remaining = []
    removed_count = 0

    for ing in data['ingredients']:
        ontology_id = ing.get('ontology_id', '') or ing.get('id', '')

        if ontology_id.startswith('MediaIngredientMech:COMPLEX_'):
            removed_count += 1
        else:
            remaining.append(ing)

    print(f"Original count: {original_count}")
    print(f"Removed: {removed_count} COMPLEX entries")
    print(f"Remaining: {len(remaining)}")

    data['ingredients'] = remaining

    if not dry_run:
        with open(canonical_file, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"✓ Updated {canonical_file}")
    else:
        print("⚠️  DRY RUN - No changes made")

    return removed_count, len(remaining)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Remove COMPLEX entries from MediaIngredientMech')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Perform dry run without modifying files (default)')
    parser.add_argument('--production', action='store_true',
                       help='Actually modify files')

    args = parser.parse_args()

    dry_run = not args.production

    # Paths
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'
    workspace = Path('workspace')

    print("="*80)
    print("REMOVE COMPLEX FORMULATION ENTRIES")
    print("="*80)
    print(f"\nMode: {'DRY RUN' if dry_run else 'PRODUCTION'}\n")

    # Remove from MediaIngredientMech
    print("1. MediaIngredientMech Repository")
    print("-"*80)
    mim_removed, mim_remaining = remove_complex_from_mim(mim_root, dry_run)

    # Remove from canonical store
    print("\n2. Canonical Store (CultureBotAI-CLAW)")
    print("-"*80)
    can_removed, can_remaining = remove_complex_from_canonical(workspace, dry_run)

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"\nMediaIngredientMech:")
    print(f"  - Removed: {mim_removed} COMPLEX entries")
    print(f"  - Remaining: {mim_remaining} single ingredients")

    print(f"\nCanonical Store:")
    print(f"  - Removed: {can_removed} COMPLEX entries")
    print(f"  - Remaining: {can_remaining} ingredients")

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No files were modified")
        print("Run with --production to apply changes")
    else:
        print("\n✓ Removal complete")

if __name__ == '__main__':
    main()
