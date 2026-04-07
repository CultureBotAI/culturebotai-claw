#!/usr/bin/env python3
"""Fetch media specifications from JCM and CCAP culture collection databases.

Extracts source URLs from identified_media.yaml, fetches specifications from
JCM (HTML) and CCAP (PDF) sources, and outputs standardized ingredient lists.

Usage:
    python scripts/fetch_collection_media.py --batch-size 10 --dry-run
    python scripts/fetch_collection_media.py --batch-size 50
"""

import argparse
import io
import re
import time
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import pdfplumber
import requests
from bs4 import BeautifulSoup


def load_identified_media(identified_file: Path) -> List[Dict]:
    """Load identified media from YAML file."""
    with open(identified_file) as f:
        data = yaml.safe_load(f)
    return data.get('high_priority', [])


def extract_source_info(media: Dict) -> Optional[Dict]:
    """Extract source type and URL from media entry."""
    notes = media.get('notes_preview', '')

    # Check for JCM
    jcm_match = re.search(r'https://www\.jcm\.riken\.jp/cgi-bin/jcm/jcm_grmd\?GRMD=(\d+)', notes)
    if jcm_match:
        return {
            'type': 'JCM',
            'url': jcm_match.group(0),
            'id': jcm_match.group(1)
        }

    # Check for CCAP
    ccap_match = re.search(r'https://www\.ccap\.ac\.uk/wp-content/uploads/(MR_[^\.]+\.pdf)', notes)
    if ccap_match:
        return {
            'type': 'CCAP',
            'url': ccap_match.group(0),
            'id': ccap_match.group(1)
        }

    return None


def parse_jcm_html(html: str, media_id: str) -> Dict:
    """
    Parse JCM HTML page to extract ingredient information.

    JCM pages contain composition tables with 3 columns:
    [ingredient name] [amount] [unit]
    """
    soup = BeautifulSoup(html, 'html.parser')

    ingredients = []

    # Find tables with BORDER attribute (JCM composition tables)
    tables = soup.find_all('table', {'border': True})

    for table in tables:
        # Look for rows with ingredient-like content
        rows = table.find_all('tr')

        for row in rows:
            cells = row.find_all('td')

            # JCM format: 3 columns [ingredient] [amount] [unit]
            if len(cells) >= 3:
                ingredient_name = cells[0].get_text(strip=True)
                amount_text = cells[1].get_text(strip=True)
                unit_text = cells[2].get_text(strip=True)

                # Skip empty rows or very short names
                if not ingredient_name or len(ingredient_name) < 2:
                    continue

                # Skip "Distilled water" and similar
                if 'distilled water' in ingredient_name.lower():
                    continue

                # Combine amount and unit for parsing
                concentration_text = f"{amount_text} {unit_text}"

                # Parse concentration
                conc = parse_concentration(concentration_text)

                ingredients.append({
                    'preferred_term': ingredient_name,
                    'concentration': conc,
                    'source': 'JCM',
                    'notes': f'From JCM Medium {media_id}'
                })

    return {
        'ingredients': ingredients,
        'source_type': 'JCM',
        'source_id': media_id,
        'parse_success': len(ingredients) > 0
    }


def normalize_concentration_unit(value: str, unit: str) -> Dict:
    """Normalize concentration to g/L or appropriate unit."""
    try:
        numeric_value = float(value)

        # Convert mg/L to g/L
        if unit.lower() in ['mg', 'mg/l']:
            return {'value': str(numeric_value / 1000), 'unit': 'G_PER_L'}

        # Convert µL/L or mL/L to appropriate units
        if unit.lower() in ['µl', 'ul', 'µl/l', 'ul/l']:
            return {'value': value, 'unit': 'UL_PER_L'}
        if unit.lower() in ['ml', 'ml/l']:
            return {'value': value, 'unit': 'ML_PER_L'}

        # g/L stays as is
        if unit.lower() in ['g', 'g/l']:
            return {'value': value, 'unit': 'G_PER_L'}

        # Percentage
        if unit == '%':
            return {'value': value, 'unit': 'PERCENT'}

        # Molarity
        if unit.upper() == 'M':
            return {'value': value, 'unit': 'MOLAR'}

        # Default: return as-is
        return {'value': value, 'unit': unit}

    except ValueError:
        return {'value': 'variable', 'unit': 'VARIABLE'}


def parse_ccap_pdf(pdf_content: bytes, media_id: str) -> Dict:
    """
    Parse CCAP PDF to extract ingredient information.

    Uses pdfplumber to extract text and parse ingredient composition.
    """
    ingredients = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            # Extract text from all pages
            text = '\n'.join(
                page.extract_text() for page in pdf.pages
                if page.extract_text()
            )

            if not text:
                return {
                    'ingredients': [],
                    'source_type': 'CCAP',
                    'source_id': media_id,
                    'parse_success': False,
                    'error': 'No text extracted from PDF'
                }

            # Find composition section (varies by PDF format)
            composition_patterns = [
                r'Composition.*?(?=\n\n|\nPreparation|\nMethod|\Z)',
                r'Ingredients.*?(?=\n\n|\nMethod|\nPreparation|\Z)',
                r'Formula.*?(?=\n\n|\nPreparation|\nMethod|\Z)',
                r'Medium composition.*?(?=\n\n|\nPreparation|\Z)',
            ]

            composition_text = None
            for pattern in composition_patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match:
                    composition_text = match.group(0)
                    break

            if not composition_text:
                # Fallback: try to find ingredient-like lines anywhere in text
                composition_text = text

            # Parse ingredient lines with various patterns
            # Pattern 1: "Sodium nitrate  0.075 g/L"
            # Pattern 2: "Yeast extract 2.0 g"
            # Pattern 3: "NaCl 5 g/L"
            ingredient_patterns = [
                r'^([A-Z][A-Za-z0-9\s\-\(\),\.]+?)\s+([\d\.]+)\s*(g|mg|mL|µL|μL|L|%|M)(?:/L)?',
                r'([A-Z][A-Za-z0-9\s\-\(\),\.]+?)\s*:\s*([\d\.]+)\s*(g|mg|mL|µL|μL|%|M)',
            ]

            for line in composition_text.split('\n'):
                line = line.strip()
                if not line or len(line) < 3:
                    continue

                # Skip obvious header lines
                if any(header in line.lower() for header in ['composition', 'ingredient', 'formula', 'per liter', 'preparation']):
                    continue

                # Try each pattern
                matched = False
                for pattern in ingredient_patterns:
                    ing_match = re.search(pattern, line)
                    if ing_match:
                        name = ing_match.group(1).strip()
                        value = ing_match.group(2)
                        unit = ing_match.group(3)

                        # Filter out false matches (too short, numbers only, etc.)
                        if len(name) < 2 or name.isdigit():
                            continue

                        # Normalize concentration
                        conc = normalize_concentration_unit(value, unit)

                        ingredients.append({
                            'preferred_term': name,
                            'concentration': conc,
                            'source': 'CCAP',
                            'notes': f'From CCAP Medium {media_id}'
                        })
                        matched = True
                        break

            return {
                'ingredients': ingredients,
                'source_type': 'CCAP',
                'source_id': media_id,
                'parse_success': len(ingredients) > 0
            }

    except Exception as e:
        return {
            'ingredients': [],
            'source_type': 'CCAP',
            'source_id': media_id,
            'parse_success': False,
            'error': str(e)
        }


def parse_concentration(text: str) -> Dict:
    """Parse concentration string into value and unit."""
    if not text:
        return {'value': 'variable', 'unit': 'VARIABLE'}

    # Common patterns: "1.0 g/L", "500 mg/L", "10.0 g", "0.5%", etc.

    # Try g/L pattern
    match = re.search(r'([\d.]+)\s*g\s*/\s*[Ll]', text)
    if match:
        return {'value': match.group(1), 'unit': 'G_PER_L'}

    # Try mg/L pattern
    match = re.search(r'([\d.]+)\s*mg\s*/\s*[Ll]', text)
    if match:
        value = float(match.group(1)) / 1000  # Convert to g/L
        return {'value': str(value), 'unit': 'G_PER_L'}

    # Try standalone g (JCM format - implies per liter)
    match = re.search(r'([\d.]+)\s*g\s*$', text)
    if match:
        return {'value': match.group(1), 'unit': 'G_PER_L'}

    # Try standalone mg (JCM format - convert to g/L)
    match = re.search(r'([\d.]+)\s*mg\s*$', text)
    if match:
        value = float(match.group(1)) / 1000  # Convert to g/L
        return {'value': str(value), 'unit': 'G_PER_L'}

    # Try mL or L
    match = re.search(r'([\d.]+)\s*(mL|L)\s*$', text, re.IGNORECASE)
    if match:
        value = match.group(1)
        unit = match.group(2).upper()
        return {'value': value, 'unit': f'{unit}_PER_L'}

    # Try percentage
    match = re.search(r'([\d.]+)\s*%', text)
    if match:
        return {'value': match.group(1), 'unit': 'PERCENT'}

    # Default: variable
    return {'value': 'variable', 'unit': 'VARIABLE'}


def fetch_media_spec(source_info: Dict, timeout: int = 10) -> Optional[Dict]:
    """
    Fetch and parse media specification from source URL.

    Args:
        source_info: Dict with 'type', 'url', 'id'
        timeout: Request timeout in seconds

    Returns:
        Parsed specification dict or None if failed
    """
    try:
        # Add user agent to avoid blocking
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; CultureMech/1.0; +https://github.com/kg-microbe)'
        }

        response = requests.get(source_info['url'], headers=headers, timeout=timeout)
        response.raise_for_status()

        if source_info['type'] == 'JCM':
            return parse_jcm_html(response.text, source_info['id'])
        elif source_info['type'] == 'CCAP':
            return parse_ccap_pdf(response.content, source_info['id'])

    except requests.RequestException as e:
        return {
            'ingredients': [],
            'source_type': source_info['type'],
            'source_id': source_info['id'],
            'parse_success': False,
            'error': str(e)
        }

    return None


def batch_fetch(
    media_list: List[Dict],
    batch_size: int = 50,
    rate_limit: float = 1.0,
    dry_run: bool = True
) -> List[Dict]:
    """
    Fetch specifications for a batch of media with rate limiting.

    Args:
        media_list: List of media dicts from identified_media.yaml
        batch_size: Number of media to process
        rate_limit: Seconds to wait between requests (default 1.0)
        dry_run: If True, only extract URLs without fetching

    Returns:
        List of fetched specifications
    """
    results = []
    processed = 0

    for media in media_list[:batch_size]:
        # Extract source info
        source_info = extract_source_info(media)

        if not source_info:
            print(f"⚠️  No source URL found for {media.get('id', 'unknown')}")
            continue

        result = {
            'media_id': media.get('id'),
            'media_name': media.get('name'),
            'source_info': source_info
        }

        if dry_run:
            print(f"[DRY RUN] {source_info['type']}: {media.get('name')} ({source_info['id']})")
            # Create mock spec for dry-run so downstream stages can test
            result['spec'] = {
                'ingredients': [],
                'source_type': source_info['type'],
                'source_id': source_info['id'],
                'parse_success': False,
                'notes': 'Dry-run mode - no actual fetching performed'
            }
        else:
            print(f"Fetching {source_info['type']}: {media.get('name')} ({source_info['id']})")
            spec = fetch_media_spec(source_info)
            result['spec'] = spec

            if spec and spec.get('parse_success'):
                print(f"  ✓ Parsed {len(spec['ingredients'])} ingredients")
            else:
                error = spec.get('error', 'Parse failed') if spec else 'Fetch failed'
                print(f"  ✗ {error}")

            # Rate limiting
            time.sleep(rate_limit)

        results.append(result)
        processed += 1

    return results


def save_results(results: List[Dict], output_file: Path, dry_run: bool = False):
    """Save fetched results to YAML file."""
    output_data = {
        'metadata': {
            'fetch_date': datetime.now().isoformat(),
            'total_fetched': len(results),
            'successful': sum(1 for r in results if r.get('spec', {}).get('parse_success', False)),
            'dry_run': dry_run
        },
        'results': results
    }

    with open(output_file, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(
        description='Fetch media specifications from JCM/CCAP databases'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Number of media to fetch (default: 10)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Extract URLs only, do not fetch'
    )
    parser.add_argument(
        '--rate-limit',
        type=float,
        default=1.0,
        help='Seconds between requests (default: 1.0)'
    )
    parser.add_argument(
        '--input',
        type=Path,
        default=Path('workspace/commercial_expansions/identified_media.yaml'),
        help='Path to identified media YAML'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output file path (default: workspace/curation/collection_media/batch_NNN.yaml)'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No HTTP requests will be made\n")

    # Load identified media
    print(f"Loading identified media from {args.input}")
    media_list = load_identified_media(args.input)
    print(f"Loaded {len(media_list)} high-priority media\n")

    # Fetch batch
    print(f"Processing batch of {args.batch_size} media...")
    print("=" * 80)

    results = batch_fetch(
        media_list,
        batch_size=args.batch_size,
        rate_limit=args.rate_limit,
        dry_run=args.dry_run
    )

    # Save results (always save, even in dry-run for downstream testing)
    output_dir = Path('workspace/curation/collection_media/fetched')
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_file = args.output
    else:
        # Auto-generate batch filename
        existing_batches = list(output_dir.glob('batch_*.yaml'))
        batch_num = len(existing_batches) + 1
        output_file = output_dir / f'batch_{batch_num:03d}.yaml'

    save_results(results, output_file, dry_run=args.dry_run)
    mode_label = " (dry-run)" if args.dry_run else ""
    print(f"\n✓ Results saved to {output_file}{mode_label}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Processed: {len(results)}")

    if not args.dry_run:
        successful = sum(1 for r in results if r.get('spec', {}).get('parse_success', False))
        failed = len(results) - successful
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
    else:
        print("(Dry run - no fetching performed)")

    return 0


if __name__ == '__main__':
    exit(main())
