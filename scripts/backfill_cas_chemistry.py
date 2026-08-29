#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Backfill `chemical_properties.molecular_formula` / `smiles` / `inchi`
for every MIM ingredient with a `cas:*` primary identifier, using
PubChem's REST API (CAS → CID → properties).

Sister script to `backfill_chebi_chemistry.py` (which uses the local
CHEBI sqlite for CHEBI primaries). Together they cover the chemistry-
defined records: CHEBI gets ~1,260, this script targets the ~249
cas:* records that have a CAS-RN but no CHEBI yet.

Cached PubChem responses go to `workspace/cache/pubchem_cas_chemistry.json`
so reruns are cheap.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients" / "mapped"
CACHE_PATH = REPO_ROOT / "workspace" / "cache" / "pubchem_cas_chemistry.json"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "cas_chemistry_backfill.tsv"
OUT_MD = OUT_DIR / "cas_chemistry_backfill.md"

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
RATE_DELAY = 0.25   # NCBI guideline: <=5 req/s

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



def _http_json(url: str, timeout: int = 20) -> dict | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": "MIM-cas-chemistry-backfill/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


def fetch_pubchem_chemistry(cas: str, cache: dict) -> dict:
    """Returns {molecular_formula, smiles, inchi, cid} or {}.
    Cached by CAS-RN."""
    if cas in cache:
        return cache[cas] or {}

    # Step 1: CAS → CID
    cid_url = (f"{PUBCHEM_BASE}/xref/RegistryID/"
               f"{urllib.parse.quote(cas)}/cids/JSON")
    cid_resp = _http_json(cid_url)
    time.sleep(RATE_DELAY)
    if not cid_resp:
        cache[cas] = None
        return {}
    # PubChem returns either IdentifierList.CID (newer endpoint shape)
    # or InformationList.Information[].CID (older). Handle both.
    cids = (cid_resp.get("IdentifierList") or {}).get("CID") or []
    if not cids:
        cids = ((cid_resp.get("InformationList") or {})
                .get("Information") or [{}])[0].get("CID") or []
    if not cids:
        cache[cas] = None
        return {}
    cid = cids[0]

    # Step 2: CID → properties.
    # PubChem renamed CanonicalSMILES → ConnectivitySMILES; request both
    # for forward/backward compat.
    props_url = (f"{PUBCHEM_BASE}/cid/{cid}/property/"
                 f"MolecularFormula,ConnectivitySMILES,CanonicalSMILES,InChI/JSON")
    props_resp = _http_json(props_url)
    time.sleep(RATE_DELAY)
    if not props_resp:
        cache[cas] = None
        return {}
    props = ((props_resp.get("PropertyTable") or {})
             .get("Properties") or [{}])[0]
    out = {"cid": cid}
    if props.get("MolecularFormula"):
        out["molecular_formula"] = props["MolecularFormula"]
    smiles = props.get("ConnectivitySMILES") or props.get("CanonicalSMILES")
    if smiles:
        out["smiles"] = smiles
    if props.get("InChI"):
        out["inchi"] = props["InChI"]
    cache[cas] = out
    return out


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    # Verify the checkout before doing work; module-level roots stay
    # plain paths so importing this file never needs one (#176).
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)
    global _TRANSACTION
    _TRANSACTION = ValidatedWriteTransaction(
        MIM_ROOT,
        journal_dir=OUT_DIR / "write_journal",
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    print(f"PubChem cache: {len(cache)} entries")

    # Walk cas:* records
    targets: list[tuple[Path, dict]] = []
    for path in sorted(INGREDIENTS.glob("*.yaml")):
        record = load_yaml(path)
        if not record:
            continue
        ident = (record.get("identifier") or "").strip()
        if not ident.startswith("cas:"):
            continue
        targets.append((path, record))
    if args.limit:
        targets = targets[: args.limit]
    print(f"cas:* records to scan: {len(targets)}")

    counts: dict[str, int] = {}
    rows: list[tuple[str, str, str, str, str, str, str]] = []

    for i, (path, record) in enumerate(targets, 1):
        cp = record.setdefault("chemical_properties", {})
        cas = (cp.get("cas_rn") or "").strip()
        rel = str(path.relative_to(MIM_ROOT))
        if not cas:
            counts["NO_CAS_RN"] = counts.get("NO_CAS_RN", 0) + 1
            rows.append((rel, "", "", "", "", "", "NO_CAS_RN"))
            continue

        # Skip if already populated
        if cp.get("molecular_formula") and cp.get("smiles"):
            counts["ALREADY_SET"] = counts.get("ALREADY_SET", 0) + 1
            rows.append((rel, cas, cp.get("molecular_formula", ""),
                         cp.get("smiles", "")[:30], cp.get("inchi", "")[:30],
                         "", "ALREADY_SET"))
            continue

        chem = fetch_pubchem_chemistry(cas, cache)
        if not chem:
            counts["NO_PUBCHEM_HIT"] = counts.get("NO_PUBCHEM_HIT", 0) + 1
            rows.append((rel, cas, "", "", "", "", "NO_PUBCHEM_HIT"))
            if i % 25 == 0:
                save_cache(cache)
                print(f"  [{i}/{len(targets)}] {cas}: NO_PUBCHEM_HIT")
            continue

        slots_to_set = {k: v for k, v in chem.items()
                        if k in ("molecular_formula", "smiles", "inchi")
                        and not cp.get(k)}
        if not slots_to_set:
            counts["NO_NEW_SLOTS"] = counts.get("NO_NEW_SLOTS", 0) + 1
            rows.append((rel, cas, chem.get("molecular_formula", ""),
                         chem.get("smiles", "")[:30],
                         chem.get("inchi", "")[:30],
                         str(chem.get("cid", "")), "NO_NEW_SLOTS"))
            continue

        action = "SET" if args.apply else "WOULD_SET"
        counts[action] = counts.get(action, 0) + 1
        if args.apply:
            cp.update(slots_to_set)
            cp.setdefault("data_source", "PubChem (CAS-RN lookup)")
            if "cid" in chem and not cp.get("pubchem_cid"):
                cp["pubchem_cid"] = chem["cid"]
            slot_summary = "; ".join(
                f"{k}={v[:50]}" for k, v in slots_to_set.items())
            append_curation_event(
                record, "AUTO_BACKFILL_PUBCHEM_CHEMISTRY", slot_summary)
            _staged_write(path, record)

        rows.append((rel, cas, slots_to_set.get("molecular_formula", ""),
                     slots_to_set.get("smiles", "")[:30],
                     slots_to_set.get("inchi", "")[:30],
                     str(chem.get("cid", "")), action))
        if i % 25 == 0:
            save_cache(cache)
            print(f"  [{i}/{len(targets)}] {cas} → cid {chem.get('cid')}; "
                  f"{action} {','.join(slots_to_set.keys())}")

    save_cache(cache)

    # Reports
    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["yaml_path", "cas_rn", "molecular_formula", "smiles",
                    "inchi", "pubchem_cid", "verdict"])
        w.writerows(rows)

    md = ["# PubChem CAS-RN chemistry backfill\n",
          f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**\n",
          f"cas:* records scanned: **{len(targets)}**\n",
          "\n## Outcomes\n", "| verdict | count |", "|---|---:|"]
    for k in sorted(counts, key=lambda x: -counts[x]):
        md.append(f"| `{k}` | {counts[k]} |")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print()
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:20s} {v}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    _result = _TRANSACTION.commit(apply=args.apply)
    if args.apply and _result.touched:
        print(f"Wrote {_result.touched} record(s); journal: {_result.journal_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
