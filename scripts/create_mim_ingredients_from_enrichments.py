#!/usr/bin/env python3
"""
Create MediaIngredientMech ingredient files from enrichment results.

Generates properly formatted ingredient YAML files for the 70 enriched
ingredients that don't yet exist in MediaIngredientMech.
"""

import yaml
from pathlib import Path
from datetime import datetime
import argparse
from typing import Dict, List
import sys
import re


class MIMIngredientCreator:
    """Creates MediaIngredientMech ingredient files from enrichments."""

    def __init__(self, mim_root: Path, enrichment_file: Path, culturemech_root: Path):
        self.mim_root = mim_root
        self.enrichment_file = enrichment_file
        self.culturemech_root = culturemech_root
        self.enrichments = {}
        self.ingredient_usage = {}
        self.stats = {
            'enrichments_loaded': 0,
            'ingredients_already_in_mim': 0,
            'ingredients_to_create': 0,
            'files_created': 0
        }

    def load_enrichments(self):
        """Load ChEBI enrichment results."""
        print(f"Loading enrichments from {self.enrichment_file}...")

        with open(self.enrichment_file) as f:
            data = yaml.safe_load(f)

        self.enrichments = data.get('enrichments', {})
        self.stats['enrichments_loaded'] = len(self.enrichments)

        # Count successful enrichments
        successful = sum(1 for e in self.enrichments.values() if e.get('chebi_id'))
        print(f"Loaded {len(self.enrichments)} enrichment entries")
        print(f"  {successful} with ChEBI IDs\n")

    def collect_usage_statistics(self):
        """
        Collect usage statistics from FEBA ontology coverage report.

        Much faster than scanning all CultureMech files - uses cached data.
        """
        print("Loading usage statistics from ontology coverage report...")

        # Try to load from ontology coverage report
        ontology_report = Path('workspace/feba_ontology_coverage_report.yaml')

        if ontology_report.exists():
            with open(ontology_report) as f:
                data = yaml.safe_load(f)

            # Get usage from both mapped and unmapped ingredients
            usage = {}

            for section in ['ingredients_with_ontology', 'ingredients_without_ontology']:
                ingredients = data.get(section, {})
                for ingredient_name, details in ingredients.items():
                    usage[ingredient_name] = {
                        'total_occurrences': details.get('media_count', 1),
                        'media_count': details.get('media_count', 1),
                        'example_media': details.get('example_media', [])
                    }

            self.ingredient_usage = usage
            print(f"Loaded usage statistics for {len(usage)} ingredients from report\n")
        else:
            print(f"Warning: Ontology coverage report not found, using default statistics\n")
            self.ingredient_usage = {}

    def normalize_filename(self, ingredient_name: str) -> str:
        """
        Create normalized filename for ingredient.

        Follows MIM convention: spaces to underscores, special chars handled.
        """
        # Replace spaces with underscores
        filename = ingredient_name.replace(' ', '_')

        # Handle special characters
        filename = filename.replace('(', '')
        filename = filename.replace(')', '')
        filename = filename.replace(',', '')
        filename = filename.replace("'", '')
        filename = filename.replace('-', '_')

        # Remove multiple underscores
        filename = re.sub(r'_+', '_', filename)

        return filename + '.yaml'

    def ingredient_exists_in_mim(self, ingredient_name: str) -> bool:
        """Check if ingredient already exists in MIM."""
        ingredients_dir = self.mim_root / 'data' / 'ingredients'

        if not ingredients_dir.exists():
            return False

        normalized_search = ingredient_name.lower().strip()

        # Search in both mapped and unmapped directories
        for subdir in ['mapped', 'unmapped']:
            subdir_path = ingredients_dir / subdir
            if not subdir_path.exists():
                continue

            for yaml_file in subdir_path.glob('*.yaml'):
                try:
                    with open(yaml_file) as f:
                        ingredient_data = yaml.safe_load(f)

                    if not ingredient_data:
                        continue

                    # Check preferred_term field
                    preferred_term = ingredient_data.get('preferred_term', '')
                    if preferred_term.lower().strip() == normalized_search:
                        return True

                except Exception:
                    continue

        return False

    def create_ingredient_file(self, ingredient_name: str, enrichment_data: Dict, dry_run: bool = False):
        """
        Create ingredient YAML file in MIM.

        Creates file in data/ingredients/mapped/ with proper schema.
        """
        chebi_id = enrichment_data.get('chebi_id')
        cas_rn = enrichment_data.get('cas_rn', '')

        if not chebi_id:
            return False

        # Get usage statistics
        usage = self.ingredient_usage.get(ingredient_name, {
            'total_occurrences': 0,
            'media_count': 0,
            'example_media': []
        })

        # Create ingredient data structure
        ingredient_data = {
            'identifier': chebi_id,
            'preferred_term': ingredient_name,
            'ontology_mapping': {
                'ontology_id': chebi_id,
                'ontology_label': '',  # Would need ChEBI API to populate
                'ontology_source': 'CHEBI',
                'mapping_quality': 'CAS_RN_LOOKUP',
                'evidence': [
                    {
                        'evidence_type': 'CAS_RN_CROSS_REFERENCE',
                        'source': 'PubChem',
                        'cas_rn': cas_rn,
                        'notes': f'ChEBI ID {chebi_id} found via PubChem CAS-RN cross-reference'
                    }
                ]
            },
            'synonyms': [],  # Could extract from CultureMech if needed
            'mapping_status': 'MAPPED',
            'occurrence_statistics': {
                'total_occurrences': usage.get('total_occurrences', 0),
                'media_count': usage.get('media_count', 0)
            },
            'curation_history': [
                {
                    'timestamp': datetime.now().isoformat(),
                    'curator': 'feba_ontology_enrichment_batch',
                    'action': 'CREATED',
                    'changes': f'Created ingredient file from FEBA ontology enrichment batch with ChEBI ID {chebi_id}',
                    'new_status': 'MAPPED',
                    'llm_assisted': False
                }
            ],
            'notes': f'Created from FEBA ontology enrichment workflow. Used in {usage.get("media_count", 0)} FEBA media formulations.'
        }

        # Add chemical properties if CAS-RN available
        if cas_rn:
            ingredient_data['chemical_properties'] = {
                'cas_rn': cas_rn,
                'data_source': 'FEBA ontology enrichment (via PubChem)',
                'retrieval_date': datetime.now().isoformat()
            }

        # Create filename
        filename = self.normalize_filename(ingredient_name)
        output_dir = self.mim_root / 'data' / 'ingredients' / 'mapped'
        output_file = output_dir / filename

        if not dry_run:
            # Ensure directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Write YAML file
            with open(output_file, 'w') as f:
                yaml.dump(ingredient_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return True

    def create_ingredients(self, dry_run: bool = False):
        """Create ingredient files for all enrichments not in MIM."""
        print("Creating ingredient files...\n")

        for ingredient_name, enrichment_data in sorted(self.enrichments.items()):
            chebi_id = enrichment_data.get('chebi_id')

            if not chebi_id:
                continue

            # Check if already exists
            if self.ingredient_exists_in_mim(ingredient_name):
                self.stats['ingredients_already_in_mim'] += 1
                print(f"  [SKIP] {ingredient_name} - already in MIM")
                continue

            # Create ingredient file
            self.stats['ingredients_to_create'] += 1

            if self.create_ingredient_file(ingredient_name, enrichment_data, dry_run):
                self.stats['files_created'] += 1

                usage = self.ingredient_usage.get(ingredient_name, {})
                media_count = usage.get('media_count', 0)

                if dry_run:
                    print(f"  [DRY RUN] {ingredient_name} → {chebi_id} (used in {media_count} media)")
                else:
                    print(f"  [CREATE] {ingredient_name} → {chebi_id} (used in {media_count} media)")

    def print_summary(self):
        """Print creation summary."""
        print("\n" + "=" * 80)
        print("INGREDIENT CREATION SUMMARY")
        print("=" * 80)
        print(f"Enrichments loaded: {self.stats['enrichments_loaded']}")
        print(f"Already in MIM (skipped): {self.stats['ingredients_already_in_mim']}")
        print(f"Ingredients to create: {self.stats['ingredients_to_create']}")
        print(f"Files created: {self.stats['files_created']}")


def main():
    parser = argparse.ArgumentParser(
        description='Create MediaIngredientMech ingredient files from enrichments'
    )
    parser.add_argument(
        '--mim',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--enrichment-file',
        type=Path,
        default=Path('workspace/feba_chebi_enrichment_results.yaml'),
        help='ChEBI enrichment results file'
    )
    parser.add_argument(
        '--culturemech',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository (for usage statistics)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - show what would be done without creating files'
    )

    args = parser.parse_args()

    if not args.mim.exists():
        print(f"Error: MediaIngredientMech directory not found: {args.mim}")
        sys.exit(1)

    if not args.enrichment_file.exists():
        print(f"Error: Enrichment file not found: {args.enrichment_file}")
        sys.exit(1)

    if not args.culturemech.exists():
        print(f"Error: CultureMech directory not found: {args.culturemech}")
        sys.exit(1)

    if args.dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No files will be created")
        print("=" * 80)
        print()

    creator = MIMIngredientCreator(args.mim, args.enrichment_file, args.culturemech)

    # Load enrichments
    creator.load_enrichments()

    # Collect usage statistics
    creator.collect_usage_statistics()

    # Create ingredient files
    creator.create_ingredients(dry_run=args.dry_run)

    # Print summary
    creator.print_summary()

    if args.dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE - Run without --dry-run to create files")
        print("=" * 80)
    else:
        print("\n✅ Ingredient files created successfully")


if __name__ == '__main__':
    main()
