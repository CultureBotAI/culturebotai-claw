#!/usr/bin/env python3
"""
Apply ChEBI enrichment results to CultureMech media files.

Updates FEBA media YAML files with newly discovered ontology term IDs.
"""

import yaml
from pathlib import Path
from collections import defaultdict
import argparse
from typing import Dict, List, Set
import sys


class OntologyEnrichmentApplicator:
    """Applies ChEBI enrichments to CultureMech media files."""

    def __init__(self, culturemech_root: Path, enrichment_file: Path):
        self.culturemech_root = culturemech_root
        self.enrichment_file = enrichment_file
        self.enrichments = {}
        self.stats = {
            'media_scanned': 0,
            'media_updated': 0,
            'ingredients_updated': 0,
            'files_modified': []
        }

    def load_enrichments(self):
        """Load ChEBI enrichment results."""
        print(f"Loading enrichments from {self.enrichment_file}...")

        with open(self.enrichment_file) as f:
            data = yaml.safe_load(f)

        self.enrichments = data.get('enrichments', {})
        print(f"Loaded {len(self.enrichments)} enrichments")

        # Count successful enrichments
        successful = sum(1 for e in self.enrichments.values() if e.get('chebi_id'))
        print(f"  {successful} with ChEBI IDs")
        print(f"  {len(self.enrichments) - successful} without ChEBI IDs")

    def get_chebi_label(self, chebi_id: str) -> str:
        """
        Get ChEBI label for a ChEBI ID.

        For now, return empty string since we'd need to query ChEBI API.
        Could be enhanced later.
        """
        return ""

    def apply_enrichments(self, dry_run: bool = False):
        """Apply enrichments to FEBA media files."""
        print(f"\nScanning FEBA media files...")

        normalized_yaml = self.culturemech_root / 'data/normalized_yaml'

        for yaml_file in sorted(normalized_yaml.rglob('*.yaml')):
            try:
                with open(yaml_file) as f:
                    media = yaml.safe_load(f)

                if not media:
                    continue

                # Check if FEBA media
                notes = media.get('notes', '')
                if 'FEBA media definitions' not in notes:
                    continue

                self.stats['media_scanned'] += 1

                # Check ingredients for enrichments
                modified = False
                ingredients = media.get('ingredients', [])

                for ingredient in ingredients:
                    preferred_term = ingredient.get('preferred_term', '')

                    # Check if we have enrichment for this ingredient
                    if preferred_term in self.enrichments:
                        enrichment = self.enrichments[preferred_term]
                        chebi_id = enrichment.get('chebi_id')

                        if chebi_id:
                            # Check if ingredient already has ontology ID
                            term = ingredient.get('term', {})
                            existing_id = term.get('id', '')

                            if not existing_id:
                                # Add ChEBI ID
                                ingredient['term'] = {
                                    'id': chebi_id,
                                    'label': self.get_chebi_label(chebi_id)
                                }

                                # Update notes to indicate enrichment source
                                existing_notes = ingredient.get('notes', '')
                                if existing_notes:
                                    ingredient['notes'] = existing_notes + f"; Ontology enriched via CAS-RN lookup"
                                else:
                                    ingredient['notes'] = f"Ontology enriched via CAS-RN lookup"

                                modified = True
                                self.stats['ingredients_updated'] += 1

                                print(f"  [UPDATE] {yaml_file.name}: {preferred_term} → {chebi_id}")

                if modified:
                    self.stats['media_updated'] += 1
                    self.stats['files_modified'].append(str(yaml_file.relative_to(self.culturemech_root)))

                    if not dry_run:
                        # Write updated YAML
                        with open(yaml_file, 'w') as f:
                            yaml.dump(media, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                        print(f"    ✓ Saved {yaml_file.name}")
                    else:
                        print(f"    [DRY RUN] Would save {yaml_file.name}")

            except Exception as e:
                print(f"  Error processing {yaml_file.name}: {e}")

    def check_unmapped_flags(self, dry_run: bool = False):
        """
        Check if any media can have has_unmapped_ingredients flag removed.

        This is a separate pass to be conservative - only remove flag
        if all ingredients now have ontology IDs.
        """
        print(f"\nChecking data quality flags...")

        normalized_yaml = self.culturemech_root / 'data/normalized_yaml'
        flags_removed = 0

        for yaml_file in sorted(normalized_yaml.rglob('*.yaml')):
            try:
                with open(yaml_file) as f:
                    media = yaml.safe_load(f)

                if not media:
                    continue

                # Check if FEBA media with unmapped flag
                notes = media.get('notes', '')
                if 'FEBA media definitions' not in notes:
                    continue

                flags = media.get('data_quality_flags', [])
                if 'has_unmapped_ingredients' not in flags:
                    continue

                # Check if all ingredients now have ontology IDs
                all_mapped = True
                ingredients = media.get('ingredients', [])

                for ingredient in ingredients:
                    term = ingredient.get('term', {})
                    term_id = term.get('id', '')
                    if not term_id:
                        all_mapped = False
                        break

                if all_mapped:
                    # Remove flag
                    flags.remove('has_unmapped_ingredients')
                    media['data_quality_flags'] = flags

                    flags_removed += 1
                    print(f"  [REMOVE FLAG] {yaml_file.name}: All ingredients now mapped")

                    if not dry_run:
                        with open(yaml_file, 'w') as f:
                            yaml.dump(media, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                        print(f"    ✓ Saved {yaml_file.name}")
                    else:
                        print(f"    [DRY RUN] Would save {yaml_file.name}")

            except Exception as e:
                print(f"  Error processing {yaml_file.name}: {e}")

        print(f"\n  Total flags removed: {flags_removed}")

    def print_summary(self):
        """Print application summary."""
        print("\n" + "=" * 80)
        print("ENRICHMENT APPLICATION SUMMARY")
        print("=" * 80)
        print(f"FEBA media scanned: {self.stats['media_scanned']}")
        print(f"Media updated: {self.stats['media_updated']}")
        print(f"Ingredients updated: {self.stats['ingredients_updated']}")

        if self.stats['files_modified']:
            print(f"\nModified files ({len(self.stats['files_modified'])}):")
            for filepath in sorted(self.stats['files_modified']):
                print(f"  - {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description='Apply ChEBI enrichments to CultureMech media files'
    )
    parser.add_argument(
        '--culturemech',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
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
    parser.add_argument(
        '--check-flags',
        action='store_true',
        help='Also check and remove has_unmapped_ingredients flags where appropriate'
    )

    args = parser.parse_args()

    if not args.culturemech.exists():
        print(f"Error: CultureMech directory not found: {args.culturemech}")
        sys.exit(1)

    if not args.enrichment_file.exists():
        print(f"Error: Enrichment file not found: {args.enrichment_file}")
        sys.exit(1)

    if args.dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No files will be modified")
        print("=" * 80)

    applicator = OntologyEnrichmentApplicator(args.culturemech, args.enrichment_file)

    # Load enrichments
    applicator.load_enrichments()

    # Apply enrichments
    applicator.apply_enrichments(dry_run=args.dry_run)

    # Check flags if requested
    if args.check_flags:
        applicator.check_unmapped_flags(dry_run=args.dry_run)

    # Print summary
    applicator.print_summary()

    if args.dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE - Run without --dry-run to apply changes")
        print("=" * 80)
    else:
        print("\n✅ Enrichments applied successfully")


if __name__ == '__main__':
    main()
