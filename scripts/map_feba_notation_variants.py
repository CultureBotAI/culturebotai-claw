#!/usr/bin/env python3
"""
Map FEBA ingredient notation variants to CAS-RN.

Handles notation variants not covered by previous phases:
- Space-separated hydrates: "FeCl2 4H2O" → "FeCl2·4H2O"
- Asterisk hydrates: "CaCl2*2H2O" → "CaCl2·2H2O"
- Spelled-out hydrates: "magnesium chloride hexahydrate"
- Gas notation: "#N2" → "nitrogen"
- Common name variants: "Thiamine" vs "Thiamine hydrochloride"
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


class FEBANotationMapper:
    """Maps FEBA ingredient notation variants to CAS-RN."""

    def __init__(self):
        self.stats = {
            'total_processed': 0,
            'space_hydrate_converted': 0,
            'asterisk_hydrate_converted': 0,
            'spelled_hydrate_converted': 0,
            'gas_notation_converted': 0,
            'vitamin_variant_converted': 0,
            'cas_found': 0,
            'cas_not_found': 0,
            'api_errors': 0
        }
        self.session = requests.Session()
        self.results = []

    def normalize_variants(self, name: str) -> List[Dict[str, str]]:
        """
        Generate normalized variants for FEBA notation.

        Returns list of dicts with 'variant' and 'strategy' keys.
        """
        variants = [{'variant': name, 'strategy': 'original'}]

        # 1. Space-separated hydrates: "FeCl2 4H2O" → standard forms
        space_hydrate = self._normalize_space_hydrate(name)
        if space_hydrate != name:
            variants.append({'variant': space_hydrate, 'strategy': 'space_hydrate_normalized'})
            self.stats['space_hydrate_converted'] += 1

        # 2. Asterisk hydrates: "CaCl2*2H2O" → standard forms
        asterisk_hydrate = self._normalize_asterisk_hydrate(name)
        if asterisk_hydrate != name:
            variants.append({'variant': asterisk_hydrate, 'strategy': 'asterisk_hydrate_normalized'})
            self.stats['asterisk_hydrate_converted'] += 1

        # 3. Spelled-out hydrates: "magnesium chloride hexahydrate" → "MgCl2·6H2O"
        spelled_hydrate = self._normalize_spelled_hydrate(name)
        if spelled_hydrate:
            variants.append({'variant': spelled_hydrate, 'strategy': 'spelled_hydrate_to_formula'})
            self.stats['spelled_hydrate_converted'] += 1

        # 4. Gas notation: "#N2" → "nitrogen"
        gas_name = self._normalize_gas_notation(name)
        if gas_name != name:
            variants.append({'variant': gas_name, 'strategy': 'gas_notation_normalized'})
            self.stats['gas_notation_converted'] += 1

        # 5. Vitamin/supplement variants
        vitamin_variants = self._expand_vitamin_variants(name)
        for v in vitamin_variants:
            variants.append({'variant': v, 'strategy': 'vitamin_variant_expanded'})
            self.stats['vitamin_variant_converted'] += 1

        return variants

    def _normalize_space_hydrate(self, name: str) -> str:
        """
        Convert space-separated hydrates to standard notation.

        Examples:
        - "FeCl2 4H2O" → "FeCl2·4H2O"
        - "FeSO4 7H2O" → "FeSO4·7H2O"
        - "CaCl2 2H2O" → "CaCl2·2H2O"
        """
        # Pattern: chemical formula + space + number + H2O
        pattern = r'^([A-Z][A-Za-z0-9()]+)\s+(\d+)H2O$'
        match = re.match(pattern, name)

        if match:
            formula = match.group(1)
            num = match.group(2)
            return f"{formula}·{num}H2O"

        return name

    def _normalize_asterisk_hydrate(self, name: str) -> str:
        """
        Convert asterisk hydrates to standard notation.

        Examples:
        - "CaCl2*2H2O" → "CaCl2·2H2O"
        - "MgCl*6H2O" → "MgCl·6H2O"
        """
        # Replace * with ·
        if '*' in name and 'H2O' in name:
            return name.replace('*', '·')

        return name

    def _normalize_spelled_hydrate(self, name: str) -> Optional[str]:
        """
        Convert spelled-out hydrates to chemical formula.

        Examples:
        - "magnesium chloride hexahydrate" → "MgCl2·6H2O"
        - "magnesium sulfate heptahydrate" → "MgSO4·7H2O"
        - "iron(II) chloride tetrahydrate" → "FeCl2·4H2O"
        """
        name_lower = name.lower()

        # Common compound mappings
        compound_map = {
            'magnesium chloride': 'MgCl2',
            'magnesium sulfate': 'MgSO4',
            'iron(ii) chloride': 'FeCl2',
            'iron(iii) chloride': 'FeCl3',
            'iron chloride': 'FeCl2',  # Assume Fe(II)
            'calcium chloride': 'CaCl2',
            'copper sulfate': 'CuSO4',
            'ferrous sulfate': 'FeSO4',
            'ferric chloride': 'FeCl3'
        }

        # Hydrate number mappings
        hydrate_map = {
            'monohydrate': '1',
            'dihydrate': '2',
            'trihydrate': '3',
            'tetrahydrate': '4',
            'pentahydrate': '5',
            'hexahydrate': '6',
            'heptahydrate': '7',
            'octahydrate': '8',
            'nonahydrate': '9',
            'decahydrate': '10',
            'dodecahydrate': '12'
        }

        # Try to match compound and hydrate
        for compound_name, formula in compound_map.items():
            if compound_name in name_lower:
                for hydrate_name, num in hydrate_map.items():
                    if hydrate_name in name_lower:
                        return f"{formula}·{num}H2O"

        return None

    def _normalize_gas_notation(self, name: str) -> str:
        """
        Convert gas notation to standard names.

        Examples:
        - "#N2" → "nitrogen"
        - "#Ar" → "argon"
        - "#N2O" → "nitrous oxide"
        """
        gas_map = {
            '#N2': 'nitrogen',
            '#n2': 'nitrogen',
            '#Ar': 'argon',
            '#ar': 'argon',
            '#N2O': 'nitrous oxide',
            '#n2o': 'nitrous oxide',
            '#argon': 'argon'
        }

        return gas_map.get(name, name)

    def _expand_vitamin_variants(self, name: str) -> List[str]:
        """
        Expand vitamin names to include common salt forms.

        Examples:
        - "Thiamine" → ["Thiamine hydrochloride", "Thiamine HCl"]
        - "Pantothenic Acid" → ["Calcium pantothenate", "D-Pantothenic acid"]
        - "pyridoxine HCl" → ["pyridoxine hydrochloride"]
        """
        name_lower = name.lower()
        variants = []

        # Vitamin B1 (Thiamine)
        if 'thiamine' in name_lower and 'hcl' not in name_lower and 'hydrochloride' not in name_lower:
            variants.extend(['Thiamine hydrochloride', 'Thiamine HCl'])

        # Vitamin B5 (Pantothenic acid)
        if 'pantothenic acid' in name_lower or 'pantothenate' in name_lower:
            variants.extend(['Calcium pantothenate', 'D-Pantothenic acid', 'Calcium D-pantothenate'])

        # Vitamin B6 (Pyridoxine)
        if 'pyridoxine' in name_lower:
            if 'hcl' in name_lower:
                variants.append('pyridoxine hydrochloride')
            else:
                variants.extend(['pyridoxine hydrochloride', 'pyridoxine HCl'])

        # Vitamin B12
        if 'vitamin b12' in name_lower or 'b12' in name_lower:
            variants.extend(['Cyanocobalamin', 'Vitamin B12'])

        return variants

    def fetch_cas_from_pubchem(self, name: str) -> Optional[str]:
        """Fetch CAS-RN from PubChem using compound name."""
        encoded = urllib.parse.quote(name)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/synonyms/JSON"

        try:
            time.sleep(0.21)  # Rate limiting
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

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate).strip()))

    def process_ingredient(self, ingredient_name: str) -> Dict:
        """
        Process a single ingredient through all variant strategies.

        Returns dict with original name, variants tried, CAS-RN if found, and strategy used.
        """
        self.stats['total_processed'] += 1

        result = {
            'original_name': ingredient_name,
            'variants_tried': [],
            'cas_rn': None,
            'successful_strategy': None,
            'pubchem_url': None
        }

        # Generate all variants
        variants = self.normalize_variants(ingredient_name)

        # Try each variant
        for variant_info in variants:
            variant = variant_info['variant']
            strategy = variant_info['strategy']

            result['variants_tried'].append({
                'variant': variant,
                'strategy': strategy
            })

            # Query PubChem
            cas_rn = self.fetch_cas_from_pubchem(variant)

            if cas_rn:
                result['cas_rn'] = cas_rn
                result['successful_strategy'] = strategy
                result['pubchem_url'] = f"https://pubchem.ncbi.nlm.nih.gov/#query={urllib.parse.quote(variant)}"
                self.stats['cas_found'] += 1
                break

        if not result['cas_rn']:
            self.stats['cas_not_found'] += 1

        self.results.append(result)
        return result

    def print_stats(self):
        """Print processing statistics."""
        print("\n" + "=" * 80)
        print("FEBA NOTATION VARIANT MAPPING STATISTICS")
        print("=" * 80)
        print(f"Total ingredients processed: {self.stats['total_processed']}")
        print(f"\nVariant conversions:")
        print(f"  Space-separated hydrates: {self.stats['space_hydrate_converted']}")
        print(f"  Asterisk hydrates: {self.stats['asterisk_hydrate_converted']}")
        print(f"  Spelled-out hydrates: {self.stats['spelled_hydrate_converted']}")
        print(f"  Gas notation: {self.stats['gas_notation_converted']}")
        print(f"  Vitamin variants: {self.stats['vitamin_variant_converted']}")
        print(f"\nResults:")
        print(f"  CAS-RN found: {self.stats['cas_found']}")
        print(f"  CAS-RN not found: {self.stats['cas_not_found']}")
        print(f"  API errors: {self.stats['api_errors']}")

        if self.stats['total_processed'] > 0:
            success_rate = (self.stats['cas_found'] / self.stats['total_processed']) * 100
            print(f"\nSuccess rate: {success_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Map FEBA ingredient notation variants to CAS-RN'
    )
    parser.add_argument(
        '--ingredients',
        type=Path,
        required=True,
        help='Text file with ingredient names (one per line)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/feba_notation_mapping_results.yaml'),
        help='Output YAML file with results'
    )

    args = parser.parse_args()

    # Read ingredient list
    with open(args.ingredients) as f:
        ingredients = [line.strip() for line in f if line.strip()]

    print(f"Processing {len(ingredients)} FEBA ingredients with notation variants...\n")

    mapper = FEBANotationMapper()

    # Process each ingredient
    for i, ingredient in enumerate(ingredients, 1):
        print(f"[{i}/{len(ingredients)}] {ingredient:50s} ", end='', flush=True)
        result = mapper.process_ingredient(ingredient)

        if result['cas_rn']:
            print(f"✓ {result['cas_rn']:15s} (via {result['successful_strategy']})")
        else:
            print(f"✗ No CAS-RN found")

    # Print statistics
    mapper.print_stats()

    # Save results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w') as f:
        yaml.dump({
            'metadata': {
                'date': datetime.now().isoformat(),
                'total_processed': mapper.stats['total_processed'],
                'cas_found': mapper.stats['cas_found'],
                'success_rate': f"{(mapper.stats['cas_found'] / mapper.stats['total_processed'] * 100):.1f}%"
            },
            'statistics': mapper.stats,
            'results': mapper.results
        }, f, default_flow_style=False, allow_unicode=True)

    print(f"\n✅ Results saved to: {args.output}")


if __name__ == '__main__':
    main()
