"""Promote 6 ENVO candidate ingredients from MIM unmapped/ to mapped/.

Curated against EBI OLS4 ENVO terms:
  ENVO:00002149  sea water
  ENVO:00001998  soil

Three seawater records (Seawater, Pasteurized_Seawater, Supplemented_Seawater)
and three site-specific soil records (CR1, Green House, Vermont). Only
pure `Seawater` is EXACT_MATCH; the others are CLOSE_MATCH because they
introduce a processing (pasteurized), enrichment (supplemented), or
site-specificity (CR1/greenhouse/Vermont) dimension that the ENVO parent
term doesn't carry.

Acquires the mediaingredientmech lock before writing. Default --dry-run.
"""
from __future__ import annotations

import argparse
import os
import importlib.util
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
CLAW_ROOT = REPO_ROOT
MIM_ROOT = MIM_ROOT
UNMAPPED = MIM_ROOT / "data" / "ingredients" / "unmapped"
MAPPED = MIM_ROOT / "data" / "ingredients" / "mapped"
LOCKS_DIR = CLAW_ROOT / "workspace" / "locks"

# (filename, envo_id, envo_label, mapping_quality, rationale)
CURATIONS: list[tuple[str, str, str, str, str]] = [
    ("Seawater.yaml", "ENVO:00002149", "sea water", "EXACT_MATCH",
     "Direct ENVO match for unprocessed sea water as a culture medium ingredient."),
    ("Pasteurized_Seawater.yaml", "ENVO:00002149", "sea water", "CLOSE_MATCH",
     "Pasteurization is a preparation variant of the parent ENVO:00002149 sea water; "
     "ENVO has no 'pasteurized' subtype, so closeMatch."),
    ("Supplemented_Seawater.yaml", "ENVO:00002149", "sea water", "CLOSE_MATCH",
     "Recipes add nutrients to the base sea water; the ingredient is the sea water "
     "carrier, so closeMatch to ENVO:00002149."),
    ("Cr1_Soil.yaml", "ENVO:00001998", "soil", "CLOSE_MATCH",
     "Site-specific soil sample (CR1); ENVO:00001998 'soil' is the closest applicable parent."),
    ("Green_House_Soil.yaml", "ENVO:00001998", "soil", "CLOSE_MATCH",
     "Greenhouse-sourced soil sample; closeMatch to generic ENVO:00001998 soil."),
    ("Vermont_Soil.yaml", "ENVO:00001998", "soil", "CLOSE_MATCH",
     "Vermont-sourced soil sample; closeMatch to generic ENVO:00001998 soil."),
]


def _load_lock_manager():
    spec = importlib.util.spec_from_file_location(
        "lock_manager", CLAW_ROOT / "plugins" / "lock_manager.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LockManager


def curate_one(
    filename: str,
    envo_id: str,
    envo_label: str,
    quality: str,
    rationale: str,
    apply: bool,
) -> str:
    src = UNMAPPED / filename
    dst = MAPPED / filename
    if not src.exists():
        if dst.exists():
            return f"SKIP (already in mapped/): {filename}"
        return f"MISSING: {filename}"

    data = yaml.safe_load(src.read_text()) or {}

    data["identifier"] = envo_id
    data["ontology_mapping"] = {
        "ontology_id": envo_id,
        "ontology_label": envo_label,
        "ontology_source": "ENVO",
        "mapping_quality": quality,
        "evidence": [
            {
                "evidence_type": "CURATOR_JUDGMENT",
                "source": "cbclaw_envo_promotion",
                "notes": rationale,
            },
        ],
    }
    data["mapping_status"] = "MAPPED"

    history = data.get("curation_history") or []
    history.append({
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "curator": "cbclaw_envo_promotion",
        "action": "PROMOTED",
        "changes": (
            f"Promoted from UNMAPPED → MAPPED. Assigned {envo_id} "
            f"({envo_label}) from ENVO with mapping_quality={quality}. "
            f"Rationale: {rationale}"
        ),
        "new_status": "MAPPED",
        "llm_assisted": False,
    })
    data["curation_history"] = history

    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        src.unlink()

    return (
        f"CURATE{' [dry-run]' if not apply else ''}: {filename}  "
        f"→ {envo_id} ({envo_label})  [{quality}]"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    apply = args.apply and not args.dry_run

    if apply:
        LockManager = _load_lock_manager()
        locker = LockManager({"locks_dir": str(LOCKS_DIR), "my_id": "curate_envo_candidates"})
        if not locker.acquire_lock(
            "mediaingredientmech",
            operation="promote 6 ENVO candidates from unmapped→mapped",
            wait=True,
            max_wait=120,
        ):
            print("Could not acquire mediaingredientmech lock", file=sys.stderr)
            sys.exit(2)

    try:
        print(f"Curating {len(CURATIONS)} ENVO candidates"
              f"{' (DRY RUN)' if not apply else ''}:\n")
        for filename, envo_id, envo_label, quality, rationale in CURATIONS:
            print("  " + curate_one(filename, envo_id, envo_label, quality, rationale, apply))
        print(f"\n{'Wrote' if apply else 'Would write'} {len(CURATIONS)} ENVO promotions.")
    finally:
        if apply:
            locker.release_lock("mediaingredientmech")


if __name__ == "__main__":
    main()
