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

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
CULTUREMECH_ROOT = Path(
    os.environ.get("CULTUREMECH_ROOT", REPO_ROOT.parent / "CultureMech")
)
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)
sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plugins.ingredient_name_normalizer import canonicalize_hydrate  # noqa: E402

DEFAULT_OUTPUT = Path('workspace/unified_ingredient_mapping.tsv')
NON_PUBLISHABLE_MIM_SYNONYM_TYPES = {"REJECTED_LABEL"}
NON_IDENTITY_MIM_STATUSES = {"UNMAPPED", "AMBIGUOUS", "REJECTED"}
MIM_MERGE_ACTIONS = {"MERGED_INTO", "MERGED_INTO_EXISTING", "MERGED"}
STRUCTURED_MIM_SYNONYM_MARKERS = (
    'cross-references:',
    'role:',
    'properties:',
    'synonym source:',
)
REJECTIONS_PATH = Path('mappings/unified_mapping_rejections.tsv')


def load_mapping_rejections(mim_root: Path, name_index: dict) -> dict:
    """Read reviewed source-ID rejections; never infer them from prefix alone.

    The ledger preserves the rejected source ID and its curation reason outside
    the published identity columns. Older MIM checkouts may lack the ledger.
    A present but malformed or stale ledger must fail rather than silently
    republish the rejected ID.
    """
    path = mim_root / REJECTIONS_PATH
    if not path.exists():
        return {}
    rejections = {}
    with path.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle, delimiter='\t')
        columns = ['ingredient_name', 'rejected_id', 'mim_id', 'reason']
        if reader.fieldnames != columns:
            raise ValueError(f'{path}: expected columns {columns}')
        for line, row in enumerate(reader, 2):
            if None in row or any(not (row.get(c) or '').strip() for c in columns):
                raise ValueError(f'{path}:{line}: incomplete rejection')
            row = {k: v.strip() for k, v in row.items()}
            key = (row['mim_id'], row['rejected_id'])
            if key in rejections or ':' not in row['rejected_id']:
                raise ValueError(f'{path}:{line}: duplicate or invalid rejection')
            mim = name_index.get(_normalize(row['ingredient_name']))
            if (not mim or mim['mim_id'] != row['mim_id']
                    or mim['mapping_status'] not in ('MAPPED', 'REJECTED')
                    or row['rejected_id'] == row['mim_id']):
                raise ValueError(f'{path}:{line}: rejection disagrees with MIM identity')
            if row['rejected_id'] in (mim['chebi_id'], mim['kg_microbe_node_id']):
                raise ValueError(f'{path}:{line}: MIM still publishes the rejected ID')
            rejections[key] = row['mim_id']
    return rejections


def _synonym_text(syn: object) -> str:
    if isinstance(syn, dict):
        return (syn.get('synonym_text') or '').strip()
    if isinstance(syn, str):
        return syn.strip()
    return ''


def _is_publishable_mim_synonym(syn: object) -> bool:
    if (
        isinstance(syn, dict)
        and (syn.get('synonym_type') or '').strip().upper()
        in NON_PUBLISHABLE_MIM_SYNONYM_TYPES
    ):
        return False
    low = _synonym_text(syn).lower()
    return bool(low) and not any(k in low for k in STRUCTURED_MIM_SYNONYM_MARKERS)


# ---------------------------------------------------------------------------
# Step 1: Build MIM index (preferred_term + all synonyms → record)
# ---------------------------------------------------------------------------

def _is_mim_nonidentity(record: dict) -> bool:
    return (
        record.get('mapping_status') in NON_IDENTITY_MIM_STATUSES
        or (record.get('mim_id') or '').startswith('UNMAPPED')
    )


def _mim_merge_target(data: dict) -> str:
    representative = (data.get('representative') or '').strip()
    if representative:
        return representative
    # A reused ID alone does not distinguish a legacy merge from an invalid
    # record. Legacy merges also record their disposition in curation history.
    for event in reversed(data.get('curation_history', []) or []):
        if event.get('action') in MIM_MERGE_ACTIONS:
            return (data.get('identifier') or '').strip()
        if event.get('new_status') == 'REJECTED':
            return ''
    return ''


def _identity_ontology_mapping(data: dict) -> dict:
    """Only equivalence mappings supply identity aliases or alternate labels.

    Missing quality preserves compatibility with older records. Explicit
    broader, narrower, and approximate mappings cannot identify one child.
    """
    mapping = data.get('ontology_mapping') or {}
    quality = (mapping.get('mapping_quality') or '').strip().upper()
    return mapping if quality in ('', 'EXACT_MATCH', 'SYNONYM_MATCH', 'LEXICAL_MATCH') else {}


def _mim_record_files(ingredients_dir: Path) -> list:
    """Read direct mapped/unmapped YAML, excluding backups and other directories.

    MIM saves gitignored backups beside its records. A recursive walk can load
    the stale copy first, making exports depend on the builder's local backups
    (MediaIngredientMech#698, claw#463).
    """
    if not ingredients_dir.is_dir():
        return []
    files = []
    for category in ('mapped', 'unmapped'):
        files.extend(sorted((ingredients_dir / category).glob('*.yaml')))
    return files


def load_mim_index(mim_root: Path) -> tuple[dict, dict, dict]:
    """
    Load only direct mapped/unmapped records. Retired labels resolve through
    live representatives; retired IDs and nested backups never supply identities.

    Returns:
        name_index: normalized_name → MIM record dict
        chebi_index: chebi_id → MIM record dict
        ontology_index: any ontology ID (CHEBI/FOODON/ENVO) → MIM record dict
            Enables lookup when CultureMech has a FOODON term.id and MIM has
            the same ingredient under a CHEBI ID.
    """
    ingredients_dir = mim_root / 'data' / 'ingredients'
    name_index: Dict[str, dict] = {}
    chebi_index: Dict[str, dict] = {}
    ontology_index: Dict[str, dict] = {}
    live_by_id: dict[str, tuple[dict, set[str]]] = {}
    redirects: dict[str, set[str]] = {}
    retired: list[dict] = []
    name_records: list[tuple[dict, dict, set[str]]] = []

    print("Loading MIM ingredient records...")
    count = 0
    yaml_files = _mim_record_files(ingredients_dir)
    for yaml_file in yaml_files:
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
        count += 1

        if data.get('mapping_status') == 'REJECTED':
            retired.append(data)
            target = _mim_merge_target(data)
            if identifier and target:
                redirects.setdefault(identifier, set()).add(target)
            continue

        nonidentity = (
            data.get('mapping_status') in NON_IDENTITY_MIM_STATUSES
            or identifier.startswith('UNMAPPED')
        )

        ont_mapping = _identity_ontology_mapping(data)
        ontology_id = ont_mapping.get('ontology_id', '').strip()
        ontology_label = ont_mapping.get('ontology_label', '').strip()

        # Collect distinct synonym surface forms: preferred_term, ontology_label,
        # and every publishable synonym_text.
        syn_set: set[str] = set()
        if not nonidentity and ontology_label and ontology_label.lower() != preferred.lower():
            syn_set.add(ontology_label)
        for syn in data.get('synonyms', []) or []:
            if not _is_publishable_mim_synonym(syn):
                continue
            txt = _synonym_text(syn)
            if txt.lower() == preferred.lower():
                continue
            syn_set.add(txt)

        record = {
            # Preserve local UNMAPPED identifiers, but never publish a retained
            # ontology ID as the identity of an explicitly unresolved record.
            'mim_id': identifier if not nonidentity or identifier.startswith('UNMAPPED') else '',
            'preferred_term': preferred,
            'chebi_id': identifier if not nonidentity and identifier.startswith('CHEBI:') else '',
            'cas_rn': '' if nonidentity else (data.get('chemical_properties') or {}).get('cas_rn', ''),
            'kg_microbe_node_id': '' if nonidentity else data.get('kg_microbe_node_id', ''),
            'mapping_status': data.get('mapping_status', ''),
            'synonyms': sorted(syn_set),
        }
        rejected_names = {
            _normalize(_synonym_text(syn))
            for syn in data.get('synonyms', []) or []
            if isinstance(syn, dict)
            and (syn.get('synonym_type') or '').strip().upper()
            in NON_PUBLISHABLE_MIM_SYNONYM_TYPES
        }
        name_records.append((data, record, rejected_names))
        if identifier:
            live_by_id.setdefault(identifier, (record, rejected_names))

        # An unresolved record may retain a parent ontology annotation, which
        # is not an identity and must not answer lookups for that ontology ID.
        if nonidentity:
            continue
        if record['chebi_id']:
            chebi_index.setdefault(record['chebi_id'], record)
        if ontology_id:
            ontology_index.setdefault(ontology_id, record)
        if identifier:
            ontology_index.setdefault(identifier, record)

    # New merges point at `representative`; documented legacy merges carry
    # the winner's identifier. Resolve only to live records. Missing, cyclic,
    # conflicting, or non-merge rejections remain identity-free refusals so
    # the caller cannot reintroduce a retired ID through CultureMech fallback.
    for data in retired:
        target = _mim_merge_target(data)
        resolved = None
        seen: set[str] = set()
        while target and target not in seen:
            if target in live_by_id:
                resolved = live_by_id[target]
                break
            seen.add(target)
            candidates = redirects.get(target, set())
            if len(candidates) != 1:
                break
            target = next(iter(candidates))

        if resolved is None:
            record = {
                'mim_id': '', 'preferred_term': data['preferred_term'],
                'chebi_id': '', 'cas_rn': '', 'kg_microbe_node_id': '',
                'mapping_status': 'REJECTED', 'synonyms': [],
            }
            rejected_names = set()
        else:
            record, rejected_names = resolved
            old_id = (data.get('identifier') or '').strip()
            if (not _is_mim_nonidentity(record) and old_id
                    and old_id != record['mim_id'] and not old_id.startswith('UNMAPPED')):
                record.setdefault('_retired_source_ids', set()).add(old_id)
        name_records.append((data, record, rejected_names))

    # Every active label sharing the representative identity inherits its
    # retired source IDs, including labels loaded as separate live records.
    for _, record, _ in name_records:
        canonical = live_by_id.get(record['mim_id'])
        if canonical and '_retired_source_ids' in canonical[0]:
            record['_retired_source_ids'] = canonical[0]['_retired_source_ids']

    # Active names come first, followed by aliases of resolved tombstones.
    # Explicit nonidentities must survive competing synonyms, and a retired
    # alias cannot undo a REJECTED_LABEL decision on its representative.
    for data, record, rejected_names in name_records:
        names = [data['preferred_term']]
        names.extend(
            _synonym_text(syn) for syn in data.get('synonyms', []) or []
            if _is_publishable_mim_synonym(syn)
        )
        for name in names:
            norm = _normalize(name)
            if not norm or norm in rejected_names:
                continue
            prior = name_index.get(norm)
            if prior is None or (_is_mim_nonidentity(record) and not _is_mim_nonidentity(prior)):
                name_index[norm] = record

    # Lookup exclusions must also hold in exported synonym columns, or a
    # consumer could recreate a refused identity from another ingredient's row.
    for _, record, rejected_names in name_records:
        record['synonyms'] = [
            synonym for synonym in record['synonyms']
            if _normalize(synonym) not in rejected_names
            and (
                _is_mim_nonidentity(record)
                or not _is_mim_nonidentity(name_index.get(_normalize(synonym), {}))
            )
        ]

    print(f"  {count} MIM records → {len(name_index)} name entries, "
          f"{len(chebi_index)} CHEBI, {len(ontology_index)} ontology IDs\n")
    return name_index, chebi_index, ontology_index


def _normalize(s: str) -> str:
    """Normalize for matching: lowercase, collapse whitespace, canonicalize
    hydrate-notation separators. See plugins.ingredient_name_normalizer."""
    return canonicalize_hydrate(s)


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
    ontology_index: dict,
) -> Optional[dict]:
    """
    Find best MIM record for this ingredient name + optional term_id.

    Priority:
      0. Explicit MIM nonidentity/refusal → no identity
      1. CultureMech CHEBI term.id → direct CHEBI index lookup
      2. Any CultureMech term.id (FOODON/ENVO) → ontology index lookup
      3. Name/synonym → name index lookup
    """
    named = name_index.get(_normalize(name))
    if named and _is_mim_nonidentity(named):
        return named
    if term_id in (named or {}).get('_retired_source_ids', ()):
        return named

    if term_id:
        if term_id in chebi_index:
            return chebi_index[term_id]
        if term_id in ontology_index:
            return ontology_index[term_id]

    return named


def _prefix(curie: str) -> str:
    return curie.split(':', 1)[0] if ':' in curie else ''


def _published_ids(term_id: str, mim: dict | None) -> tuple[str, str]:
    """The (chebi_id, culturemech_term_id) a row publishes, MIM's ruling first.

    ``build_unified_rows`` removes explicitly rejected source IDs before calling
    this helper; the rules here apply to the remaining, unreviewed source IDs.
    This file is the source of truth for kg-microbe's ingredient groundings
    (priority 11 in its consolidator), and that consumer selects a row's
    primary with ``best_primary([chebi_id, culturemech_term_id, mim_id,
    kg_microbe_node_id, cas_rn])``: equal-tier candidates tie, and the tie
    goes to the earlier column. So a MIM correction written to ``mim_id`` lost
    to a superseded CultureMech id republished in ``chebi_id`` or
    ``culturemech_term_id`` -- every rebuild re-asserted the stale grounding
    and demoted MIM's to an xref. kg-microbe declined to reorder, since that
    would also move disagreements nobody has reviewed (kg-microbe#723). The
    only lever left is what this file publishes (MediaIngredientMech#138).

    Rules, deliberately narrow:

    - MIM MAPPED to a CURIE: ``chebi_id`` is MIM's CHEBI id (CultureMech's only
      as fallback when MIM's identity is not CHEBI). ``culturemech_term_id`` is
      withheld only when it would tie MIM's id downstream -- same prefix,
      different value. A different-prefix disagreement is left as today: the
      consumer's tier ranking already decides it, and blanking would only
      erase provenance the curation queue (CultureMech#256) still needs.
    - MIM explicitly UNMAPPED/AMBIGUOUS/REJECTED: MIM's ruling is "no identity". A raw column
      asserting one contradicts that and would win by default, since there is
      no corrected candidate at all. Both columns are withheld.
    - No MIM record: unchanged. CultureMech's term is the only opinion.

    The loader resolves documented merge labels to live representatives.
    Rejected records without a live representative cannot assert an identity.
    """
    term_id = term_id or ''
    mim_id = (mim or {}).get('mim_id') or ''
    status = (mim or {}).get('mapping_status') or ''
    ruled = (
        bool(mim)
        and status == 'MAPPED'
        and ':' in mim_id
        and not mim_id.startswith('UNMAPPED')
    )
    refused = bool(mim) and _is_mim_nonidentity(mim)

    if refused:
        return '', ''

    if ruled and mim['chebi_id']:
        chebi_id = mim['chebi_id']
    elif term_id.startswith('CHEBI:'):
        chebi_id = term_id
    elif mim and mim['chebi_id']:
        chebi_id = mim['chebi_id']
    else:
        chebi_id = ''

    cm_term_id = term_id
    if ruled and term_id and term_id != mim_id and _prefix(term_id) == _prefix(mim_id):
        cm_term_id = ''
    return chebi_id, cm_term_id


def build_unified_rows(
    occurrences: dict,
    name_index: dict,
    chebi_index: dict,
    ontology_index: dict,
    rejections: dict | None = None,
) -> list:
    """
    Join CultureMech occurrences with MIM records.

    Retired primary IDs and reviewed source-ID rejections are applied before
    identifier lookup and publication. Other IDs follow the existing MIM-ruling policy in
    ``_published_ids``.

    Returns list of row dicts, sorted by occurrence count descending.
    """
    rows = []
    matched = unmatched = 0

    for name, info in occurrences.items():
        term_id = info['term_id']
        named_mim = name_index.get(_normalize(name))
        if term_id in (named_mim or {}).get('_retired_source_ids', ()):
            term_id = ''
        expected_id = (rejections or {}).get(((named_mim or {}).get('mim_id'), term_id))
        if expected_id:
            # Do not let a rejected source ID select another MIM record before
            # the curated name can resolve (e.g. a real detergent record).
            term_id = ''
        mim = resolve_mim_record(name, term_id, name_index, chebi_index, ontology_index)
        if expected_id and (not mim or mim['mim_id'] != expected_id):
            raise ValueError(f'{name}: rejected source ID has no matching curated identity')

        chebi_id, cm_term_id = _published_ids(term_id, mim)

        row = {
            'ingredient_name': name,
            'culturemech_term_id': cm_term_id,
            'occurrence_count': info['count'],
            'chebi_id': chebi_id,
            'mim_id': mim['mim_id'] if mim else '',
            'cas_rn': mim['cas_rn'] if mim else '',
            'kg_microbe_node_id': mim['kg_microbe_node_id'] if mim else '',
            'mapping_status': '',
            'synonyms': '|'.join(mim.get('synonyms', [])) if mim else '',
            'example_media': '; '.join(info['example_media']),
        }

        if mim:
            matched += 1
            if chebi_id:
                row['mapping_status'] = mim['mapping_status'] or 'MAPPED'
            else:
                # MIM has record but no CHEBI (e.g. UNMAPPED or FOODON-only)
                row['mapping_status'] = mim['mapping_status'] or 'MIM_NO_CHEBI'
        else:
            unmatched += 1
            if chebi_id:
                row['mapping_status'] = 'CHEBI_NO_MIM'
            elif term_id:
                row['mapping_status'] = 'TERM_ID_NO_MIM'
            else:
                row['mapping_status'] = 'UNMAPPED'

        rows.append(row)

    rows.sort(key=lambda r: -r['occurrence_count'])

    print(f"Resolved: {matched} matched to MIM, {unmatched} not in MIM")
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

COLUMNS = [
    'ingredient_name',
    'occurrence_count',
    'chebi_id',       # primary chemical ID — CultureMech term.id (if CHEBI) or MIM fallback
    'cas_rn',
    'kg_microbe_node_id',
    'mim_id',         # MIM record fallback identifier
    'culturemech_term_id',
    'mapping_status',
    'synonyms',       # pipe-separated alternate labels harvested from MIM
    'example_media',
]


def write_tsv(rows: list, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=COLUMNS,
            delimiter='\t',
            lineterminator='\n',
        )
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
    from collections import Counter
    total = len(rows)
    has_chebi = sum(1 for r in rows if r['chebi_id'])
    has_cas = sum(1 for r in rows if r['cas_rn'])
    has_kg = sum(1 for r in rows if r['kg_microbe_node_id'])
    has_mim = sum(1 for r in rows if r['mim_id'])
    fully_mapped = sum(1 for r in rows if r['chebi_id'] and r['cas_rn'])
    chebi_from_cm = sum(1 for r in rows if r['chebi_id'] and r['culturemech_term_id'].startswith('CHEBI:'))
    chebi_from_mim = sum(1 for r in rows if r['chebi_id'] and not r['culturemech_term_id'].startswith('CHEBI:'))
    status_counts = Counter(r['mapping_status'] for r in rows)

    print()
    print("=" * 60)
    print("UNIFIED MAPPING COVERAGE REPORT")
    print("=" * 60)
    print(f"Total unique ingredient names:  {total}")
    print(f"Have CHEBI ID:                  {has_chebi}  ({100*has_chebi//total}%)")
    print(f"  - from CultureMech term.id:   {chebi_from_cm}")
    print(f"  - from MIM (fallback):        {chebi_from_mim}")
    print(f"Have CAS-RN:                    {has_cas}  ({100*has_cas//total}%)")
    print(f"Have KG-Microbe node ID:        {has_kg}  ({100*has_kg//total}%)")
    print(f"Matched to MIM record:          {has_mim}  ({100*has_mim//total}%)")
    print(f"Fully mapped (CHEBI + CAS):     {fully_mapped}  ({100*fully_mapped//total}%)")
    print()
    print("Status breakdown:")
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<25} {count}")


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
    require_mech_roots("culturemech", "mediaingredientmech", claw_root=REPO_ROOT)

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
    name_index, chebi_index, ontology_index = load_mim_index(args.mim)
    rejections = load_mapping_rejections(args.mim, name_index)

    # Scan CultureMech
    occurrences = scan_culturemech(args.culturemech)

    # Join
    rows = build_unified_rows(occurrences, name_index, chebi_index, ontology_index, rejections)

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
