#!/usr/bin/env python3
"""
Generate TSV export of FEBA uncovered ingredients with mappability classification.

Creates a standardized TSV file showing all FEBA ingredients without CAS-RN,
their categories, mappability classification, and resolution status.
"""

import yaml
import csv
from pathlib import Path
import argparse
from datetime import datetime


class FEBAUncoveredTSVGenerator:
    """Generates TSV export of uncovered FEBA ingredients."""

    def __init__(self):
        self.rows = []

    def load_data(self, uncovered_report: Path, classification_report: Path):
        """Load uncovered report and classification data."""
        with open(uncovered_report) as f:
            self.uncovered = yaml.safe_load(f)

        if classification_report.exists():
            with open(classification_report) as f:
                self.classifications = yaml.safe_load(f)
        else:
            self.classifications = {
                'summary': {},
                'classifications': {
                    'RESOLVED': [],
                    'RESOLVABLE_HIGH': [],
                    'RESOLVABLE_MEDIUM': [],
                    'RESOLVABLE_LOW': [],
                    'UNMAPPABLE': []
                }
            }

    def build_tsv_rows(self):
        """Build TSV rows from loaded data."""
        # Build lookup for classifications
        classification_lookup = {}

        for status, items in self.classifications['classifications'].items():
            for item in items:
                ingredient = item.get('ingredient')
                if not ingredient:
                    continue

                classification_lookup[ingredient] = {
                    'mappability': status,
                    'reasoning': item.get('reasoning', ''),
                    'cas_rn': item.get('cas_rn', ''),
                    'resolution_strategy': item.get('resolution_strategy', ''),
                    'pubchem_url': item.get('pubchem_url', '')
                }

        # Build rows from uncovered report
        for category, info in self.uncovered.get('categories', {}).items():
            for ingredient in info.get('ingredients', []):
                classification = classification_lookup.get(ingredient, {})

                row = {
                    'ingredient': ingredient,
                    'category': category,
                    'mappability': classification.get('mappability', 'UNKNOWN'),
                    'cas_rn': classification.get('cas_rn', ''),
                    'resolution_strategy': classification.get('resolution_strategy', ''),
                    'reasoning': classification.get('reasoning', ''),
                    'pubchem_url': classification.get('pubchem_url', '')
                }

                self.rows.append(row)

        # Sort by mappability priority, then ingredient name
        mappability_order = {
            'RESOLVED': 0,
            'RESOLVABLE_HIGH': 1,
            'RESOLVABLE_MEDIUM': 2,
            'RESOLVABLE_LOW': 3,
            'UNMAPPABLE': 4,
            'UNKNOWN': 5
        }

        self.rows.sort(key=lambda x: (
            mappability_order.get(x['mappability'], 999),
            x['category'],
            x['ingredient']
        ))

    def save_tsv(self, output_file: Path):
        """Save TSV file."""
        fieldnames = [
            'mappability',
            'category',
            'ingredient',
            'cas_rn',
            'resolution_strategy',
            'reasoning',
            'pubchem_url'
        ]

        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t')
            writer.writeheader()
            writer.writerows(self.rows)

        print(f"✅ Saved {len(self.rows)} ingredients to: {output_file}")

    def print_summary(self):
        """Print summary of TSV contents."""
        from collections import Counter

        mappability_counts = Counter(row['mappability'] for row in self.rows)
        category_counts = Counter(row['category'] for row in self.rows)

        print("\n" + "=" * 80)
        print("FEBA UNCOVERED INGREDIENTS TSV SUMMARY")
        print("=" * 80)
        print(f"Total ingredients: {len(self.rows)}")

        print("\nBy Mappability:")
        for status in ['RESOLVED', 'RESOLVABLE_HIGH', 'RESOLVABLE_MEDIUM', 'RESOLVABLE_LOW', 'UNMAPPABLE', 'UNKNOWN']:
            count = mappability_counts.get(status, 0)
            if count > 0:
                pct = (count / len(self.rows) * 100) if self.rows else 0
                print(f"  {status:20s}: {count:3d} ({pct:5.1f}%)")

        print("\nBy Category:")
        for category, count in category_counts.most_common():
            pct = (count / len(self.rows) * 100) if self.rows else 0
            print(f"  {category:30s}: {count:3d} ({pct:5.1f}%)")


def main():
    parser = argparse.ArgumentParser(
        description='Generate TSV export of FEBA uncovered ingredients'
    )
    parser.add_argument(
        '--uncovered-report',
        type=Path,
        default=Path('workspace/feba_uncovered_report.yaml'),
        help='Uncovered ingredients report'
    )
    parser.add_argument(
        '--classification-report',
        type=Path,
        default=Path('workspace/feba_mappability_classification.yaml'),
        help='Mappability classification report'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('FEBA_UNCOVERED_INGREDIENTS.tsv'),
        help='Output TSV file'
    )

    args = parser.parse_args()

    generator = FEBAUncoveredTSVGenerator()

    print("Loading data...")
    generator.load_data(args.uncovered_report, args.classification_report)

    print("Building TSV rows...")
    generator.build_tsv_rows()

    generator.print_summary()

    generator.save_tsv(args.output)


if __name__ == '__main__':
    main()
