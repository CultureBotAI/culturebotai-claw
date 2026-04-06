#!/usr/bin/env python3
"""
Integrate CAS-RN mappings from CultureBotHT to MediaIngredientMech.

Reads compound mappings from CultureBotHT's MicroMediaParam pipeline data
and adds CAS-RN identifiers to MediaIngredientMech ingredient records.
"""

import yaml
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Set
import re
import argparse


class CASRNIntegrator:
    """Integrates CAS-RN data from CultureBotHT to MediaIngredientMech."""

    def __init__(self, culturebot_ht_root: Path, mim_root: Path):
        self.culturebot_ht_root = culturebot_ht_root
        self.mim_root = mim_root
        self.cas_mappings = {}  # ingredient_name -> CAS-RN
        self.chebi_to_cas = {}  # CHEBI:XXXXX -> CAS-RN
        self.stats = {
            'total_cas_mappings_loaded': 0,
            'mim_ingredients_total': 0,
            'mim_ingredients_updated': 0,
            'mim_ingredients_already_had_cas': 0,
            'mim_ingredients_matched_by_name': 0,
            'mim_ingredients_matched_by_chebi': 0,
            'mim_ingredients_no_match': 0
        }

    def load_cas_mappings_from_culturebot_ht(self):
        """Load CAS-RN mappings from CultureBotHT compound_mappings files."""
        print("Loading CAS-RN mappings from CultureBotHT...")

        mappings_file = self.culturebot_ht_root / 'data/mappings/compound_mappings_strict_final.tsv'
        hydrate_file = self.culturebot_ht_root / 'data/mappings/compound_mappings_strict_final_hydrate.tsv'

        for file_path in [mappings_file, hydrate_file]:
            if not file_path.exists():
                print(f"  ⚠ File not found: {file_path}")
                continue

            print(f"  Loading {file_path.name}...")
            df = pd.read_csv(file_path, sep='\t', low_memory=False)

            for _, row in df.iterrows():
                original = row.get('original', '')
                mapped = row.get('mapped', '')

                if pd.isna(original):
                    continue

                # Extract CAS-RN from mapped column
                cas_rn = self._extract_cas_rn(mapped)

                if cas_rn:
                    # Normalize ingredient name and store mapping
                    normalized = self._normalize_name(original)
                    self.cas_mappings[normalized] = cas_rn
                    self.stats['total_cas_mappings_loaded'] += 1

                # Also check if this row has CHEBI mapping - we can use it for indirect CAS lookup
                # Store CHEBI -> ingredient name -> CAS-RN chain
                chebi_id = self._extract_chebi_id(mapped)
                if chebi_id and cas_rn:
                    self.chebi_to_cas[chebi_id] = cas_rn

        # Also build reverse lookup: if ingredient has CHEBI but no direct CAS-RN,
        # we can look up other ingredients with same CHEBI that do have CAS-RN
        print(f"\n  Building indirect CAS-RN lookups via CHEBI...")
        self._build_indirect_cas_mappings()

        print(f"  ✓ Loaded {self.stats['total_cas_mappings_loaded']} direct CAS-RN mappings")
        print(f"  ✓ {len(self.cas_mappings)} unique by name")
        print(f"  ✓ {len(self.chebi_to_cas)} unique by CHEBI ID\n")

    def _build_indirect_cas_mappings(self):
        """Build indirect CAS-RN mappings via CHEBI IDs."""
        # Reload to build CHEBI->CAS mappings from all rows
        mappings_file = self.culturebot_ht_root / 'data/mappings/compound_mappings_strict_final.tsv'

        if not mappings_file.exists():
            return

        df = pd.read_csv(mappings_file, sep='\t', low_memory=False)

        # First pass: collect all CHEBI IDs
        chebi_to_names = {}  # CHEBI:XXXXX -> [list of ingredient names]

        for _, row in df.iterrows():
            original = row.get('original', '')
            mapped = row.get('mapped', '')

            if pd.isna(original) or pd.isna(mapped):
                continue

            chebi_id = self._extract_chebi_id(mapped)
            if chebi_id:
                if chebi_id not in chebi_to_names:
                    chebi_to_names[chebi_id] = []
                chebi_to_names[chebi_id].append(original)

        # Second pass: for each CHEBI, if any variant has CAS-RN, apply to all
        for chebi_id, names in chebi_to_names.items():
            # Find if any name variant has CAS-RN
            cas_rn_found = None
            for name in names:
                normalized = self._normalize_name(name)
                if normalized in self.cas_mappings:
                    cas_rn_found = self.cas_mappings[normalized]
                    break

            # If found, apply to all name variants and to the CHEBI ID itself
            if cas_rn_found:
                self.chebi_to_cas[chebi_id] = cas_rn_found
                for name in names:
                    normalized = self._normalize_name(name)
                    if normalized not in self.cas_mappings:
                        self.cas_mappings[normalized] = cas_rn_found

    def _extract_cas_rn(self, mapped_value: str) -> Optional[str]:
        """Extract CAS-RN from mapped value (e.g., 'CAS-RN:50-99-7')."""
        if pd.isna(mapped_value):
            return None

        match = re.search(r'CAS-RN:(\d+-\d+-\d+)', str(mapped_value))
        if match:
            return match.group(1)
        return None

    def _extract_chebi_id(self, mapped_value: str) -> Optional[str]:
        """Extract CHEBI ID from mapped value (e.g., 'CHEBI:26710')."""
        if pd.isna(mapped_value):
            return None

        match = re.search(r'CHEBI:(\d+)', str(mapped_value))
        if match:
            return f"CHEBI:{match.group(1)}"
        return None

    def _normalize_name(self, name: str) -> str:
        """Normalize ingredient name for matching."""
        if pd.isna(name):
            return ""

        # Convert to lowercase
        normalized = str(name).lower().strip()

        # Remove common punctuation
        normalized = normalized.replace(',', ' ')
        normalized = normalized.replace('-', ' ')
        normalized = normalized.replace('_', ' ')
        normalized = normalized.replace('(', ' ')
        normalized = normalized.replace(')', ' ')

        # Remove multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized)

        return normalized

    def process_mim_ingredients(self, dry_run: bool = True):
        """Process MediaIngredientMech ingredients and add CAS-RN."""
        print("Processing MediaIngredientMech ingredients...")

        ingredients_dir = self.mim_root / 'data/ingredients'

        for status_dir in ['mapped', 'unmapped']:
            status_path = ingredients_dir / status_dir
            if not status_path.exists():
                continue

            print(f"\n  Processing {status_dir} ingredients...")

            for yaml_file in status_path.glob('*.yaml'):
                try:
                    with open(yaml_file) as f:
                        ingredient = yaml.safe_load(f)

                    if not ingredient:
                        continue

                    self.stats['mim_ingredients_total'] += 1

                    # Check if already has CAS-RN
                    if self._has_cas_rn(ingredient):
                        self.stats['mim_ingredients_already_had_cas'] += 1
                        continue

                    # Try to find CAS-RN
                    cas_rn = self._find_cas_rn_for_ingredient(ingredient)

                    if cas_rn:
                        if not dry_run:
                            self._add_cas_rn_to_ingredient(ingredient, yaml_file, cas_rn)
                        self.stats['mim_ingredients_updated'] += 1
                        print(f"    ✓ {yaml_file.stem[:50]:50s} → CAS-RN:{cas_rn}")
                    else:
                        self.stats['mim_ingredients_no_match'] += 1

                except Exception as e:
                    print(f"    ✗ Error processing {yaml_file.name}: {e}")

    def _has_cas_rn(self, ingredient: dict) -> bool:
        """Check if ingredient already has CAS-RN."""
        chem_props = ingredient.get('chemical_properties', {})
        return chem_props.get('cas_rn') is not None

    def _find_cas_rn_for_ingredient(self, ingredient: dict) -> Optional[str]:
        """Find CAS-RN for an ingredient by matching name or CHEBI ID."""

        # Try matching by CHEBI ID first (most reliable)
        ontology_mapping = ingredient.get('ontology_mapping', {})
        if ontology_mapping:
            chebi_id = ontology_mapping.get('ontology_id', '')
            if chebi_id and chebi_id.startswith('CHEBI:'):
                cas_rn = self.chebi_to_cas.get(chebi_id)
                if cas_rn:
                    self.stats['mim_ingredients_matched_by_chebi'] += 1
                    return cas_rn

        # Try matching by preferred term
        preferred_term = ingredient.get('preferred_term', '')
        if preferred_term:
            normalized = self._normalize_name(preferred_term)
            cas_rn = self.cas_mappings.get(normalized)
            if cas_rn:
                self.stats['mim_ingredients_matched_by_name'] += 1
                return cas_rn

        # Try matching by synonyms
        for synonym in ingredient.get('synonyms', []):
            syn_text = synonym.get('synonym_text', '')
            if syn_text:
                normalized = self._normalize_name(syn_text)
                cas_rn = self.cas_mappings.get(normalized)
                if cas_rn:
                    self.stats['mim_ingredients_matched_by_name'] += 1
                    return cas_rn

        return None

    def _add_cas_rn_to_ingredient(self, ingredient: dict, yaml_file: Path, cas_rn: str):
        """Add CAS-RN to ingredient and save file."""

        # Ensure chemical_properties exists
        if 'chemical_properties' not in ingredient:
            ingredient['chemical_properties'] = {}

        # Add CAS-RN
        ingredient['chemical_properties']['cas_rn'] = cas_rn
        ingredient['chemical_properties']['data_source'] = 'CultureBotHT/MicroMediaParam'
        ingredient['chemical_properties']['retrieval_date'] = datetime.now().isoformat()

        # Add to curation history
        if 'curation_history' not in ingredient:
            ingredient['curation_history'] = []

        ingredient['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'integrate_cas_rn_from_culturebot_ht',
            'action': 'ADDED_CAS_RN',
            'changes': f'Added CAS-RN:{cas_rn} from CultureBotHT compound mappings',
            'new_status': ingredient.get('mapping_status', 'MAPPED'),
            'llm_assisted': False
        })

        # Save file
        with open(yaml_file, 'w') as f:
            yaml.dump(ingredient, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def print_stats(self):
        """Print integration statistics."""
        print("\n" + "=" * 80)
        print("CAS-RN INTEGRATION STATISTICS")
        print("=" * 80)
        print(f"CultureBotHT CAS-RN mappings loaded: {self.stats['total_cas_mappings_loaded']}")
        print(f"\nMediaIngredientMech ingredients:")
        print(f"  Total processed: {self.stats['mim_ingredients_total']}")
        print(f"  Already had CAS-RN: {self.stats['mim_ingredients_already_had_cas']}")
        print(f"  Updated with CAS-RN: {self.stats['mim_ingredients_updated']}")
        print(f"    - Matched by CHEBI ID: {self.stats['mim_ingredients_matched_by_chebi']}")
        print(f"    - Matched by name: {self.stats['mim_ingredients_matched_by_name']}")
        print(f"  No CAS-RN found: {self.stats['mim_ingredients_no_match']}")

        if self.stats['mim_ingredients_total'] > 0:
            coverage = (self.stats['mim_ingredients_updated'] + self.stats['mim_ingredients_already_had_cas']) / self.stats['mim_ingredients_total'] * 100
            print(f"\nCAS-RN coverage: {coverage:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description='Integrate CAS-RN mappings from CultureBotHT to MediaIngredientMech'
    )
    parser.add_argument(
        '--culturebot-ht',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureBotHT/CultureBotHT',
        help='Path to CultureBotHT repository'
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

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    integrator = CASRNIntegrator(args.culturebot_ht, args.mim)

    # Load CAS-RN mappings from CultureBotHT
    integrator.load_cas_mappings_from_culturebot_ht()

    # Process MediaIngredientMech ingredients
    integrator.process_mim_ingredients(dry_run=args.dry_run)

    # Print statistics
    integrator.print_stats()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print(f"\n✅ Updated {integrator.stats['mim_ingredients_updated']} ingredients with CAS-RN")


if __name__ == '__main__':
    main()
