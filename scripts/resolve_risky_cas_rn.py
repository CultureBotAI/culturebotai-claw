#!/usr/bin/env python3
"""
Resolve the 7 RISKY merges from mim_merge_plan.tsv whose CAS-RN values
disagree across the group.

For each RISKY merge:
  1. Query OAK for the CHEBI's canonical CAS-RN xref.
  2. Check whether any of the per-YAML CAS-RN values match OAK's.
  3. If YES → resolve winner's chemical_properties.cas_rn to the match.
     If NO  → force winner's CAS-RN to OAK's canonical value and flag
              for curator review (the existing MIM CAS-RNs were all
              likely incorrect).
  4. Execute the merge same as the SAFE path: union synonyms, concat
     curation_history, sum occurrences, delete losers, republish.

Requires: oaklib + local CHEBI sqlite.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
WORKSPACE = REPO_ROOT / "workspace"
MIM_ROOT = MIM_ROOT
MIM_MAPPED_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"
PLAN_TSV = WORKSPACE / "reports/mim_merge_plan.tsv"

TIMESTAMP = datetime.now(timezone.utc).isoformat()

# Reuse the merge primitives from apply_mim_merges.py.
sys.path.insert(0, str(Path(__file__).parent))
from apply_mim_merges import (  # noqa: E402
    _merge_synonyms, _merge_curation_history,
    _sum_occurrences, _append_merge_entry,
)


def _oak_cas(chebi: str, cache: dict) -> str:
    if chebi in cache:
        return cache[chebi]
    from oaklib import get_adapter
    a = get_adapter("sqlite:obo:chebi")
    for pred, obj in a.simple_mappings_by_curie(chebi):
        if pred.endswith("hasDbXref") and str(obj).lower().startswith("cas:"):
            v = str(obj).split(":", 1)[1]
            cache[chebi] = v
            return v
    cache[chebi] = ""
    return ""


def _load_risky() -> list[dict]:
    rows = []
    with PLAN_TSV.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            conflicts = [c for c in (r.get("cas_rn_conflicts") or "").split("|") if c]
            if len(conflicts) > 1:
                r["_conflicts"] = conflicts
                rows.append(r)
    return rows


def _resolve_and_apply(row: dict, apply: bool, cas_cache: dict) -> dict:
    chebi = row["chebi"]
    oak_cas = _oak_cas(chebi, cas_cache)
    conflicts = row["_conflicts"]

    if oak_cas and oak_cas in conflicts:
        resolution = "match"
        chosen_cas = oak_cas
    elif oak_cas:
        resolution = "override"
        chosen_cas = oak_cas
    else:
        resolution = "no_oak_cas"
        chosen_cas = ""

    winner_name = row["winner"]
    loser_names = [l for l in row["losers"].split("|") if l]

    winner_path = MIM_MAPPED_DIR / winner_name
    loser_paths = [MIM_MAPPED_DIR / l for l in loser_names]

    missing = [p.name for p in [winner_path, *loser_paths] if not p.exists()]
    if missing:
        return {"status": "SKIP", "reason": f"missing: {missing}",
                "resolution": resolution, "oak_cas": oak_cas}

    winner_doc = yaml.safe_load(winner_path.read_text())
    loser_docs = [yaml.safe_load(p.read_text()) for p in loser_paths]

    loser_pts = [d.get("preferred_term", "") for d in loser_docs]

    _merge_synonyms(winner_doc, loser_docs, loser_pts)
    _merge_curation_history(winner_doc, loser_docs)
    _sum_occurrences(winner_doc, loser_docs)

    # CAS-RN resolution — force to OAK's value (or first conflict if OAK unknown).
    w_props = winner_doc.get("chemical_properties") or {}
    prev_cas = w_props.get("cas_rn", "")
    if chosen_cas:
        w_props["cas_rn"] = chosen_cas
        if resolution == "override":
            w_props["data_source"] = f"OAK/CHEBI xref (overrode {'|'.join(conflicts)})"
            w_props["retrieval_date"] = TIMESTAMP
        elif resolution == "match" and prev_cas != chosen_cas:
            w_props["data_source"] = "OAK/CHEBI xref"
            w_props["retrieval_date"] = TIMESTAMP
    if w_props:
        winner_doc["chemical_properties"] = w_props

    _append_merge_entry(winner_doc, loser_names)

    # Extra curation_history entry about CAS-RN resolution.
    winner_doc.setdefault("curation_history", []).append({
        "timestamp": TIMESTAMP,
        "curator": "audit_resolve_risky_cas_rn",
        "action": "RESOLVED_CAS_RN_CONFLICT",
        "changes": (
            f"CAS-RN conflict across merged group ({'|'.join(conflicts)}) "
            f"resolved via OAK canonical xref: {chosen_cas or 'UNKNOWN'} "
            f"({resolution})"
        ),
        "new_status": winner_doc.get("mapping_status", "MAPPED"),
        "llm_assisted": False,
    })

    if not apply:
        return {"status": "PLAN", "resolution": resolution, "oak_cas": oak_cas,
                "chosen_cas": chosen_cas, "prev_cas": prev_cas}

    winner_path.write_text(yaml.safe_dump(winner_doc, sort_keys=False,
                                          allow_unicode=True))
    for p in loser_paths:
        subprocess.run(["git", "rm", "-q", str(p)],
                       cwd=str(MIM_ROOT), check=True)
    return {"status": "DONE", "resolution": resolution, "oak_cas": oak_cas,
            "chosen_cas": chosen_cas, "prev_cas": prev_cas}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)


    rows = _load_risky()
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(rows)} RISKY merges\n")

    cas_cache: dict[str, str] = {}
    for r in rows:
        result = _resolve_and_apply(r, args.apply, cas_cache)
        chebi = r["chebi"]
        print(
            f"  [{result['status']}] {chebi} {r['winner']:32s} "
            f"conflicts=[{'|'.join(r['_conflicts'])}] "
            f"→ CAS={result.get('chosen_cas', '?')} "
            f"({result.get('resolution', 'unknown')})"
        )

    if args.apply:
        print("\nNext: build-sssom, publish-sssom --allow-drop 20")


if __name__ == "__main__":
    main()
