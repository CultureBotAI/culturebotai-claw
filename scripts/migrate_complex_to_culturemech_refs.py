#!/usr/bin/env python3
"""Migrate COMPLEX references from MediaIngredientMech to CultureMech cross-references.

This script:
1. Loads all COMPLEX entries from MediaIngredientMech/workspace
2. Extracts culturemech_reference data (23 entries have this)
3. Scans CultureMech recipes for ingredients/solutions using COMPLEX entries
4. Replaces mediaingredientmech_term with culturemech_term
5. Generates report of affected recipes
"""

import yaml
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def load_complex_mappings(workspace: Path) -> dict:
    """Load COMPLEX entries and build mapping to CultureMech IDs."""
    complex_file = workspace / 'curation/complex_formulations_mim_entries.yaml'

    with open(complex_file) as f:
        data = yaml.safe_load(f)

    # Build mapping: COMPLEX_ID -> CultureMech_ID
    mapping = {}
    for entry in data['entries']:
        complex_id = entry['ontology_id']
        if 'culturemech_reference' in entry:
            cm_id = entry['culturemech_reference']['id']
            mapping[complex_id] = {
                'culturemech_id': cm_id,
                'label': entry['preferred_term'],
                'occurrences': entry['occurrence_statistics']['total_occurrences']
            }
        else:
            # No CultureMech reference found
            mapping[complex_id] = {
                'culturemech_id': None,
                'label': entry['preferred_term'],
                'occurrences': entry['occurrence_statistics']['total_occurrences']
            }

    print(f"Loaded {len(mapping)} COMPLEX entries")
    print(f"  - {len([v for v in mapping.values() if v['culturemech_id']])} with CultureMech references")
    print(f"  - {len([v for v in mapping.values() if not v['culturemech_id']])} without CultureMech references")

    return mapping

def scan_culturemech_recipes(cm_root: Path, complex_mapping: dict, dry_run: bool = True):
    """Scan CultureMech recipes and migrate COMPLEX references."""
    recipes_updated = []
    recipes_skipped = []
    errors = []

    # Stats tracking
    stats = {
        'files_scanned': 0,
        'ingredients_migrated': 0,
        'solutions_migrated': 0,
        'skipped_no_cm_id': 0,
        'recipes_modified': 0
    }

    # Find all YAML files
    yaml_files = list(cm_root.glob('data/normalized_yaml/**/*.yaml'))

    print(f"\nScanning {len(yaml_files)} CultureMech recipe files...")

    for yaml_file in yaml_files:
        stats['files_scanned'] += 1

        try:
            with open(yaml_file) as f:
                recipe = yaml.safe_load(f)

            if not recipe:
                continue

            modified = False

            # Check ingredients
            if 'ingredients' in recipe:
                for ing in recipe['ingredients']:
                    if 'mediaingredientmech_term' in ing:
                        mim_id = ing['mediaingredientmech_term'].get('id', '')

                        if mim_id in complex_mapping:
                            cm_info = complex_mapping[mim_id]

                            if cm_info['culturemech_id']:
                                # Migrate to culturemech_term
                                ing['culturemech_term'] = {
                                    'id': cm_info['culturemech_id'],
                                    'label': ing['preferred_term']
                                }
                                del ing['mediaingredientmech_term']

                                stats['ingredients_migrated'] += 1
                                modified = True
                            else:
                                stats['skipped_no_cm_id'] += 1

            # Check solutions
            if 'solutions' in recipe:
                for sol in recipe['solutions']:
                    if 'mediaingredientmech_term' in sol:
                        mim_id = sol['mediaingredientmech_term'].get('id', '')

                        if mim_id in complex_mapping:
                            cm_info = complex_mapping[mim_id]

                            if cm_info['culturemech_id']:
                                # Migrate to culturemech_term
                                sol['culturemech_term'] = {
                                    'id': cm_info['culturemech_id'],
                                    'label': sol['preferred_term']
                                }
                                del sol['mediaingredientmech_term']

                                stats['solutions_migrated'] += 1
                                modified = True
                            else:
                                stats['skipped_no_cm_id'] += 1

            if modified:
                stats['recipes_modified'] += 1
                recipes_updated.append({
                    'file': str(yaml_file.relative_to(cm_root)),
                    'id': recipe.get('id', 'unknown'),
                    'name': recipe.get('name', 'unknown')
                })

                if not dry_run:
                    # Write back
                    with open(yaml_file, 'w') as f:
                        yaml.dump(recipe, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        except Exception as e:
            errors.append({
                'file': str(yaml_file.relative_to(cm_root)),
                'error': str(e)
            })

    return stats, recipes_updated, recipes_skipped, errors

def generate_report(stats: dict, recipes_updated: list, errors: list, dry_run: bool):
    """Generate migration report."""
    print("\n" + "="*80)
    print("MIGRATION REPORT")
    print("="*80)

    print(f"\nMode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
    print(f"\nFiles scanned: {stats['files_scanned']}")
    print(f"Recipes modified: {stats['recipes_modified']}")
    print(f"\nMigrations:")
    print(f"  - Ingredients: {stats['ingredients_migrated']}")
    print(f"  - Solutions: {stats['solutions_migrated']}")
    print(f"  - Total: {stats['ingredients_migrated'] + stats['solutions_migrated']}")

    print(f"\nSkipped (no CultureMech ID): {stats['skipped_no_cm_id']}")

    if recipes_updated:
        print(f"\nRecipes updated ({len(recipes_updated)}):")
        for recipe in recipes_updated[:10]:  # Show first 10
            print(f"  - {recipe['id']}: {recipe['name']}")
            print(f"    File: {recipe['file']}")

        if len(recipes_updated) > 10:
            print(f"  ... and {len(recipes_updated) - 10} more")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for error in errors[:5]:
            print(f"  - {error['file']}: {error['error']}")

    print("\n" + "="*80)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Migrate COMPLEX references to CultureMech cross-references')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Perform dry run without modifying files (default)')
    parser.add_argument('--production', action='store_true',
                       help='Actually modify files')

    args = parser.parse_args()

    dry_run = not args.production

    # Paths
    workspace = Path('workspace')
    cm_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech'

    # Load COMPLEX mappings
    complex_mapping = load_complex_mappings(workspace)

    # Scan and migrate
    stats, recipes_updated, recipes_skipped, errors = scan_culturemech_recipes(
        cm_root, complex_mapping, dry_run
    )

    # Generate report
    generate_report(stats, recipes_updated, errors, dry_run)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No files were modified")
        print("Run with --production to apply changes")
    else:
        print("\n✓ Migration complete")

if __name__ == '__main__':
    main()
