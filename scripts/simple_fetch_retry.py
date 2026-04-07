#!/usr/bin/env python3
"""Simple fetch script for Option C Phase 1 HTTP retries.

Directly fetches and parses 18 CCAP PDFs without pipeline overhead.
"""

import yaml
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import fetch_collection_media functions
from fetch_collection_media import (
    fetch_ccap_pdf,
    parse_ccap_composition
)


def main():
    # Load batch
    batch_file = Path('workspace/curation/option_c_phase1_http_retries_batch.yaml')
    with open(batch_file) as f:
        batch = yaml.safe_load(f)

    media_list = batch['high_priority']

    print(f"Fetching 18 CCAP media from Option C Phase 1...")
    print("=" * 80)

    results = {
        'fetched': [],
        'failed': [],
        'stats': {
            'total': len(media_list),
            'success': 0,
            'failed': 0,
            'total_ingredients': 0
        }
    }

    for i, medium in enumerate(media_list, 1):
        name = medium['name']
        notes = medium['notes_preview']

        # Extract URL
        if 'URL:' in notes:
            url = notes.split('URL:')[-1].strip()
        else:
            print(f"[{i}/{len(media_list)}] {name:30s} ✗ No URL found")
            results['failed'].append({'medium': medium, 'error': 'No URL'})
            results['stats']['failed'] += 1
            continue

        print(f"[{i}/{len(media_list)}] {name:30s}", end=' ')

        try:
            # Fetch PDF
            pdf_content = fetch_ccap_pdf(url)

            if pdf_content is None:
                print("✗ Fetch failed")
                results['failed'].append({'medium': medium, 'error': 'Fetch failed'})
                results['stats']['failed'] += 1
                continue

            # Parse composition
            composition = parse_ccap_composition(pdf_content, name)

            if not composition or not composition.get('ingredients'):
                print("⚠️  No ingredients parsed")
                results['failed'].append({'medium': medium, 'error': 'Parse failed'})
                results['stats']['failed'] += 1
                continue

            ing_count = len(composition['ingredients'])
            print(f"✓ {ing_count} ingredients")

            results['fetched'].append({
                'medium': medium,
                'composition': composition,
                'ingredient_count': ing_count
            })
            results['stats']['success'] += 1
            results['stats']['total_ingredients'] += ing_count

        except Exception as e:
            print(f"✗ Error: {str(e)[:50]}")
            results['failed'].append({'medium': medium, 'error': str(e)})
            results['stats']['failed'] += 1

    # Print summary
    print("\n" + "=" * 80)
    print("FETCH SUMMARY")
    print("=" * 80)
    print(f"Total media: {results['stats']['total']}")
    print(f"Successful: {results['stats']['success']}")
    print(f"Failed: {results['stats']['failed']}")
    print(f"Total ingredients: {results['stats']['total_ingredients']}")

    if results['stats']['success'] > 0:
        avg = results['stats']['total_ingredients'] / results['stats']['success']
        print(f"Average ingredients per medium: {avg:.1f}")

    # Save results
    output_file = Path('workspace/curation/option_c_phase1_fetch_results.yaml')
    with open(output_file, 'w') as f:
        yaml.dump(results, f, default_flow_style=False, sort_keys=False)

    print(f"\nResults saved to: {output_file}")

    return 0 if results['stats']['failed'] == 0 else 1


if __name__ == '__main__':
    exit(main())
