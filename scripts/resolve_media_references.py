#!/usr/bin/env python3
"""Resolve media references to create composite media specifications.

Handles JCM media that reference other media with modifications like:
"Use Medium No. 174 with 0.02 g/L (final) yeast extract"

Usage:
    python scripts/resolve_media_references.py \
        --input workspace/commercial_expansions/validated_media_complete.yaml \
        --output workspace/commercial_expansions/resolved_media.yaml
"""

import argparse
import re
import time
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import requests
from bs4 import BeautifulSoup


def parse_reference(notes_preview: str) -> Optional[Dict]:
    """
    Parse reference pattern from media notes.

    Examples:
    - "Use Medium No. 174 with 0.02 g/L (final) yeast extract"
    - "Use Medium No. <a href="/cgi-bin/jcm/jcm_grmd?GRMD=174">174</a> with 0.02 g/L yeast extract"

    Returns dict with:
    - base_medium: str (medium number)
    - modifications: list of dicts with ingredient and concentration
    """
    # Pattern: Use Medium No. X with ...
    match = re.search(r'Use Medium No\.\s*(?:<a[^>]*>)?(\d+)', notes_preview, re.IGNORECASE)

    if not match:
        return None

    base_medium = match.group(1)

    # Extract modifications (ingredient and concentration)
    modifications = []

    # Pattern: "0.02 g/L yeast extract"
    mod_pattern = r'([\d.]+)\s*(g|mg)/L.*?([a-z][a-z\s\-,]+?)(?:\.|$|with|and)'

    for mod_match in re.finditer(mod_pattern, notes_preview, re.IGNORECASE):
        value = mod_match.group(1)
        unit = mod_match.group(2)
        ingredient = mod_match.group(3).strip()

        # Convert to g/L if needed
        if unit.lower() == 'mg':
            value = str(float(value) / 1000)
            unit = 'g'

        modifications.append({
            'ingredient': ingredient,
            'concentration': {
                'value': value,
                'unit': 'G_PER_L'
            }
        })

    return {
        'base_medium': base_medium,
        'modifications': modifications
    }


def fetch_base_medium(medium_number: str) -> Optional[List[Dict]]:
    """
    Fetch the base medium composition from JCM.

    Returns list of ingredients.
    """
    url = f"https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD={medium_number}"

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; CultureMech/1.0; +https://github.com/kg-microbe)'
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Check for composition table
        tables = soup.find_all('table', {'border': True})

        if not tables:
            return None

        ingredients = []

        for table in tables:
            rows = table.find_all('tr')

            for row in rows:
                cells = row.find_all('td')

                if len(cells) >= 3:
                    ingredient_name = cells[0].get_text(strip=True)
                    amount_text = cells[1].get_text(strip=True)
                    unit_text = cells[2].get_text(strip=True)

                    # Skip empty or water
                    if not ingredient_name or len(ingredient_name) < 2:
                        continue
                    if 'distilled water' in ingredient_name.lower():
                        continue

                    # Parse concentration
                    value = amount_text
                    unit = unit_text.strip()

                    # Normalize to g/L
                    if unit.lower() == 'mg':
                        value = str(float(value) / 1000)
                        unit = 'g'

                    ingredients.append({
                        'preferred_term': ingredient_name,
                        'concentration': {
                            'value': value,
                            'unit': 'G_PER_L'
                        },
                        'source': f'JCM Medium {medium_number}'
                    })

        return ingredients if ingredients else None

    except Exception as e:
        print(f"  ✗ Error fetching base medium {medium_number}: {e}")
        return None


def resolve_reference(media: Dict, rate_limit: float = 1.0) -> Optional[Dict]:
    """
    Resolve a reference media to its base + modifications.

    Returns dict with resolved ingredients.
    """
    validation = media.get('validation', {})

    if not validation.get('is_reference'):
        return None

    # Parse reference
    reference = parse_reference(media.get('notes_preview', ''))

    if not reference:
        print(f"  ⚠️  Could not parse reference")
        return None

    base_medium = reference['base_medium']
    modifications = reference['modifications']

    print(f"  → Base: Medium {base_medium}, Modifications: {len(modifications)}")

    # Fetch base medium
    base_ingredients = fetch_base_medium(base_medium)

    if not base_ingredients:
        print(f"  ✗ Could not fetch base medium {base_medium}")
        return None

    print(f"  ✓ Fetched {len(base_ingredients)} ingredients from base medium")

    # Apply modifications
    resolved_ingredients = base_ingredients.copy()

    for mod in modifications:
        mod_ingredient = mod['ingredient']
        mod_conc = mod['concentration']

        # Check if ingredient already exists (replace) or is new (add)
        existing_idx = None
        for i, ing in enumerate(resolved_ingredients):
            if ing['preferred_term'].lower() == mod_ingredient.lower():
                existing_idx = i
                break

        if existing_idx is not None:
            # Replace existing
            resolved_ingredients[existing_idx]['concentration'] = mod_conc
            resolved_ingredients[existing_idx]['notes'] = f"Modified from base (was {resolved_ingredients[existing_idx]['concentration']})"
            print(f"  ↻ Modified: {mod_ingredient} → {mod_conc['value']} {mod_conc['unit']}")
        else:
            # Add new
            resolved_ingredients.append({
                'preferred_term': mod_ingredient,
                'concentration': mod_conc,
                'source': f"Addition to JCM Medium {base_medium}",
                'notes': "Added per reference specification"
            })
            print(f"  + Added: {mod_ingredient} ({mod_conc['value']} {mod_conc['unit']})")

    # Rate limiting
    time.sleep(rate_limit)

    return {
        'base_medium': base_medium,
        'modifications': modifications,
        'resolved_ingredients': resolved_ingredients
    }


def main():
    parser = argparse.ArgumentParser(
        description='Resolve media references to base media + modifications'
    )
    parser.add_argument(
        '--input',
        type=Path,
        required=True,
        help='Input validated media YAML'
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Output resolved media YAML'
    )
    parser.add_argument(
        '--max-resolve',
        type=int,
        default=100,
        help='Maximum number of references to resolve (default: 100)'
    )
    parser.add_argument(
        '--rate-limit',
        type=float,
        default=1.0,
        help='Seconds between requests (default: 1.0)'
    )

    args = parser.parse_args()

    # Load validated media
    print(f"Loading validated media from {args.input}")
    with open(args.input) as f:
        data = yaml.safe_load(f)

    invalid_media = data.get('invalid_media', [])
    reference_media = [m for m in invalid_media if m.get('validation', {}).get('is_reference')]

    print(f"Found {len(reference_media)} reference media\n")

    # Resolve references
    print(f"Resolving up to {args.max_resolve} references...")
    print("=" * 80)

    resolved = []
    failed = []

    for i, media in enumerate(reference_media[:args.max_resolve], 1):
        media_id = media.get('id')
        media_name = media.get('name')

        print(f"{i:3d}. {media_id:20s} {media_name[:40]}")

        resolution = resolve_reference(media, rate_limit=args.rate_limit)

        if resolution:
            resolved.append({
                'media': media,
                'resolution': resolution
            })
        else:
            failed.append(media)

        print()

    # Save results
    output_data = {
        'metadata': {
            'resolution_date': datetime.now().isoformat(),
            'total_references': len(reference_media),
            'attempted': min(args.max_resolve, len(reference_media)),
            'resolved': len(resolved),
            'failed': len(failed)
        },
        'resolved_media': resolved,
        'failed_resolutions': failed
    }

    with open(args.output, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print("=" * 80)
    print("RESOLUTION SUMMARY")
    print("=" * 80)
    print(f"Total references: {len(reference_media)}")
    print(f"Attempted: {min(args.max_resolve, len(reference_media))}")
    print(f"Resolved: {len(resolved)}")
    print(f"Failed: {len(failed)}")
    print(f"\n✓ Saved resolved media to {args.output}")

    return 0


if __name__ == '__main__':
    exit(main())
