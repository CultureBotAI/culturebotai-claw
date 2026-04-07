#!/usr/bin/env python3
"""
Update MediaIngredientMech with ChEBI enrichment results.

Adds ontology mappings to ingredient YAML files based on ChEBI enrichments.
"""

import yaml
from pathlib import Path
from datetime import datetime
import argparse
from typing import Dict, List
import sys


class MIMEnrichmentUpdater:
    """Updates MediaIngredientMech with ChEBI enrichments."""

    def __init__(self, mim_root: Path, enrichment_file: Path):
        self.mim_root = mim_root
        self.enrichment_file = enrichment_file
        self.enrichments = {}
        self.stats = {
            'enrichments_loaded': 0,
            'ingredients_found_in_mim': 0,
            'ingredients_already_mapped': 0,
            'ingredients_updated': 0,
            'ingredients_not_in_mim': 0,
            'files_modified': []
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
        print(f"  {successful} with ChEBI IDs")
        print(f"  {len(self.enrichments) - successful} without ChEBI IDs")

    def normalize_name(self, name: str) -> str:
        """Normalize ingredient name for matching."""
        # Remove special characters, lowercase, strip whitespace
        normalized = name.lower().strip()
        # Remove common prefixes like concentrations
        for prefix in ['0.1%', '0.2%', '1%', '2%', '5%', '10%']:
            if normalized.startswith(prefix.lower()):
                normalized = normalized[len(prefix):].strip()
        return normalized

    def find_ingredient_file(self, ingredient_name: str) -> Path:
        """
        Find ingredient YAML file in MediaIngredientMech.

        Returns: Path to ingredient file, or None if not found
        """
        ingredients_dir = self.mim_root / 'data' / 'ingredients'

        if not ingredients_dir.exists():
            return None

        normalized_search = self.normalize_name(ingredient_name)

        # Search in both mapped and unmapped directories
        for subdir in ['mapped', 'unmapped']:
            subdir_path = ingredients_dir / subdir
            if not subdir_path.exists():
                continue

            # Try looking inside YAML files for name match
            for yaml_file in subdir_path.glob('*.yaml'):
                try:
                    with open(yaml_file) as f:
                        ingredient_data = yaml.safe_load(f)

                    if not ingredient_data:
                        continue

                    # Check preferred_term field
                    preferred_term = ingredient_data.get('preferred_term', '')
                    if self.normalize_name(preferred_term) == normalized_search:
                        return yaml_file

                    # Check synonyms
                    synonyms = ingredient_data.get('synonyms', [])
                    for synonym in synonyms:
                        synonym_text = synonym.get('synonym_text', '')
                        if self.normalize_name(synonym_text) == normalized_search:
                            return yaml_file

                except Exception:
                    continue

        return None

    def update_ingredient_file(self, ingredient_file: Path, chebi_id: str, cas_rn: str, dry_run: bool = False):
        """
        Update ingredient YAML file with ChEBI ID.

        Adds to ontology_mapping section with appropriate metadata.
        """
        with open(ingredient_file) as f:
            ingredient_data = yaml.safe_load(f)

        if not ingredient_data:
            return False

        # Check if already has this ChEBI ID as identifier
        existing_identifier = ingredient_data.get('identifier', '')
        if existing_identifier == chebi_id:
            return False  # Already has this ChEBI ID

        # Check if already mapped in ontology_mapping
        ontology_mapping = ingredient_data.get('ontology_mapping', {})
        existing_ontology_id = ontology_mapping.get('ontology_id', '')

        if existing_ontology_id == chebi_id:
            return False  # Already mapped

        # If ingredient has no identifier or different identifier, update
        modified = False

        if not existing_identifier or existing_identifier.startswith('UNMAPPED_'):
            # Set ChEBI ID as primary identifier
            ingredient_data['identifier'] = chebi_id
            modified = True

            # Update ontology_mapping
            ingredient_data['ontology_mapping'] = {
                'ontology_id': chebi_id,
                'ontology_label': '',  # Would need ChEBI API to get label
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
            }

            # Update mapping status if it was unmapped
            if ingredient_data.get('mapping_status') == 'UNMAPPED':
                ingredient_data['mapping_status'] = 'MAPPED'

        # Add curation history entry
        if 'curation_history' not in ingredient_data:
            ingredient_data['curation_history'] = []

        ingredient_data['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'cas_rn_ontology_enrichment',
            'action': 'ADDED_ONTOLOGY_MAPPING',
            'changes': f'Added ChEBI ID {chebi_id} via CAS-RN ({cas_rn}) lookup through PubChem',
            'new_status': ingredient_data.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        if not dry_run and modified:
            # Write updated YAML
            with open(ingredient_file, 'w') as f:
                yaml.dump(ingredient_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return modified

    def apply_enrichments(self, dry_run: bool = False):
        """Apply enrichments to MediaIngredientMech ingredient files."""
        print(f"\nApplying enrichments to MediaIngredientMech...")

        for ingredient_name, enrichment_data in sorted(self.enrichments.items()):
            chebi_id = enrichment_data.get('chebi_id')
            cas_rn = enrichment_data.get('cas_rn', '')

            if not chebi_id:
                continue

            # Find ingredient file
            ingredient_file = self.find_ingredient_file(ingredient_name)

            if not ingredient_file:
                self.stats['ingredients_not_in_mim'] += 1
                print(f"  [NOT IN MIM] {ingredient_name}")
                continue

            self.stats['ingredients_found_in_mim'] += 1

            # Update ingredient file
            updated = self.update_ingredient_file(ingredient_file, chebi_id, cas_rn, dry_run)

            if updated:
                self.stats['ingredients_updated'] += 1
                self.stats['files_modified'].append(str(ingredient_file.relative_to(self.mim_root)))

                if dry_run:
                    print(f"  [DRY RUN] {ingredient_name} → {chebi_id} ({ingredient_file.name})")
                else:
                    print(f"  [UPDATE] {ingredient_name} → {chebi_id} ({ingredient_file.name})")
            else:
                self.stats['ingredients_already_mapped'] += 1
                print(f"  [SKIP] {ingredient_name} - already has {chebi_id}")

    def print_summary(self):
        """Print update summary."""
        print("\n" + "=" * 80)
        print("MEDIAINGREDIENTMECH UPDATE SUMMARY")
        print("=" * 80)
        print(f"Enrichments loaded: {self.stats['enrichments_loaded']}")
        print(f"Ingredients found in MIM: {self.stats['ingredients_found_in_mim']}")
        print(f"Ingredients already mapped: {self.stats['ingredients_already_mapped']}")
        print(f"Ingredients updated: {self.stats['ingredients_updated']}")
        print(f"Ingredients not in MIM: {self.stats['ingredients_not_in_mim']}")

        if self.stats['files_modified']:
            print(f"\nModified files ({len(self.stats['files_modified'])}):")
            for filepath in sorted(self.stats['files_modified'])[:20]:
                print(f"  - {filepath}")
            if len(self.stats['files_modified']) > 20:
                print(f"  ... and {len(self.stats['files_modified']) - 20} more")


def main():
    parser = argparse.ArgumentParser(
        description='Update MediaIngredientMech with ChEBI enrichments'
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
        '--dry-run',
        action='store_true',
        help='Dry run mode - show what would be done without modifying files'
    )

    args = parser.parse_args()

    if not args.mim.exists():
        print(f"Error: MediaIngredientMech directory not found: {args.mim}")
        sys.exit(1)

    if not args.enrichment_file.exists():
        print(f"Error: Enrichment file not found: {args.enrichment_file}")
        sys.exit(1)

    if args.dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No files will be modified")
        print("=" * 80)

    updater = MIMEnrichmentUpdater(args.mim, args.enrichment_file)

    # Load enrichments
    updater.load_enrichments()

    # Apply enrichments
    updater.apply_enrichments(dry_run=args.dry_run)

    # Print summary
    updater.print_summary()

    if args.dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE - Run without --dry-run to apply changes")
        print("=" * 80)
    else:
        print("\n✅ MediaIngredientMech updated successfully")


if __name__ == '__main__':
    main()
