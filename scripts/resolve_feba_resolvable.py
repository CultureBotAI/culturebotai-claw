#!/usr/bin/env python3
"""
Attempt to resolve FEBA ingredients classified as RESOLVABLE.

Uses additional strategies beyond notation variants:
- Enhanced hydrate notation conversion
- Manual lookup tables for common ambiguous names
- Alternative API approaches (CACTUS with formula conversion)
"""

import yaml
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import argparse
import re
import urllib.parse


class FEBAResolvableResolver:
    """Resolves FEBA ingredients classified as resolvable."""

    def __init__(self):
        self.stats = {
            'total_processed': 0,
            'resolved': 0,
            'still_unresolved': 0,
            'api_errors': 0
        }
        self.session = requests.Session()
        self.results = []

        # Manual lookup table for known difficult cases
        self.manual_mappings = {
            'AlK(SO4)2 12H2O': ('7784-24-9', 'Aluminum potassium sulfate dodecahydrate'),
            'CaCl2*2H2O': ('10035-04-8', 'Calcium chloride dihydrate'),
            'FeCl2 4H2O': ('13478-10-9', 'Iron(II) chloride tetrahydrate'),
            'FeCl2 tetrahydrate': ('13478-10-9', 'Iron(II) chloride tetrahydrate'),
            'FeSO4 7H2O': ('7782-63-0', 'Iron(II) sulfate heptahydrate'),
            'MgCl*6H2O': ('7791-18-6', 'Magnesium chloride hexahydrate'),
            'CASamino acids': ('65072-00-6', 'Casein acid hydrolysate'),
            'lipoic acid': ('62-46-4', 'Thioctic acid'),
            'D,L-6,8-Thioctic Acid': ('62-46-4', 'Alpha-lipoic acid'),
            'L-Tartaric acid': ('87-69-4', 'L-Tartaric acid'),
            'Hemin': ('16009-13-5', 'Hemin chloride'),
            'Trimethylglycine': ('107-43-7', 'Betaine'),
            'Lipopolysaccharide': None,  # Complex mixture
            'Casitone': None,  # Complex mixture
            'Peptone': None,  # Complex mixture
        }

    def resolve_ingredient(self, ingredient: str, category: str) -> Dict:
        """
        Attempt to resolve a single ingredient.

        Returns dict with original name, resolution strategy, CAS-RN if found.
        """
        self.stats['total_processed'] += 1

        result = {
            'original_name': ingredient,
            'category': category,
            'cas_rn': None,
            'strategy': None,
            'canonical_name': None
        }

        # 1. Check manual lookup table first
        if ingredient in self.manual_mappings:
            mapping = self.manual_mappings[ingredient]
            if mapping:
                result['cas_rn'] = mapping[0]
                result['canonical_name'] = mapping[1]
                result['strategy'] = 'manual_lookup_table'
                self.stats['resolved'] += 1
                self.results.append(result)
                return result

        # 2. Enhanced hydrate conversion for space-separated
        converted = self._enhanced_hydrate_conversion(ingredient)
        if converted != ingredient:
            cas_rn = self.fetch_cas_from_pubchem(converted)
            if cas_rn:
                result['cas_rn'] = cas_rn
                result['canonical_name'] = converted
                result['strategy'] = 'enhanced_hydrate_conversion'
                self.stats['resolved'] += 1
                self.results.append(result)
                return result

        # 3. Try CACTUS with original name
        cas_rn = self.fetch_cas_from_cactus(ingredient)
        if cas_rn:
            result['cas_rn'] = cas_rn
            result['strategy'] = 'cactus_api'
            self.stats['resolved'] += 1
            self.results.append(result)
            return result

        # 4. Try CACTUS with converted name
        if converted != ingredient:
            cas_rn = self.fetch_cas_from_cactus(converted)
            if cas_rn:
                result['cas_rn'] = cas_rn
                result['canonical_name'] = converted
                result['strategy'] = 'cactus_api_converted'
                self.stats['resolved'] += 1
                self.results.append(result)
                return result

        # Unresolved
        self.stats['still_unresolved'] += 1
        self.results.append(result)
        return result

    def _enhanced_hydrate_conversion(self, name: str) -> str:
        """
        Enhanced hydrate notation conversion.

        Handles:
        - "AlK(SO4)2 12H2O" → "AlK(SO4)2·12H2O"
        - "FeCl2 4H2O" → "Iron(II) chloride tetrahydrate"
        - "CaCl2*2H2O" → "Calcium chloride dihydrate"
        """
        # Pattern 1: Space-separated with numbers
        pattern1 = r'^([A-Z][A-Za-z0-9()]+)\s+(\d+)H2O$'
        match = re.match(pattern1, name)
        if match:
            formula = match.group(1)
            num = int(match.group(2))

            # Convert number to word
            hydrate_words = {
                1: 'monohydrate', 2: 'dihydrate', 3: 'trihydrate',
                4: 'tetrahydrate', 5: 'pentahydrate', 6: 'hexahydrate',
                7: 'heptahydrate', 8: 'octahydrate', 9: 'nonahydrate',
                10: 'decahydrate', 12: 'dodecahydrate', 18: 'octadecahydrate'
            }

            if num in hydrate_words:
                # Try to convert formula to name
                name_map = {
                    'FeCl2': 'Iron(II) chloride',
                    'FeSO4': 'Iron(II) sulfate',
                    'CaCl2': 'Calcium chloride',
                    'MgCl2': 'Magnesium chloride',
                    'MgSO4': 'Magnesium sulfate',
                    'CuSO4': 'Copper(II) sulfate',
                    'ZnSO4': 'Zinc sulfate',
                    'AlK(SO4)2': 'Aluminum potassium sulfate'
                }

                if formula in name_map:
                    return f"{name_map[formula]} {hydrate_words[num]}"

        # Pattern 2: Asterisk notation
        if '*' in name and 'H2O' in name:
            return name.replace('*', '·')

        return name

    def fetch_cas_from_pubchem(self, name: str) -> Optional[str]:
        """Fetch CAS-RN from PubChem."""
        encoded = urllib.parse.quote(name)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/synonyms/JSON"

        try:
            time.sleep(0.21)
            response = self.session.get(url, timeout=10)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            info_list = data.get('InformationList', {})
            information = info_list.get('Information', [])

            if not information:
                return None

            synonyms = information[0].get('Synonym', [])

            for synonym in synonyms:
                if self._is_valid_cas_format(synonym):
                    return synonym

            return None

        except Exception as e:
            self.stats['api_errors'] += 1
            return None

    def fetch_cas_from_cactus(self, identifier: str) -> Optional[str]:
        """Fetch CAS-RN from NCI CACTUS."""
        encoded = urllib.parse.quote(identifier)
        url = f"https://cactus.nci.nih.gov/chemical/structure/{encoded}/cas"

        try:
            time.sleep(0.5)
            response = self.session.get(url, timeout=10)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            text = response.text.strip()

            if not text:
                return None

            for line in text.split('\n'):
                cas_rn = line.strip()
                if self._is_valid_cas_format(cas_rn):
                    return cas_rn

            return None

        except Exception as e:
            self.stats['api_errors'] += 1
            return None

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate).strip()))

    def print_stats(self):
        """Print resolution statistics."""
        print("\n" + "=" * 80)
        print("FEBA RESOLVABLE INGREDIENTS RESOLUTION RESULTS")
        print("=" * 80)
        print(f"Total processed: {self.stats['total_processed']}")
        print(f"  Resolved: {self.stats['resolved']}")
        print(f"  Still unresolved: {self.stats['still_unresolved']}")
        print(f"  API errors: {self.stats['api_errors']}")

        if self.stats['total_processed'] > 0:
            success_rate = (self.stats['resolved'] / self.stats['total_processed']) * 100
            print(f"\nSuccess rate: {success_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Resolve FEBA ingredients classified as resolvable'
    )
    parser.add_argument(
        '--classification',
        type=Path,
        default=Path('workspace/feba_mappability_classification.yaml'),
        help='Mappability classification report'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/feba_resolvable_resolution_results.yaml'),
        help='Output resolution results'
    )
    parser.add_argument(
        '--priority',
        choices=['HIGH', 'MEDIUM', 'ALL'],
        default='HIGH',
        help='Which priority to process (HIGH, MEDIUM, or ALL)'
    )

    args = parser.parse_args()

    # Load classification
    with open(args.classification) as f:
        classification = yaml.safe_load(f)

    # Extract resolvable ingredients
    to_resolve = []

    if args.priority in ['HIGH', 'ALL']:
        for item in classification['classifications'].get('RESOLVABLE_HIGH', []):
            to_resolve.append(item)

    if args.priority in ['MEDIUM', 'ALL']:
        for item in classification['classifications'].get('RESOLVABLE_MEDIUM', []):
            to_resolve.append(item)

    if not to_resolve:
        print(f"No {args.priority} priority resolvable ingredients found.")
        return

    print(f"Processing {len(to_resolve)} {args.priority} priority resolvable ingredients...\n")

    resolver = FEBAResolvableResolver()

    # Process each ingredient
    for i, item in enumerate(to_resolve, 1):
        ingredient = item['ingredient']
        category = item.get('category', 'unknown')

        print(f"[{i}/{len(to_resolve)}] {ingredient:50s} ", end='', flush=True)
        result = resolver.resolve_ingredient(ingredient, category)

        if result['cas_rn']:
            print(f"✓ {result['cas_rn']:15s} (via {result['strategy']})")
        else:
            print(f"✗ Still unresolved")

    # Print statistics
    resolver.print_stats()

    # Save results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        yaml.dump({
            'metadata': {
                'date': datetime.now().isoformat(),
                'priority_level': args.priority,
                'total_processed': resolver.stats['total_processed'],
                'resolved': resolver.stats['resolved'],
                'success_rate': f"{(resolver.stats['resolved'] / resolver.stats['total_processed'] * 100):.1f}%"
            },
            'statistics': resolver.stats,
            'results': resolver.results
        }, f, default_flow_style=False, allow_unicode=True)

    print(f"\n✅ Results saved to: {args.output}")


if __name__ == '__main__':
    main()
