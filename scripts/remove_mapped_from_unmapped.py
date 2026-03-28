#!/usr/bin/env python3
"""Remove successfully mapped ingredients from unmapped list."""

import yaml
from pathlib import Path
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python remove_mapped_from_unmapped.py <curated_batch_file>")
        sys.exit(1)

    batch_file = Path(sys.argv[1])

    # Load the curated batch
    with open(batch_file) as f:
        batch_data = yaml.safe_load(f)

    # Get names of successfully curated ingredients
    curated_names = set()
    for ing in batch_data.get('ingredients', []):
        if ing.get('suggested_ontology_id'):  # Has a mapping
            curated_names.add(ing['name'])

    print(f"Found {len(curated_names)} curated ingredients in batch")

    # Load unmapped ingredients
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'
    unmapped_file = mim_root / 'data/curated/unmapped_ingredients.yaml'

    with open(unmapped_file) as f:
        unmapped_data = yaml.safe_load(f)

    original_count = len(unmapped_data['ingredients'])
    print(f"Original unmapped count: {original_count}")

    # Filter out curated ingredients
    remaining = []
    removed_count = 0

    for ing in unmapped_data['ingredients']:
        preferred_term = ing.get('preferred_term', '')
        if preferred_term in curated_names:
            print(f"  Removing: {preferred_term}")
            removed_count += 1
        else:
            remaining.append(ing)

    # Update counts
    unmapped_data['ingredients'] = remaining
    unmapped_data['total_count'] = len(remaining)
    unmapped_data['unmapped_count'] = len(remaining)

    # Write back
    with open(unmapped_file, 'w') as f:
        yaml.dump(unmapped_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Removed {removed_count} ingredients")
    print(f"✓ Remaining unmapped: {len(remaining)}")
    print(f"✓ Updated {unmapped_file}")

if __name__ == '__main__':
    main()
