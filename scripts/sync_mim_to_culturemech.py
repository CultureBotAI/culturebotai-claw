#!/usr/bin/env python3
"""
Sync MIM (MediaIngredientMech) CHEBI mappings into CultureMech ingredient term.id fields.

For each CultureMech ingredient that lacks a CHEBI term.id, looks up the ingredient
name in the unified ingredient mapping and backfills the CHEBI ID.

Rules:
  - Ingredients with no term.id → set term.id to CHEBI from MIM
  - Ingredients with FOODON/other term.id → add chebi_term.id (preserves FOODON)
  - Ingredients already with CHEBI term.id → skip

Usage:
    python scripts/sync_mim_to_culturemech.py [--dry-run]
"""

import re
import sys
import csv
import yaml
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plugins.ingredient_name_normalizer import canonicalize_hydrate


CULTUREMECH_ROOT = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech'
UNIFIED_MAPPING = Path('workspace/unified_ingredient_mapping.tsv')


def _normalize(s: str) -> str:
    return canonicalize_hydrate(s)


def load_mim_chebi_index(mapping_file: Path) -> dict:
    """
    Build normalized_name → chebi_id from the unified ingredient mapping TSV.
    Only includes rows where chebi_id starts with CHEBI: (authoritative mappings).
    """
    index = {}
    with open(mapping_file) as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            chebi_id = row.get('chebi_id', '').strip()
            name = row.get('ingredient_name', '').strip()
            if chebi_id.startswith('CHEBI:') and name:
                index[_normalize(name)] = chebi_id
    print(f"  Loaded {len(index)} name→CHEBI entries from unified mapping")
    return index


def process_file(yaml_file: Path, chebi_index: dict, dry_run: bool, stats: dict) -> None:
    """Process one CultureMech YAML file, upgrading ingredient term.ids where possible."""
    try:
        data = yaml.safe_load(yaml_file.read_text())
    except Exception as e:
        print(f"  [ERROR] {yaml_file.name}: {e}")
        return

    if not data or not isinstance(data, dict):
        return

    ingredients = data.get('ingredients', []) or []
    if not ingredients:
        return

    changed = False
    for ing in ingredients:
        if not isinstance(ing, dict):
            continue

        name = ing.get('preferred_term', '').strip()
        if not name:
            continue

        term = ing.get('term') or {}
        term_id = term.get('id', '') if isinstance(term, dict) else ''

        # Already has CHEBI → skip
        if term_id.startswith('CHEBI:'):
            stats['already_chebi'] += 1
            continue

        # Look up in MIM index
        chebi_id = chebi_index.get(_normalize(name))
        if not chebi_id:
            stats['no_match'] += 1
            continue

        if not term_id:
            # No term.id at all → set it
            if not dry_run:
                ing['term'] = {'id': chebi_id, 'label': ''}
            stats['added_term_id'] += 1
            changed = True
            if dry_run:
                print(f"  [DRY RUN] {yaml_file.stem}: {name} → term.id={chebi_id}")
            else:
                print(f"  [UPDATE]  {yaml_file.stem}: {name} → term.id={chebi_id}")
        else:
            # Has FOODON/other → add chebi_term.id as enriched field (preserve original)
            existing_chebi_term = ing.get('chebi_term') or {}
            if isinstance(existing_chebi_term, dict) and existing_chebi_term.get('id', '').startswith('CHEBI:'):
                stats['already_chebi'] += 1
                continue
            if not dry_run:
                ing['chebi_term'] = {
                    'id': chebi_id,
                    'label': '',
                    'confidence': 0.85,
                    'match_type': 'mim_sync',
                }
            stats['added_chebi_term'] += 1
            changed = True
            if dry_run:
                print(f"  [DRY RUN] {yaml_file.stem}: {name} ({term_id}) → chebi_term.id={chebi_id}")
            else:
                print(f"  [UPDATE]  {yaml_file.stem}: {name} ({term_id}) → chebi_term.id={chebi_id}")

    if changed and not dry_run:
        with open(yaml_file, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        stats['files_updated'] += 1


def main():
    parser = argparse.ArgumentParser(
        description='Sync MIM CHEBI mappings into CultureMech ingredient term.id fields'
    )
    parser.add_argument('--culturemech', type=Path, default=CULTUREMECH_ROOT)
    parser.add_argument('--mapping', type=Path, default=UNIFIED_MAPPING,
                        help='Path to unified_ingredient_mapping.tsv')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not args.culturemech.exists():
        print(f"Error: CultureMech not found: {args.culturemech}")
        sys.exit(1)
    if not args.mapping.exists():
        print(f"Error: Mapping file not found: {args.mapping}")
        print("Run: python scripts/build_unified_ingredient_mapping.py first")
        sys.exit(1)

    if args.dry_run:
        print("=" * 60)
        print("DRY RUN MODE")
        print("=" * 60)
        print()

    print("Loading MIM CHEBI index...")
    chebi_index = load_mim_chebi_index(args.mapping)
    print()

    normalized_yaml = args.culturemech / 'data' / 'normalized_yaml'
    yaml_files = list(normalized_yaml.rglob('*.yaml'))
    print(f"Processing {len(yaml_files)} CultureMech YAML files...\n")

    stats = {
        'already_chebi': 0,
        'added_term_id': 0,
        'added_chebi_term': 0,
        'no_match': 0,
        'files_updated': 0,
    }

    for yaml_file in sorted(yaml_files):
        process_file(yaml_file, chebi_index, args.dry_run, stats)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Already had CHEBI:         {stats['already_chebi']}")
    print(f"Added term.id (from none):  {stats['added_term_id']}")
    print(f"Added chebi_term.id:        {stats['added_chebi_term']}")
    print(f"No MIM match:               {stats['no_match']}")
    print(f"Files updated:              {stats['files_updated']}")

    if args.dry_run:
        print()
        print("DRY RUN — run without --dry-run to apply")
    else:
        total = stats['added_term_id'] + stats['added_chebi_term']
        print(f"\n✅ Synced {total} ingredient CHEBI IDs from MIM into CultureMech")


if __name__ == '__main__':
    main()
