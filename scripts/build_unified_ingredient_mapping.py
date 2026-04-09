#!/usr/bin/env python3
"""
Build a unified ingredient mapping file across CultureMech, MediaIngredientMech,
and CommunityMech.

Outputs a TSV where each row is a unique ingredient name observed in CultureMech,
annotated with all available identifiers from MIM:
  - MIM record ID (identifier field)
  - CHEBI ID
  - CAS-RN
  - KG-Microbe node ID
  - mapping status
  - occurrence count in CultureMech
  - source ontology term ID (as used in CultureMech media files)

Usage:
    python scripts/build_unified_ingredient_mapping.py [--output PATH] [--format tsv|yaml]
"""

import csv
import sys
import yaml
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, Optional


CULTUREMECH_ROOT = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech'
MIM_ROOT = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'
DEFAULT_OUTPUT = Path('workspace/unified_ingredient_mapping.tsv')


# ---------------------------------------------------------------------------
# Step 1: Build MIM index (preferred_term + all synonyms → record)
# ---------------------------------------------------------------------------

def load_mim_index(mim_root: Path) -> tuple[dict, dict]:
    """
    Returns:
        name_index: normalized_name → MIM record dict
        chebi_index: chebi_id → MIM record dict
    """
    ingredients_dir = mim_root / 'data' / 'ingredients'
    name_index: Dict[str, dict] = {}
    chebi_index: Dict[str, dict] = {}

    print("Loading MIM ingredient records...")
    count = 0
    for yaml_file in sorted(ingredients_dir.rglob('*.yaml')):
        try:
            data = yaml.safe_load(yaml_file.read_text())
        except Exception:
            continue
        if not data or not isinstance(data, dict):
            continue

        preferred = data.get('preferred_term', '').strip()
        identifier = data.get('identifier', '').strip()
        if not preferred:
            continue

        record = {
            'mim_id': identifier,
            'preferred_term': preferred,
            'chebi_id': identifier if identifier.startswith('CHEBI:') else '',
            'cas_rn': (data.get('chemical_properties') or {}).get('cas_rn', ''),
            'kg_microbe_node_id': data.get('kg_microbe_node_id', ''),
            'mapping_status': data.get('mapping_status', ''),
            'ontology_source': (data.get('ontology_mapping') or {}).get('ontology_source', ''),
        }

        # Index by normalized preferred_term
        norm = _normalize(preferred)
        if norm and norm not in name_index:
            name_index[norm] = record

        # Index synonyms
        for syn in data.get('synonyms', []) or []:
            syn_text = ''
            if isinstance(syn, dict):
                syn_text = syn.get('synonym_text', '').strip()
            elif isinstance(syn, str):
                syn_text = syn.strip()
            if syn_text:
                norm_syn = _normalize(syn_text)
                if norm_syn and norm_syn not in name_index:
                    name_index[norm_syn] = record

        # Index by CHEBI
        if record['chebi_id']:
            chebi_index[record['chebi_id']] = record

        count += 1

    print(f"  {count} MIM records → {len(name_index)} name entries, {len(chebi_index)} CHEBI entries\n")
    return name_index, chebi_index


def _normalize(s: str) -> str:
    """Normalize for matching: lowercase, collapse whitespace."""
    import re
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    return s


# ---------------------------------------------------------------------------
# Step 2: Scan CultureMech for all ingredient occurrences
# ---------------------------------------------------------------------------

def scan_culturemech(culturemech_root: Path) -> dict:
    """
    Returns: name → {'count': N, 'term_id': str, 'media': [list]}
    """
    normalized_yaml = culturemech_root / 'data' / 'normalized_yaml'
    occurrences: Dict[str, dict] = {}

    print("Scanning CultureMech ingredient occurrences...")
    file_count = 0
    for yaml_file in sorted(normalized_yaml.rglob('*.yaml')):
        try:
            data = yaml.safe_load(yaml_file.read_text())
        except Exception:
            continue
        if not data or not isinstance(data, dict):
            continue

        media_id = data.get('id', yaml_file.stem)
        file_count += 1

        for ing in data.get('ingredients', []) or []:
            name = ing.get('preferred_term', '').strip()
            if not name:
                continue

            term = ing.get('term') or {}
            term_id = term.get('id', '') if isinstance(term, dict) else ''

            if name not in occurrences:
                occurrences[name] = {
                    'count': 0,
                    'term_id': term_id,
                    'example_media': [],
                }

            entry = occurrences[name]
            entry['count'] += 1
            # Prefer entries that have a term_id
            if term_id and not entry['term_id']:
                entry['term_id'] = term_id
            if len(entry['example_media']) < 3:
                entry['example_media'].append(media_id)

    print(f"  {file_count} media files → {len(occurrences)} unique ingredient names\n")
    return occurrences


# ---------------------------------------------------------------------------
# Step 3: Join and resolve
# ---------------------------------------------------------------------------

def resolve_mim_record(
    name: str,
    term_id: str,
    name_index: dict,
    chebi_index: dict,
) -> Optional[dict]:
    """
    Find best MIM record for this ingredient name + optional term_id.
    Priority: term_id CHEBI lookup > name lookup.
    """
    # 1. Term ID from CultureMech (CHEBI or FOODON)
    if term_id and term_id.startswith('CHEBI:') and term_id in chebi_index:
        return chebi_index[term_id]

    # 2. Name-based lookup
    norm = _normalize(name)
    if norm in name_index:
        return name_index[norm]

    return None


def build_unified_rows(
    occurrences: dict,
    name_index: dict,
    chebi_index: dict,
) -> list:
    """
    Join CultureMech occurrences with MIM records.
    Returns list of row dicts, sorted by occurrence count descending.
    """
    rows = []
    matched = unmatched = 0

    for name, info in occurrences.items():
        term_id = info['term_id']
        mim = resolve_mim_record(name, term_id, name_index, chebi_index)

        row = {
            'ingredient_name': name,
            'culturemech_term_id': term_id,
            'occurrence_count': info['count'],
            'mim_id': '',
            'chebi_id': '',
            'cas_rn': '',
            'kg_microbe_node_id': '',
            'mapping_status': 'UNMATCHED_IN_MIM',
            'example_media': '; '.join(info['example_media']),
        }

        if mim:
            row['mim_id'] = mim['mim_id']
            row['chebi_id'] = mim['chebi_id'] or term_id if term_id.startswith('CHEBI:') else mim['chebi_id']
            row['cas_rn'] = mim['cas_rn']
            row['kg_microbe_node_id'] = mim['kg_microbe_node_id']
            row['mapping_status'] = mim['mapping_status'] or 'MATCHED'
            matched += 1
        else:
            # Still record the CultureMech term_id even without MIM match
            if term_id:
                row['chebi_id'] = term_id if term_id.startswith('CHEBI:') else ''
                row['mapping_status'] = 'HAS_TERM_ID_NO_MIM'
            unmatched += 1

        rows.append(row)

    rows.sort(key=lambda r: -r['occurrence_count'])

    print(f"Resolved: {matched} matched to MIM, {unmatched} not in MIM")
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

COLUMNS = [
    'ingredient_name',
    'culturemech_term_id',
    'occurrence_count',
    'mim_id',
    'chebi_id',
    'cas_rn',
    'kg_microbe_node_id',
    'mapping_status',
    'example_media',
]


def write_tsv(rows: list, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✅ TSV written to {output}  ({len(rows)} rows)")


def write_yaml_summary(rows: list, output: Path) -> None:
    """Write a YAML summary grouped by mapping status."""
    yaml_out = output.with_suffix('.yaml')
    from collections import Counter
    status_counts = Counter(r['mapping_status'] for r in rows)
    summary = {
        'total_unique_ingredients': len(rows),
        'status_breakdown': dict(status_counts),
        'fully_mapped': [
            {
                'name': r['ingredient_name'],
                'chebi_id': r['chebi_id'],
                'cas_rn': r['cas_rn'],
                'kg_microbe_node_id': r['kg_microbe_node_id'],
                'count': r['occurrence_count'],
            }
            for r in rows
            if r['chebi_id'] and r['cas_rn'] and r['kg_microbe_node_id']
        ][:50],  # top 50 fully mapped
    }
    with open(yaml_out, 'w') as f:
        yaml.dump(summary, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"✅ YAML summary written to {yaml_out}")


def print_coverage_report(rows: list) -> None:
    total = len(rows)
    has_chebi = sum(1 for r in rows if r['chebi_id'])
    has_cas = sum(1 for r in rows if r['cas_rn'])
    has_kg = sum(1 for r in rows if r['kg_microbe_node_id'])
    has_mim = sum(1 for r in rows if r['mim_id'])
    fully_mapped = sum(1 for r in rows if r['chebi_id'] and r['cas_rn'])

    print()
    print("=" * 60)
    print("UNIFIED MAPPING COVERAGE REPORT")
    print("=" * 60)
    print(f"Total unique ingredient names:  {total}")
    print(f"Matched to MIM record:          {has_mim}  ({100*has_mim//total}%)")
    print(f"Have CHEBI ID:                  {has_chebi}  ({100*has_chebi//total}%)")
    print(f"Have CAS-RN:                    {has_cas}  ({100*has_cas//total}%)")
    print(f"Have KG-Microbe node ID:        {has_kg}  ({100*has_kg//total}%)")
    print(f"Fully mapped (CHEBI + CAS):     {fully_mapped}  ({100*fully_mapped//total}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Build unified ingredient mapping across CultureMech, MIM, and CommunityMech'
    )
    parser.add_argument('--culturemech', type=Path, default=CULTUREMECH_ROOT)
    parser.add_argument('--mim', type=Path, default=MIM_ROOT)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--format', choices=['tsv', 'yaml', 'both'], default='both',
                        help='Output format (default: both TSV and YAML summary)')

    args = parser.parse_args()

    if not args.culturemech.exists():
        print(f"Error: CultureMech not found: {args.culturemech}")
        sys.exit(1)
    if not args.mim.exists():
        print(f"Error: MIM not found: {args.mim}")
        sys.exit(1)

    print("=" * 60)
    print("BUILDING UNIFIED INGREDIENT MAPPING")
    print("=" * 60)
    print()

    # Load MIM index
    name_index, chebi_index = load_mim_index(args.mim)

    # Scan CultureMech
    occurrences = scan_culturemech(args.culturemech)

    # Join
    rows = build_unified_rows(occurrences, name_index, chebi_index)

    # Print coverage report
    print_coverage_report(rows)

    # Write output
    print()
    if args.format in ('tsv', 'both'):
        write_tsv(rows, args.output)
    if args.format in ('yaml', 'both'):
        write_yaml_summary(rows, args.output)


if __name__ == '__main__':
    main()
