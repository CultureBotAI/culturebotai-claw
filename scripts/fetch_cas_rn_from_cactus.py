#!/usr/bin/env python3
"""
Fetch CAS-RN from NCI CACTUS Chemical Identifier Resolver.

Phase 4 of CAS-RN integration: Query NCI CACTUS API using compound names
to retrieve CAS Registry Numbers for ingredients not found via CSV or PubChem.
"""

import yaml
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
import argparse
import re
import urllib.parse


class CACTUSCASFetcher:
    """Fetches CAS-RN from NCI CACTUS API using compound names."""

    def __init__(self, mim_root: Path):
        self.mim_root = mim_root
        self.stats = {
            'total_ingredients': 0,
            'already_has_cas': 0,
            'no_preferred_term': 0,
            'api_queries': 0,
            'cas_found': 0,
            'cas_not_found': 0,
            'api_errors': 0,
            'updated': 0
        }
        self.session = requests.Session()

    def fetch_cas_from_cactus(self, identifier: str) -> Optional[str]:
        """
        Fetch CAS-RN from NCI CACTUS Chemical Identifier Resolver.

        API: https://cactus.nci.nih.gov/chemical/structure/{id}/cas
        Returns: Plain text CAS-RN (may return multiple, takes first valid one)
        """
        encoded = urllib.parse.quote(identifier)
        url = f"https://cactus.nci.nih.gov/chemical/structure/{encoded}/cas"

        try:
            self.stats['api_queries'] += 1

            # Conservative rate limiting
            time.sleep(0.5)

            response = self.session.get(url, timeout=10)

            if response.status_code == 404:
                return None

            response.raise_for_status()

            # CACTUS returns plain text, potentially multiple CAS-RNs (one per line)
            text = response.text.strip()

            if not text:
                return None

            # Take first valid CAS-RN
            for line in text.split('\n'):
                cas_rn = line.strip()
                if self._is_valid_cas_format(cas_rn):
                    return cas_rn

            return None

        except requests.exceptions.Timeout:
            print(f"      ⚠ Timeout for {identifier}")
            self.stats['api_errors'] += 1
            return None
        except requests.exceptions.RequestException as e:
            # CACTUS returns 404 for not found, which is normal
            if response.status_code != 404:
                print(f"      ⚠ API error for {identifier}: {e}")
                self.stats['api_errors'] += 1
            return None
        except Exception as e:
            print(f"      ⚠ Error for {identifier}: {e}")
            return None

    def _strip_concentration_prefix(self, name: str) -> str:
        """Strip concentration prefixes from compound names."""
        # Remove patterns like "1 M", "0.5 M", "0.2%", "10 mM", etc.
        patterns = [
            r'^\d+\.?\d*\s*[mMuµnpf]?M\s+',  # Molar concentrations
            r'^\d+\.?\d*\s*%\s+',             # Percentages
            r'^\d+\.?\d*\s*[gmµn]g?/[LmldµM]+\s+',  # g/L, mg/mL, etc.
        ]

        stripped = name
        for pattern in patterns:
            stripped = re.sub(pattern, '', stripped)

        return stripped.strip()

    def try_multiple_identifiers(self, ingredient: dict) -> Optional[str]:
        """Try multiple identifier forms for an ingredient."""
        preferred_term = ingredient.get('preferred_term', '')

        if not preferred_term:
            self.stats['no_preferred_term'] += 1
            return None

        # Try 1: Original preferred term
        cas = self.fetch_cas_from_cactus(preferred_term)
        if cas:
            return cas

        # Try 2: Strip concentration prefix
        normalized = self._strip_concentration_prefix(preferred_term)
        if normalized != preferred_term:
            cas = self.fetch_cas_from_cactus(normalized)
            if cas:
                return cas

        # Try 3: Ontology label (if different from preferred term)
        ontology_label = ingredient.get('ontology_mapping', {}).get('ontology_label', '')
        if ontology_label and ontology_label != preferred_term:
            cas = self.fetch_cas_from_cactus(ontology_label)
            if cas:
                return cas

        return None

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate).strip()))

    def process_ingredients(self, dry_run: bool = True, max_queries: Optional[int] = None):
        """Process all MediaIngredientMech ingredients and fetch CAS-RN."""
        print("Processing MediaIngredientMech ingredients for CAS-RN fetching...\n")

        ingredients_dir = self.mim_root / 'data/ingredients'
        query_count = 0

        for status_dir in ['mapped', 'unmapped']:
            status_path = ingredients_dir / status_dir
            if not status_path.exists():
                continue

            print(f"  Processing {status_dir} ingredients...")

            for yaml_file in sorted(status_path.glob('*.yaml')):
                try:
                    with open(yaml_file) as f:
                        ingredient = yaml.safe_load(f)

                    if not ingredient:
                        continue

                    self.stats['total_ingredients'] += 1

                    # Skip if already has CAS-RN
                    if self._has_cas_rn(ingredient):
                        self.stats['already_has_cas'] += 1
                        continue

                    # Fetch CAS-RN from CACTUS
                    preferred_term = ingredient.get('preferred_term', '')
                    if preferred_term:
                        print(f"    Querying {yaml_file.stem[:50]:50s} ({preferred_term[:30]})...")
                        cas_rn = self.try_multiple_identifiers(ingredient)

                        if cas_rn:
                            self.stats['cas_found'] += 1
                            print(f"      ✓ Found CAS-RN: {cas_rn}")

                            if not dry_run:
                                self._add_cas_rn_to_ingredient(ingredient, yaml_file, cas_rn)
                                self.stats['updated'] += 1
                        else:
                            self.stats['cas_not_found'] += 1
                            print(f"      - No CAS-RN found")

                    query_count += 1

                    # Check if reached max queries limit
                    if max_queries and query_count >= max_queries:
                        print(f"\n    [Reached max queries limit: {max_queries}]")
                        return

                except Exception as e:
                    print(f"      ✗ Error processing {yaml_file.name}: {e}")

        print()

    def _has_cas_rn(self, ingredient: dict) -> bool:
        """Check if ingredient already has CAS-RN."""
        chem_props = ingredient.get('chemical_properties', {})
        return chem_props.get('cas_rn') is not None

    def _add_cas_rn_to_ingredient(self, ingredient: dict, yaml_file: Path, cas_rn: str):
        """Add CAS-RN to ingredient and save file."""
        # Ensure chemical_properties exists
        if 'chemical_properties' not in ingredient:
            ingredient['chemical_properties'] = {}

        # Add CAS-RN
        ingredient['chemical_properties']['cas_rn'] = cas_rn
        ingredient['chemical_properties']['data_source'] = 'NCI CACTUS Chemical Identifier Resolver'
        ingredient['chemical_properties']['retrieval_date'] = datetime.now().isoformat()

        # Add to curation history
        if 'curation_history' not in ingredient:
            ingredient['curation_history'] = []

        preferred_term = ingredient.get('preferred_term', 'unknown')
        ingredient['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'fetch_cas_rn_from_cactus',
            'action': 'ADDED_CAS_RN',
            'changes': f'Added CAS-RN:{cas_rn} from NCI CACTUS via name lookup ({preferred_term})',
            'new_status': ingredient.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        # Save file
        with open(yaml_file, 'w') as f:
            yaml.dump(ingredient, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def print_stats(self):
        """Print fetching statistics."""
        print("=" * 80)
        print("NCI CACTUS CAS-RN FETCH STATISTICS")
        print("=" * 80)
        print(f"Ingredients processed: {self.stats['total_ingredients']}")
        print(f"  Already had CAS-RN: {self.stats['already_has_cas']}")
        print(f"  No preferred term: {self.stats['no_preferred_term']}")
        print(f"\nNCI CACTUS API queries: {self.stats['api_queries']}")
        print(f"  CAS-RN found: {self.stats['cas_found']}")
        print(f"  CAS-RN not found: {self.stats['cas_not_found']}")
        print(f"  API errors: {self.stats['api_errors']}")
        print(f"\nIngredients updated: {self.stats['updated']}")

        if self.stats['api_queries'] > 0:
            success_rate = (self.stats['cas_found'] / self.stats['api_queries']) * 100
            print(f"Success rate: {success_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch CAS-RN from NCI CACTUS for MediaIngredientMech ingredients'
    )
    parser.add_argument(
        '--mim',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying files'
    )
    parser.add_argument(
        '--max-queries',
        type=int,
        help='Maximum number of API queries (for testing/rate limiting)'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    fetcher = CACTUSCASFetcher(args.mim)

    # Fetch CAS-RN from CACTUS
    fetcher.process_ingredients(dry_run=args.dry_run, max_queries=args.max_queries)

    # Print statistics
    fetcher.print_stats()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print(f"\n✅ Updated {fetcher.stats['updated']} ingredients with CAS-RN from CACTUS")


if __name__ == '__main__':
    main()
