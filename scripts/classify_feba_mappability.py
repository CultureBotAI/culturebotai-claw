#!/usr/bin/env python3
"""
Classify FEBA unmapped ingredients as truly unmappable vs potentially resolvable.

Uses results from notation variant mapping to categorize ingredients:
- RESOLVED: Found CAS-RN via notation variants
- RESOLVABLE: Likely resolvable with additional effort (manual lookup, different APIs)
- UNMAPPABLE: No CAS-RN exists (mixtures, complex biological materials, etc.)
"""

import yaml
from pathlib import Path
from typing import Dict, List
import argparse


class FEBAMappabilityClassifier:
    """Classifies FEBA ingredients by mappability."""

    def __init__(self):
        self.classifications = {
            'RESOLVED': [],
            'RESOLVABLE_HIGH': [],
            'RESOLVABLE_MEDIUM': [],
            'RESOLVABLE_LOW': [],
            'UNMAPPABLE': []
        }

    def classify_from_results(self, uncovered_report: Dict, mapping_results: Dict) -> Dict:
        """
        Classify ingredients based on notation mapping results and categorization.

        Args:
            uncovered_report: Output from extract_feba_uncovered_ingredients.py
            mapping_results: Output from map_feba_notation_variants.py

        Returns:
            Dict with classifications and reasoning
        """
        # Build CAS-RN lookup from mapping results
        cas_lookup = {}
        for result in mapping_results.get('results', []):
            original = result.get('original_name')
            cas_rn = result.get('cas_rn')
            if cas_rn:
                cas_lookup[original] = {
                    'cas_rn': cas_rn,
                    'strategy': result.get('successful_strategy'),
                    'pubchem_url': result.get('pubchem_url')
                }

        # Get uncovered categories
        categories = uncovered_report.get('categories', {})

        # Classify each ingredient
        for category, info in categories.items():
            ingredients = info.get('ingredients', [])

            for ingredient in ingredients:
                # Check if resolved via notation mapping
                if ingredient in cas_lookup:
                    self.classifications['RESOLVED'].append({
                        'ingredient': ingredient,
                        'original_category': category,
                        'cas_rn': cas_lookup[ingredient]['cas_rn'],
                        'resolution_strategy': cas_lookup[ingredient]['strategy'],
                        'pubchem_url': cas_lookup[ingredient]['pubchem_url']
                    })
                    continue

                # Classify by category and characteristics
                classification = self._classify_ingredient(ingredient, category)
                self.classifications[classification].append({
                    'ingredient': ingredient,
                    'category': category,
                    'reasoning': self._get_reasoning(ingredient, category)
                })

        return self.classifications

    def _classify_ingredient(self, ingredient: str, category: str) -> str:
        """
        Classify individual ingredient by mappability.

        Returns: RESOLVABLE_HIGH, RESOLVABLE_MEDIUM, RESOLVABLE_LOW, or UNMAPPABLE
        """
        ing_lower = ingredient.lower()

        # UNMAPPABLE: Complex biological materials
        if category == 'complex_biological':
            return 'UNMAPPABLE'

        # UNMAPPABLE: Media components (mixtures)
        if category == 'media_components':
            return 'UNMAPPABLE'

        # RESOLVABLE_HIGH: Hydrated salts (notation variants)
        if category == 'hydrated_salts_variants':
            return 'RESOLVABLE_HIGH'

        # RESOLVABLE_HIGH: Gases (standard compounds)
        if category == 'gases':
            return 'RESOLVABLE_HIGH'

        # RESOLVABLE_MEDIUM: Vitamins/supplements (may need specific forms)
        if category == 'vitamins_supplements':
            # If already specific form (HCl, hydrochloride), higher priority
            if 'hcl' in ing_lower or 'hydrochloride' in ing_lower:
                return 'RESOLVABLE_HIGH'
            return 'RESOLVABLE_MEDIUM'

        # OTHER category - evaluate individually
        if category == 'other':
            # Check for salt forms
            if any(term in ing_lower for term in ['sodium', 'potassium', 'calcium', 'magnesium', 'chloride', 'sulfate', 'phosphate']):
                return 'RESOLVABLE_HIGH'

            # Check for acids
            if 'acid' in ing_lower:
                return 'RESOLVABLE_MEDIUM'

            # Complex or ambiguous names
            if any(term in ing_lower for term in ['base', 'filtered', 'sampling', 'spring']):
                return 'UNMAPPABLE'

            # Default for other
            return 'RESOLVABLE_LOW'

        return 'RESOLVABLE_LOW'

    def _get_reasoning(self, ingredient: str, category: str) -> str:
        """Get explanation for classification."""
        ing_lower = ingredient.lower()

        if category == 'complex_biological':
            return "Complex biological material - no single CAS-RN exists"

        if category == 'media_components':
            return "Media mixture or formulation - no single CAS-RN exists"

        if category == 'hydrated_salts_variants':
            if ' ' in ingredient and 'H2O' in ingredient:
                return "Space-separated hydrate notation - convertible to standard form"
            elif '*' in ingredient:
                return "Asterisk hydrate notation - convertible to standard form"
            elif 'hydrate' in ing_lower:
                return "Spelled-out hydrate - convertible to formula notation"
            return "Hydrate notation variant - likely resolvable"

        if category == 'gases':
            if ingredient.startswith('#'):
                return "Non-standard gas notation - resolvable to standard name"
            return "Standard gas - should have CAS-RN"

        if category == 'vitamins_supplements':
            if 'hcl' in ing_lower or 'hydrochloride' in ing_lower:
                return "Specific vitamin salt form - should be resolvable"
            return "Vitamin - may need specific salt form specified"

        if category == 'other':
            if 'acid' in ing_lower:
                return "Chemical acid - likely resolvable with manual lookup"
            if 'base' in ing_lower or 'filtered' in ing_lower:
                return "Ambiguous or undefined material"
            return "Requires manual investigation"

        return "Classification reason unclear"

    def save_report(self, output_file: Path):
        """Save classification report to YAML."""
        report = {
            'summary': {
                'RESOLVED': len(self.classifications['RESOLVED']),
                'RESOLVABLE_HIGH': len(self.classifications['RESOLVABLE_HIGH']),
                'RESOLVABLE_MEDIUM': len(self.classifications['RESOLVABLE_MEDIUM']),
                'RESOLVABLE_LOW': len(self.classifications['RESOLVABLE_LOW']),
                'UNMAPPABLE': len(self.classifications['UNMAPPABLE'])
            },
            'classifications': self.classifications
        }

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            yaml.dump(report, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        print(f"✅ Saved classification report to: {output_file}")

    def print_summary(self):
        """Print classification summary."""
        print("\n" + "=" * 80)
        print("FEBA INGREDIENTS MAPPABILITY CLASSIFICATION")
        print("=" * 80)

        total = sum(len(v) for v in self.classifications.values())

        for classification in ['RESOLVED', 'RESOLVABLE_HIGH', 'RESOLVABLE_MEDIUM', 'RESOLVABLE_LOW', 'UNMAPPABLE']:
            count = len(self.classifications[classification])
            pct = (count / total * 100) if total > 0 else 0
            print(f"{classification:20s}: {count:3d} ({pct:5.1f}%)")

        print(f"\n{'Total':20s}: {total:3d}")

        # Print examples
        print("\n" + "=" * 80)
        print("EXAMPLES")
        print("=" * 80)

        for classification in ['RESOLVED', 'RESOLVABLE_HIGH', 'RESOLVABLE_MEDIUM', 'RESOLVABLE_LOW', 'UNMAPPABLE']:
            items = self.classifications[classification]
            if items:
                print(f"\n{classification}:")
                for item in items[:3]:
                    if classification == 'RESOLVED':
                        print(f"  • {item['ingredient']:50s} → CAS: {item['cas_rn']}")
                    else:
                        print(f"  • {item['ingredient']:50s} ({item['reasoning']})")
                if len(items) > 3:
                    print(f"  ... and {len(items) - 3} more")


def main():
    parser = argparse.ArgumentParser(
        description='Classify FEBA ingredients by mappability'
    )
    parser.add_argument(
        '--uncovered-report',
        type=Path,
        default=Path('workspace/feba_uncovered_report.yaml'),
        help='Uncovered ingredients report from extract_feba_uncovered_ingredients.py'
    )
    parser.add_argument(
        '--mapping-results',
        type=Path,
        default=Path('workspace/feba_notation_mapping_results.yaml'),
        help='Mapping results from map_feba_notation_variants.py'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/feba_mappability_classification.yaml'),
        help='Output classification report'
    )

    args = parser.parse_args()

    # Load inputs
    print("Loading input files...")
    with open(args.uncovered_report) as f:
        uncovered_report = yaml.safe_load(f)

    # Check if mapping results exist
    mapping_results = {'results': []}
    if args.mapping_results.exists():
        with open(args.mapping_results) as f:
            mapping_results = yaml.safe_load(f)
    else:
        print(f"Warning: Mapping results not found at {args.mapping_results}")
        print("         Will classify without mapping results")

    # Classify
    classifier = FEBAMappabilityClassifier()
    classifier.classify_from_results(uncovered_report, mapping_results)

    # Print summary
    classifier.print_summary()

    # Save report
    classifier.save_report(args.output)


if __name__ == '__main__':
    main()
