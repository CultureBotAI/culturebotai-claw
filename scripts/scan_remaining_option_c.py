#!/usr/bin/env python3
"""Scan remaining Option C Phase 1 media to categorize by type.

Identifies:
- Empty/not found media (genuinely missing from JCM)
- References to other media
- Commercial products
- Text-only descriptions
"""

import argparse
import requests
from bs4 import BeautifulSoup
import yaml
from pathlib import Path
import time
from typing import Dict, List


def fetch_jcm_page(grmd: str) -> tuple:
    """Fetch JCM page content for a medium."""
    url = f"https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD={grmd}"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text, None
    except Exception as e:
        return None, str(e)


def classify_medium(html: str, grmd: str) -> Dict:
    """Classify medium based on HTML content."""
    soup = BeautifulSoup(html, 'html.parser')

    # Check for "Nothing found"
    if "Nothing found" in html or "nothing found" in html.lower():
        return {
            'type': 'EMPTY',
            'description': 'JCM page returns "Nothing found"',
            'recoverable': False
        }

    # Get all text content
    text = soup.get_text().lower()

    # Check for references to other media
    if 'use medium no.' in text or 'solution a of medium no.' in text or 'prepare medium no.' in text:
        # Extract medium number
        import re
        match = re.search(r'medium no\.\s*(\d+)', text, re.IGNORECASE)
        target_medium = match.group(1) if match else 'UNKNOWN'

        return {
            'type': 'REFERENCE',
            'description': f'References JCM Medium {target_medium}',
            'target_medium': target_medium,
            'recoverable': True
        }

    # Check for commercial products
    if 'commercially available' in text or 'oxoid' in text or 'bd-bbl' in text or 'bd-difco' in text or 'eiken' in text:
        vendor = 'Unknown'
        if 'oxoid' in text:
            vendor = 'Oxoid'
        elif 'bd-bbl' in text or 'bd bbl' in text:
            vendor = 'BD-BBL'
        elif 'bd-difco' in text or 'bd difco' in text:
            vendor = 'BD-Difco'
        elif 'eiken' in text:
            vendor = 'Eiken'

        return {
            'type': 'COMMERCIAL',
            'description': f'Commercial product ({vendor})',
            'vendor': vendor,
            'recoverable': vendor in ['Oxoid', 'BD-BBL', 'BD-Difco']
        }

    # Check for table
    tables = soup.find_all('table')
    composition_tables = [t for t in tables if any(header in str(t).lower() for header in ['ingredient', 'composition', 'formula'])]

    if composition_tables:
        return {
            'type': 'TABLE',
            'description': 'Has composition table',
            'recoverable': True
        }

    # Check for text descriptions with ingredients
    if any(word in text for word in ['g/l', 'mg/l', 'ml/l', 'yeast extract', 'peptone', 'agar', 'nacl']):
        return {
            'type': 'TEXT_DESCRIPTION',
            'description': 'Text-only ingredient description',
            'recoverable': True
        }

    # Unknown
    return {
        'type': 'UNKNOWN',
        'description': 'Page exists but no clear composition format',
        'recoverable': False
    }


def scan_media(media_list: List[Dict], delay: float = 1.0) -> Dict:
    """Scan all media and categorize them."""
    results = {
        'EMPTY': [],
        'REFERENCE': [],
        'COMMERCIAL': [],
        'TABLE': [],
        'TEXT_DESCRIPTION': [],
        'UNKNOWN': [],
        'ERROR': []
    }

    for i, medium in enumerate(media_list, 1):
        grmd = medium['grmd']
        print(f"\n[{i}/{len(media_list)}] Scanning GRMD={grmd} ({medium['name']})...")

        html, error = fetch_jcm_page(grmd)

        if error:
            print(f"  ✗ Error: {error}")
            results['ERROR'].append({
                **medium,
                'error': error
            })
            continue

        classification = classify_medium(html, grmd)
        medium_type = classification['type']

        print(f"  → {medium_type}: {classification['description']}")

        results[medium_type].append({
            **medium,
            **classification
        })

        # Rate limiting
        if i < len(media_list):
            time.sleep(delay)

    return results


def main():
    parser = argparse.ArgumentParser(description='Scan remaining Option C media')
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/curation/option_c_remaining_scan.yaml'),
        help='Output file for scan results'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests (seconds)'
    )

    args = parser.parse_args()

    print("=" * 80)
    print("SCANNING REMAINING OPTION C PHASE 1 MEDIA")
    print("=" * 80)

    # Get all JCM media with incomplete composition
    print("\nScanning CultureMech repository...")
    incomplete = []
    data_dir = args.cm_root / 'data' / 'normalized_yaml'

    for yaml_file in data_dir.rglob('*.yaml'):
        try:
            with open(yaml_file) as f:
                media = yaml.safe_load(f)

            if not media:
                continue

            # Check if JCM media
            media_term_id = media.get('media_term', {}).get('term', {}).get('id', '')
            if not media_term_id.startswith('mediadive.medium:J'):
                continue

            # Check if incomplete
            flags = media.get('data_quality_flags', {})
            if isinstance(flags, dict):
                if flags.get('incomplete_composition') == True:
                    incomplete.append({
                        'id': media.get('id'),
                        'name': media.get('name'),
                        'grmd': media_term_id.replace('mediadive.medium:J', ''),
                        'file': str(yaml_file.relative_to(args.cm_root))
                    })
            elif isinstance(flags, list):
                if 'incomplete_composition' in flags:
                    incomplete.append({
                        'id': media.get('id'),
                        'name': media.get('name'),
                        'grmd': media_term_id.replace('mediadive.medium:J', ''),
                        'file': str(yaml_file.relative_to(args.cm_root))
                    })
        except:
            pass

    print(f"✓ Found {len(incomplete)} JCM media with incomplete_composition\n")

    # Scan all media
    results = scan_media(incomplete, args.delay)

    # Generate summary
    print("\n" + "=" * 80)
    print("SCAN SUMMARY")
    print("=" * 80)
    print(f"Total media scanned: {len(incomplete)}")
    print(f"\nCategory breakdown:")
    print(f"  Empty/not found: {len(results['EMPTY'])} (not recoverable)")
    print(f"  References: {len(results['REFERENCE'])} (recoverable)")
    print(f"  Commercial products: {len(results['COMMERCIAL'])} ({sum(1 for m in results['COMMERCIAL'] if m['recoverable'])} recoverable)")
    print(f"  Has table: {len(results['TABLE'])} (recoverable)")
    print(f"  Text descriptions: {len(results['TEXT_DESCRIPTION'])} (recoverable with effort)")
    print(f"  Unknown: {len(results['UNKNOWN'])} (manual review needed)")
    print(f"  Errors: {len(results['ERROR'])} (retry later)")

    # Calculate recoverable
    recoverable = (
        len(results['REFERENCE']) +
        sum(1 for m in results['COMMERCIAL'] if m['recoverable']) +
        len(results['TABLE']) +
        len(results['TEXT_DESCRIPTION'])
    )
    print(f"\nTotal recoverable: {recoverable}/{len(incomplete)} ({recoverable/len(incomplete)*100:.1f}%)")

    # Save results
    output_data = {
        'metadata': {
            'scan_date': '2026-04-05',
            'total_scanned': len(incomplete),
            'total_recoverable': recoverable
        },
        'empty': results['EMPTY'],
        'references': results['REFERENCE'],
        'commercial': results['COMMERCIAL'],
        'tables': results['TABLE'],
        'text_descriptions': results['TEXT_DESCRIPTION'],
        'unknown': results['UNKNOWN'],
        'errors': results['ERROR']
    }

    with open(args.output, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✅ Results saved to: {args.output}")

    return 0


if __name__ == '__main__':
    exit(main())
