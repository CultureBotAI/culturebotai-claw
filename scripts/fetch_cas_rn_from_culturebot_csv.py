#!/usr/bin/env python3
"""
Fetch CAS-RN from CultureBotHT compounds_to_cas.csv for MediaIngredientMech ingredients.

Phase 3 of CAS-RN integration: Load CAS-RN mappings from local CSV file
and match against MediaIngredientMech ingredients.
"""

import yaml
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import argparse
import re


class CultureBotCSVFetcher:
    """Fetches CAS-RN from CultureBotHT compounds_to_cas.csv file."""

    def __init__(self, mim_root: Path, culturebot_ht_root: Path):
        self.mim_root = mim_root
        self.culturebot_ht_root = culturebot_ht_root
        self.cas_mappings = {}  # normalized_name -> CAS-RN
        self.stats = {
            'total_ingredients': 0,
            'already_has_cas': 0,
            'csv_entries_loaded': 0,
            'csv_matches': 0,
            'no_match': 0,
            'updated': 0
        }

    def load_cas_from_csv(self):
        """Load CAS-RN mappings from compounds_to_cas.csv."""
        csv_path = self.culturebot_ht_root / 'data/raw/google_sheets/compounds_to_cas.csv'

        if not csv_path.exists():
            print(f"⚠️  CSV file not found: {csv_path}")
            return

        print(f"Loading CAS-RN mappings from {csv_path.name}...")

        df = pd.read_csv(csv_path)

        for _, row in df.iterrows():
            compound = row.get('Compound', '')
            cas_rn = row.get('CAS', '')
            synonyms = row.get('Synonyms', '')

            # Skip if no valid CAS-RN
            if pd.isna(cas_rn) or not self._is_valid_cas_format(str(cas_rn)):
                continue

            cas_rn = str(cas_rn).strip()

            # Add primary compound name
            if pd.notna(compound):
                normalized = self._normalize_name(str(compound))
                if normalized:
                    self.cas_mappings[normalized] = cas_rn
                    self.stats['csv_entries_loaded'] += 1

            # Add synonyms if present
            if pd.notna(synonyms) and synonyms:
                for syn in str(synonyms).split(','):
                    normalized = self._normalize_name(syn.strip())
                    if normalized and normalized not in self.cas_mappings:
                        self.cas_mappings[normalized] = cas_rn

        print(f"  ✓ Loaded {self.stats['csv_entries_loaded']} CAS-RN entries")
        print(f"  ✓ Total normalized names (with synonyms): {len(self.cas_mappings)}\n")

    def _normalize_name(self, name: str) -> str:
        """Normalize compound name for matching."""
        if not name or pd.isna(name):
            return ""

        # Convert to lowercase
        normalized = str(name).lower().strip()

        # Remove common punctuation and special characters
        normalized = normalized.replace(',', ' ')
        normalized = normalized.replace('-', ' ')
        normalized = normalized.replace('_', ' ')
        normalized = normalized.replace('(', ' ')
        normalized = normalized.replace(')', ' ')
        normalized = normalized.replace('[', ' ')
        normalized = normalized.replace(']', ' ')
        normalized = normalized.replace('·', ' ')
        normalized = normalized.replace('.', ' ')

        # Remove multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate).strip()))

    def match_ingredient(self, ingredient: dict) -> Optional[str]:
        """
        Try to match ingredient against CSV mappings.

        Tries in order:
        1. preferred_term
        2. synonyms
        3. ontology_label
        """
        # Try preferred term
        preferred_term = ingredient.get('preferred_term', '')
        if preferred_term:
            normalized = self._normalize_name(preferred_term)
            if normalized in self.cas_mappings:
                return self.cas_mappings[normalized]

        # Try synonyms
        for syn in ingredient.get('synonyms', []):
            syn_text = syn.get('synonym_text', '')
            if syn_text:
                normalized = self._normalize_name(syn_text)
                if normalized in self.cas_mappings:
                    return self.cas_mappings[normalized]

        # Try ontology label
        ontology_mapping = ingredient.get('ontology_mapping', {})
        ontology_label = ontology_mapping.get('ontology_label', '')
        if ontology_label:
            normalized = self._normalize_name(ontology_label)
            if normalized in self.cas_mappings:
                return self.cas_mappings[normalized]

        return None

    def process_ingredients(self, dry_run: bool = True):
        """Process all MediaIngredientMech ingredients and fetch CAS-RN."""
        print("Processing MediaIngredientMech ingredients for CAS-RN matching...\n")

        ingredients_dir = self.mim_root / 'data/ingredients'

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

                    # Try to match against CSV
                    cas_rn = self.match_ingredient(ingredient)

                    if cas_rn:
                        self.stats['csv_matches'] += 1
                        print(f"    ✓ {yaml_file.stem[:50]:50s} → CAS-RN:{cas_rn}")

                        if not dry_run:
                            self._add_cas_rn_to_ingredient(ingredient, yaml_file, cas_rn)
                            self.stats['updated'] += 1
                    else:
                        self.stats['no_match'] += 1

                except Exception as e:
                    print(f"    ✗ Error processing {yaml_file.name}: {e}")

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
        ingredient['chemical_properties']['data_source'] = 'CultureBotHT compounds_to_cas.csv'
        ingredient['chemical_properties']['retrieval_date'] = datetime.now().isoformat()

        # Add to curation history
        if 'curation_history' not in ingredient:
            ingredient['curation_history'] = []

        preferred_term = ingredient.get('preferred_term', 'unknown')
        ingredient['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'fetch_cas_rn_from_culturebot_csv',
            'action': 'ADDED_CAS_RN',
            'changes': f'Added CAS-RN:{cas_rn} from CultureBotHT compounds_to_cas.csv (matched: {preferred_term})',
            'new_status': ingredient.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        # Save file
        with open(yaml_file, 'w') as f:
            yaml.dump(ingredient, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def print_stats(self):
        """Print fetching statistics."""
        print("=" * 80)
        print("CULTUREBOT CSV CAS-RN MATCH STATISTICS")
        print("=" * 80)
        print(f"CSV entries loaded: {self.stats['csv_entries_loaded']}")
        print(f"Total normalized names: {len(self.cas_mappings)}")
        print(f"\nIngredients processed: {self.stats['total_ingredients']}")
        print(f"  Already had CAS-RN: {self.stats['already_has_cas']}")
        print(f"  Matched from CSV: {self.stats['csv_matches']}")
        print(f"  No match found: {self.stats['no_match']}")
        print(f"\nIngredients updated: {self.stats['updated']}")

        if self.stats['csv_matches'] > 0:
            match_rate = (self.stats['csv_matches'] /
                         (self.stats['total_ingredients'] - self.stats['already_has_cas'])) * 100
            print(f"Match rate: {match_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch CAS-RN from CultureBotHT compounds_to_cas.csv for MediaIngredientMech ingredients'
    )
    parser.add_argument(
        '--mim',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--culturebot-ht',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureBotHT/CultureBotHT',
        help='Path to CultureBotHT repository'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying files'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    fetcher = CultureBotCSVFetcher(args.mim, args.culturebot_ht)

    # Load CAS-RN from CSV
    fetcher.load_cas_from_csv()

    # Process ingredients
    fetcher.process_ingredients(dry_run=args.dry_run)

    # Print statistics
    fetcher.print_stats()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print(f"\n✅ Updated {fetcher.stats['updated']} ingredients with CAS-RN from CSV")


if __name__ == '__main__':
    main()
