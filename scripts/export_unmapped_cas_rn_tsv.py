#!/usr/bin/env python3
"""
Export unmapped CAS-RN ingredients to standardized TSV for manual curation.

Generates a TSV file with all 367 ingredients lacking CAS-RN, categorized
by unmappability reason for prioritization and manual lookup.
"""

import yaml
from pathlib import Path
from typing import Dict, List
import argparse
import re
import csv


class UnmappedCASExporter:
    """Exports unmapped CAS-RN ingredients to TSV format."""

    def __init__(self, mim_root: Path):
        self.mim_root = mim_root
        self.unmapped = []

    def categorize_ingredient(self, ingredient: dict, filename: str) -> str:
        """Categorize why an ingredient doesn't have CAS-RN."""
        preferred_term = ingredient.get('preferred_term', '')

        # Category 1: Stock Solutions/Mixtures
        solution_patterns = [
            r'solution', r'stock', r'mixture', r'medium', r'media',
            r'buffer', r'supplement', r'mix'
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in solution_patterns):
            return 'Stock Solutions/Mixtures'

        # Category 2: Natural Products
        natural_patterns = [
            r'seawater', r'soil', r'peat', r'extract', r'organic',
            r'natural', r'plant', r'animal', r'environmental'
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in natural_patterns):
            return 'Natural Products'

        # Category 3: Incomplete Chemical Formulas
        if self._is_incomplete_formula(preferred_term):
            return 'Incomplete Formulas'

        # Category 4: Placeholders/Errors
        placeholder_patterns = [
            r'see source', r'original amount', r'chebi:1$', r'unknown',
            r'placeholder', r'tbd', r'n/a'
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in placeholder_patterns):
            return 'Placeholders/Errors'

        # Category 5: Complex Notation (special characters)
        if self._has_complex_notation(preferred_term):
            return 'Complex Notation'

        # Category 6: Proprietary/Commercial Products
        commercial_patterns = [
            r'bacto', r'difco', r'sigma', r'fisher', r'bd-', r'brand',
            r'catalog', r'\d{4,}'
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in commercial_patterns):
            return 'Commercial Products'

        # Category 7: Abbreviations
        if self._looks_like_abbreviation(preferred_term):
            return 'Abbreviations'

        # Category 8: "x" notation hydrated salts
        if re.search(r'\s+x\s+\d*\s*H2O', preferred_term, re.IGNORECASE):
            return 'Hydrated Salts (x notation)'

        # Category 9: Other/Unknown
        return 'Other/Uncategorized'

    def _is_incomplete_formula(self, name: str) -> bool:
        """Check if chemical formula appears incomplete."""
        incomplete_patterns = [
            r'^[A-Z][a-z]?[A-Z][a-z]?$',
            r'^[A-Z][a-z]?\d+[A-Z][a-z]?$',
        ]
        return any(re.match(pattern, name) for pattern in incomplete_patterns)

    def _has_complex_notation(self, name: str) -> bool:
        """Check if name has special characters."""
        special_chars = ['·', '•', '‧', '⋅', '∙']
        return any(char in name for char in special_chars)

    def _looks_like_abbreviation(self, name: str) -> bool:
        """Check if name appears to be an abbreviation."""
        if len(name) <= 15 and name.replace('-', '').replace('_', '').isupper():
            return True
        if re.match(r'^[A-Z]\d*-[A-Z]', name):
            return True
        return False

    def get_mappability_priority(self, category: str) -> str:
        """Assign priority for manual curation."""
        priority_map = {
            'Hydrated Salts (x notation)': 'HIGH',
            'Other/Uncategorized': 'MEDIUM',
            'Abbreviations': 'MEDIUM',
            'Complex Notation': 'MEDIUM',
            'Commercial Products': 'LOW',
            'Incomplete Formulas': 'LOW',
            'Stock Solutions/Mixtures': 'UNMAPPABLE',
            'Natural Products': 'UNMAPPABLE',
            'Placeholders/Errors': 'UNMAPPABLE'
        }
        return priority_map.get(category, 'MEDIUM')

    def collect_unmapped_ingredients(self):
        """Collect all ingredients without CAS-RN."""
        print("Collecting ingredients without CAS-RN...\n")

        ingredients_dir = self.mim_root / 'data/ingredients'

        for status_dir in ['mapped', 'unmapped']:
            status_path = ingredients_dir / status_dir
            if not status_path.exists():
                continue

            for yaml_file in sorted(status_path.glob('*.yaml')):
                try:
                    with open(yaml_file) as f:
                        ingredient = yaml.safe_load(f)

                    if not ingredient:
                        continue

                    # Check if has CAS-RN
                    chem_props = ingredient.get('chemical_properties', {})
                    if chem_props.get('cas_rn'):
                        continue  # Skip - has CAS-RN

                    # Collect unmapped ingredient data
                    preferred_term = ingredient.get('preferred_term', '')
                    ontology_mapping = ingredient.get('ontology_mapping', {})

                    # Get synonyms
                    synonyms = ingredient.get('synonyms', [])
                    synonym_list = [s.get('synonym_text', '') for s in synonyms if isinstance(s, dict)]

                    # Categorize
                    category = self.categorize_ingredient(ingredient, yaml_file.name)
                    priority = self.get_mappability_priority(category)

                    self.unmapped.append({
                        'filename': yaml_file.name,
                        'preferred_term': preferred_term,
                        'mapping_status': ingredient.get('mapping_status', 'UNKNOWN'),
                        'ontology_id': ontology_mapping.get('ontology_id', ''),
                        'ontology_label': ontology_mapping.get('ontology_label', ''),
                        'ontology_source': ontology_mapping.get('ontology_source', ''),
                        'synonym_count': len(synonym_list),
                        'synonyms': '|'.join(synonym_list[:3]),  # First 3 synonyms
                        'category': category,
                        'priority': priority,
                        'has_chebi_id': 'CHEBI:' in ontology_mapping.get('ontology_id', ''),
                        'file_path': str(yaml_file.relative_to(self.mim_root))
                    })

                except Exception as e:
                    print(f"Error processing {yaml_file.name}: {e}")

        print(f"Collected {len(self.unmapped)} unmapped ingredients\n")

    def export_tsv(self, output_file: Path):
        """Export unmapped ingredients to TSV."""
        # Sort by priority then category
        priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'UNMAPPABLE': 3}
        self.unmapped.sort(key=lambda x: (priority_order.get(x['priority'], 999), x['category'], x['preferred_term']))

        # Write TSV
        fieldnames = [
            'priority',
            'category',
            'preferred_term',
            'ontology_id',
            'ontology_label',
            'ontology_source',
            'mapping_status',
            'has_chebi_id',
            'synonym_count',
            'synonyms',
            'filename',
            'file_path'
        ]

        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t')
            writer.writeheader()
            writer.writerows(self.unmapped)

        print(f"✅ Exported {len(self.unmapped)} unmapped ingredients to: {output_file}")

    def print_summary(self):
        """Print summary statistics."""
        print("\n" + "=" * 80)
        print("UNMAPPED INGREDIENTS SUMMARY")
        print("=" * 80)

        # By category
        from collections import Counter
        categories = Counter(item['category'] for item in self.unmapped)
        priorities = Counter(item['priority'] for item in self.unmapped)

        print(f"\nTotal unmapped: {len(self.unmapped)}")

        print("\nBy Category:")
        for category, count in categories.most_common():
            pct = (count / len(self.unmapped)) * 100
            print(f"  {category:40s}: {count:3d} ({pct:5.1f}%)")

        print("\nBy Priority:")
        for priority in ['HIGH', 'MEDIUM', 'LOW', 'UNMAPPABLE']:
            count = priorities.get(priority, 0)
            pct = (count / len(self.unmapped)) * 100 if len(self.unmapped) > 0 else 0
            print(f"  {priority:15s}: {count:3d} ({pct:5.1f}%)")

        # ChEBI ID coverage
        has_chebi = sum(1 for item in self.unmapped if item['has_chebi_id'])
        print(f"\nWith ChEBI IDs: {has_chebi}/{len(self.unmapped)} ({has_chebi/len(self.unmapped)*100:.1f}%)")


def main():
    parser = argparse.ArgumentParser(
        description='Export unmapped CAS-RN ingredients to TSV for manual curation'
    )
    parser.add_argument(
        '--mim',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/unmapped_cas_rn_ingredients.tsv'),
        help='Output TSV file'
    )

    args = parser.parse_args()

    exporter = UnmappedCASExporter(args.mim)

    # Collect unmapped ingredients
    exporter.collect_unmapped_ingredients()

    # Export to TSV
    exporter.export_tsv(args.output)

    # Print summary
    exporter.print_summary()


if __name__ == '__main__':
    main()
