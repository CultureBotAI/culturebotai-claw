#!/usr/bin/env python3
"""
Fetch CAS-RN from ChemSpider API for MediaIngredientMech ingredients.

Phase 6 of CAS-RN integration: Query ChemSpider API using compound names
and CHEBI IDs to retrieve CAS Registry Numbers.

REQUIREMENTS:
- ChemSpider API key (free registration at https://developer.rsc.org/)
- Python requests library
- Free tier: 1,000 calls/month

HOW TO OBTAIN API KEY:
1. Visit https://developer.rsc.org/
2. Sign up for a free account
3. Register an Application
4. Copy the API key

USAGE:
    export CHEMSPIDER_API_KEY="your-api-key-here"
    python scripts/fetch_cas_rn_from_chemspider.py

    OR

    python scripts/fetch_cas_rn_from_chemspider.py --api-key YOUR_KEY
"""

import yaml
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
import argparse
import os
import re
import urllib.parse


class ChemSpiderCASFetcher:
    """Fetches CAS-RN from ChemSpider API."""

    def __init__(self, mim_root: Path, api_key: str):
        self.mim_root = mim_root
        self.api_key = api_key
        self.base_url = "https://api.rsc.org/compounds/v1"
        self.stats = {
            'total_ingredients': 0,
            'already_has_cas': 0,
            'no_identifiers': 0,
            'api_queries': 0,
            'cas_found': 0,
            'cas_not_found': 0,
            'api_errors': 0,
            'updated': 0,
            'rate_limit_errors': 0
        }
        self.session = requests.Session()
        self.session.headers.update({'apikey': self.api_key})

    def search_by_name(self, name: str) -> Optional[str]:
        """
        Search ChemSpider by compound name.

        API: GET /compounds/v1/filter/name
        Returns: QueryId for results retrieval
        """
        try:
            # Filter search by name
            url = f"{self.base_url}/filter/name"
            response = self.session.post(url, json={"name": name}, timeout=10)

            if response.status_code == 429:
                self.stats['rate_limit_errors'] += 1
                print(f"      ⚠ Rate limit exceeded")
                return None

            if response.status_code != 200:
                return None

            data = response.json()
            query_id = data.get('queryId')

            if not query_id:
                return None

            # Wait for results (ChemSpider requires polling)
            time.sleep(1)

            # Get results
            results_url = f"{self.base_url}/filter/{query_id}/results"
            results_response = self.session.get(results_url, timeout=10)

            if results_response.status_code != 200:
                return None

            results_data = results_response.json()
            results = results_data.get('results', [])

            if not results:
                return None

            # Get first result ChemSpider ID
            chemspider_id = results[0]

            # Get details including CAS-RN
            details_url = f"{self.base_url}/records/{chemspider_id}/details"
            details_response = self.session.get(details_url, timeout=10)

            if details_response.status_code != 200:
                return None

            details = details_response.json()

            # Look for CAS-RN in externalReferences or commonName
            external_refs = details.get('externalReferences', [])
            for ref in external_refs:
                if ref.get('source') == 'CAS Registry Number':
                    cas_rn = ref.get('externalId')
                    if self._is_valid_cas_format(cas_rn):
                        return cas_rn

            return None

        except requests.exceptions.Timeout:
            self.stats['api_errors'] += 1
            return None
        except Exception as e:
            self.stats['api_errors'] += 1
            print(f"      ⚠ Error: {e}")
            return None

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        if not cas_candidate:
            return False
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate).strip()))

    def process_ingredients(self, dry_run: bool = True, max_queries: Optional[int] = None):
        """Process all MediaIngredientMech ingredients without CAS-RN."""
        print("Processing MediaIngredientMech ingredients for ChemSpider CAS-RN fetching...\n")

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

                    preferred_term = ingredient.get('preferred_term', '')
                    if not preferred_term:
                        self.stats['no_identifiers'] += 1
                        continue

                    self.stats['api_queries'] += 1
                    print(f"    Querying {yaml_file.stem[:50]:50s} ({preferred_term[:30]})...")

                    # Rate limiting: ChemSpider allows ~1000/month, be conservative
                    time.sleep(1.5)

                    cas_rn = self.search_by_name(preferred_term)

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
        if 'chemical_properties' not in ingredient:
            ingredient['chemical_properties'] = {}

        ingredient['chemical_properties']['cas_rn'] = cas_rn
        ingredient['chemical_properties']['data_source'] = 'ChemSpider API'
        ingredient['chemical_properties']['retrieval_date'] = datetime.now().isoformat()

        if 'curation_history' not in ingredient:
            ingredient['curation_history'] = []

        preferred_term = ingredient.get('preferred_term', 'unknown')
        ingredient['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'fetch_cas_rn_from_chemspider',
            'action': 'ADDED_CAS_RN',
            'changes': f'Added CAS-RN:{cas_rn} from ChemSpider API ({preferred_term})',
            'new_status': ingredient.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        with open(yaml_file, 'w') as f:
            yaml.dump(ingredient, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def print_stats(self):
        """Print fetching statistics."""
        print("=" * 80)
        print("CHEMSPIDER CAS-RN FETCH STATISTICS")
        print("=" * 80)
        print(f"Ingredients processed: {self.stats['total_ingredients']}")
        print(f"  Already had CAS-RN: {self.stats['already_has_cas']}")
        print(f"  No identifiers: {self.stats['no_identifiers']}")
        print(f"\nChemSpider API queries: {self.stats['api_queries']}")
        print(f"  CAS-RN found: {self.stats['cas_found']}")
        print(f"  CAS-RN not found: {self.stats['cas_not_found']}")
        print(f"  API errors: {self.stats['api_errors']}")
        print(f"  Rate limit errors: {self.stats['rate_limit_errors']}")
        print(f"\nIngredients updated: {self.stats['updated']}")

        if self.stats['api_queries'] > 0:
            success_rate = (self.stats['cas_found'] / self.stats['api_queries']) * 100
            print(f"Success rate: {success_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch CAS-RN from ChemSpider API for MediaIngredientMech ingredients',
        epilog='''
API KEY SETUP:
  1. Register at https://developer.rsc.org/
  2. Create an Application
  3. Copy your API key
  4. Set environment variable: export CHEMSPIDER_API_KEY="your-key"
     OR use --api-key parameter

FREE TIER LIMITS:
  - 1,000 API calls per month
  - No commercial use
        '''
    )
    parser.add_argument(
        '--mim',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--api-key',
        type=str,
        default=os.environ.get('CHEMSPIDER_API_KEY'),
        help='ChemSpider API key (or set CHEMSPIDER_API_KEY environment variable)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying files'
    )
    parser.add_argument(
        '--max-queries',
        type=int,
        help='Maximum number of API queries (for testing)'
    )

    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: ChemSpider API key required!")
        print()
        print("Please provide an API key via:")
        print("  1. Environment variable: export CHEMSPIDER_API_KEY='your-key'")
        print("  2. Command line: --api-key YOUR_KEY")
        print()
        print("To obtain a free API key:")
        print("  1. Visit https://developer.rsc.org/")
        print("  2. Sign up and register an Application")
        print("  3. Copy your API key")
        print()
        print("Free tier: 1,000 API calls per month")
        return 1

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    fetcher = ChemSpiderCASFetcher(args.mim, args.api_key)

    # Process ingredients
    fetcher.process_ingredients(dry_run=args.dry_run, max_queries=args.max_queries)

    # Print statistics
    fetcher.print_stats()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print(f"\n✅ Updated {fetcher.stats['updated']} ingredients with CAS-RN from ChemSpider")

    return 0


if __name__ == '__main__':
    exit(main())
