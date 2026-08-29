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

Stale entries removed (2026-07-07 rebuild reconciliation):
  The 18 CONSIDER_SPECIFIC decisions below were reconciled to the generic
  MIM CHEBI by commit cfd643c ("Reconcile 19 stale SSSOM mappings to
  curated terms", 2026-06-05) directly on the published SSSOM, but the
  residual JSON was never pruned to match. A full rebuild re-applied the
  stale specific-form swaps (e.g. Xylose CHEBI:18222 "xylose" →
  CHEBI:15936 "aldehydo-D-xylose"), reverting the curation. Each YAML's
  curated ontology_id equals the published object_id; the override no
  longer applies. Removing them lets the build honor the curated term.
    Arginine, Ascorbic_Acid, Asparagine, Cellobiose, Cysteine,
    D-glucuronic_Acid, Dl-dithiothreitol, Fucose, Gluconic_Acid,
    Glutamic_Acid, Lactose, Mannitol, Na-ascorbate, Proline, Ribose,
    Sorbitol, Trehalose, Xylose
"""
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CLAW_ROOT = REPO_ROOT
RESIDUAL_JSON = CLAW_ROOT / "workspace" / "reports" / "kg_microbe_residual_p25_categorized.json"

STALE_SOURCE_FILES = {
    "Histidine.yaml",
    "L-cysteine_Hcl.yaml",
    "Ferric_Citrate.yaml",
    "Folinic_Acid.yaml",
    "Starch_soluble.yaml",
    "Tween_20.yaml",
    # 2026-07-07: reconciled to generic MIM CHEBI by cfd643c; residual swap
    # would revert the curation on rebuild. See module docstring.
    "Arginine.yaml",
    "Ascorbic_Acid.yaml",
    "Asparagine.yaml",
    "Cellobiose.yaml",
    "Cysteine.yaml",
    "D-glucuronic_Acid.yaml",
    "Dl-dithiothreitol.yaml",
    "Fucose.yaml",
    "Gluconic_Acid.yaml",
    "Glutamic_Acid.yaml",
    "Lactose.yaml",
    "Mannitol.yaml",
    "Na-ascorbate.yaml",
    "Proline.yaml",
    "Ribose.yaml",
    "Sorbitol.yaml",
    "Trehalose.yaml",
    "Xylose.yaml",
}


def main():
    # The residual-P2.5 cache is an optional, gitignored runtime artifact
    # (build_mim_ingredient_sssom.py treats a missing file as "no
    # overrides"). When it's absent there's nothing to prune — no-op so
    # this stays safe to run unconditionally as a build-sssom pre-step.
    if not RESIDUAL_JSON.exists():
        print(f"Residual cache not present ({RESIDUAL_JSON}); nothing to prune.")
        return

    # Tolerate a malformed / partial cache: this runs as a build-sssom
    # pre-step, so a hard parse error or a missing key must degrade to a
    # no-op rather than aborting the whole build (issue #15). The build
    # loader is equally lenient (data.get("decisions", [])).
    try:
        data = json.loads(RESIDUAL_JSON.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"Residual cache unreadable ({e}); skipping prune.")
        return
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        print("Residual cache has no 'decisions' list; skipping prune.")
        return

    before = len(decisions)
    removed = [d for d in decisions if d.get("source_file") in STALE_SOURCE_FILES]
    kept = [d for d in decisions if d.get("source_file") not in STALE_SOURCE_FILES]

    if not removed:
        # Idempotent: already pruned (or never present). Leave the file
        # untouched so repeated builds don't churn its mtime.
        print(f"No stale residual entries to prune ({before} decisions unchanged).")
        return

    data["decisions"] = kept
    summary = data.setdefault("summary", {})
    summary["residual_total"] = len(kept)

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
            f"  {d.get('source_file',''):28s}  {d.get('category',''):20s}  "
            f"mim={d.get('mim_chebi',''):15s}  kg={d.get('kg_microbe_chebi','')}"
        )
    print(f"\nResidual decisions: {before} -> {len(kept)}")


if __name__ == "__main__":
    main()
