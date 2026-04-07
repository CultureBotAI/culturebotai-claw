#!/usr/bin/env python3
"""
Analyze ontology term coverage for FEBA ingredients.

Checks which FEBA ingredients have ontology term IDs (CHEBI, FOODON, ENVO, etc.)
and provides detailed statistics on coverage.
"""

import yaml
from pathlib import Path
from collections import defaultdict, Counter
import argparse


class FEBAOntologyAnalyzer:
    """Analyzes ontology term coverage for FEBA ingredients."""

    def __init__(self, culturemech_root: Path):
        self.culturemech_root = culturemech_root
        self.feba_ingredients = {}  # ingredient -> details
        self.stats = {
            'total_feba_media': 0,
            'total_unique_ingredients': 0,
            'with_ontology_id': 0,
            'without_ontology_id': 0,
            'by_ontology': Counter()
        }

    def analyze_feba_media(self):
        """Analyze all FEBA media files."""
        print("Analyzing FEBA media for ontology coverage...\n")

        normalized_yaml = self.culturemech_root / 'data/normalized_yaml'

        for yaml_file in normalized_yaml.rglob('*.yaml'):
            try:
                with open(yaml_file) as f:
                    media = yaml.safe_load(f)

                if not media:
                    continue

                # Check if FEBA media
                notes = media.get('notes', '')
                if 'FEBA media definitions' not in notes:
                    continue

                self.stats['total_feba_media'] += 1

                # Analyze ingredients
                for ingredient in media.get('ingredients', []):
                    preferred_term = ingredient.get('preferred_term', '')
                    if not preferred_term:
                        continue

                    # Get ontology term info
                    term = ingredient.get('term', {})
                    term_id = term.get('id', '')
                    term_label = term.get('label', '')

                    # Store or update ingredient details
                    if preferred_term not in self.feba_ingredients:
                        self.feba_ingredients[preferred_term] = {
                            'has_ontology_id': bool(term_id),
                            'ontology_id': term_id,
                            'ontology_label': term_label,
                            'ontology_source': self._extract_ontology_source(term_id),
                            'media_count': 0,
                            'example_media': []
                        }

                    self.feba_ingredients[preferred_term]['media_count'] += 1
                    if len(self.feba_ingredients[preferred_term]['example_media']) < 3:
                        self.feba_ingredients[preferred_term]['example_media'].append(yaml_file.name)

            except Exception as e:
                print(f"  Error reading {yaml_file.name}: {e}")

        # Calculate statistics
        self.stats['total_unique_ingredients'] = len(self.feba_ingredients)

        for ingredient, details in self.feba_ingredients.items():
            if details['has_ontology_id']:
                self.stats['with_ontology_id'] += 1
                source = details['ontology_source']
                if source:
                    self.stats['by_ontology'][source] += 1
            else:
                self.stats['without_ontology_id'] += 1

    def _extract_ontology_source(self, term_id: str) -> str:
        """Extract ontology source from term ID."""
        if not term_id:
            return ''

        # Common patterns
        if term_id.startswith('CHEBI:'):
            return 'CHEBI'
        elif term_id.startswith('FOODON:'):
            return 'FOODON'
        elif term_id.startswith('ENVO:'):
            return 'ENVO'
        elif term_id.startswith('NCIT:'):
            return 'NCIT'
        elif term_id.startswith('GO:'):
            return 'GO'
        else:
            # Extract prefix
            if ':' in term_id:
                return term_id.split(':')[0]
            return 'UNKNOWN'

    def save_report(self, output_file: Path):
        """Save detailed report to YAML."""
        # Separate ingredients by ontology status
        with_ontology = {k: v for k, v in self.feba_ingredients.items() if v['has_ontology_id']}
        without_ontology = {k: v for k, v in self.feba_ingredients.items() if not v['has_ontology_id']}

        report = {
            'summary': {
                'total_feba_media': self.stats['total_feba_media'],
                'total_unique_ingredients': self.stats['total_unique_ingredients'],
                'with_ontology_id': self.stats['with_ontology_id'],
                'without_ontology_id': self.stats['without_ontology_id'],
                'coverage_percentage': f"{(self.stats['with_ontology_id'] / self.stats['total_unique_ingredients'] * 100):.1f}%",
                'by_ontology_source': dict(self.stats['by_ontology'])
            },
            'ingredients_with_ontology': dict(sorted(with_ontology.items())),
            'ingredients_without_ontology': dict(sorted(without_ontology.items()))
        }

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            yaml.dump(report, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        print(f"\n✅ Saved detailed report to: {output_file}")

    def save_unmapped_list(self, output_file: Path):
        """Save list of ingredients without ontology IDs."""
        unmapped = [k for k, v in self.feba_ingredients.items() if not v['has_ontology_id']]

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            for ingredient in sorted(unmapped):
                f.write(f"{ingredient}\n")

        print(f"✅ Saved {len(unmapped)} unmapped ingredients to: {output_file}")

    def print_summary(self):
        """Print summary statistics."""
        print("\n" + "=" * 80)
        print("FEBA INGREDIENTS ONTOLOGY COVERAGE SUMMARY")
        print("=" * 80)
        print(f"Total FEBA media files: {self.stats['total_feba_media']}")
        print(f"Total unique ingredients: {self.stats['total_unique_ingredients']}")
        print(f"\nOntology Coverage:")
        print(f"  With ontology ID: {self.stats['with_ontology_id']} ({self.stats['with_ontology_id']/self.stats['total_unique_ingredients']*100:.1f}%)")
        print(f"  Without ontology ID: {self.stats['without_ontology_id']} ({self.stats['without_ontology_id']/self.stats['total_unique_ingredients']*100:.1f}%)")

        if self.stats['by_ontology']:
            print(f"\nBy Ontology Source:")
            for source, count in self.stats['by_ontology'].most_common():
                pct = (count / self.stats['with_ontology_id'] * 100) if self.stats['with_ontology_id'] > 0 else 0
                print(f"  {source:15s}: {count:3d} ({pct:5.1f}% of mapped)")

        # Show examples
        unmapped = [k for k, v in self.feba_ingredients.items() if not v['has_ontology_id']]
        if unmapped:
            print(f"\nExamples WITHOUT ontology ID (showing first 10):")
            for ingredient in sorted(unmapped)[:10]:
                media_count = self.feba_ingredients[ingredient]['media_count']
                print(f"  • {ingredient:50s} (used in {media_count} media)")

        mapped = [k for k, v in self.feba_ingredients.items() if v['has_ontology_id']]
        if mapped:
            print(f"\nExamples WITH ontology ID (showing first 10):")
            for ingredient in sorted(mapped)[:10]:
                details = self.feba_ingredients[ingredient]
                print(f"  • {ingredient:40s} → {details['ontology_id']:20s} ({details['ontology_source']})")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze ontology term coverage for FEBA ingredients'
    )
    parser.add_argument(
        '--culturemech',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--output-report',
        type=Path,
        default=Path('workspace/feba_ontology_coverage_report.yaml'),
        help='Output YAML report'
    )
    parser.add_argument(
        '--output-unmapped',
        type=Path,
        default=Path('workspace/feba_ontology_unmapped_ingredients.txt'),
        help='Output text file with unmapped ingredients'
    )

    args = parser.parse_args()

    analyzer = FEBAOntologyAnalyzer(args.culturemech)

    # Analyze FEBA media
    analyzer.analyze_feba_media()

    # Print summary
    analyzer.print_summary()

    # Save outputs
    analyzer.save_report(args.output_report)
    analyzer.save_unmapped_list(args.output_unmapped)


if __name__ == '__main__':
    main()
