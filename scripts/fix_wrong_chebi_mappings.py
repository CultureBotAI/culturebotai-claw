"""Batch-fix MIM ingredient YAMLs whose `ontology_mapping.ontology_id` is
a wrong CHEBI ID, as surfaced by the SSSOM synonym review
(workspace/reports/sssom_suspect_mappings.md).

For each fix:
  * update `identifier`, `ontology_mapping.ontology_id`, `ontology_mapping.ontology_label`
  * strip `synonyms[]` entries with source=kg_microbe (those were pulled in
    by the P4.4 sweep against the WRONG CHEBI and are therefore
    contaminated; a future sweep against the corrected CHEBI will
    re-populate them correctly)
  * append a `curation_history` entry recording the correction

Acquires the `mediaingredientmech` lock via plugins.lock_manager.LockManager
before any writes. Default is --dry-run.
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
MAPPED_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"
LOCKS_DIR = CLAW_ROOT / "workspace" / "locks"

# (yaml_filename, new_chebi_id, new_ontology_label, reason)
# Reasons cite the OLS search query that surfaced the correct CHEBI.
FIXES: list[tuple[str, str, str, str]] = [
    ("Aces.yaml", "CHEBI:39061", "ACES",
     "Previous CHEBI:65994 was 'gypsosaponin C' — unrelated compound."),
    ("Eisencitrat.yaml", "CHEBI:144421", "iron(III) citrate",
     "Previous CHEBI:55553 was a nucleotide. Eisencitrat = iron(III) citrate."),
    ("Ethanol_Absolute.yaml", "CHEBI:16236", "ethanol",
     "Previous CHEBI:64175 was a mannose oligosaccharide — unrelated."),
    ("Ferric_Citrate.yaml", "CHEBI:144421", "iron(III) citrate",
     "Previous CHEBI:61300 was a mannose polymer — unrelated."),
    ("Folinic_Acid.yaml", "CHEBI:15640", "5-formyltetrahydrofolic acid",
     "Previous CHEBI:42521 no longer resolves in CHEBI."),
    ("Hepes_Buffer.yaml", "CHEBI:46756", "HEPES",
     "Previous CHEBI:19708 is obsolete in current CHEBI release."),
    ("Histidine.yaml", "CHEBI:15971", "L-histidine",
     "Previous CHEBI:27676 was L-histidinal (aldehyde), not L-histidine."),
    ("Iso-valeric_Acid.yaml", "CHEBI:28484", "isovaleric acid",
     "Previous CHEBI:503742 no longer resolves in CHEBI."),
    ("L-cysteine_Hcl.yaml", "CHEBI:91247", "L-cysteine hydrochloride",
     "Previous CHEBI:52891 was QSY9 succinimidyl ester — unrelated."),
    ("L-sodium_Lactate.yaml", "CHEBI:232798", "sodium L-lactate",
     "Previous CHEBI:867561 no longer resolves in CHEBI."),
    ("Nh42hpo4.yaml", "CHEBI:63051", "diammonium hydrogen phosphate",
     "Previous CHEBI:62476 was a sugar — unrelated."),
    ("Phenyl_Propionic_Acid.yaml", "CHEBI:28631", "3-phenylpropionic acid",
     "Previous CHEBI:501520 no longer resolves in CHEBI."),
    ("Pyruvic_Acid_Sodium_Salt.yaml", "CHEBI:50144", "sodium pyruvate",
     "Previous CHEBI:113246 was a triazine — unrelated."),
    ("Starch_soluble.yaml", "CHEBI:28017", "starch",
     "Previous CHEBI:18167 was alpha-maltose, not starch."),
    ("Sulfur_Powder.yaml", "CHEBI:33403", "elemental sulfur",
     "Previous CHEBI:14258 is obsolete in current CHEBI release."),
    ("Sulfur_Powder_2.yaml", "CHEBI:33403", "elemental sulfur",
     "Previous CHEBI:14258 is obsolete in current CHEBI release."),
    ("Sulfur_Powder_3.yaml", "CHEBI:33403", "elemental sulfur",
     "Previous CHEBI:14258 is obsolete in current CHEBI release."),
    ("Sulfur_Powder_4.yaml", "CHEBI:33403", "elemental sulfur",
     "Previous CHEBI:14258 is obsolete in current CHEBI release."),
    ("Tween_20.yaml", "CHEBI:53424", "polysorbate 20",
     "Previous CHEBI:9784 no longer resolves in CHEBI."),
]


def _load_lock_manager():
    spec = importlib.util.spec_from_file_location(
        "lock_manager", CLAW_ROOT / "plugins" / "lock_manager.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LockManager


def apply_fix(path: Path, new_chebi: str, new_label: str, reason: str,
              apply: bool) -> str:
    """Mutate a single YAML. Returns a human-readable diff summary."""
    if not path.exists():
        return f"SKIP (missing): {path.name}"

    data = yaml.safe_load(path.read_text()) or {}
    om = data.get("ontology_mapping") or {}
    old_chebi = om.get("ontology_id") or data.get("identifier") or "?"
    old_label = om.get("ontology_label") or ""

    if old_chebi == new_chebi and old_label == new_label:
        return f"NO-OP: {path.name} already at {new_chebi}"

    # Update identifier + ontology_mapping
    data["identifier"] = new_chebi
    om["ontology_id"] = new_chebi
    om["ontology_label"] = new_label
    data["ontology_mapping"] = om

    # Strip kg_microbe-sourced synonyms — they were pulled against the
    # WRONG CHEBI so they're contaminated. A fresh sweep will re-add
    # whatever belongs to the correct CHEBI.
    syns = data.get("synonyms") or []
    kept = [s for s in syns if (s.get("source") or "") != "kg_microbe"]
    dropped_count = len(syns) - len(kept)
    data["synonyms"] = kept

    # Append curation_history
    history = data.get("curation_history") or []
    history.append({
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "curator": "cbclaw_sssom_review_fix",
        "action": "CORRECTED_ONTOLOGY_ID",
        "changes": (
            f"Corrected ontology_id {old_chebi} -> {new_chebi} "
            f"(old label: {old_label!r}, new label: {new_label!r}). "
            f"Reason: {reason} "
            f"Stripped {dropped_count} kg_microbe-sourced synonyms that were "
            f"contaminated by the wrong CHEBI."
        ),
        "new_status": data.get("mapping_status", "MAPPED"),
        "llm_assisted": False,
    })
    data["curation_history"] = history

    if apply:
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))

    return (
        f"FIX{' [dry-run]' if not apply else ''}: {path.name}  "
        f"{old_chebi} -> {new_chebi}  "
        f"({old_label!r} -> {new_label!r})  "
        f"stripped {dropped_count} contaminated syns"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--dry-run", action="store_true", help="(default)")
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    apply = args.apply and not args.dry_run

    if apply:
        LockManager = _load_lock_manager()
        locker = LockManager({"locks_dir": str(LOCKS_DIR), "my_id": "fix_wrong_chebi_mappings"})
        if not locker.acquire_lock(
            "mediaingredientmech",
            operation="fix wrong CHEBI IDs surfaced by SSSOM review",
            wait=True,
            max_wait=300,
        ):
            print("Could not acquire mediaingredientmech lock", file=sys.stderr)
            sys.exit(2)

    try:
        print(f"Applying {len(FIXES)} CHEBI corrections"
              f"{' (DRY RUN)' if not apply else ''}:\n")
        for yml, chebi, label, reason in FIXES:
            msg = apply_fix(MAPPED_DIR / yml, chebi, label, reason, apply)
            print("  " + msg)
        print(f"\n{'Wrote' if apply else 'Would write'} {len(FIXES)} YAMLs.")
    finally:
        if apply:
            locker.release_lock("mediaingredientmech")


if __name__ == "__main__":
    main()
