#!/usr/bin/env python3
"""
Export unmapped ingredients for Claude Code curation.

This script extracts and prioritizes unmapped ingredients, then exports them
to a simple format that Claude Code can review and curate.

Usage:
    python scripts/export_for_curation.py --batch-size 50 --min-occurrences 10
"""

import sys
import yaml
from pathlib import Path
from dotenv import load_dotenv
import click

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from plugins.lock_manager import LockManager
from plugins.ingredient_deduplicator import IngredientDeduplicator


@click.command()
@click.option('--batch-size', type=int, default=20, help='Number of ingredients to export')
@click.option('--min-occurrences', type=int, default=10, help='Minimum occurrences')
@click.option('--output', type=str, default='workspace/curation/ingredients_to_curate.yaml', help='Output file')
def main(batch_size, min_occurrences, output):
    """Export ingredients for Claude Code curation."""

    # Setup paths
    workspace = Path('workspace')
    culturemech_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech'
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'

    output_file = Path(output)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"Extracting unmapped ingredients...")

    # Extract from both repos
    culturemech_unmapped = []
    mim_unmapped = []

    cm_file = culturemech_root / "output/unmapped_ingredients.yaml"
    if cm_file.exists():
        with open(cm_file) as f:
            data = yaml.safe_load(f) or {}
            culturemech_unmapped = data.get('ingredients', [])

    mim_file = mim_root / "data/curated/unmapped_ingredients.yaml"
    if mim_file.exists():
        with open(mim_file) as f:
            data = yaml.safe_load(f) or {}
            mim_unmapped = data.get('ingredients', [])

    print(f"  CultureMech: {len(culturemech_unmapped)} unmapped")
    print(f"  MediaIngredientMech: {len(mim_unmapped)} unmapped")

    # Deduplicate
    deduplicator = IngredientDeduplicator()
    deduplicated, conflicts = deduplicator.deduplicate_unmapped(
        culturemech_unmapped,
        mim_unmapped
    )

    print(f"  Deduplicated: {len(deduplicated)} total")

    # Filter by min occurrences
    filtered = [
        ing for ing in deduplicated
        if ing.get('occurrence_statistics', {}).get('total_occurrences', 0) >= min_occurrences
    ]

    # Sort by occurrence count
    sorted_ingredients = sorted(
        filtered,
        key=lambda x: x.get('occurrence_statistics', {}).get('total_occurrences', 0),
        reverse=True
    )

    # Take batch
    batch = sorted_ingredients[:batch_size]

    print(f"  Filtered to {len(filtered)} with >={min_occurrences} occurrences")
    print(f"  Exporting top {len(batch)} ingredients")

    # Export in Claude Code-friendly format
    export_data = {
        'metadata': {
            'batch_size': len(batch),
            'min_occurrences': min_occurrences,
            'total_unmapped': len(deduplicated),
            'instructions': 'For each ingredient, suggest CHEBI or FOODON ontology mappings'
        },
        'ingredients': []
    }

    for idx, ing in enumerate(batch, 1):
        stats = ing.get('occurrence_statistics', {})

        export_data['ingredients'].append({
            'id': idx,
            'name': ing.get('preferred_term', 'Unknown'),
            'synonyms': ing.get('synonyms', []),
            'total_occurrences': stats.get('total_occurrences', 0),
            'sources': ing.get('sources', []),

            # Fields to fill in during curation
            'suggested_ontology_id': None,  # e.g., "CHEBI:12345"
            'suggested_ontology_label': None,  # e.g., "sodium chloride"
            'ontology_source': None,  # e.g., "CHEBI" or "FOODON"
            'confidence_score': None,  # 0.0-1.0
            'notes': None,  # Any curation notes
        })

    # Write output
    with open(output_file, 'w') as f:
        yaml.dump(export_data, f, default_flow_style=False, sort_keys=False)

    print(f"\n✓ Exported to: {output_file}")
    print(f"\nNext steps:")
    print(f"1. Open this file in Claude Code")
    print(f"2. Have Claude curate each ingredient (suggest ontology mappings)")
    print(f"3. Save the curated file")
    print(f"4. Run: python scripts/import_curated_ingredients.py")


if __name__ == '__main__':
    main()
