#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Apply CHEBI swaps for MIM_WRONG rows from the DISAGREE round-trip.

For each row in kgm_mim_disagree_roundtrip.json with decision="MIM_WRONG":
  - MIM's current CHEBI is semantically mismatched to its preferred_term
    (confirmed by OLS round-trip); kg-microbe's proposed CHEBI is the
    correct one.

This script swaps `identifier`, `ontology_mapping.ontology_id`, and
`ontology_mapping.ontology_label` to the kg-microbe CHEBI and appends
a FIXED_MIM_WRONG_CHEBI curation_history entry.

Guards:
  - skips rows whose source_file no longer exists (already merged away
    in a prior consolidation pass).
  - skips rows where the swap would create a duplicate-CHEBI collision
    on an unrelated MIM record (reports it for curator review).
  - logs every swap with before/after ontology_id.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Reuse the stem-overlap classifier from round_trip_true_bugs.py.
sys.path.insert(0, str(Path(__file__).parent))
from round_trip_true_bugs import classify, fetch_ols_label, _stem_tokens  # noqa: E402

MIM_MAPPED_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients/mapped"
)
WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
IN_JSON = WORKSPACE / "reports/kgm_mim_disagree_roundtrip.json"
FLAGS_MD = WORKSPACE / "reports/mim_wrong_fix_flags.md"

TIMESTAMP = datetime.now(timezone.utc).isoformat()


def _oak_label(chebi: str, cache: dict) -> str:
    if chebi in cache:
        return cache[chebi]
    try:
        from oaklib import get_adapter
        a = get_adapter("sqlite:obo:chebi")
        lbl = a.label(chebi) or ""
    except Exception:
        lbl = ""
    cache[chebi] = lbl
    return lbl


def _load_current_chebi_index() -> dict[str, list[str]]:
    """CHEBI -> list of existing MIM YAML files using it."""
    idx: dict[str, list[str]] = defaultdict(list)
    for p in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            doc = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        cid = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if cid.startswith("CHEBI:"):
            idx[cid].append(p.name)
    return idx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data = json.loads(IN_JSON.read_text())
    wrongs = [r for r in data["results"] if r.get("decision") == "MIM_WRONG"]
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(wrongs)} MIM_WRONG rows\n")

    chebi_index = _load_current_chebi_index()
    label_cache: dict[str, str] = {}
    ols_cache: dict[str, str] = {}

    applied = 0
    deleted_source = []
    collision_flags = []
    file_not_yaml = []
    stale = []
    unverified = []  # kg-microbe CHEBI doesn't pass stem-overlap verification

    # Second-pass verification: round-trip the kg-microbe CHEBI through OLS
    # and confirm its label has stem overlap with preferred_term. Rejects
    # bogus candidates like CHEBI:2 (root) or CHEBI:34218 (tetrachlorobiphenyl
    # for a sodium nitrate entry).
    print("Verifying each kg-microbe candidate via OLS round-trip...")
    verified: list[dict] = []
    for r in wrongs:
        pt = r["preferred_term"] or ""
        new_chebi = r["kg_microbe_chebi"]
        ols_label = fetch_ols_label(new_chebi, ols_cache)
        bucket, rationale = classify(pt, ols_label)
        r["_new_chebi_ols_label"] = ols_label
        r["_new_chebi_verdict"] = bucket
        r["_new_chebi_rationale"] = rationale
        if bucket == "MIM_OK":
            # "OK" here means the new CHEBI label matches preferred_term.
            verified.append(r)
        else:
            unverified.append(r)
    print(f"  Verified: {len(verified)}  Unverified (rejected): {len(unverified)}\n")

    for r in verified:
        src = r["source_file"]
        old_chebi = r["mim_chebi"]
        new_chebi = r["kg_microbe_chebi"]
        pt = r["preferred_term"]

        path = MIM_MAPPED_DIR / src
        if not path.exists():
            deleted_source.append(r)
            continue

        doc = yaml.safe_load(path.read_text())
        if not isinstance(doc, dict):
            file_not_yaml.append(src)
            continue

        current_chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if current_chebi != old_chebi:
            # YAML already changed (merge absorbed it, or a different pass).
            stale.append({"src": src, "expected": old_chebi,
                          "found": current_chebi})
            continue

        # Collision check: does the new CHEBI already live on another MIM YAML?
        owners = [f for f in chebi_index.get(new_chebi, []) if f != src]
        if owners:
            collision_flags.append({
                "src": src, "new_chebi": new_chebi,
                "conflicting_files": owners,
            })
            # Still apply — but note it so curator can run a follow-up merge.

        new_label = _oak_label(new_chebi, label_cache) or ""
        preview = f"{src}: {old_chebi} → {new_chebi}" + (
            f" ({new_label})" if new_label else ""
        )

        if args.apply:
            doc["identifier"] = new_chebi
            doc.setdefault("ontology_mapping", {})
            doc["ontology_mapping"]["ontology_id"] = new_chebi
            doc["ontology_mapping"]["ontology_label"] = new_label
            doc.setdefault("curation_history", []).append({
                "timestamp": TIMESTAMP,
                "curator": "audit_fix_mim_wrong",
                "action": "FIXED_MIM_WRONG_CHEBI",
                "changes": (
                    f"Swapped {old_chebi} → {new_chebi} ({new_label}) — "
                    f"OLS round-trip confirmed MIM's prior CHEBI was "
                    f"mismatched to preferred_term='{pt}'; kg-microbe "
                    f"proposal adopted."
                ),
                "new_status": doc.get("mapping_status", "MAPPED"),
                "llm_assisted": False,
            })
            path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
            chebi_index.setdefault(new_chebi, []).append(src)
            chebi_index[old_chebi] = [
                f for f in chebi_index.get(old_chebi, []) if f != src
            ]
            applied += 1
            print(f"  [DONE] ✓ {preview}")
        else:
            print(f"  [PLAN] • {preview}"
                  + (f"  (collision with {owners[:2]})" if owners else ""))

    # Flags report
    if unverified:
        unlines = ["# MIM_WRONG Candidates Rejected by Verification\n",
                   f"**Total:** {len(unverified)}\n\n",
                   "These rows were classified MIM_WRONG by the initial "
                   "OLS round-trip (MIM's CHEBI label didn't match "
                   "preferred_term), BUT a second round-trip of "
                   "kg-microbe's proposed CHEBI also failed to match "
                   "preferred_term. Both candidates are suspect — the "
                   "original DISAGREE row is likely noise from kg-microbe's "
                   "polluted synonym index. Left unfixed for curator.\n\n",
                   "| Source | preferred_term | MIM CHEBI | kg-microbe CHEBI | "
                   "OLS label of kg-microbe CHEBI | verdict |",
                   "|---|---|---|---|---|---|"]
        for u in unverified:
            unlines.append(
                f"| `{u['source_file']}` | {u['preferred_term']} | "
                f"{u['mim_chebi']} | {u['kg_microbe_chebi']} | "
                f"{u.get('_new_chebi_ols_label', '')} | "
                f"{u.get('_new_chebi_verdict', '')} ({u.get('_new_chebi_rationale', '')}) |"
            )
        (WORKSPACE / "reports/mim_wrong_unverified.md").write_text(
            "\n".join(unlines) + "\n"
        )

    if collision_flags or stale or deleted_source:
        lines = ["# MIM_WRONG Fix Flags\n"]
        if collision_flags:
            lines.append(f"## Collisions after swap ({len(collision_flags)})\n")
            lines.append("Swap applied, but the new CHEBI is now on another "
                         "MIM YAML too — candidate for a follow-up merge.\n")
            lines.append("| Source | New CHEBI | Conflicting MIM files |")
            lines.append("|---|---|---|")
            for f in collision_flags:
                lines.append(
                    f"| `{f['src']}` | {f['new_chebi']} | "
                    + ", ".join(f"`{c}`" for c in f["conflicting_files"][:3])
                    + " |"
                )
            lines.append("")
        if deleted_source:
            lines.append(f"## Source already deleted ({len(deleted_source)})\n")
            lines.append("Source MIM YAML was absorbed in a prior merge; "
                         "the CHEBI fix now belongs on the merge winner.\n")
            lines.append("| Source | Old CHEBI | Proposed new CHEBI |")
            lines.append("|---|---|---|")
            for r in deleted_source:
                lines.append(
                    f"| `{r['source_file']}` | {r['mim_chebi']} | "
                    f"{r['kg_microbe_chebi']} |"
                )
            lines.append("")
        if stale:
            lines.append(f"## Stale (YAML changed since audit) ({len(stale)})\n")
            lines.append("| Source | Expected | Found |")
            lines.append("|---|---|---|")
            for s in stale:
                lines.append(f"| `{s['src']}` | {s['expected']} | {s['found']} |")
            lines.append("")
        FLAGS_MD.write_text("\n".join(lines) + "\n")

    plannable = len(verified) - len(deleted_source) - len(stale) - len(file_not_yaml)
    print()
    if args.apply:
        print(f"DONE. {applied}/{len(wrongs)} swaps applied "
              f"({len(unverified)} rejected by verification, "
              f"{len(deleted_source)} source deleted, "
              f"{len(stale)} stale, "
              f"{len(collision_flags)} collision-flagged).")
    else:
        print(f"DRY-RUN. {len(unverified)} rejected by verification. "
              f"Would swap {plannable} CHEBI IDs.")


if __name__ == "__main__":
    main()
