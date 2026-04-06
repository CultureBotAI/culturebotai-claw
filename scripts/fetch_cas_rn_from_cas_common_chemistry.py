#!/usr/bin/env python3
"""
Fetch CAS-RN from CAS Common Chemistry API for MediaIngredientMech ingredients.

Phase 6 of CAS-RN integration: Query CAS Common Chemistry API using compound names
to retrieve CAS Registry Numbers from the official CAS source.

REQUIREMENTS:
- CAS Common Chemistry account (free registration)
- API access via registration at https://commonchemistry.cas.org/
- Free tier: 50,000 requests/month
- No API key required - open access API

HOW TO ACCESS:
1. Visit https://commonchemistry.cas.org/
2. Review Terms of Use
3. API is open access - no authentication required
4. Rate limits: Be respectful with request frequency

USAGE:
    python scripts/fetch_cas_rn_from_cas_common_chemistry.py

    # With options
    python scripts/fetch_cas_rn_from_cas_common_chemistry.py --dry-run --max-queries 50
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


class CASCommonChemistryFetcher:
    """Fetches CAS-RN from CAS Common Chemistry API."""

    def __init__(self, mim_root: Path):
        self.mim_root = mim_root
        self.base_url = "https://commonchemistry.cas.org/api"
        self.stats = {
            'total_ingredients': 0,
            'already_has_cas': 0,
            'no_identifiers': 0,
            'api_queries': 0,
            'cas_found': 0,
            'cas_not_found': 0,
            'api_errors': 0,
            'updated': 0
        }
        self.session = requests.Session()
        # Set user agent to identify research use
        self.session.headers.update({
            'User-Agent': 'MediaIngredientMech/1.0 (Research; +https://github.com/KG-Hub/KG-Microbe)'
        })

    def search_by_name(self, name: str) -> Optional[str]:
        """
        Search CAS Common Chemistry by compound name.

        API: GET /search?q={name}
        Returns: List of search results with CAS-RN
        """
        try:
            # URL encode the name
            encoded_name = urllib.parse.quote(name)
            url = f"{self.base_url}/search?q={encoded_name}"

            response = self.session.get(url, timeout=10)

            if response.status_code == 404:
                return None

            if response.status_code != 200:
                self.stats['api_errors'] += 1
                return None

            data = response.json()

            # API returns list of results
            results = data.get('results', [])

            if not results:
                return None

            # Get first result (best match)
            first_result = results[0]
            cas_rn = first_result.get('rn')  # 'rn' is the CAS-RN field

            if cas_rn and self._is_valid_cas_format(cas_rn):
                return cas_rn

            return None

        except requests.exceptions.Timeout:
            self.stats['api_errors'] += 1
            return None
        except Exception as e:
            self.stats['api_errors'] += 1
            print(f"      ⚠ Error: {e}")
            return None

    def get_detail_by_cas(self, cas_rn: str) -> Optional[dict]:
        """
        Get detailed information for a specific CAS-RN.

        API: GET /detail?cas_rn={cas_rn}
        Returns: Detailed compound information
        """
        try:
            url = f"{self.base_url}/detail?cas_rn={cas_rn}"

            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()
            return data

        except Exception as e:
            return None

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        if not cas_candidate:
            return False
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate).strip()))

    def process_ingredients(self, dry_run: bool = True, max_queries: Optional[int] = None):
        """Process all MediaIngredientMech ingredients without CAS-RN."""
        print("Processing MediaIngredientMech ingredients for CAS Common Chemistry CAS-RN fetching...\n")

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

                    # Rate limiting: Be respectful, 1 request per second
                    time.sleep(1.0)

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
        ingredient['chemical_properties']['data_source'] = 'CAS Common Chemistry API'
        ingredient['chemical_properties']['retrieval_date'] = datetime.now().isoformat()

        if 'curation_history' not in ingredient:
            ingredient['curation_history'] = []

        preferred_term = ingredient.get('preferred_term', 'unknown')
        ingredient['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'fetch_cas_rn_from_cas_common_chemistry',
            'action': 'ADDED_CAS_RN',
            'changes': f'Added CAS-RN:{cas_rn} from CAS Common Chemistry API ({preferred_term})',
            'new_status': ingredient.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        with open(yaml_file, 'w') as f:
            yaml.dump(ingredient, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def print_stats(self):
        """Print fetching statistics."""
        print("=" * 80)
        print("CAS COMMON CHEMISTRY CAS-RN FETCH STATISTICS")
        print("=" * 80)
        print(f"Ingredients processed: {self.stats['total_ingredients']}")
        print(f"  Already had CAS-RN: {self.stats['already_has_cas']}")
        print(f"  No identifiers: {self.stats['no_identifiers']}")
        print(f"\nCAS Common Chemistry API queries: {self.stats['api_queries']}")
        print(f"  CAS-RN found: {self.stats['cas_found']}")
        print(f"  CAS-RN not found: {self.stats['cas_not_found']}")
        print(f"  API errors: {self.stats['api_errors']}")
        print(f"\nIngredients updated: {self.stats['updated']}")

        if self.stats['api_queries'] > 0:
            success_rate = (self.stats['cas_found'] / self.stats['api_queries']) * 100
            print(f"Success rate: {success_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch CAS-RN from CAS Common Chemistry API for MediaIngredientMech ingredients',
        epilog='''
API ACCESS:
  - CAS Common Chemistry is an open access API
  - No API key or registration required
  - Free tier: 50,000 requests/month
  - Visit https://commonchemistry.cas.org/ for more information
  - Be respectful with request frequency

USAGE EXAMPLES:
  # Dry run (preview only)
  python scripts/fetch_cas_rn_from_cas_common_chemistry.py --dry-run

  # Test with limited queries
  python scripts/fetch_cas_rn_from_cas_common_chemistry.py --dry-run --max-queries 10

  # Full run (write changes)
  python scripts/fetch_cas_rn_from_cas_common_chemistry.py
        '''
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
        help='Maximum number of API queries (for testing)'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    fetcher = CASCommonChemistryFetcher(args.mim)

    # Process ingredients
    fetcher.process_ingredients(dry_run=args.dry_run, max_queries=args.max_queries)

    # Print statistics
    fetcher.print_stats()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print(f"\n✅ Updated {fetcher.stats['updated']} ingredients with CAS-RN from CAS Common Chemistry")

    return 0


if __name__ == '__main__':
    exit(main())
