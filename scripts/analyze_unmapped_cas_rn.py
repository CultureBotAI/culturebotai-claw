#!/usr/bin/env python3
"""
Analyze ingredients without CAS-RN and categorize reasons for unmappability.

Generates a comprehensive report of unmappable CAS-RN categories with examples.
"""

import yaml
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
import argparse
import re


class UnmappedCASAnalyzer:
    """Analyzes ingredients without CAS-RN and categorizes unmappability reasons."""

    def __init__(self, mim_root: Path):
        self.mim_root = mim_root
        self.categories = defaultdict(list)
        self.stats = {
            'total_ingredients': 0,
            'has_cas_rn': 0,
            'no_cas_rn': 0
        }

    def categorize_ingredient(self, ingredient: dict, filename: str) -> str:
        """Categorize why an ingredient doesn't have CAS-RN."""
        preferred_term = ingredient.get('preferred_term', '')

        # Category 1: Stock Solutions/Mixtures
        solution_patterns = [
            r'solution', r'stock', r'mixture', r'medium', r'media',
            r'buffer', r'supplement', r'mix'
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in solution_patterns):
            return 'stock_solutions_mixtures'

        # Category 2: Natural Products
        natural_patterns = [
            r'seawater', r'soil', r'peat', r'extract', r'organic',
            r'natural', r'plant', r'animal', r'environmental'
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in natural_patterns):
            return 'natural_products'

        # Category 3: Incomplete Chemical Formulas
        if self._is_incomplete_formula(preferred_term):
            return 'incomplete_formulas'

        # Category 4: Placeholders/Errors
        placeholder_patterns = [
            r'see source', r'original amount', r'chebi:1$', r'unknown',
            r'placeholder', r'tbd', r'n/a'
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in placeholder_patterns):
            return 'placeholders_errors'

        # Category 5: Complex Notation (special characters)
        if self._has_complex_notation(preferred_term):
            return 'complex_notation'

        # Category 6: Proprietary/Commercial Products
        commercial_patterns = [
            r'bacto', r'difco', r'sigma', r'fisher', r'bd-', r'brand',
            r'catalog', r'\d{4,}'  # Catalog numbers
        ]
        if any(re.search(pattern, preferred_term, re.IGNORECASE) for pattern in commercial_patterns):
            return 'commercial_products'

        # Category 7: Concentration Variants (may be mappable with preprocessing)
        if self._has_concentration_prefix(preferred_term):
            return 'concentration_variants'

        # Category 8: Abbreviations (may be mappable with expansion)
        if self._looks_like_abbreviation(preferred_term):
            return 'abbreviations'

        # Category 9: Other/Unknown
        return 'other'

    def _is_incomplete_formula(self, name: str) -> bool:
        """Check if chemical formula appears incomplete."""
        # Simple formulas without proper subscripts
        incomplete_patterns = [
            r'^[A-Z][a-z]?[A-Z][a-z]?$',  # e.g., NaCO, NaHCO (missing subscripts)
            r'^[A-Z][a-z]?\d+[A-Z][a-z]?$',  # e.g., Na2CO (missing final subscript)
        ]
        return any(re.match(pattern, name) for pattern in incomplete_patterns)

    def _has_complex_notation(self, name: str) -> bool:
        """Check if name has special characters that may cause API issues."""
        special_chars = ['·', '•', '‧', '⋅', '∙']
        return any(char in name for char in special_chars)

    def _has_concentration_prefix(self, name: str) -> bool:
        """Check if name starts with concentration prefix."""
        patterns = [
            r'^\d+\.?\d*\s*[mMuµnpf]?M\s+',  # Molar
            r'^\d+\.?\d*\s*%\s+',             # Percentage
            r'^\d+\.?\d*\s*[gmµn]g?/[LmldµM]+\s+',  # g/L, mg/mL
        ]
        return any(re.match(pattern, name) for pattern in patterns)

    def _looks_like_abbreviation(self, name: str) -> bool:
        """Check if name appears to be an abbreviation."""
        # All caps, short, with hyphens or numbers
        if len(name) <= 15 and name.replace('-', '').replace('_', '').isupper():
            return True
        # Common abbreviation patterns
        if re.match(r'^[A-Z]\d*-[A-Z]', name):  # e.g., Ca-pantothenate
            return True
        return False

    def analyze_all_ingredients(self):
        """Analyze all ingredients without CAS-RN."""
        print("Analyzing ingredients without CAS-RN...\n")

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

                    self.stats['total_ingredients'] += 1

                    # Check if has CAS-RN
                    chem_props = ingredient.get('chemical_properties', {})
                    if chem_props.get('cas_rn'):
                        self.stats['has_cas_rn'] += 1
                        continue

                    self.stats['no_cas_rn'] += 1

                    # Categorize
                    category = self.categorize_ingredient(ingredient, yaml_file.name)
                    self.categories[category].append({
                        'filename': yaml_file.name,
                        'preferred_term': ingredient.get('preferred_term', ''),
                        'status': ingredient.get('mapping_status', 'UNKNOWN'),
                        'ontology_id': ingredient.get('ontology_mapping', {}).get('ontology_id', 'None')
                    })

                except Exception as e:
                    print(f"Error processing {yaml_file.name}: {e}")

    def generate_report(self, output_file: Path):
        """Generate markdown report of unmappable categories."""
        category_names = {
            'stock_solutions_mixtures': 'Stock Solutions & Mixtures',
            'natural_products': 'Natural Products & Environmental Samples',
            'incomplete_formulas': 'Incomplete Chemical Formulas',
            'placeholders_errors': 'Placeholders & Data Errors',
            'complex_notation': 'Complex Notation (Special Characters)',
            'commercial_products': 'Proprietary/Commercial Products',
            'concentration_variants': 'Concentration Variants (Potentially Mappable)',
            'abbreviations': 'Abbreviations (Potentially Mappable)',
            'other': 'Other/Uncategorized'
        }

        category_descriptions = {
            'stock_solutions_mixtures': 'Multi-component mixtures that do not have single CAS-RN. These are formulations, not pure compounds.',
            'natural_products': 'Complex environmental or biological materials with variable composition.',
            'incomplete_formulas': 'Chemical formulas missing subscripts or other notation elements.',
            'placeholders_errors': 'Invalid entries, placeholders, or data quality issues.',
            'complex_notation': 'Special characters (·, •, etc.) causing API query failures. May be resolvable with better normalization.',
            'commercial_products': 'Brand-specific products or catalog items without standardized composition.',
            'concentration_variants': 'Ingredients with concentration prefixes that could be stripped. High potential for mapping.',
            'abbreviations': 'Abbreviated names that may expand to known compounds. Moderate potential for mapping.',
            'other': 'Ingredients that do not fit other categories.'
        }

        mappability = {
            'stock_solutions_mixtures': 'Unmappable (no single CAS-RN)',
            'natural_products': 'Unmappable (complex mixtures)',
            'incomplete_formulas': 'Potentially mappable (needs formula completion)',
            'placeholders_errors': 'Unmappable (data quality issues)',
            'complex_notation': 'Potentially mappable (needs character normalization)',
            'commercial_products': 'Low mappability (proprietary)',
            'concentration_variants': 'High mappability (strip prefixes)',
            'abbreviations': 'Moderate mappability (expand abbreviations)',
            'other': 'Unknown'
        }

        report = []
        report.append('# Unmapped CAS-RN Analysis Report\n')
        report.append(f'**Date**: {yaml.safe_dump(None)}')
        report.append(f'**Total Ingredients**: {self.stats["total_ingredients"]}')
        report.append(f'**With CAS-RN**: {self.stats["has_cas_rn"]} ({self.stats["has_cas_rn"]/self.stats["total_ingredients"]*100:.1f}%)')
        report.append(f'**Without CAS-RN**: {self.stats["no_cas_rn"]} ({self.stats["no_cas_rn"]/self.stats["total_ingredients"]*100:.1f}%)\n')
        report.append('---\n')

        # Summary table
        report.append('## Summary by Category\n')
        report.append('| Category | Count | Percentage | Mappability |\n')
        report.append('|----------|-------|------------|-------------|\n')

        sorted_categories = sorted(self.categories.items(), key=lambda x: len(x[1]), reverse=True)

        for category, items in sorted_categories:
            name = category_names.get(category, category)
            count = len(items)
            pct = count / self.stats['no_cas_rn'] * 100
            mappable = mappability.get(category, 'Unknown')
            report.append(f'| {name} | {count} | {pct:.1f}% | {mappable} |\n')

        report.append('\n---\n')

        # Detailed sections
        for category, items in sorted_categories:
            name = category_names.get(category, category)
            desc = category_descriptions.get(category, 'No description available.')
            mappable = mappability.get(category, 'Unknown')

            report.append(f'\n## {name}\n')
            report.append(f'**Count**: {len(items)} ({len(items)/self.stats["no_cas_rn"]*100:.1f}% of unmapped)\n')
            report.append(f'**Mappability**: {mappable}\n')
            report.append(f'**Description**: {desc}\n')

            # Examples (first 20)
            report.append('\n### Examples\n')
            for item in items[:20]:
                status = item['status']
                ont_id = item['ontology_id']
                report.append(f"- `{item['preferred_term']}` ({status}, {ont_id})\n")

            if len(items) > 20:
                report.append(f'\n*...and {len(items) - 20} more*\n')

            report.append('\n')

        # Recommendations
        report.append('---\n')
        report.append('\n## Recommendations for Further Improvement\n')
        report.append('\n### High Priority (Concentration Variants)\n')
        conc_count = len(self.categories.get('concentration_variants', []))
        report.append(f'**Potential gain**: {conc_count} ingredients\n')
        report.append('**Approach**: Strip concentration prefixes before API queries\n')
        report.append('- "1 M Sodium acetate" → "Sodium acetate"\n')
        report.append('- "0.2% Thiamine" → "Thiamine"\n')
        report.append('- "10 mM HEPES" → "HEPES"\n')

        report.append('\n### Medium Priority (Complex Notation)\n')
        complex_count = len(self.categories.get('complex_notation', []))
        report.append(f'**Potential gain**: {complex_count} ingredients\n')
        report.append('**Approach**: Normalize special characters\n')
        report.append('- "CaCl2·6H2O" → "Calcium chloride hexahydrate"\n')
        report.append('- "Na2EDTA•2H2O" → "Disodium EDTA dihydrate"\n')

        report.append('\n### Low Priority (Abbreviations)\n')
        abbrev_count = len(self.categories.get('abbreviations', []))
        report.append(f'**Potential gain**: {abbrev_count} ingredients\n')
        report.append('**Approach**: Build synonym expansion dictionary\n')
        report.append('- "Ca-pantothenate" → "Calcium pantothenate"\n')
        report.append('- "2Na-EDTA" → "Disodium EDTA"\n')

        total_potential = conc_count + complex_count + abbrev_count
        report.append(f'\n**Total potential gain**: {total_potential} ingredients ({total_potential/self.stats["no_cas_rn"]*100:.1f}% of unmapped, {total_potential/self.stats["total_ingredients"]*100:.1f}% overall)\n')

        # Write report
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            f.writelines(report)

        print(f"\n✅ Report written to: {output_file}")

    def print_summary(self):
        """Print summary statistics."""
        print("\n" + "=" * 80)
        print("UNMAPPED CAS-RN ANALYSIS SUMMARY")
        print("=" * 80)
        print(f"Total ingredients: {self.stats['total_ingredients']}")
        print(f"  With CAS-RN: {self.stats['has_cas_rn']} ({self.stats['has_cas_rn']/self.stats['total_ingredients']*100:.1f}%)")
        print(f"  Without CAS-RN: {self.stats['no_cas_rn']} ({self.stats['no_cas_rn']/self.stats['total_ingredients']*100:.1f}%)")
        print(f"\nCategories identified: {len(self.categories)}")

        sorted_categories = sorted(self.categories.items(), key=lambda x: len(x[1]), reverse=True)
        for category, items in sorted_categories:
            print(f"  {category}: {len(items)} ({len(items)/self.stats['no_cas_rn']*100:.1f}%)")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze ingredients without CAS-RN and categorize unmappability reasons'
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
        default=Path('workspace/reports/unmapped_cas_rn_analysis.md'),
        help='Output report file'
    )

    args = parser.parse_args()

    analyzer = UnmappedCASAnalyzer(args.mim)

    # Analyze all ingredients
    analyzer.analyze_all_ingredients()

    # Print summary
    analyzer.print_summary()

    # Generate report
    analyzer.generate_report(args.output)


if __name__ == '__main__':
    main()
