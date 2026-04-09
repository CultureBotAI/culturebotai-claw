#!/usr/bin/env python3
"""
Match CultureMech media to KG-Microbe medium nodes by CHEBI ingredient sets.

For each CultureMech media record, collects CHEBI IDs from its ingredients,
then finds the exact matching medium in KG-Microbe (mediadive.medium:XXX)
by comparing CHEBI ingredient sets (concentrations ignored).

Populates the `kg_microbe_match` field in CultureMech YAML files.
"""

import csv
import yaml
import argparse
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, FrozenSet, Optional, Set


def build_kg_chebi_index(edges_file: Path) -> Dict[FrozenSet[str], list]:
    """
    Build index: frozenset(CHEBI IDs) -> list of mediadive.medium:XXX IDs.

    Graph traversal: medium -> solution -> CHEBI
    Returns sets with >= 1 CHEBI (empty sets excluded).
    """
    print(f"Building KG-Microbe CHEBI index from {edges_file}...")

    medium_solutions: Dict[str, Set[str]] = defaultdict(set)
    solution_chebis: Dict[str, Set[str]] = defaultdict(set)

    with open(edges_file) as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            subj = row['subject']
            pred = row['predicate']
            obj = row['object']
            if pred != 'biolink:has_part':
                continue
            if subj.startswith('mediadive.medium:') and obj.startswith('mediadive.solution:'):
                medium_solutions[subj].add(obj)
            elif subj.startswith('mediadive.solution:') and obj.startswith('CHEBI:'):
                solution_chebis[subj].add(obj)

    # Build CHEBI-set -> medium mapping
    chebi_set_to_mediums: Dict[FrozenSet[str], list] = defaultdict(list)
    for medium, solutions in medium_solutions.items():
        chebi_set = frozenset(
            chebi
            for sol in solutions
            for chebi in solution_chebis.get(sol, set())
        )
        if chebi_set:
            chebi_set_to_mediums[chebi_set].append(medium)

    print(f"  {len(medium_solutions)} KG-Microbe media")
    print(f"  {len(chebi_set_to_mediums)} unique CHEBI ingredient sets\n")
    return dict(chebi_set_to_mediums)


def extract_chebi_ids(data: dict) -> FrozenSet[str]:
    """Extract all CHEBI IDs from a CultureMech media record's ingredients."""
    chebi_ids = set()
    for ing in data.get('ingredients', []):
        term = ing.get('term', {}) or {}
        tid = term.get('id', '') or ''
        if tid.startswith('CHEBI:'):
            chebi_ids.add(tid)
    return frozenset(chebi_ids)


def find_kg_match(chebi_ids: FrozenSet[str], index: Dict) -> Optional[str]:
    """
    Find exact KG-Microbe medium match for a CHEBI ingredient set.

    Returns the first matching mediadive.medium:XXX ID, or None.
    When multiple media share the same CHEBI set, returns the lowest numeric ID.
    """
    if not chebi_ids:
        return None
    mediums = index.get(chebi_ids)
    if not mediums:
        return None
    # Sort: numeric IDs first (mediadive.medium:1, :2, ...), then alphanumeric
    def sort_key(m):
        parts = m.split(':')
        try:
            return (0, int(parts[-1]))
        except ValueError:
            return (1, parts[-1])
    return sorted(mediums, key=sort_key)[0]


def process_media_files(culturemech_root: Path, index: Dict, dry_run: bool = False) -> dict:
    """
    Scan all CultureMech YAML files, find matches, populate kg_microbe_match.

    Returns statistics dict.
    """
    normalized_yaml = culturemech_root / 'data' / 'normalized_yaml'
    stats = {
        'total_files': 0,
        'with_chebi': 0,
        'matched': 0,
        'already_matched': 0,
        'no_chebi': 0,
        'no_match': 0,
        'updated': 0,
    }

    yaml_files = list(normalized_yaml.rglob('*.yaml'))
    print(f"Scanning {len(yaml_files)} CultureMech YAML files...")

    for yaml_file in sorted(yaml_files):
        try:
            text = yaml_file.read_text()
            data = yaml.safe_load(text)
            if not data or not isinstance(data, dict):
                continue

            stats['total_files'] += 1
            chebi_ids = extract_chebi_ids(data)

            if not chebi_ids:
                stats['no_chebi'] += 1
                continue

            stats['with_chebi'] += 1

            # Check if already populated
            existing = data.get('kg_microbe_match')
            if existing:
                stats['already_matched'] += 1
                continue

            kg_id = find_kg_match(chebi_ids, index)
            if not kg_id:
                stats['no_match'] += 1
                continue

            stats['matched'] += 1

            if dry_run:
                cm_id = data.get('id', yaml_file.stem)
                print(f"  [DRY RUN] {cm_id} ({yaml_file.stem}) → {kg_id}  ({len(chebi_ids)} CHEBIs)")
            else:
                # Insert kg_microbe_match after the 'id' field (or at beginning)
                # Rebuild the YAML preserving order by inserting field
                data['kg_microbe_match'] = kg_id
                with open(yaml_file, 'w') as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                stats['updated'] += 1
                cm_id = data.get('id', yaml_file.stem)
                print(f"  [UPDATE] {cm_id} → {kg_id}  ({len(chebi_ids)} CHEBIs)")

        except Exception as e:
            print(f"  [ERROR] {yaml_file}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Match CultureMech media to KG-Microbe medium nodes by CHEBI ingredient sets'
    )
    parser.add_argument(
        '--culturemech',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
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

    edges_file = args.kg_microbe / 'data/transformed_last9/mediadive/edges.tsv'

    if not args.culturemech.exists():
        print(f"Error: CultureMech not found: {args.culturemech}")
        sys.exit(1)
    if not edges_file.exists():
        print(f"Error: KG-Microbe edges file not found: {edges_file}")
        sys.exit(1)

    if args.dry_run:
        print("=" * 70)
        print("DRY RUN MODE - No files will be modified")
        print("=" * 70)
        print()

    # Build index
    index = build_kg_chebi_index(edges_file)

    # Process CultureMech files
    stats = process_media_files(args.culturemech, index, dry_run=args.dry_run)

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total media files scanned:  {stats['total_files']}")
    print(f"With CHEBI ingredients:     {stats['with_chebi']}")
    print(f"Already had kg_microbe_match: {stats['already_matched']}")
    print(f"New matches found:          {stats['matched']}")
    print(f"  - Files updated:          {stats['updated']}")
    print(f"No CHEBI ingredients:       {stats['no_chebi']}")
    print(f"No KG-Microbe match:        {stats['no_match']}")

    if args.dry_run:
        print()
        print("=" * 70)
        print("DRY RUN COMPLETE - Run without --dry-run to apply changes")
        print("=" * 70)
    else:
        print()
        print("✅ CultureMech media matched to KG-Microbe nodes")


if __name__ == '__main__':
    main()
