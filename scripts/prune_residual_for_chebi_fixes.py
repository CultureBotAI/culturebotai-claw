"""Remove residual-P2.5 decisions that would conflict with the MIM CHEBI
corrections applied by `scripts/fix_wrong_chebi_mappings.py`.

The residual-P2.5 JSON (workspace/reports/kg_microbe_residual_p25_categorized.json)
drives predicate selection and, for CONSIDER_SPECIFIC rows, actively swaps
the emitted CHEBI to the kg-microbe one. For the YAMLs we're about to
correct, those decisions were generated against the WRONG MIM CHEBI and
would either (a) override our correction back to a wrong CHEBI, or (b)
emit a stale closeMatch rationale about CHEBIs that no longer apply.

Stale entries removed (2026-04-18 SSSOM cleanup):
  Histidine.yaml              — 3 entries (SYMMETRIC + 2× CONSIDER_SPECIFIC)
  L-cysteine_Hcl.yaml         — SYMMETRIC, stale comparison
  Ferric_Citrate.yaml         — CONSIDER_SPECIFIC swapping to a sugar polymer
  Folinic_Acid.yaml           — SYMMETRIC, now redundant (mim == kg)
  Starch_soluble.yaml         — SYMMETRIC, stale comparison
  Tween_20.yaml               — SYMMETRIC, now redundant (mim == kg)
"""
from __future__ import annotations

import json
from pathlib import Path

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
RESIDUAL_JSON = CLAW_ROOT / "workspace" / "reports" / "kg_microbe_residual_p25_categorized.json"

STALE_SOURCE_FILES = {
    "Histidine.yaml",
    "L-cysteine_Hcl.yaml",
    "Ferric_Citrate.yaml",
    "Folinic_Acid.yaml",
    "Starch_soluble.yaml",
    "Tween_20.yaml",
}


def main():
    data = json.loads(RESIDUAL_JSON.read_text())
    before = len(data["decisions"])
    removed = [d for d in data["decisions"] if d["source_file"] in STALE_SOURCE_FILES]
    kept = [d for d in data["decisions"] if d["source_file"] not in STALE_SOURCE_FILES]
    data["decisions"] = kept
    data["summary"]["residual_total"] = len(kept)

    # Recompute category counts so summary stays coherent
    cat_counts: dict[str, int] = {}
    cat_x_triage: dict[str, dict[str, int]] = {}
    for d in kept:
        c = d.get("category", "UNKNOWN")
        t = d.get("triage_bucket", "UNKNOWN")
        cat_counts[c] = cat_counts.get(c, 0) + 1
        cat_x_triage.setdefault(c, {})
        cat_x_triage[c][t] = cat_x_triage[c].get(t, 0) + 1
    data["summary"]["categories"] = cat_counts
    data["summary"]["categories_x_triage"] = cat_x_triage

    RESIDUAL_JSON.write_text(json.dumps(data, indent=2) + "\n")

    print(f"Removed {len(removed)} residual entries:")
    for d in removed:
        print(
            f"  {d['source_file']:28s}  {d['category']:20s}  "
            f"mim={d['mim_chebi']:15s}  kg={d['kg_microbe_chebi']}"
        )
    print(f"\nResidual decisions: {before} -> {len(kept)}")


if __name__ == "__main__":
    main()
