#!/usr/bin/env python3
"""Remove merge artifacts from unmapped ingredients."""

import yaml
from pathlib import Path

def main():
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'
    unmapped_file = mim_root / 'data/curated/unmapped_ingredients.yaml'

    with open(unmapped_file) as f:
        unmapped_data = yaml.safe_load(f)

    original_count = len(unmapped_data['ingredients'])
    print(f"Original unmapped count: {original_count}")

    # Filter out merge artifacts
    remaining = []
    removed_count = 0

    for ing in unmapped_data['ingredients']:
        preferred_term = ing.get('preferred_term', '')
        if preferred_term.startswith('[Merged ') and 'duplicates:' in preferred_term:
            print(f"  Removing artifact: {preferred_term}")
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

    print(f"\n✓ Removed {removed_count} merge artifacts")
    print(f"✓ Remaining unmapped: {len(remaining)}")
    print(f"✓ Updated {unmapped_file}")

if __name__ == '__main__':
    main()
