#!/usr/bin/env python3
"""Import complex formulation entries into MediaIngredientMech."""

import yaml
from pathlib import Path

def main():
    workspace = Path('workspace')
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'

    # Load complex formulation entries
    entries_file = workspace / 'curation/complex_formulations_mim_entries.yaml'
    with open(entries_file) as f:
        data = yaml.safe_load(f)

    complex_entries = data['entries']
    print(f"Loaded {len(complex_entries)} complex formulation entries")

    # Load mapped ingredients
    mapped_file = mim_root / 'data/curated/mapped_ingredients.yaml'
    with open(mapped_file) as f:
        mapped_data = yaml.safe_load(f)

    original_count = len(mapped_data['ingredients'])
    print(f"Original mapped count: {original_count}")

    # Append complex formulation entries
    for entry in complex_entries:
        mapped_data['ingredients'].append(entry)

    # Update metadata
    mapped_data['metadata']['total_ingredients'] = len(mapped_data['ingredients'])
    mapped_data['metadata']['last_update'] = '2026-03-27'

    # Write back
    with open(mapped_file, 'w') as f:
        yaml.dump(mapped_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Added {len(complex_entries)} complex formulation entries")
    print(f"✓ New total: {len(mapped_data['ingredients'])} mapped ingredients")
    print(f"✓ Updated {mapped_file}")

if __name__ == '__main__':
    main()
