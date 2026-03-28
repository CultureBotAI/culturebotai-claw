#!/usr/bin/env python3
"""Identify commercial media products with placeholder ingredients in CultureMech.

Scans CultureMech recipes to find:
1. Placeholder ingredients ("See source for composition")
2. Commercial product names (from media_term or notes)
3. Supplier information (if identifiable)
4. Current ingredient expansion status

Output: Priority list for commercial expansion research
"""

import yaml
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional
import re

def extract_supplier_from_notes(notes: str) -> Optional[str]:
    """Extract supplier name from notes field."""
    if not notes:
        return None

    # Common supplier patterns
    suppliers = [
        'Difco', 'BD', 'Sigma', 'Sigma-Aldrich', 'Thermo', 'Thermo Fisher',
        'ATCC', 'DSMZ', 'JCM', 'CCAP', 'Merck', 'Oxoid', 'HiMedia'
    ]

    notes_lower = notes.lower()
    for supplier in suppliers:
        if supplier.lower() in notes_lower:
            return supplier

    return None

def extract_catalog_number(notes: str) -> Optional[str]:
    """Extract catalog number from notes field."""
    if not notes:
        return None

    # Look for catalog number patterns
    patterns = [
        r'catalog[:\s]+([A-Z0-9-]+)',
        r'cat[\.:\s]+([A-Z0-9-]+)',
        r'#\s*([A-Z0-9-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, notes, re.IGNORECASE)
        if match:
            return match.group(1)

    return None

def has_placeholder_ingredient(recipe: dict) -> bool:
    """Check if recipe has placeholder ingredients."""
    if 'ingredients' not in recipe:
        return False

    for ing in recipe['ingredients']:
        preferred_term = ing.get('preferred_term', '').lower()
        if 'see source' in preferred_term or 'full composition' in preferred_term:
            return True

    return False

def count_real_ingredients(recipe: dict) -> int:
    """Count non-placeholder ingredients."""
    if 'ingredients' not in recipe:
        return 0

    count = 0
    for ing in recipe['ingredients']:
        preferred_term = ing.get('preferred_term', '').lower()
        if 'see source' not in preferred_term and 'full composition' not in preferred_term:
            count += 1

    return count

def analyze_recipe(yaml_file: Path, cm_root: Path) -> Optional[Dict]:
    """Analyze a single recipe file for commercial product indicators."""
    try:
        with open(yaml_file) as f:
            recipe = yaml.safe_load(f)

        if not recipe:
            return None

        # Check if it has placeholder ingredients
        has_placeholder = has_placeholder_ingredient(recipe)
        real_ingredient_count = count_real_ingredients(recipe)

        # Get basic info
        recipe_id = recipe.get('id', 'unknown')
        recipe_name = recipe.get('name', 'unknown')
        notes = recipe.get('notes', '')

        # Extract supplier and catalog info
        supplier = extract_supplier_from_notes(notes)
        catalog_number = extract_catalog_number(notes)

        # Get media_term info
        media_term = recipe.get('media_term', {})
        media_term_id = media_term.get('term', {}).get('id', '') if isinstance(media_term.get('term'), dict) else ''
        media_term_label = media_term.get('preferred_term', '')

        # Determine if this is a commercial product candidate
        is_commercial = (
            has_placeholder or
            supplier is not None or
            catalog_number is not None or
            any(word in recipe_name.lower() for word in ['medium', 'agar', 'broth']) and
            any(word in notes.lower() for word in ['catalog', 'supplier', 'source', 'product'])
        )

        if not is_commercial:
            return None

        return {
            'id': recipe_id,
            'name': recipe_name,
            'file': str(yaml_file.relative_to(cm_root)),
            'has_placeholder': has_placeholder,
            'real_ingredient_count': real_ingredient_count,
            'supplier': supplier,
            'catalog_number': catalog_number,
            'media_term_id': media_term_id,
            'media_term_label': media_term_label,
            'notes_preview': notes[:200] if notes else ''
        }

    except Exception as e:
        print(f"⚠️  Error analyzing {yaml_file}: {e}")
        return None

def scan_culturemech(cm_root: Path) -> List[Dict]:
    """Scan all CultureMech recipe files."""
    print(f"Scanning CultureMech recipes in {cm_root}...")

    commercial_media = []

    # Scan normalized_yaml directory
    yaml_files = list(cm_root.glob('data/normalized_yaml/**/*.yaml'))
    print(f"Found {len(yaml_files)} recipe files\n")

    for yaml_file in yaml_files:
        result = analyze_recipe(yaml_file, cm_root)
        if result:
            commercial_media.append(result)

    return commercial_media

def prioritize_media(commercial_media: List[Dict]) -> Dict[str, List[Dict]]:
    """Prioritize commercial media by expansion status and commonality."""

    # Priority categories
    high_priority = []  # Placeholder ingredients, common products
    medium_priority = []  # Has supplier info but no placeholder
    low_priority = []  # Mentioned in notes but unclear

    for item in commercial_media:
        if item['has_placeholder']:
            # High priority: needs expansion
            high_priority.append(item)
        elif item['supplier'] or item['catalog_number']:
            # Medium priority: has commercial info
            medium_priority.append(item)
        else:
            # Low priority: weak indicators
            low_priority.append(item)

    return {
        'high': sorted(high_priority, key=lambda x: -x['real_ingredient_count']),
        'medium': sorted(medium_priority, key=lambda x: -x['real_ingredient_count']),
        'low': sorted(low_priority, key=lambda x: -x['real_ingredient_count'])
    }

def generate_report(prioritized: Dict[str, List[Dict]], output_file: Path):
    """Generate report and YAML output."""

    print("="*80)
    print("COMMERCIAL MEDIA IDENTIFICATION REPORT")
    print("="*80)

    total_count = sum(len(items) for items in prioritized.values())
    print(f"\nTotal commercial media identified: {total_count}\n")

    # Print high priority
    high = prioritized['high']
    print(f"HIGH PRIORITY ({len(high)}): Placeholder ingredients - needs expansion")
    print("-"*80)
    for item in high[:20]:  # Show first 20
        print(f"\n{item['id']}: {item['name']}")
        print(f"  File: {item['file']}")
        print(f"  Supplier: {item['supplier'] or 'Unknown'}")
        print(f"  Catalog: {item['catalog_number'] or 'Unknown'}")
        print(f"  Real ingredients: {item['real_ingredient_count']}")
        if item['media_term_label']:
            print(f"  Media term: {item['media_term_label']} ({item['media_term_id']})")

    if len(high) > 20:
        print(f"\n  ... and {len(high) - 20} more")

    # Print medium priority
    medium = prioritized['medium']
    print(f"\n\nMEDIUM PRIORITY ({len(medium)}): Has commercial info, no placeholder")
    print("-"*80)
    for item in medium[:10]:  # Show first 10
        print(f"\n{item['id']}: {item['name']}")
        print(f"  Supplier: {item['supplier'] or 'Unknown'}")
        print(f"  Real ingredients: {item['real_ingredient_count']}")

    if len(medium) > 10:
        print(f"\n  ... and {len(medium) - 10} more")

    # Print low priority
    low = prioritized['low']
    print(f"\n\nLOW PRIORITY ({len(low)}): Weak commercial indicators")
    print("-"*80)
    print(f"  {len(low)} items (see output YAML for details)")

    # Export to YAML
    export_data = {
        'metadata': {
            'scan_date': '2026-03-27',
            'total_identified': total_count,
            'high_priority': len(high),
            'medium_priority': len(medium),
            'low_priority': len(low)
        },
        'high_priority': high,
        'medium_priority': medium,
        'low_priority': low
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        yaml.dump(export_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n\n{'='*80}")
    print(f"✓ Full report exported to: {output_file}")
    print(f"{'='*80}\n")

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Identify commercial media products in CultureMech')
    parser.add_argument('--output', default='workspace/commercial_expansions/identified_media.yaml',
                       help='Output YAML file for results')

    args = parser.parse_args()

    # Paths
    cm_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech'
    output_file = Path(args.output)

    # Scan CultureMech
    commercial_media = scan_culturemech(cm_root)

    # Prioritize
    prioritized = prioritize_media(commercial_media)

    # Generate report
    generate_report(prioritized, output_file)

    print("\nNext Steps:")
    print("1. Review high priority items in the output YAML")
    print("2. Research product specifications for top candidates")
    print("3. Start with: BHI (Brain Heart Infusion), TSB/TSA (Tryptic Soy), LB (Luria-Bertani)")

if __name__ == '__main__':
    main()
