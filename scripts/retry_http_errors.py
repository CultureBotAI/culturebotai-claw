#!/usr/bin/env python3
"""Retry fetching media that failed with HTTP errors.

Usage:
    python scripts/retry_http_errors.py --dry-run  # Test connections
    python scripts/retry_http_errors.py            # Fetch and parse
"""

import argparse
import yaml
import requests
from pathlib import Path
from datetime import datetime
from io import BytesIO


def test_url_accessibility(url: str, timeout: int = 10) -> dict:
    """Test if URL is accessible and returns valid content."""
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get('content-type', '')
        content_length = len(response.content)

        return {
            'accessible': True,
            'status_code': response.status_code,
            'content_type': content_type,
            'content_length': content_length,
            'is_pdf': 'pdf' in content_type.lower()
        }
    except requests.exceptions.Timeout:
        return {'accessible': False, 'error': 'Timeout'}
    except requests.exceptions.ConnectionError as e:
        return {'accessible': False, 'error': f'Connection error: {str(e)[:50]}'}
    except requests.exceptions.HTTPError as e:
        return {'accessible': False, 'error': f'HTTP error: {e.response.status_code}'}
    except Exception as e:
        return {'accessible': False, 'error': f'Error: {str(e)[:50]}'}


def parse_ccap_pdf(url: str) -> dict:
    """Fetch and parse CCAP PDF to extract composition table."""
    try:
        import pdfplumber

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # Parse PDF
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            tables = []
            for page in pdf.pages:
                page_tables = page.extract_tables()
                if page_tables:
                    tables.extend(page_tables)

            if not tables:
                return {
                    'success': False,
                    'error': 'No tables found in PDF',
                    'page_count': len(pdf.pages)
                }

            # Extract ingredients from first table
            ingredients = []
            table = tables[0]

            for row in table[1:]:  # Skip header
                if not row or len(row) < 2:
                    continue

                ingredient = row[0]
                concentration = row[1] if len(row) > 1 else None

                if ingredient and ingredient.strip():
                    ingredients.append({
                        'name': ingredient.strip(),
                        'concentration': concentration.strip() if concentration else None
                    })

            return {
                'success': True,
                'ingredient_count': len(ingredients),
                'ingredients': ingredients[:5],  # Sample
                'page_count': len(pdf.pages),
                'table_count': len(tables)
            }

    except Exception as e:
        return {
            'success': False,
            'error': f'Parse error: {str(e)[:100]}'
        }


def main():
    parser = argparse.ArgumentParser(description='Retry HTTP error media')
    parser.add_argument('--dry-run', action='store_true', help='Test accessibility only')
    parser.add_argument('--timeout', type=int, default=30, help='Request timeout (seconds)')

    args = parser.parse_args()

    # Load retry batch
    batch_file = Path('workspace/curation/option_c_phase1_http_retries.yaml')
    with open(batch_file) as f:
        batch = yaml.safe_load(f)

    media_list = batch['media']

    print(f"{'DRY RUN - ' if args.dry_run else ''}Retrying {len(media_list)} CCAP media\n")

    results = {
        'successful': [],
        'still_failing': [],
        'stats': {
            'total': len(media_list),
            'accessible': 0,
            'not_accessible': 0,
            'parseable': 0,
            'unparseable': 0
        }
    }

    for i, medium in enumerate(media_list, 1):
        print(f"[{i}/{len(media_list)}] {medium['name']:30s}", end=' ')

        # Test accessibility
        access_result = test_url_accessibility(medium['url'], args.timeout)

        if not access_result['accessible']:
            print(f"✗ {access_result['error']}")
            results['still_failing'].append({
                'medium': medium,
                'error': access_result['error']
            })
            results['stats']['not_accessible'] += 1
            continue

        results['stats']['accessible'] += 1

        # If dry-run, just report accessibility
        if args.dry_run:
            size_mb = access_result['content_length'] / 1024 / 1024
            print(f"✓ Accessible ({size_mb:.1f} MB, {access_result['content_type']})")
            results['successful'].append({
                'medium': medium,
                'accessible': True,
                'content_info': access_result
            })
            continue

        # Try to parse PDF
        parse_result = parse_ccap_pdf(medium['url'])

        if parse_result['success']:
            ing_count = parse_result['ingredient_count']
            print(f"✓ Parsed ({ing_count} ingredients)")
            results['successful'].append({
                'medium': medium,
                'accessible': True,
                'parseable': True,
                'parse_result': parse_result
            })
            results['stats']['parseable'] += 1
        else:
            print(f"⚠️  Accessible but parse failed: {parse_result['error']}")
            results['successful'].append({
                'medium': medium,
                'accessible': True,
                'parseable': False,
                'parse_result': parse_result
            })
            results['stats']['unparseable'] += 1

    # Print summary
    print("\n" + "=" * 80)
    print("RETRY SUMMARY")
    print("=" * 80)
    print(f"Total media: {results['stats']['total']}")
    print(f"Accessible: {results['stats']['accessible']}")
    print(f"Not accessible: {results['stats']['not_accessible']}")

    if not args.dry_run:
        print(f"Parseable: {results['stats']['parseable']}")
        print(f"Unparseable: {results['stats']['unparseable']}")

    # Save results
    output_file = Path('workspace/curation/option_c_phase1_http_retry_results.yaml')
    with open(output_file, 'w') as f:
        yaml.dump(results, f, default_flow_style=False, sort_keys=False)

    print(f"\nResults saved to: {output_file}")

    if results['still_failing']:
        print(f"\n⚠️  {len(results['still_failing'])} media still failing:")
        for item in results['still_failing'][:5]:
            print(f"  - {item['medium']['name']}: {item['error']}")

    return 0 if results['stats']['not_accessible'] == 0 else 1


if __name__ == '__main__':
    exit(main())
