#!/usr/bin/env python3
"""Expand commercial product placeholder ingredients with researched constituents.

Replaces "See source for composition" placeholders with detailed ingredient
lists that include ontology mappings (UBERON, FOODON, CHEBI).

Usage:
    python scripts/expand_commercial_product.py --product bhi --dry-run
    python scripts/expand_commercial_product.py --product bhi
"""

import argparse
import yaml
from pathlib import Path
from typing import Dict, List
from datetime import datetime


def load_product_composition(product_file: Path) -> Dict:
    """Load researched product composition from YAML."""
    with open(product_file) as f:
        return yaml.safe_load(f)


def find_media_files(cm_root: Path, product_name: str, product_aliases: List[str] = None) -> List[Path]:
    """
    Find all CultureMech media files containing the product as an ingredient.

    Args:
        cm_root: CultureMech repository root
        product_name: Product name to search for (case-insensitive)
        product_aliases: Alternative product names to search for

    Returns:
        List of matching YAML file paths
    """
    matches = []

    # Build search patterns
    search_patterns = [product_name.lower()]
    if product_aliases:
        search_patterns.extend([alias.lower() for alias in product_aliases])

    # For common bacterial products, scan only bacterial directory (faster)
    # For broader search, scan all directories
    if any(x in product_name.lower() for x in ['bhi', 'lb', 'tsb', 'tsa', 'brain', 'luria', 'tryptic']):
        yaml_files = list(cm_root.glob('data/normalized_yaml/bacterial/*.yaml'))
    else:
        yaml_files = list(cm_root.glob('data/normalized_yaml/**/*.yaml'))

    for yaml_file in yaml_files:
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)

            if not data:
                continue

            # Check ingredients for product name
            ingredients = data.get('ingredients', [])
            for ing in ingredients:
                term = ing.get('preferred_term', '').lower()

                # Match if ingredient contains product name
                if any(pattern in term for pattern in search_patterns):
                    matches.append(yaml_file)
                    break

        except Exception as e:
            continue

    return matches


def expand_ingredients(product_data: Dict) -> List[Dict]:
    """
    Convert product constituents to CultureMech ingredient format.

    Args:
        product_data: Product composition data

    Returns:
        List of ingredient dicts in CultureMech format
    """
    ingredients = []
    supplier = product_data['supplier']
    catalog = product_data['catalog_number']
    source_url = product_data['source_url']

    for constituent in product_data['constituents']:
        ingredient = {
            'preferred_term': constituent['name']
        }

        # Add ontology term
        if 'ontology_id' in constituent:
            ingredient['term'] = {
                'id': constituent['ontology_id'],
                'label': constituent['ontology_label']
            }

        # Add concentration (if present)
        if 'concentration' in constituent:
            ingredient['concentration'] = constituent['concentration']
        elif 'amount' in constituent:
            # For infusions, store as text in notes
            ingredient['concentration'] = {
                'value': 'variable',
                'unit': 'VARIABLE'
            }

        # Add supplier catalog info
        ingredient['supplier_catalog'] = {
            'supplier_name': f"{supplier} {product_data['product_name']}",
            'catalog_number': catalog,
            'product_url': source_url
        }

        # Add notes
        notes_parts = []
        if 'amount' in constituent:
            notes_parts.append(constituent['amount'])
        if 'notes' in constituent:
            notes_parts.append(constituent['notes'])
        notes_parts.append(f"Constituent of {product_data['product_name']} commercial product")

        ingredient['notes'] = '; '.join(notes_parts)

        # Add synonyms if present
        if 'synonyms' in constituent:
            ingredient['synonyms'] = [
                {'synonym_text': syn, 'synonym_type': 'EXACT'}
                for syn in constituent['synonyms']
            ]

        ingredients.append(ingredient)

    return ingredients


def expand_media_file(
    media_file: Path,
    product_data: Dict,
    dry_run: bool = True
) -> bool:
    """
    Expand a single media file with product constituents.

    Args:
        media_file: Path to CultureMech YAML file
        product_data: Product composition data
        dry_run: If True, don't write changes

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(media_file) as f:
            media = yaml.safe_load(f)

        if not media:
            return False

        # Replace ingredients
        original_ingredients = media.get('ingredients', [])

        # Get expanded ingredients
        new_ingredients = expand_ingredients(product_data)

        # Build search patterns for product matching
        product_patterns = [product_data['product_name'].lower()]
        if 'product_aliases' in product_data:
            product_patterns.extend([alias.lower() for alias in product_data['product_aliases']])

        # Replace product ingredients with expanded constituents
        expanded_ingredients = []
        replaced_count = 0
        for ing in original_ingredients:
            term = ing.get('preferred_term', '').lower()

            # Check if this ingredient matches any product pattern
            should_replace = any(pattern in term for pattern in product_patterns)

            if should_replace:
                # Replace with all constituents
                expanded_ingredients.extend(new_ingredients)
                replaced_count += 1
                print(f"    Replacing: {ing.get('preferred_term', 'unknown')}")
            else:
                # Keep existing ingredient
                expanded_ingredients.append(ing)

        if replaced_count == 0:
            print(f"  ⚠️  No matching product ingredient found in {media_file.name}")
            return False

        media['ingredients'] = expanded_ingredients
        print(f"    Replaced {replaced_count} ingredient(s) with {len(new_ingredients)} constituents")

        # Update notes with source citation
        notes = media.get('notes', '')
        source_citation = f"""
Commercial Product: {product_data['product_name']}
Supplier: {product_data['supplier']}
Catalog: {product_data['catalog_number']}
Source: {product_data['source_url']}
Accessed: {product_data['source_accessed']}

Constituent composition researched from product specification.
"""

        if notes:
            media['notes'] = f"{notes}\n\n{source_citation.strip()}"
        else:
            media['notes'] = source_citation.strip()

        # Write back if not dry-run
        if not dry_run:
            with open(media_file, 'w') as f:
                yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        return True

    except Exception as e:
        print(f"  ✗ Error processing {media_file}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Expand commercial product placeholder ingredients'
    )
    parser.add_argument(
        '--product',
        required=True,
        help='Product name (e.g., "bhi", "lb", "tsa")'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing files'
    )
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--data-dir',
        type=Path,
        default=Path('workspace/commercial_expansions'),
        help='Path to product composition data'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    # Load product composition
    product_file = args.data_dir / f"{args.product}_composition.yaml"
    if not product_file.exists():
        print(f"✗ Product composition file not found: {product_file}")
        print(f"  Available products:")
        for f in args.data_dir.glob("*_composition.yaml"):
            print(f"    - {f.stem.replace('_composition', '')}")
        return 1

    print(f"Loading product composition: {product_file}")
    product_data = load_product_composition(product_file)

    print(f"Product: {product_data['product_name']}")
    print(f"Supplier: {product_data['supplier']}")
    print(f"Constituents: {len(product_data['constituents'])}")

    # Find matching media files
    print(f"\nSearching for media files in {args.cm_root}...")
    product_aliases = product_data.get('product_aliases', [])
    media_files = find_media_files(args.cm_root, product_data['product_name'], product_aliases)

    print(f"Found {len(media_files)} media files with placeholders\n")

    if not media_files:
        print("✗ No matching media files found")
        return 1

    # Expand each file
    print("="*80)
    print("EXPANDING MEDIA FILES")
    print("="*80)

    success_count = 0
    for media_file in media_files:
        print(f"\n{media_file.relative_to(args.cm_root)}")
        if expand_media_file(media_file, product_data, args.dry_run):
            success_count += 1
            print(f"  ✓ Expanded {len(product_data['constituents'])} constituents")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Files processed: {len(media_files)}")
    print(f"Successfully expanded: {success_count}")
    print(f"Failed: {len(media_files) - success_count}")

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
        print("Run without --dry-run to apply expansions")
    else:
        print(f"\n✓ Expansion complete for {product_data['product_name']}")

    return 0


if __name__ == '__main__':
    exit(main())
