#!/usr/bin/env python3
"""
Extract FEBA ingredients without CAS-RN coverage.

Finds all ingredients in FEBA media that lack CAS Registry Numbers
in both CultureMech media files and MediaIngredientMech database.
"""

import yaml
import re
from pathlib import Path
from typing import Set, Dict
from collections import defaultdict
import argparse


class FEBAUncoveredExtractor:
    """Extracts FEBA ingredients without CAS-RN."""

    def __init__(self, culturemech_root: Path, mim_root: Path):
        self.culturemech_root = culturemech_root
        self.mim_root = mim_root
        self.feba_ingredients = set()
        self.ingredients_with_cas_in_cm = set()
        self.ingredients_with_cas_in_mim = set()
        self.ingredient_details = defaultdict(dict)

    def extract_feba_ingredients(self):
        """Extract all unique ingredients from FEBA media files."""
        print("Extracting ingredients from FEBA media files...")

        normalized_yaml = self.culturemech_root / 'data/normalized_yaml'
        feba_count = 0

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

                feba_count += 1

                # Extract ingredients
                for ingredient in media.get('ingredients', []):
                    preferred_term = ingredient.get('preferred_term', '')
                    if not preferred_term:
                        continue

                    self.feba_ingredients.add(preferred_term)

                    # Check if has CAS in notes
                    ing_notes = ingredient.get('notes', '')
                    if re.search(r'CAS:\s*\d+-\d+-\d+', ing_notes):
                        self.ingredients_with_cas_in_cm.add(preferred_term)

                    # Store details
                    if preferred_term not in self.ingredient_details:
                        self.ingredient_details[preferred_term] = {
                            'has_cas_in_cm': bool(re.search(r'CAS:\s*\d+-\d+-\d+', ing_notes)),
                            'has_ontology_id': bool(ingredient.get('term', {}).get('id')),
                            'media_files': []
                        }

                    self.ingredient_details[preferred_term]['media_files'].append(yaml_file.name)

            except Exception as e:
                print(f"  Error reading {yaml_file.name}: {e}")

        print(f"  Found {len(self.feba_ingredients)} unique ingredients in {feba_count} FEBA media")

    def check_mim_coverage(self):
        """Check which FEBA ingredients have CAS-RN in MediaIngredientMech."""
        print("Checking MediaIngredientMech coverage...")

        ingredients_dir = self.mim_root / 'data/ingredients'

        for status_dir in ['mapped', 'unmapped']:
            status_path = ingredients_dir / status_dir
            if not status_path.exists():
                continue

            for yaml_file in status_path.glob('*.yaml'):
                try:
                    with open(yaml_file) as f:
                        ingredient = yaml.safe_load(f)

                    if not ingredient:
                        continue

                    preferred_term = ingredient.get('preferred_term', '')
                    if preferred_term not in self.feba_ingredients:
                        continue

                    # Check if has CAS-RN
                    chem_props = ingredient.get('chemical_properties', {})
                    if chem_props.get('cas_rn'):
                        self.ingredients_with_cas_in_mim.add(preferred_term)

                        if preferred_term in self.ingredient_details:
                            self.ingredient_details[preferred_term]['has_cas_in_mim'] = True
                            self.ingredient_details[preferred_term]['cas_rn'] = chem_props['cas_rn']
                            self.ingredient_details[preferred_term]['mim_file'] = yaml_file.name

                except Exception as e:
                    print(f"  Error reading {yaml_file.name}: {e}")

        print(f"  Found {len(self.ingredients_with_cas_in_mim)} FEBA ingredients with CAS-RN in MIM")

    def get_uncovered_ingredients(self) -> Set[str]:
        """Get ingredients without CAS-RN in either source."""
        covered = self.ingredients_with_cas_in_cm | self.ingredients_with_cas_in_mim
        uncovered = self.feba_ingredients - covered
        return uncovered

    def categorize_uncovered(self, uncovered: Set[str]) -> Dict[str, list]:
        """Categorize uncovered ingredients by type."""
        categories = {
            'complex_biological': [],
            'gases': [],
            'hydrated_salts_variants': [],
            'vitamins_supplements': [],
            'media_components': [],
            'other': []
        }

        for ingredient in uncovered:
            ing_lower = ingredient.lower()

            # Complex biological materials
            bio_terms = ['extract', 'peptone', 'digest', 'serum', 'infusion', 'casein', 'heart', 'brain', 'liver', 'meat']
            if any(term in ing_lower for term in bio_terms):
                categories['complex_biological'].append(ingredient)

            # Gases
            elif ingredient.startswith('#') or ingredient in ['argon']:
                categories['gases'].append(ingredient)

            # Hydrated salts with variant notation
            elif (re.search(r'\s+\d+H2O$', ingredient) or  # Space notation
                  re.search(r'\*\d*H2O', ingredient) or    # Asterisk notation
                  'hydrate' in ing_lower):                 # Spelled out
                categories['hydrated_salts_variants'].append(ingredient)

            # Vitamins and supplements
            elif any(term in ing_lower for term in ['vitamin', 'thiamine', 'pantothenic', 'pyridoxine', 'biotin', 'niacin', 'riboflavin']):
                categories['vitamins_supplements'].append(ingredient)

            # Media components
            elif any(term in ing_lower for term in ['medium', 'media', 'agar', 'broth', 'base', 'supplement']):
                categories['media_components'].append(ingredient)

            # Other
            else:
                categories['other'].append(ingredient)

        return categories

    def save_uncovered_list(self, output_file: Path):
        """Save uncovered ingredients to text file (one per line)."""
        uncovered = sorted(self.get_uncovered_ingredients())

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            for ingredient in uncovered:
                f.write(f"{ingredient}\n")

        print(f"\n✅ Saved {len(uncovered)} uncovered ingredients to: {output_file}")

    def save_categorized_report(self, output_file: Path):
        """Save detailed categorization report."""
        uncovered = self.get_uncovered_ingredients()
        categories = self.categorize_uncovered(uncovered)

        report = {
            'metadata': {
                'total_feba_ingredients': len(self.feba_ingredients),
                'with_cas_in_culturemech': len(self.ingredients_with_cas_in_cm),
                'with_cas_in_mim': len(self.ingredients_with_cas_in_mim),
                'with_cas_either_source': len(self.ingredients_with_cas_in_cm | self.ingredients_with_cas_in_mim),
                'uncovered_total': len(uncovered)
            },
            'categories': {}
        }

        for category, ingredients in categories.items():
            report['categories'][category] = {
                'count': len(ingredients),
                'ingredients': sorted(ingredients)
            }

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            yaml.dump(report, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        print(f"✅ Saved categorized report to: {output_file}")

    def print_summary(self):
        """Print summary statistics."""
        uncovered = self.get_uncovered_ingredients()
        categories = self.categorize_uncovered(uncovered)
        covered = self.ingredients_with_cas_in_cm | self.ingredients_with_cas_in_mim

        print("\n" + "=" * 80)
        print("FEBA INGREDIENTS CAS-RN COVERAGE SUMMARY")
        print("=" * 80)
        print(f"Total FEBA ingredients: {len(self.feba_ingredients)}")
        print(f"  With CAS-RN in CultureMech: {len(self.ingredients_with_cas_in_cm)} ({len(self.ingredients_with_cas_in_cm)/len(self.feba_ingredients)*100:.1f}%)")
        print(f"  With CAS-RN in MediaIngredientMech: {len(self.ingredients_with_cas_in_mim)} ({len(self.ingredients_with_cas_in_mim)/len(self.feba_ingredients)*100:.1f}%)")
        print(f"  With CAS-RN (either source): {len(covered)} ({len(covered)/len(self.feba_ingredients)*100:.1f}%)")
        print(f"  WITHOUT CAS-RN (uncovered): {len(uncovered)} ({len(uncovered)/len(self.feba_ingredients)*100:.1f}%)")

        print(f"\nUncovered ingredients by category:")
        for category, ingredients in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
            if ingredients:
                print(f"  {category:30s}: {len(ingredients):3d}")


def main():
    parser = argparse.ArgumentParser(
        description='Extract FEBA ingredients without CAS-RN coverage'
    )
    parser.add_argument(
        '--culturemech',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--mim',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--output-list',
        type=Path,
        default=Path('workspace/feba_uncovered_ingredients.txt'),
        help='Output text file (one ingredient per line)'
    )
    parser.add_argument(
        '--output-report',
        type=Path,
        default=Path('workspace/feba_uncovered_report.yaml'),
        help='Output YAML report with categorization'
    )

    args = parser.parse_args()

    extractor = FEBAUncoveredExtractor(args.culturemech, args.mim)

    # Extract FEBA ingredients
    extractor.extract_feba_ingredients()

    # Check MediaIngredientMech coverage
    extractor.check_mim_coverage()

    # Print summary
    extractor.print_summary()

    # Save outputs
    extractor.save_uncovered_list(args.output_list)
    extractor.save_categorized_report(args.output_report)


if __name__ == '__main__':
    main()
