#!/usr/bin/env python3
"""
Match MediaIngredientMech ingredients to KG-Microbe nodes.

For each MIM ingredient with a CHEBI ID (identifier field), checks whether
that CHEBI ID appears as a node in the KG-Microbe mediadive graph.

Populates the `kg_microbe_node_id` field in MIM ingredient YAML files.

Node ID format: CHEBI:XXXXX (the ingredient's own CHEBI ID, if present in KG).
"""

import csv
import yaml
import argparse
import sys
from pathlib import Path
from typing import Set, Optional


def load_kg_chebi_nodes(nodes_file: Path) -> Set[str]:
    """
    Load all CHEBI node IDs from KG-Microbe mediadive nodes.tsv.

    These are CHEBI IDs that appear as named nodes (i.e., are used as
    ingredient identifiers in media solutions in the KG).
    """
    print(f"Loading KG-Microbe CHEBI nodes from {nodes_file}...")
    chebi_nodes: Set[str] = set()

    with open(nodes_file) as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            node_id = row['id']
            if node_id.startswith('CHEBI:'):
                chebi_nodes.add(node_id)

    print(f"  Found {len(chebi_nodes)} CHEBI nodes in KG-Microbe\n")
    return chebi_nodes


def process_mim_ingredients(mim_root: Path, chebi_nodes: Set[str], dry_run: bool = False) -> dict:
    """
    Scan MIM ingredient YAML files, find CHEBI nodes in KG, populate kg_microbe_node_id.
    """
    ingredients_dir = mim_root / 'data' / 'ingredients'
    stats = {
        'total_files': 0,
        'with_chebi_id': 0,
        'in_kg': 0,
        'already_matched': 0,
        'not_in_kg': 0,
        'updated': 0,
    }

    yaml_files = []
    for subdir in ['mapped', 'unmapped']:
        subdir_path = ingredients_dir / subdir
        if subdir_path.exists():
            yaml_files.extend(subdir_path.glob('*.yaml'))

    print(f"Scanning {len(yaml_files)} MIM ingredient files...")

    for yaml_file in sorted(yaml_files):
        try:
            data = yaml.safe_load(yaml_file.read_text())
            if not data or not isinstance(data, dict):
                continue

            stats['total_files'] += 1

            # Get the CHEBI ID from identifier field
            identifier = data.get('identifier', '') or ''
            if not identifier.startswith('CHEBI:'):
                continue

            stats['with_chebi_id'] += 1

            # Check if already populated
            if data.get('kg_microbe_node_id'):
                stats['already_matched'] += 1
                continue

            # Check if this CHEBI is in KG-Microbe
            if identifier not in chebi_nodes:
                stats['not_in_kg'] += 1
                continue

            stats['in_kg'] += 1
            preferred_term = data.get('preferred_term', yaml_file.stem)

            if dry_run:
                print(f"  [DRY RUN] {preferred_term} ({identifier}) → kg_microbe_node_id: {identifier}")
            else:
                data['kg_microbe_node_id'] = identifier
                with open(yaml_file, 'w') as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                stats['updated'] += 1
                print(f"  [UPDATE] {preferred_term} → {identifier}")

        except Exception as e:
            print(f"  [ERROR] {yaml_file}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Match MIM ingredients to KG-Microbe CHEBI nodes'
    )
    parser.add_argument(
        '--mim',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--kg-microbe',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe',
        help='Path to kg-microbe repository'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show matches without writing to files'
    )

    args = parser.parse_args()

    nodes_file = args.kg_microbe / 'data/transformed_last9/mediadive/nodes.tsv'

    if not args.mim.exists():
        print(f"Error: MediaIngredientMech not found: {args.mim}")
        sys.exit(1)
    if not nodes_file.exists():
        print(f"Error: KG-Microbe nodes file not found: {nodes_file}")
        sys.exit(1)

    if args.dry_run:
        print("=" * 70)
        print("DRY RUN MODE - No files will be modified")
        print("=" * 70)
        print()

    # Load KG CHEBI nodes
    chebi_nodes = load_kg_chebi_nodes(nodes_file)

    # Process MIM ingredients
    stats = process_mim_ingredients(args.mim, chebi_nodes, dry_run=args.dry_run)

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total ingredient files:       {stats['total_files']}")
    print(f"With CHEBI identifier:        {stats['with_chebi_id']}")
    print(f"Already had kg_microbe_node_id: {stats['already_matched']}")
    print(f"Found in KG-Microbe:          {stats['in_kg']}")
    print(f"  - Files updated:            {stats['updated']}")
    print(f"Not in KG-Microbe:            {stats['not_in_kg']}")

    if args.dry_run:
        print()
        print("=" * 70)
        print("DRY RUN COMPLETE - Run without --dry-run to apply changes")
        print("=" * 70)
    else:
        print()
        print("✅ MIM ingredients matched to KG-Microbe nodes")


if __name__ == '__main__':
    main()
