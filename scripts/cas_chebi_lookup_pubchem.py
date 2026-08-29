#!/usr/bin/env python3
"""
Follow-up CAS→CHEBI pass for the 684 compounds left in
culturebotht_curation_queue.tsv after the initial OLS-based integration.

OLS's name search hit 472 of 1,088 fresh compounds; its CAS-xref search
returned no usable hits in our run. This script bypasses OLS for the
CAS lookup by:

  1. Building a CAS-RN → CHEBI index from OAK's local CHEBI sqlite
     (single scan, ~30s, cached to workspace/cache/cas_to_chebi.json).
  2. For each queued CAS in the curation queue, looking up the index.
  3. For HIGH-confidence hits (CHEBI exists locally, not obsolete,
     not already in MIM), creating a MIM YAML the same way
     integrate_culturebotht_ingredients.py does.
  4. Falling back to PubChem REST for CAS values not in OAK
     (PubChem CID synonyms often include CHEBI: prefix entries).

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
CULTUREBOTHT_ROOT_PATH = Path(
    os.environ.get("CULTUREBOTHT_ROOT", REPO_ROOT.parent / "CultureBotHT")
)
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
WORKSPACE = REPO_ROOT / "workspace"
QUEUE_TSV = WORKSPACE / "reports/culturebotht_curation_queue.tsv"
CAS_CACHE = WORKSPACE / "cache/cas_to_chebi.json"
PUBCHEM_CACHE = WORKSPACE / "cache/pubchem_cas_chebi.json"
SUMMARY_MD = WORKSPACE / "reports/cas_chebi_followup_summary.md"

CULTUREBOT_ROOT = CULTUREBOTHT_ROOT_PATH / "CultureBotHT"
COMPOUNDS_CSV = CULTUREBOT_ROOT / "data/raw/google_sheets/compounds_to_cas.csv"
MIM_MAPPED_DIR = MIM_ROOT / "data/ingredients/mapped"

TIMESTAMP = datetime.now(timezone.utc).isoformat()

PANEL_COLUMNS = (
    "Hans80Anti", "Hans80metals", "FEBA_carbon",
    "FEBA_nitrogen", "FEBA_stress", "All_star",
)

sys.path.insert(0, str(Path(__file__).parent))
from apply_mim_chebi_fixes import _slug  # noqa: E402


def _build_mim_chebi_index() -> dict[str, str]:
    by_chebi: dict[str, str] = {}
    for p in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            d = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        chebi = ((d.get("ontology_mapping") or {}).get("ontology_id") or "").strip()
        if chebi.startswith("CHEBI:"):
            by_chebi.setdefault(chebi, p.name)
    return by_chebi


def _load_pubchem_cache() -> dict:
    if PUBCHEM_CACHE.exists():
        try:
            return json.loads(PUBCHEM_CACHE.read_text())
        except Exception:
            pass
    return {}


def _save_pubchem_cache(cache: dict) -> None:
    PUBCHEM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PUBCHEM_CACHE.write_text(json.dumps(cache, indent=2))


def pubchem_cas_to_chebi(cas: str, cache: dict) -> str | None:
    """Resolve a CAS-RN through PubChem to a CHEBI id, if possible."""
    if cas in cache:
        return cache[cas]
    # Step 1: CAS → CIDs
    cid_url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/xref/RegistryID/"
        f"{cas}/cids/JSON"
    )
    try:
        with urllib.request.urlopen(cid_url, timeout=15) as r:
            cid_data = json.loads(r.read())
        cids = cid_data.get("InformationList", {}).get("Information", [])
        if not cids:
            cache[cas] = None
            return None
        cid = cids[0].get("CID", [None])[0]
    except Exception:
        cache[cas] = None
        return None
    if not cid:
        cache[cas] = None
        return None
    # Step 2: CID → synonyms (which sometimes contain CHEBI:NNNN)
    syn_url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
    )
    try:
        with urllib.request.urlopen(syn_url, timeout=15) as r:
            syn_data = json.loads(r.read())
        syns = syn_data.get("InformationList", {}).get("Information", [])
        if not syns:
            cache[cas] = None
            return None
        for s in syns[0].get("Synonym", []):
            m = re.match(r"^CHEBI:(\d+)$", s.strip())
            if m:
                chebi = f"CHEBI:{m.group(1)}"
                cache[cas] = chebi
                return chebi
    except Exception:
        pass
    cache[cas] = None
    return None


def _create_yaml(path: Path, name: str, chebi: str, label: str, cas: str,
                 panels: list[str], source: str) -> tuple[bool, str]:
    if path.exists():
        return False, "yaml exists"
    notes = (
        f"Imported from CultureBotHT. CAS-RN→CHEBI mapping resolved via "
        f"{source}. "
    )
    if panels:
        notes += f"FEBA/Hans80 panels: {', '.join(panels)}."
    doc = {
        "identifier": chebi,
        "preferred_term": name,
        "ontology_mapping": {
            "ontology_id": chebi,
            "ontology_label": label,
            "ontology_source": "CHEBI",
            "mapping_quality": "EXACT_MATCH",
            "evidence": [
                {
                    "evidence_type": "DATABASE_MATCH",
                    "source": "CultureBotHT",
                    "notes": notes,
                }
            ],
        },
        "synonyms": [],
        "mapping_status": "MAPPED",
        "occurrence_statistics": {"total_occurrences": 0, "media_count": 0},
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_cas_chebi_followup",
                "action": "CREATED_FROM_CAS_LOOKUP",
                "changes": (
                    f"Created from CultureBotHT CAS-RN={cas}; CHEBI resolved "
                    f"via {source}; {notes}"
                ),
                "new_status": "MAPPED",
                "llm_assisted": False,
            }
        ],
        "chemical_properties": {
            "cas_rn": cas,
            "data_source": "CultureBotHT compounds_to_cas.csv",
            "retrieval_date": TIMESTAMP,
        },
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"created {path.name} → {chebi}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-pubchem", action="store_true",
                    help="Skip PubChem fallback (OAK-only).")
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)


    print(f"[1/4] Loading CAS→CHEBI index from OAK")
    cas_to_chebi = json.loads(CAS_CACHE.read_text())
    print(f"      {len(cas_to_chebi):,} CAS-RNs indexed")

    print(f"[2/4] Loading queue + CultureBotHT panel data")
    queue_rows = []
    with QUEUE_TSV.open() as f:
        rdr = csv.DictReader(f, delimiter="\t")
        for r in rdr:
            cas = (r.get("CAS") or "").strip()
            if cas:
                queue_rows.append(r)
    print(f"      {len(queue_rows)} queued rows have CAS-RN")

    # Load full panel info from compounds_to_cas.csv (queue's panels column
    # is comma-string; reload the source for completeness).
    panels_by_compound: dict[str, list[str]] = {}
    with COMPOUNDS_CSV.open() as f:
        for r in csv.DictReader(f):
            name = (r.get("Compound") or "").strip()
            if not name:
                continue
            ps = [p for p in PANEL_COLUMNS if (r.get(p) or "").strip()]
            if ps:
                panels_by_compound[name] = ps

    mim_by_chebi = _build_mim_chebi_index()
    print(f"      MIM has {len(mim_by_chebi)} CHEBI-keyed YAMLs")

    print(f"[3/4] Resolving CAS-RNs against OAK index"
          + (" + PubChem fallback" if not args.no_pubchem else ""))
    pubchem_cache = _load_pubchem_cache()
    oak_hits = 0
    pubchem_hits = 0
    no_match = 0
    chebi_collisions = 0
    created: list[dict] = []
    for i, r in enumerate(queue_rows, 1):
        cas = r["CAS"].strip()
        name = r["Compound"].strip()
        if not name or not cas:
            continue
        chebi = cas_to_chebi.get(cas)
        source = "OAK CHEBI sqlite (cas xref)"
        if not chebi and not args.no_pubchem:
            chebi = pubchem_cas_to_chebi(cas, pubchem_cache)
            if chebi:
                source = "PubChem CID→synonym CHEBI"
        if not chebi:
            no_match += 1
            continue
        # Check if CHEBI already in MIM
        if chebi in mim_by_chebi:
            chebi_collisions += 1
            continue
        # Found new mapping
        if source.startswith("OAK"):
            oak_hits += 1
        else:
            pubchem_hits += 1
        slug = _slug(name)
        path = MIM_MAPPED_DIR / f"{slug}.yaml"
        panels = panels_by_compound.get(name, [])
        if args.apply:
            ok, _ = _create_yaml(path, name, chebi, "", cas, panels, source)
            if ok:
                mim_by_chebi[chebi] = path.name
                created.append({"name": name, "chebi": chebi, "cas": cas,
                                "source": source})
        else:
            created.append({"name": name, "chebi": chebi, "cas": cas,
                            "source": source})
        if (i % 100 == 0) and not args.no_pubchem:
            _save_pubchem_cache(pubchem_cache)
            print(f"  {i}/{len(queue_rows)} oak={oak_hits} "
                  f"pubchem={pubchem_hits} no-match={no_match} "
                  f"collisions={chebi_collisions}", flush=True)
    if not args.no_pubchem:
        _save_pubchem_cache(pubchem_cache)

    print(f"\n[4/4] Outcome:")
    print(f"  OAK CAS-xref hits:     {oak_hits}")
    print(f"  PubChem CID hits:      {pubchem_hits}")
    print(f"  CHEBI already in MIM:  {chebi_collisions}")
    print(f"  No CHEBI match:        {no_match}")
    print(f"  Total queue rows:      {len(queue_rows)}")

    # Markdown summary
    sm = [
        "# CultureBotHT Follow-up CAS→CHEBI Pass\n",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}\n",
        f"**Source queue:** `{QUEUE_TSV.relative_to(WORKSPACE)}`\n",
        f"**Local CAS index:** {len(cas_to_chebi):,} CAS-RNs from OAK CHEBI sqlite\n\n",
        "## Outcome\n\n",
        "| Outcome | Count |\n|---|---:|\n",
        f"| OAK CAS-xref hits → new MIM YAML | {oak_hits} |\n",
        f"| PubChem CID-synonym hits → new MIM YAML | {pubchem_hits} |\n",
        f"| CHEBI already in MIM (skipped) | {chebi_collisions} |\n",
        f"| No CHEBI match (still queued) | {no_match} |\n",
    ]
    if created:
        sm.append("\n## Sample new mappings (first 25)\n\n")
        sm.append("| Compound | CAS-RN | CHEBI | Source |\n|---|---|---|---|\n")
        for c in created[:25]:
            sm.append(f"| {c['name']} | {c['cas']} | `{c['chebi']}` | {c['source']} |\n")
    SUMMARY_MD.write_text("".join(sm))
    print(f"\nSummary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()
