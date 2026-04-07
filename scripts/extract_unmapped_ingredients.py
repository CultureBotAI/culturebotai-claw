#!/usr/bin/env python3
"""Extract unmapped ingredients from fetched collection media specifications.

Stage 2 of the collection media curation pipeline:
- Loads fetched media specifications (batch YAML files)
- Extracts all ingredient terms
- Queries MediaIngredientMech to check existing mappings
- Deduplicates and aggregates by occurrence count
- Outputs consolidated unmapped ingredient list

Usage:
    python scripts/extract_unmapped_ingredients.py \
        --fetch-results workspace/curation/collection_media/fetched/batch_001.yaml \
        --output workspace/curation/collection_media/extracted/batch_001_unmapped.yaml \
        --mediaingredientmech-root /path/to/MediaIngredientMech
"""

import argparse
import yaml
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict
from datetime import datetime


def load_fetch_results(fetch_file: Path) -> List[Dict]:
    """Load fetched media specifications from YAML file."""
    with open(fetch_file) as f:
        data = yaml.safe_load(f)
    return data.get('results', [])


def load_existing_mappings(mediaingredientmech_root: Path) -> Dict[str, Dict]:
    """
    Load existing ingredient mappings from MediaIngredientMech.

    Returns dict mapping normalized ingredient terms to their ontology info.
    """
    existing_mappings = {}

    # Try to load from MediaIngredientMech collection file
    collection_file = mediaingredientmech_root / 'data' / 'curated' / 'ingredient_collection.yaml'

    if not collection_file.exists():
        print(f"⚠️  MediaIngredientMech collection file not found at {collection_file}")
        print("    Proceeding without existing mappings - all ingredients will be treated as unmapped")
        return existing_mappings

    try:
        with open(collection_file) as f:
            data = yaml.safe_load(f)

        for ingredient in data.get('ingredients', []):
            # Check if ingredient is already mapped
            if ingredient.get('mapping_status') == 'MAPPED':
                preferred_term = ingredient.get('preferred_term', '').lower().strip()
                existing_mappings[preferred_term] = {
                    'ontology_id': ingredient.get('ontology_mapping', {}).get('ontology_id'),
                    'ontology_label': ingredient.get('ontology_mapping', {}).get('ontology_label'),
                    'ontology_source': ingredient.get('ontology_mapping', {}).get('ontology_source'),
                }

                # Also add synonyms
                for synonym in ingredient.get('synonyms', []):
                    syn_text = synonym.get('synonym_text', '').lower().strip()
                    if syn_text and syn_text not in existing_mappings:
                        existing_mappings[syn_text] = existing_mappings[preferred_term]

        print(f"✓ Loaded {len(existing_mappings)} existing mappings from MediaIngredientMech")

    except Exception as e:
        print(f"⚠️  Error loading existing mappings: {e}")

    return existing_mappings


def normalize_term(term: str) -> str:
    """Normalize ingredient term for deduplication."""
    normalized = term.lower().strip()

    # Remove common suffixes/prefixes that don't affect identity
    normalized = normalized.replace(' (difco)', '')
    normalized = normalized.replace(' (bd)', '')
    normalized = normalized.replace(' (sigma)', '')

    return normalized


def extract_unmapped_ingredients(
    fetch_results: List[Dict],
    existing_mappings: Dict[str, Dict]
) -> List[Dict]:
    """
    Extract unmapped ingredients from fetch results.

    Returns list of unmapped ingredients with occurrence statistics.
    """
    # Aggregate by normalized term
    ingredient_stats = defaultdict(lambda: {
        'preferred_term': '',
        'synonyms': set(),
        'occurrence_count': 0,
        'media_sources': [],
        'concentrations': [],
    })

    for result in fetch_results:
        media_id = result.get('media_id')
        spec = result.get('spec')

        if not spec or not spec.get('parse_success'):
            continue

        for ingredient in spec.get('ingredients', []):
            term = ingredient.get('preferred_term', '').strip()
            if not term or len(term) < 2:
                continue

            normalized = normalize_term(term)

            # Skip if already mapped in MediaIngredientMech
            if normalized in existing_mappings:
                continue

            # Aggregate statistics
            stats = ingredient_stats[normalized]
            if not stats['preferred_term']:
                stats['preferred_term'] = term  # Use first occurrence as preferred

            stats['synonyms'].add(term)
            stats['occurrence_count'] += 1
            stats['media_sources'].append(media_id)

            # Track concentration if present
            conc = ingredient.get('concentration')
            if conc:
                stats['concentrations'].append({
                    'value': conc.get('value'),
                    'unit': conc.get('unit'),
                    'media_id': media_id
                })

    # Convert to list format
    unmapped_list = []
    for normalized, stats in ingredient_stats.items():
        unmapped_list.append({
            'preferred_term': stats['preferred_term'],
            'synonyms': sorted(list(stats['synonyms']))[:10],  # Limit synonyms
            'occurrence_count': stats['occurrence_count'],
            'media_sources': stats['media_sources'][:20],  # Sample of media sources
            'sample_concentrations': stats['concentrations'][:5],  # Sample concentrations
        })

    # Sort by occurrence count (most common first)
    unmapped_list.sort(key=lambda x: x['occurrence_count'], reverse=True)

    return unmapped_list


def save_unmapped(unmapped: List[Dict], output_file: Path, metadata: Dict):
    """Save unmapped ingredients to YAML file."""
    output_data = {
        'metadata': {
            'extraction_date': datetime.now().isoformat(),
            'total_unmapped': len(unmapped),
            'source_file': metadata.get('source_file', ''),
            'media_processed': metadata.get('media_processed', 0),
        },
        'unmapped_ingredients': unmapped
    }

    with open(output_file, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main():
    parser = argparse.ArgumentParser(
        description='Extract unmapped ingredients from fetched media specifications'
    )
    parser.add_argument(
        '--fetch-results',
        type=Path,
        required=True,
        help='Path to fetch results YAML file'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output file path (default: auto-generated in extracted/ directory)'
    )
    parser.add_argument(
        '--mediaingredientmech-root',
        type=Path,
        default=Path('../MediaIngredientMech'),
        help='Path to MediaIngredientMech repository root'
    )

    args = parser.parse_args()

    # Load fetch results
    print(f"Loading fetch results from {args.fetch_results}")
    fetch_results = load_fetch_results(args.fetch_results)
    print(f"Loaded {len(fetch_results)} media fetch results\n")

    # Load existing mappings from MediaIngredientMech
    print(f"Checking existing mappings in {args.mediaingredientmech_root}")
    existing_mappings = load_existing_mappings(args.mediaingredientmech_root)
    print()

    # Extract unmapped ingredients
    print("Extracting unmapped ingredients...")
    unmapped = extract_unmapped_ingredients(fetch_results, existing_mappings)
    print(f"✓ Found {len(unmapped)} unmapped ingredient terms\n")

    # Determine output path
    if args.output:
        output_file = args.output
    else:
        # Auto-generate output path
        output_dir = Path('workspace/curation/collection_media/extracted')
        output_dir.mkdir(parents=True, exist_ok=True)

        # Use same batch ID as input
        batch_id = args.fetch_results.stem  # e.g., "batch_001"
        output_file = output_dir / f'{batch_id}_unmapped.yaml'

    # Save results
    metadata = {
        'source_file': str(args.fetch_results),
        'media_processed': len(fetch_results),
    }
    save_unmapped(unmapped, output_file, metadata)
    print(f"✓ Saved unmapped ingredients to {output_file}")

    # Summary statistics
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Media processed: {len(fetch_results)}")
    print(f"Unmapped ingredients: {len(unmapped)}")

    if unmapped:
        print(f"\nTop 10 most common unmapped ingredients:")
        for i, ing in enumerate(unmapped[:10], 1):
            print(f"  {i}. {ing['preferred_term']} ({ing['occurrence_count']} occurrences)")

    return 0


if __name__ == '__main__':
    exit(main())
