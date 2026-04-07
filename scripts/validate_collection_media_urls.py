#!/usr/bin/env python3
"""Validate collection media URLs to filter out non-existent or reference-only media.

Checks JCM and CCAP URLs to identify:
- Media that don't exist ("Nothing found")
- Media that are references to other media ("Use Medium No. X")
- Media with actual composition tables

Usage:
    python scripts/validate_collection_media_urls.py \
        --input workspace/commercial_expansions/identified_media.yaml \
        --output workspace/commercial_expansions/validated_media.yaml \
        --batch-size 100 \
        --dry-run
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


def extract_source_url(media: Dict) -> Optional[str]:
    """Extract source URL from media notes."""
    notes = media.get('notes_preview', '')

    # Check for JCM
    jcm_match = re.search(r'https://www\.jcm\.riken\.jp/cgi-bin/jcm/jcm_grmd\?GRMD=(\d+)', notes)
    if jcm_match:
        return jcm_match.group(0)

    # Check for CCAP
    ccap_match = re.search(r'https://www\.ccap\.ac\.uk/wp-content/uploads/(MR_[^\.]+\.pdf)', notes)
    if ccap_match:
        return ccap_match.group(0)

    return None


def validate_jcm_medium(url: str) -> Dict:
    """
    Validate a JCM medium URL.

    Returns dict with:
    - valid: bool (has composition table)
    - reason: str (why valid/invalid)
    - is_reference: bool (references another medium)
    - has_table: bool (has composition table)
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; CultureMech/1.0; +https://github.com/kg-microbe)'
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # Check for "Nothing found"
        if 'Nothing found' in html:
            return {
                'valid': False,
                'reason': 'Medium not found',
                'is_reference': False,
                'has_table': False
            }

        # Check for reference pattern ("Use Medium No. X")
        if re.search(r'Use Medium No\.\s*<a href', html, re.IGNORECASE):
            # Extract referenced medium number
            ref_match = re.search(r'GRMD=(\d+)', html)
            ref_medium = ref_match.group(1) if ref_match else 'unknown'
            return {
                'valid': False,
                'reason': f'References medium {ref_medium}',
                'is_reference': True,
                'has_table': False,
                'reference_medium': ref_medium
            }

        # Check for composition table (has BORDER attribute)
        tables = soup.find_all('table', {'border': True})

        if not tables:
            return {
                'valid': False,
                'reason': 'No composition table found',
                'is_reference': False,
                'has_table': False
            }

        # Count ingredient rows (skip distilled water)
        ingredient_count = 0
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 3:
                    ingredient = cells[0].get_text(strip=True).lower()
                    if ingredient and 'distilled water' not in ingredient:
                        ingredient_count += 1

        if ingredient_count == 0:
            return {
                'valid': False,
                'reason': 'Empty composition table',
                'is_reference': False,
                'has_table': True
            }

        return {
            'valid': True,
            'reason': f'Has composition table with {ingredient_count} ingredients',
            'is_reference': False,
            'has_table': True,
            'ingredient_count': ingredient_count
        }

    except requests.RequestException as e:
        return {
            'valid': False,
            'reason': f'HTTP error: {str(e)}',
            'is_reference': False,
            'has_table': False,
            'error': str(e)
        }


def validate_ccap_medium(url: str) -> Dict:
    """
    Validate a CCAP medium URL (PDF).

    For now, just check if URL is accessible.
    Full validation requires downloading and parsing PDF.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; CultureMech/1.0; +https://github.com/kg-microbe)'
        }

        response = requests.head(url, headers=headers, timeout=10, allow_redirects=True)

        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' in content_type.lower():
                return {
                    'valid': True,
                    'reason': 'PDF accessible',
                    'is_reference': False,
                    'has_table': True  # Assume PDFs have content
                }
            else:
                return {
                    'valid': False,
                    'reason': f'Not a PDF (Content-Type: {content_type})',
                    'is_reference': False,
                    'has_table': False
                }
        else:
            return {
                'valid': False,
                'reason': f'HTTP {response.status_code}',
                'is_reference': False,
                'has_table': False
            }

    except requests.RequestException as e:
        return {
            'valid': False,
            'reason': f'HTTP error: {str(e)}',
            'is_reference': False,
            'has_table': False,
            'error': str(e)
        }


def validate_batch(
    media_list: List[Dict],
    batch_size: int,
    rate_limit: float = 1.0,
    dry_run: bool = False
) -> List[Dict]:
    """
    Validate a batch of media URLs.

    Returns list of validation results.
    """
    results = []

    for i, media in enumerate(media_list[:batch_size], 1):
        media_id = media.get('id')
        media_name = media.get('name')
        supplier = media.get('supplier')

        # Extract source URL
        url = extract_source_url(media)

        if not url:
            results.append({
                'media': media,
                'validation': {
                    'valid': False,
                    'reason': 'No source URL found',
                    'is_reference': False,
                    'has_table': False
                }
            })
            print(f"{i:4d}. {media_id:20s} ⚠️  No URL")
            continue

        if dry_run:
            print(f"{i:4d}. {media_id:20s} [DRY RUN] {supplier}")
            results.append({
                'media': media,
                'validation': {
                    'valid': None,
                    'reason': 'Dry run - not validated',
                    'is_reference': False,
                    'has_table': False
                }
            })
            continue

        # Validate based on source type
        if 'jcm.riken.jp' in url:
            validation = validate_jcm_medium(url)
        elif 'ccap.ac.uk' in url:
            validation = validate_ccap_medium(url)
        else:
            validation = {
                'valid': False,
                'reason': 'Unknown source type',
                'is_reference': False,
                'has_table': False
            }

        results.append({
            'media': media,
            'validation': validation
        })

        # Print result
        status_icon = "✅" if validation['valid'] else "❌"
        reason = validation['reason'][:60]
        print(f"{i:4d}. {media_id:20s} {status_icon} {reason}")

        # Rate limiting
        if not dry_run:
            time.sleep(rate_limit)

    return results


def save_validated_media(results: List[Dict], output_file: Path):
    """Save validated media to YAML file."""

    # Separate valid and invalid media
    valid_media = []
    invalid_media = []

    for result in results:
        media = result['media'].copy()
        validation = result['validation']

        # Add validation metadata
        media['validation'] = validation

        if validation['valid']:
            valid_media.append(media)
        else:
            invalid_media.append(media)

    # Create output data
    output_data = {
        'metadata': {
            'validation_date': datetime.now().isoformat(),
            'total_validated': len(results),
            'valid_count': len(valid_media),
            'invalid_count': len(invalid_media),
            'valid_percentage': (len(valid_media) / len(results) * 100) if results else 0
        },
        'valid_media': valid_media,
        'invalid_media': invalid_media
    }

    with open(output_file, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main():
    parser = argparse.ArgumentParser(
        description='Validate collection media URLs'
    )
    parser.add_argument(
        '--input',
        type=Path,
        default=Path('workspace/commercial_expansions/identified_media.yaml'),
        help='Input identified media YAML'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/commercial_expansions/validated_media.yaml'),
        help='Output validated media YAML'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of media to validate (default: 100)'
    )
    parser.add_argument(
        '--rate-limit',
        type=float,
        default=1.0,
        help='Seconds between requests (default: 1.0)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run - do not fetch URLs'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No HTTP requests will be made\n")

    # Load identified media
    print(f"Loading identified media from {args.input}")
    with open(args.input) as f:
        data = yaml.safe_load(f)

    media_list = data.get('high_priority', [])
    print(f"Loaded {len(media_list)} high-priority media\n")

    # Validate batch
    print(f"Validating batch of {args.batch_size} media...")
    print("=" * 80)

    results = validate_batch(
        media_list,
        batch_size=args.batch_size,
        rate_limit=args.rate_limit,
        dry_run=args.dry_run
    )

    # Save results
    if not args.dry_run:
        save_validated_media(results, args.output)
        print(f"\n✓ Saved validated media to {args.output}")

    # Summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    if not args.dry_run:
        valid_count = sum(1 for r in results if r['validation']['valid'])
        invalid_count = len(results) - valid_count

        reference_count = sum(1 for r in results if r['validation'].get('is_reference', False))
        not_found_count = sum(1 for r in results if 'not found' in r['validation']['reason'].lower())
        no_table_count = sum(1 for r in results if not r['validation'].get('has_table', False) and not r['validation'].get('is_reference', False))

        print(f"Total validated: {len(results)}")
        print(f"Valid: {valid_count} ({valid_count/len(results)*100:.1f}%)")
        print(f"Invalid: {invalid_count} ({invalid_count/len(results)*100:.1f}%)")
        print(f"\nBreakdown of invalid:")
        print(f"  - References to other media: {reference_count}")
        print(f"  - Not found: {not_found_count}")
        print(f"  - No composition table: {no_table_count}")

        if valid_count > 0:
            print(f"\n✅ Found {valid_count} valid media ready for curation")
        else:
            print(f"\n⚠️  No valid media found in this batch")
    else:
        print(f"Processed: {len(results)} (dry run)")

    return 0


if __name__ == '__main__':
    exit(main())
