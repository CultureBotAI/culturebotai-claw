#!/usr/bin/env python3
"""
Enrich MediaIngredientMech ingredient files with CAS-RN numbers.

Strategy (in priority order):
  1. CHEBI-mapped ingredients → PubChem API (CHEBI xref → PubChem CID → CAS-RN)
  2. All ingredients → normalized name match against CultureBotHT compounds_to_cas.csv

Writes CAS-RN to chemical_properties.cas_rn in each MIM ingredient YAML.

Usage:
    python scripts/enrich_mim_cas_rn.py [--dry-run] [--max-queries N]
"""

import csv
import re
import sys
import time
import yaml
import argparse
import urllib.request
import urllib.error
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


MIM_ROOT = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'
CULTUREBOT_ROOT = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureBotHT/CultureBotHT'
PUBCHEM_BASE = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug'


# ---------------------------------------------------------------------------
# CAS-RN validation
# ---------------------------------------------------------------------------

CAS_PATTERN = re.compile(r'^\d{2,7}-\d{2}-\d$')


def valid_cas(cas: str) -> bool:
    return bool(cas and CAS_PATTERN.match(cas.strip()))


# ---------------------------------------------------------------------------
# Source 1: CultureBotHT compounds_to_cas.csv (name-based lookup)
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Aggressive normalization for fuzzy name matching."""
    s = s.lower().strip()
    # Remove hydration notation variations
    s = re.sub(r'[·•\*×xX]\s*\d+\s*h2o', '', s)
    s = re.sub(r'\d+\s*h2o', '', s)
    # Strip all non-alphanumeric
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


def load_cas_name_index(culturebot_root: Path) -> dict:
    """
    Build normalized-name → CAS-RN lookup from CultureBotHT CSV.
    Indexes both compound names and their synonyms.
    """
    csv_path = culturebot_root / 'data/raw/google_sheets/compounds_to_cas.csv'
    index = {}

    if not csv_path.exists():
        print(f"  Warning: CultureBotHT CAS CSV not found at {csv_path}")
        return index

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            cas = row.get('CAS', '').strip()
            if not valid_cas(cas):
                continue
            compound = row.get('Compound', '').strip()
            synonyms = row.get('Synonyms', '').strip()

            if compound:
                index[_normalize(compound)] = (cas, compound)
            for syn in synonyms.split(';'):
                syn = syn.strip()
                if syn:
                    index[_normalize(syn)] = (cas, compound)

    print(f"  Loaded {len(index)} name→CAS entries from CultureBotHT CSV")
    return index


def lookup_by_name(preferred_term: str, name_index: dict) -> Optional[str]:
    """Look up CAS-RN by normalized ingredient name."""
    norm = _normalize(preferred_term)
    if norm in name_index:
        return name_index[norm][0]
    return None


# ---------------------------------------------------------------------------
# Source 2: PubChem API  (CHEBI → CAS-RN)
# ---------------------------------------------------------------------------

def _get(url: str, retries: int = 3) -> Optional[dict]:
    """HTTP GET with simple retry logic."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def pubchem_chebi_to_cas(chebi_id: str) -> Optional[str]:
    """
    Query PubChem: CHEBI ID → PubChem CID → CAS-RN.

    Uses the PubChem xref endpoint to find compounds that cross-reference
    this ChEBI ID, then retrieves their CAS synonyms.
    """
    # Step 1: CHEBI xref → PubChem CID
    chebi_num = chebi_id.replace('CHEBI:', '')
    url = f"{PUBCHEM_BASE}/compound/xref/RegistryID/CHEBI:{chebi_num}/cids/JSON"
    data = _get(url)
    if not data:
        # Try searching by name as fallback
        return None

    cids = data.get('IdentifierList', {}).get('CID', [])
    if not cids:
        return None

    cid = cids[0]

    # Step 2: CID → CAS-RN (via synonyms endpoint, filter for CAS pattern)
    url2 = f"{PUBCHEM_BASE}/compound/cid/{cid}/synonyms/JSON"
    data2 = _get(url2)
    if not data2:
        return None

    synonyms = data2.get('InformationList', {}).get('Information', [{}])[0].get('Synonym', [])
    for syn in synonyms:
        if valid_cas(syn):
            return syn.strip()

    return None


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def enrich_mim_ingredients(
    mim_root: Path,
    culturebot_root: Path,
    dry_run: bool = False,
    max_queries: int = 0,
) -> None:
    """
    Enrich MIM ingredient YAML files with CAS-RN numbers.
    """
    ingredients_dir = mim_root / 'data' / 'ingredients'
    yaml_files = list(ingredients_dir.rglob('*.yaml'))
    print(f"Scanning {len(yaml_files)} MIM ingredient files...\n")

    # Load name-based index
    print("Loading CultureBotHT CAS reference data...")
    name_index = load_cas_name_index(culturebot_root)
    print()

    stats = {
        'already_has_cas': 0,
        'matched_by_name': 0,
        'matched_by_pubchem': 0,
        'no_match': 0,
        'api_queries': 0,
        'updated': 0,
    }

    timestamp = datetime.now().isoformat()

    for yaml_file in sorted(yaml_files):
        try:
            data = yaml.safe_load(yaml_file.read_text())
        except Exception as e:
            print(f"  [ERROR] {yaml_file.name}: {e}")
            continue

        if not data or not isinstance(data, dict):
            continue

        preferred_term = data.get('preferred_term', '').strip()
        if not preferred_term:
            continue

        identifier = data.get('identifier', '')
        chem_props = data.get('chemical_properties') or {}
        existing_cas = chem_props.get('cas_rn', '')

        # Skip if already has a valid CAS-RN
        if valid_cas(existing_cas):
            stats['already_has_cas'] += 1
            continue

        cas_found = None
        source = None

        # --- Strategy 1: name-based lookup from CultureBotHT CSV ---
        cas_found = lookup_by_name(preferred_term, name_index)
        if cas_found:
            source = 'CultureBotHT/compounds_to_cas.csv'
            stats['matched_by_name'] += 1

        # --- Strategy 2: PubChem API via CHEBI xref ---
        if not cas_found and identifier.startswith('CHEBI:'):
            if max_queries and stats['api_queries'] >= max_queries:
                stats['no_match'] += 1
                continue

            stats['api_queries'] += 1
            time.sleep(0.2)  # PubChem rate limit: 5 req/s
            cas_found = pubchem_chebi_to_cas(identifier)
            if cas_found:
                source = f'PubChem (via {identifier})'
                stats['matched_by_pubchem'] += 1

        if not cas_found:
            stats['no_match'] += 1
            continue

        # --- Apply ---
        if dry_run:
            print(f"  [DRY RUN] {preferred_term} ({identifier}) → CAS {cas_found}  [{source}]")
        else:
            # Build or update chemical_properties
            if 'chemical_properties' not in data or data['chemical_properties'] is None:
                data['chemical_properties'] = {}
            data['chemical_properties']['cas_rn'] = cas_found
            data['chemical_properties']['data_source'] = source
            data['chemical_properties']['retrieval_date'] = timestamp

            # Add curation history entry
            if 'curation_history' not in data:
                data['curation_history'] = []
            data['curation_history'].append({
                'timestamp': timestamp,
                'curator': 'enrich_mim_cas_rn_batch',
                'action': 'CAS_RN_ADDED',
                'changes': f'Added CAS-RN {cas_found} from {source}',
                'new_status': data.get('mapping_status', ''),
                'llm_assisted': False,
            })

            with open(yaml_file, 'w') as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            stats['updated'] += 1
            print(f"  [UPDATE] {preferred_term} → {cas_found}  [{source}]")

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Already had CAS-RN:     {stats['already_has_cas']}")
    print(f"Matched by name (CSV):  {stats['matched_by_name']}")
    print(f"Matched by PubChem API: {stats['matched_by_pubchem']}")
    print(f"PubChem API queries:    {stats['api_queries']}")
    print(f"No match found:         {stats['no_match']}")
    print(f"Files updated:          {stats['updated']}")

    if dry_run:
        print()
        print("DRY RUN — run without --dry-run to apply changes")
    else:
        total_matched = stats['matched_by_name'] + stats['matched_by_pubchem']
        print(f"\n✅ Added CAS-RN to {total_matched} MIM ingredients")


def main():
    parser = argparse.ArgumentParser(
        description='Enrich MIM ingredient files with CAS-RN numbers'
    )
    parser.add_argument(
        '--mim', type=Path, default=MIM_ROOT,
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--culturebot', type=Path, default=CULTUREBOT_ROOT,
        help='Path to CultureBotHT repository root'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Preview matches without writing files'
    )
    parser.add_argument(
        '--max-queries', type=int, default=0,
        help='Limit PubChem API queries (0 = unlimited)'
    )

    args = parser.parse_args()

    if not args.mim.exists():
        print(f"Error: MIM not found: {args.mim}")
        sys.exit(1)

    if args.dry_run:
        print("=" * 70)
        print("DRY RUN MODE")
        print("=" * 70)
        print()

    enrich_mim_ingredients(
        mim_root=args.mim,
        culturebot_root=args.culturebot,
        dry_run=args.dry_run,
        max_queries=args.max_queries,
    )


if __name__ == '__main__':
    main()
