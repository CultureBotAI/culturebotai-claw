#!/usr/bin/env python3
"""
Import Claude Code-curated ingredients and run the sync pipeline.

This script takes the curated ingredients from Claude Code and runs the
quality gate + sync steps of the pipeline.

Usage:
    python scripts/import_curated_ingredients.py --input workspace/curation/ingredients_to_curate.yaml --dry-run
"""

import sys
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import click

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from plugins.lock_manager import LockManager
from plugins.ingredient_repo_synchronizer import IngredientRepoSynchronizer


@click.command()
@click.option('--input', type=str, default='workspace/curation/ingredients_to_curate.yaml', help='Curated ingredients file')
@click.option('--threshold', type=float, default=0.85, help='Auto-accept confidence threshold')
@click.option('--dry-run', is_flag=True, default=True, help='Preview mode')
@click.option('--production', is_flag=True, help='Run in production mode (saves changes)')
def main(input, threshold, dry_run, production):
    """Import curated ingredients and sync to repositories."""

    if production:
        dry_run = False

    input_file = Path(input)
    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Load curated data
    with open(input_file) as f:
        data = yaml.safe_load(f)

    ingredients = data.get('ingredients', [])

    print(f"=== Importing Curated Ingredients ===")
    print(f"Threshold: {threshold}")
    print(f"Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
    print(f"Total ingredients: {len(ingredients)}")

    # Filter for curated ingredients (those with ontology_id filled in)
    curated = [
        ing for ing in ingredients
        if ing.get('suggested_ontology_id') and ing.get('confidence_score') is not None
    ]

    print(f"Curated: {len(curated)}")

    if not curated:
        print("⚠️  No curated ingredients found. Make sure to fill in:")
        print("   - suggested_ontology_id")
        print("   - suggested_ontology_label")
        print("   - ontology_source")
        print("   - confidence_score")
        sys.exit(1)

    # Quality gate: separate by confidence
    auto_accepted = [ing for ing in curated if ing['confidence_score'] >= threshold]
    manual_review = [ing for ing in curated if 0.70 <= ing['confidence_score'] < threshold]
    rejected = [ing for ing in curated if ing['confidence_score'] < 0.70]

    print(f"\nQuality Gate Results:")
    print(f"  Auto-accepted:  {len(auto_accepted)}")
    print(f"  Manual review:  {len(manual_review)}")
    print(f"  Rejected:       {len(rejected)}")

    if not auto_accepted:
        print("\n⚠️  No ingredients meet auto-accept threshold")
        sys.exit(0)

    # Prepare for sync
    canonical_mapped = []
    for ing in auto_accepted:
        canonical_mapped.append({
            'ontology_id': ing['suggested_ontology_id'],
            'preferred_term': ing['suggested_ontology_label'],
            'ontology_source': ing.get('ontology_source', 'CHEBI'),
            'confidence_score': ing['confidence_score'],
            'original_name': ing['name'],
            'synonyms': ing.get('synonyms', []),
            'occurrence_statistics': {
                'total_occurrences': ing.get('total_occurrences', 0)
            }
        })

    workspace = Path('workspace')
    canonical_dir = workspace / 'canonical_ingredients'
    canonical_dir.mkdir(parents=True, exist_ok=True)

    # Update canonical store
    if not dry_run:
        print("\nUpdating canonical store...")
        canonical_file = canonical_dir / 'mapped_ingredients.yaml'

        # Load existing or create new
        if canonical_file.exists():
            with open(canonical_file) as f:
                canonical_data = yaml.safe_load(f) or {}
        else:
            canonical_data = {'ingredients': []}

        existing = canonical_data.get('ingredients', [])

        # Add newly mapped
        for item in canonical_mapped:
            existing.append({
                'ontology_id': item['ontology_id'],
                'preferred_term': item['preferred_term'],
                'ontology_mapping': {
                    'ontology_id': item['ontology_id'],
                    'ontology_label': item['preferred_term'],
                    'ontology_source': item['ontology_source'],
                    'mapping_quality': 'CLAUDE_CODE_CURATED',
                    'confidence_score': item['confidence_score'],
                },
                'occurrence_statistics': item['occurrence_statistics'],
                'mapping_status': 'MAPPED',
                'curation_history': [{
                    'timestamp': datetime.utcnow().isoformat(),
                    'curator': 'claude_code',
                    'action': 'MANUAL_CURATION',
                    'confidence_score': item['confidence_score'],
                }]
            })

        canonical_data['ingredients'] = existing
        canonical_data['metadata'] = {
            'version': '1.0.0',
            'last_updated': datetime.utcnow().isoformat(),
            'total_count': len(existing)
        }

        with open(canonical_file, 'w') as f:
            yaml.dump(canonical_data, f, default_flow_style=False)

        print(f"  ✓ Added {len(canonical_mapped)} mappings to canonical store")

    # Sync to repositories
    print("\nSyncing to repositories...")

    synchronizer = IngredientRepoSynchronizer()

    if dry_run:
        print("  [DRY RUN] Would sync to both repos")
        sync_diff = synchronizer.generate_sync_diff(canonical_mapped)

        print("\n  CultureMech changes:")
        print(f"    - Would update {sync_diff.get('culturemech_updates', 0)} recipes")

        print("\n  MediaIngredientMech changes:")
        print(f"    - Would add {sync_diff.get('mim_additions', 0)} new mappings")

    else:
        # Acquire locks
        lock_manager = LockManager()
        print("  Acquiring locks...")

        cm_locked = lock_manager.acquire_lock("culturemech", "import_curated", wait=False)
        mim_locked = lock_manager.acquire_lock("mediaingredientmech", "import_curated", wait=False)

        if not (cm_locked and mim_locked):
            print("  ✗ Failed to acquire locks")
            sys.exit(1)

        try:
            # Sync to CultureMech
            cm_sync = synchronizer.sync_to_culturemech(canonical_mapped, dry_run=False)
            print(f"  ✓ CultureMech: {cm_sync.updated} recipes updated")

            # Sync to MediaIngredientMech
            mim_sync = synchronizer.sync_to_mediaingredientmech(canonical_mapped, dry_run=False)
            print(f"  ✓ MediaIngredientMech: {mim_sync.added} added, {mim_sync.updated} updated")

        finally:
            lock_manager.release_lock("culturemech")
            lock_manager.release_lock("mediaingredientmech")
            print("  ✓ Locks released")

    print("\n=== Import Complete ===")

    # Save manual review list
    if manual_review:
        review_file = workspace / 'curation' / 'manual_review_needed.yaml'
        with open(review_file, 'w') as f:
            yaml.dump({'ingredients': manual_review}, f, default_flow_style=False)
        print(f"\nℹ️  {len(manual_review)} ingredients need manual review: {review_file}")


if __name__ == '__main__':
    main()
