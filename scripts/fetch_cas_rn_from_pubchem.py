#!/usr/bin/env python3
"""
Fetch CAS-RN from PubChem API for MediaIngredientMech ingredients.

Phase 2 of CAS-RN integration: Query PubChem REST API using compound names
to retrieve CAS Registry Numbers for ingredients lacking CAS-RN.
"""

import yaml
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
import argparse
import json


class PubChemCASFetcher:
    """Fetches CAS-RN from PubChem API for ingredients using compound names."""

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
        self.checkpoint_file = Path('workspace/cas_rn_fetch_checkpoint.json')

    def fetch_cas_from_pubchem(self, compound_name: str) -> Optional[str]:
        """
        Fetch CAS-RN from PubChem using compound name.

        API endpoint: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{NAME}/synonyms/JSON
        CAS-RN is extracted from the synonyms list.
        """
        import urllib.parse

        # URL encode the compound name
        encoded_name = urllib.parse.quote(compound_name)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded_name}/synonyms/JSON"

        try:
            self.stats['api_queries'] += 1

            # PubChem rate limit: 5 requests per second
            time.sleep(0.21)  # ~4.5 requests/second to be safe

            response = self.session.get(url, timeout=30)

            if response.status_code == 404:
                # Compound name not found in PubChem
                return None

            response.raise_for_status()
            data = response.json()

            # Navigate JSON structure to find CAS-RN in synonyms
            # Structure: InformationList -> Information[] -> Synonym[]
            info_list = data.get('InformationList', {})
            information = info_list.get('Information', [])

            if not information:
                return None

            # Get first compound (usually the primary one)
            compound = information[0]
            synonyms = compound.get('Synonym', [])

            # Find CAS-RN format (XXX-XX-X) in synonyms
            for synonym in synonyms:
                if self._is_valid_cas_format(synonym):
                    return synonym

            return None

        except requests.exceptions.Timeout:
            print(f"      ⚠ Timeout for {compound_name}")
            self.stats['api_errors'] += 1
            return None
        except requests.exceptions.RequestException as e:
            print(f"      ⚠ API error for {compound_name}: {e}")
            self.stats['api_errors'] += 1
            return None
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"      ⚠ Parse error for {compound_name}: {e}")
            return None

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        import re
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate)))

    def process_ingredients(self, dry_run: bool = True, max_queries: Optional[int] = None):
        """Process all MediaIngredientMech ingredients and fetch CAS-RN."""
        print("Processing MediaIngredientMech ingredients for CAS-RN fetching...\n")

        ingredients_dir = self.mim_root / 'data/ingredients'
        processed_ids = self._load_checkpoint()

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
                    ingredient_id = ingredient.get('identifier', yaml_file.stem)

                    # Skip if already processed in previous run
                    if ingredient_id in processed_ids:
                        continue

                    # Check if already has CAS-RN
                    if self._has_cas_rn(ingredient):
                        self.stats['already_has_cas'] += 1
                        processed_ids.add(ingredient_id)
                        continue

                    # Check if has preferred_term
                    preferred_term = ingredient.get('preferred_term', '')
                    if not preferred_term:
                        self.stats['no_preferred_term'] += 1
                        processed_ids.add(ingredient_id)
                        continue

                    # Fetch CAS-RN from PubChem
                    print(f"    Querying {yaml_file.stem[:50]:50s} ({preferred_term[:30]})...")
                    cas_rn = self.fetch_cas_from_pubchem(preferred_term)

                    if cas_rn:
                        self.stats['cas_found'] += 1
                        print(f"      ✓ Found CAS-RN: {cas_rn}")

                        if not dry_run:
                            self._add_cas_rn_to_ingredient(ingredient, yaml_file, cas_rn)
                            self.stats['updated'] += 1
                    else:
                        self.stats['cas_not_found'] += 1
                        print(f"      - No CAS-RN found")

                    processed_ids.add(ingredient_id)
                    query_count += 1

                    # Save checkpoint every 50 queries
                    if query_count % 50 == 0:
                        self._save_checkpoint(processed_ids)
                        print(f"\n    [Checkpoint saved: {query_count} queries, {self.stats['cas_found']} found]\n")

                    # Check if reached max queries limit
                    if max_queries and query_count >= max_queries:
                        print(f"\n    [Reached max queries limit: {max_queries}]")
                        self._save_checkpoint(processed_ids)
                        return

                except Exception as e:
                    print(f"      ✗ Error processing {yaml_file.name}: {e}")

        # Save final checkpoint
        self._save_checkpoint(processed_ids)

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
        ingredient['chemical_properties']['data_source'] = 'PubChem API'
        ingredient['chemical_properties']['retrieval_date'] = datetime.now().isoformat()

        # Add to curation history
        if 'curation_history' not in ingredient:
            ingredient['curation_history'] = []

        preferred_term = ingredient.get('preferred_term', 'unknown')
        ingredient['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'fetch_cas_rn_from_pubchem',
            'action': 'ADDED_CAS_RN',
            'changes': f'Added CAS-RN:{cas_rn} from PubChem API via name lookup ({preferred_term})',
            'new_status': ingredient.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        # Save file
        with open(yaml_file, 'w') as f:
            yaml.dump(ingredient, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _load_checkpoint(self) -> set:
        """Load checkpoint of processed ingredient IDs."""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file) as f:
                    data = json.load(f)
                    processed = set(data.get('processed_ids', []))
                    print(f"  ✓ Loaded checkpoint: {len(processed)} ingredients already processed\n")
                    return processed
            except:
                pass
        return set()

    def _save_checkpoint(self, processed_ids: set):
        """Save checkpoint of processed ingredient IDs."""
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.checkpoint_file, 'w') as f:
            json.dump({
                'processed_ids': list(processed_ids),
                'timestamp': datetime.now().isoformat(),
                'stats': self.stats
            }, f, indent=2)

    def print_stats(self):
        """Print fetching statistics."""
        print("\n" + "=" * 80)
        print("PUBCHEM CAS-RN FETCH STATISTICS")
        print("=" * 80)
        print(f"Ingredients processed: {self.stats['total_ingredients']}")
        print(f"  Already had CAS-RN: {self.stats['already_has_cas']}")
        print(f"  No preferred term: {self.stats['no_preferred_term']}")
        print(f"\nPubChem API queries: {self.stats['api_queries']}")
        print(f"  CAS-RN found: {self.stats['cas_found']}")
        print(f"  CAS-RN not found: {self.stats['cas_not_found']}")
        print(f"  API errors: {self.stats['api_errors']}")
        print(f"\nIngredients updated: {self.stats['updated']}")

        if self.stats['api_queries'] > 0:
            success_rate = (self.stats['cas_found'] / self.stats['api_queries']) * 100
            print(f"Success rate: {success_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch CAS-RN from PubChem API for MediaIngredientMech ingredients'
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
    parser.add_argument(
        '--reset-checkpoint',
        action='store_true',
        help='Clear checkpoint and start from beginning'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    if args.reset_checkpoint:
        checkpoint_file = Path('workspace/cas_rn_fetch_checkpoint.json')
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            print("✓ Checkpoint cleared\n")

    fetcher = PubChemCASFetcher(args.mim)

    # Fetch CAS-RN from PubChem
    fetcher.process_ingredients(dry_run=args.dry_run, max_queries=args.max_queries)

    # Print statistics
    fetcher.print_stats()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print(f"\n✅ Updated {fetcher.stats['updated']} ingredients with CAS-RN from PubChem")


if __name__ == '__main__':
    main()
