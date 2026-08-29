#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Backfill `chemical_properties.molecular_formula / smiles / inchi`
for every MIM ingredient YAML whose primary identifier is a CHEBI
term, using the local CHEBI sqlite that OAK already maintains at
`~/.data/oaklib/chebi.db`.

Activates the formula-trumps-name rule in
`scripts/classify_ingredient_type.py` so any future re-run produces
stronger rationale on these records.

Existing values are preserved (curator-set data wins). Empty values
in the source CHEBI record are skipped (legitimate — not every CHEBI
term has a formula; e.g. abstract chemical roles).

Task A of `docs/proposals/...` follow-ups; see plan at
~/.claude/plans/work-on-these-tasks-swift-dragonfly.md
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients"

CHEBI_DB = Path(os.environ.get(
    "CHEBI_SQLITE",
    Path.home() / ".data" / "oaklib" / "chebi.db",
))

OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "chebi_chemistry_backfill.tsv"
OUT_MD = OUT_DIR / "chebi_chemistry_backfill.md"

# CHEBI predicate → MIM chemical_properties slot. inchi_key not
# included because the schema doesn't currently expose it.
_PREDICATE_TO_SLOT = {
    "chemrof:generalized_empirical_formula": "molecular_formula",
    "chemrof:smiles_string": "smiles",
    "chemrof:inchi_string": "inchi",
}

# Reuse YAML I/O + curation history append from the classifier
sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_ingredient_type import (  # noqa: E402
    append_curation_event,
    load_yaml,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from classify_ingredient_type import dump_yaml  # noqa: E402

from kg_microbe_write import ValidatedWriteTransaction  # noqa: E402

# Staged rather than written per record: a failure part-way through a per-record
# write loop leaves an unknown subset of MediaIngredientMech modified with no
# recovery path (#156). The transaction validates the whole set first, replaces
# atomically, and journals prior contents.
_TRANSACTION = None


def _staged_write(path, record) -> None:
    """Stage a record into the run's transaction instead of writing it."""
    if _TRANSACTION is None:
        raise RuntimeError("no write transaction is open for this run")
    _TRANSACTION.stage(path, dump_yaml(record))



def fetch_chebi_chemistry(conn: sqlite3.Connection, chebi_id: str
                          ) -> dict[str, str]:
    """Returns {slot_name: value} from the CHEBI sqlite, omitting
    empty / missing predicates."""
    sql = (
        "SELECT predicate, value FROM node_to_value_statement "
        "WHERE subject = ? AND predicate IN (" +
        ",".join("?" * len(_PREDICATE_TO_SLOT)) + ")"
    )
    rows = conn.execute(
        sql, [chebi_id, *_PREDICATE_TO_SLOT.keys()]
    ).fetchall()
    out: dict[str, str] = {}
    for predicate, value in rows:
        slot = _PREDICATE_TO_SLOT.get(predicate)
        if slot and value:
            out[slot] = str(value).strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap number of CHEBI records processed")
    args = ap.parse_args()
    global _TRANSACTION
    _TRANSACTION = ValidatedWriteTransaction(
        MIM_ROOT,
        journal_dir=OUT_DIR / "write_journal",
    )

    if not CHEBI_DB.is_file():
        print(f"CHEBI sqlite not found at {CHEBI_DB}", file=sys.stderr)
        print("Run any oaklib chebi command (e.g. "
              "`runoak -i sqlite:obo:chebi info CHEBI:15377`) to "
              "trigger the lazy download.", file=sys.stderr)
        return 2
    conn = sqlite3.connect(CHEBI_DB)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, str, str, str]] = []
    n_total = n_chebi = n_set = n_already = n_no_chebi_data = n_skip = 0

    for path in sorted(INGREDIENTS.rglob("*.yaml")):
        record = load_yaml(path)
        if not record:
            continue
        n_total += 1
        ident = (record.get("identifier") or "").strip()
        om = record.get("ontology_mapping") or {}
        chebi_id = ident if ident.startswith("CHEBI:") else (
            (om.get("ontology_id") or "").strip()
            if (om.get("ontology_id") or "").startswith("CHEBI:") else "")
        if not chebi_id:
            continue
        n_chebi += 1
        if args.limit and n_chebi > args.limit:
            break

        rel = str(path.relative_to(MIM_ROOT))
        cp = record.setdefault("chemical_properties", {})
        chem = fetch_chebi_chemistry(conn, chebi_id)

        if not chem:
            n_no_chebi_data += 1
            rows.append((rel, chebi_id, "NO_CHEBI_DATA", "", ""))
            continue

        # Only set slots that are currently empty
        slots_to_set = {k: v for k, v in chem.items() if not cp.get(k)}
        if not slots_to_set:
            n_already += 1
            rows.append((rel, chebi_id, "ALREADY_SET",
                         ",".join(sorted(chem.keys())), ""))
            continue

        n_set += 1
        slot_summary = "; ".join(f"{k}={v[:50]}" for k, v in slots_to_set.items())
        rows.append((rel, chebi_id, "WOULD_SET" if not args.apply else "SET",
                     ",".join(sorted(slots_to_set.keys())), slot_summary))

        if args.apply:
            cp.update(slots_to_set)
            # Anchor data_source if first chemistry write
            cp.setdefault("data_source", "CHEBI sqlite (oaklib)")
            append_curation_event(
                record, "AUTO_BACKFILL_CHEBI_CHEMISTRY", slot_summary)
            _staged_write(path, record)

    # Reports
    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["yaml_path", "chebi_id", "verdict",
                    "slots_in_chebi", "slots_written"])
        w.writerows(rows)

    md: list[str] = []
    md.append("# CHEBI chemistry backfill\n")
    md.append(f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**\n")
    md.append(f"Total YAMLs scanned: **{n_total}**")
    md.append(f"With CHEBI primary: **{n_chebi}**")
    md.append(
        f"{'Set' if args.apply else 'Would set'} chemistry slots: "
        f"**{n_set}**")
    md.append(f"Already populated (preserved): **{n_already}**")
    md.append(f"CHEBI has no chemistry data: **{n_no_chebi_data}**\n")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"Total YAMLs:           {n_total}")
    print(f"With CHEBI primary:    {n_chebi}")
    print(f"  set:                 {n_set}")
    print(f"  already-set:         {n_already}")
    print(f"  no chebi chemistry:  {n_no_chebi_data}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"         {OUT_MD.relative_to(REPO_ROOT)}")
    _result = _TRANSACTION.commit(apply=args.apply)
    if args.apply and _result.touched:
        print(f"Wrote {_result.touched} record(s); journal: {_result.journal_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
