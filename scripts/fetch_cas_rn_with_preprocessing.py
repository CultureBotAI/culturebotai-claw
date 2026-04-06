#!/usr/bin/env python3
"""
Fetch CAS-RN with advanced name preprocessing for difficult cases.

Phase 5 of CAS-RN integration: Apply name normalization strategies to query
APIs more effectively for ingredients that failed in previous phases.
"""

import yaml
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import argparse
import re
import urllib.parse


class PreprocessingCASFetcher:
    """Fetches CAS-RN using advanced name preprocessing strategies."""

    def __init__(self, mim_root: Path):
        self.mim_root = mim_root
        self.stats = {
            'total_ingredients': 0,
            'already_has_cas': 0,
            'pubchem_found': 0,
            'cactus_found': 0,
            'not_found': 0,
            'updated': 0
        }
        self.session = requests.Session()

    def preprocess_name(self, name: str) -> List[str]:
        """
        Generate multiple normalized variants of a name.

        Returns list of name variants to try (in order of priority).
        """
        variants = []

        # Original name
        variants.append(name)

        # Strip concentration prefixes
        stripped = self._strip_concentration_prefix(name)
        if stripped != name:
            variants.append(stripped)

        # Normalize hydrate notation
        normalized_hydrate = self._normalize_hydrate_notation(name)
        if normalized_hydrate != name:
            variants.append(normalized_hydrate)

        # Replace special chars with spaces
        no_special = self._remove_special_chars(name)
        if no_special != name:
            variants.append(no_special)

        # Expand common abbreviations
        expanded = self._expand_abbreviations(name)
        if expanded != name:
            variants.append(expanded)

        # Remove parentheses and contents
        no_parens = re.sub(r'\([^)]*\)', '', name).strip()
        if no_parens and no_parens != name:
            variants.append(no_parens)

        return variants

    def _strip_concentration_prefix(self, name: str) -> str:
        """Strip concentration prefixes from compound names."""
        patterns = [
            r'^\d+\.?\d*\s*[mMuµnpf]?M\s+',  # Molar
            r'^\d+\.?\d*\s*%\s+',             # Percentage
            r'^\d+\.?\d*\s*[gmµn]g?/[LmldµM]+\s+',  # g/L, mg/mL
        ]

        stripped = name
        for pattern in patterns:
            stripped = re.sub(pattern, '', stripped)

        return stripped.strip()

    def _normalize_hydrate_notation(self, name: str) -> str:
        """Convert hydrate notation to word form."""
        # Pattern: compound followed by · or • or x then number H2O
        patterns = [
            (r'([A-Za-z0-9()]+)\s*[·•x]\s*(\d+)\s*H2O', r'\1 \2-hydrate'),
            (r'([A-Za-z0-9()]+)\s*[·•x]\s*H2O', r'\1 monohydrate'),
            (r'([A-Za-z0-9()]+)·(\d+)H2O', r'\1 \2-hydrate'),
            (r'([A-Za-z0-9()]+)•(\d+)H2O', r'\1 \2-hydrate'),
        ]

        normalized = name
        for pattern, replacement in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                # Extract base compound and hydrate number
                base = match.group(1)
                try:
                    num = int(match.group(2)) if len(match.groups()) > 1 else 1
                except:
                    num = 1

                # Convert number to word
                num_words = {
                    1: 'monohydrate', 2: 'dihydrate', 3: 'trihydrate',
                    4: 'tetrahydrate', 5: 'pentahydrate', 6: 'hexahydrate',
                    7: 'heptahydrate', 8: 'octahydrate', 9: 'nonahydrate',
                    10: 'decahydrate', 12: 'dodecahydrate', 18: 'octadecahydrate'
                }

                if num in num_words:
                    normalized = f"{base} {num_words[num]}"
                    break

        return normalized

    def _remove_special_chars(self, name: str) -> str:
        """Remove or replace special characters."""
        # Replace special dots with spaces
        special_dots = ['·', '•', '‧', '⋅', '∙']
        cleaned = name
        for char in special_dots:
            cleaned = cleaned.replace(char, ' ')

        # Clean up multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        return cleaned

    def _expand_abbreviations(self, name: str) -> str:
        """Expand common abbreviations."""
        abbreviations = {
            r'\bCa-': 'Calcium ',
            r'\bMg-': 'Magnesium ',
            r'\bNa-': 'Sodium ',
            r'\bK-': 'Potassium ',
            r'\b2Na-': 'Disodium ',
            r'\b3Na-': 'Trisodium ',
            r'\bFe-': 'Iron ',
            r'\bCu-': 'Copper ',
            r'\bZn-': 'Zinc ',
        }

        expanded = name
        for abbrev, full in abbreviations.items():
            expanded = re.sub(abbrev, full, expanded, flags=re.IGNORECASE)

        return expanded

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

        except:
            return None

    def fetch_cas_from_cactus(self, name: str) -> Optional[str]:
        """Fetch CAS-RN from NCI CACTUS."""
        encoded = urllib.parse.quote(name)
        url = f"https://cactus.nci.nih.gov/chemical/structure/{encoded}/cas"

        try:
            time.sleep(0.5)  # Rate limiting
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

        except:
            return None

    def try_fetch_with_preprocessing(self, ingredient: dict) -> tuple[Optional[str], Optional[str]]:
        """
        Try to fetch CAS-RN using preprocessing strategies.

        Returns: (cas_rn, source) tuple
        """
        preferred_term = ingredient.get('preferred_term', '')

        if not preferred_term:
            return None, None

        # Generate name variants
        variants = self.preprocess_name(preferred_term)

        # Try PubChem first (faster, better coverage)
        for variant in variants:
            if variant == preferred_term:
                continue  # Skip original (already tried in previous phases)

            cas_rn = self.fetch_cas_from_pubchem(variant)
            if cas_rn:
                return cas_rn, 'PubChem API (preprocessed)'

        # Try CACTUS as fallback
        for variant in variants:
            if variant == preferred_term:
                continue

            cas_rn = self.fetch_cas_from_cactus(variant)
            if cas_rn:
                return cas_rn, 'NCI CACTUS (preprocessed)'

        # Try using ontology label if different from preferred term
        ontology_label = ingredient.get('ontology_mapping', {}).get('ontology_label', '')
        if ontology_label and ontology_label != preferred_term:
            # Try PubChem with ontology label
            cas_rn = self.fetch_cas_from_pubchem(ontology_label)
            if cas_rn:
                return cas_rn, 'PubChem API (ontology label)'

            # Try CACTUS with ontology label
            cas_rn = self.fetch_cas_from_cactus(ontology_label)
            if cas_rn:
                return cas_rn, 'NCI CACTUS (ontology label)'

        return None, None

    def _is_valid_cas_format(self, cas_candidate: str) -> bool:
        """Validate CAS-RN format: digits-digits-digit."""
        return bool(re.match(r'^\d+-\d+-\d+$', str(cas_candidate).strip()))

    def process_ingredients(self, dry_run: bool = True, max_queries: Optional[int] = None):
        """Process ingredients without CAS-RN using preprocessing."""
        print("Processing ingredients with name preprocessing...\n")

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

                    # Try preprocessing
                    preferred_term = ingredient.get('preferred_term', '')
                    print(f"    Querying {yaml_file.stem[:50]:50s} ({preferred_term[:30]})...")

                    cas_rn, source = self.try_fetch_with_preprocessing(ingredient)

                    if cas_rn:
                        if 'PubChem' in source:
                            self.stats['pubchem_found'] += 1
                        else:
                            self.stats['cactus_found'] += 1

                        print(f"      ✓ Found CAS-RN: {cas_rn} ({source})")

                        if not dry_run:
                            self._add_cas_rn_to_ingredient(ingredient, yaml_file, cas_rn, source)
                            self.stats['updated'] += 1
                    else:
                        self.stats['not_found'] += 1
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

    def _add_cas_rn_to_ingredient(self, ingredient: dict, yaml_file: Path, cas_rn: str, source: str):
        """Add CAS-RN to ingredient and save file."""
        if 'chemical_properties' not in ingredient:
            ingredient['chemical_properties'] = {}

        ingredient['chemical_properties']['cas_rn'] = cas_rn
        ingredient['chemical_properties']['data_source'] = source
        ingredient['chemical_properties']['retrieval_date'] = datetime.now().isoformat()

        if 'curation_history' not in ingredient:
            ingredient['curation_history'] = []

        preferred_term = ingredient.get('preferred_term', 'unknown')
        ingredient['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'fetch_cas_rn_with_preprocessing',
            'action': 'ADDED_CAS_RN',
            'changes': f'Added CAS-RN:{cas_rn} from {source} via name preprocessing ({preferred_term})',
            'new_status': ingredient.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        with open(yaml_file, 'w') as f:
            yaml.dump(ingredient, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def print_stats(self):
        """Print fetching statistics."""
        print("=" * 80)
        print("NAME PREPROCESSING CAS-RN FETCH STATISTICS")
        print("=" * 80)
        print(f"Ingredients processed: {self.stats['total_ingredients']}")
        print(f"  Already had CAS-RN: {self.stats['already_has_cas']}")
        print(f"\nCAS-RN found:")
        print(f"  PubChem (preprocessed): {self.stats['pubchem_found']}")
        print(f"  CACTUS (preprocessed): {self.stats['cactus_found']}")
        print(f"  Total found: {self.stats['pubchem_found'] + self.stats['cactus_found']}")
        print(f"  Not found: {self.stats['not_found']}")
        print(f"\nIngredients updated: {self.stats['updated']}")

        total_queries = self.stats['total_ingredients'] - self.stats['already_has_cas']
        if total_queries > 0:
            found = self.stats['pubchem_found'] + self.stats['cactus_found']
            success_rate = (found / total_queries) * 100
            print(f"Success rate: {success_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch CAS-RN with advanced name preprocessing'
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
        help='Maximum number of ingredients to process (for testing)'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    fetcher = PreprocessingCASFetcher(args.mim)

    # Process ingredients
    fetcher.process_ingredients(dry_run=args.dry_run, max_queries=args.max_queries)

    # Print statistics
    fetcher.print_stats()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print(f"\n✅ Updated {fetcher.stats['updated']} ingredients with CAS-RN")


if __name__ == '__main__':
    main()
