#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Apply CHEBI fixes to MIM ingredient YAMLs.

Sources:
  1) workspace/patches/mim_chebi_recuration_patches.yaml
     — HIGH-confidence re-curations of 6 obsolete/removed CHEBIs.
     Applied as UPDATE to existing YAML (ontology_mapping + curation_history).

  2) workspace/reports/mim_curation_candidates.tsv
     — HIGH-confidence new ingredients from 430 UNMAPPED queue.
     Applied as CREATE: new YAML under data/ingredients/mapped/.

Guards:
  - Only HIGH-confidence items are applied. MEDIUM/LOW/NONE are skipped,
    listed in the dry-run report, and left for a curator.
  - CREATE refuses to overwrite an existing slug.
  - --dry-run (default) prints the plan. --apply performs the write.

This operates directly on MediaIngredientMech/data/ingredients/mapped/
— no lock acquisition, matching the existing apply_p44_synonym_enrichment.py
precedent.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
INGREDIENTS_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
RECURATION_YAML = WORKSPACE / "patches/mim_chebi_recuration_patches.yaml"
CANDIDATES_TSV = WORKSPACE / "reports/mim_curation_candidates.tsv"

TIMESTAMP = datetime.now(timezone.utc).isoformat()


def _slug(term: str) -> str:
    """Mimic the existing MIM slug style: capitalized words joined by underscores."""
    cleaned = re.sub(r"[^\w\s()\-]", "", term).strip()
    parts = re.split(r"[\s]+", cleaned)
    out_parts: list[str] = []
    for p in parts:
        if not p:
            continue
        out_parts.append(p[0].upper() + p[1:])
    return "_".join(out_parts) or "Unnamed"


def _update_existing_yaml(path: Path, patch: dict) -> tuple[bool, str]:
    """Return (applied, message)."""
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        return False, "not a dict"

    old_id = doc.get("ontology_mapping", {}).get("ontology_id")
    if old_id != patch["bad_chebi"]:
        return False, f"ontology_id is {old_id}, expected {patch['bad_chebi']}"

    doc["identifier"] = patch["new_chebi"]
    doc.setdefault("ontology_mapping", {})
    doc["ontology_mapping"]["ontology_id"] = patch["new_chebi"]
    doc["ontology_mapping"]["ontology_label"] = patch["new_label"]
    doc.setdefault("curation_history", []).append({
        "timestamp": TIMESTAMP,
        "curator": "audit_recurate_chebi",
        "action": patch["proposed_curation_entry"]["action"],
        "changes": patch["proposed_curation_entry"]["changes"],
        "new_status": "MAPPED",
        "llm_assisted": False,
    })
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"updated {old_id} -> {patch['new_chebi']}"


def _create_new_yaml(path: Path, source_id: str, term: str, chebi: str, label: str) -> tuple[bool, str]:
    if path.exists():
        return False, f"yaml already exists: {path.name}"

    doc = {
        "identifier": chebi,
        "preferred_term": term,
        "ontology_mapping": {
            "ontology_id": chebi,
            "ontology_label": label,
            "ontology_source": "CHEBI",
            "mapping_quality": "EXACT_MATCH",
            "evidence": [
                {
                    "evidence_type": "LEXICAL_MATCH",
                    "source": source_id,
                    "notes": (
                        "Auto-curated from UNMAPPED_PENDING_CURATION queue; "
                        "OLS exact-label match"
                    ),
                }
            ],
        },
        "synonyms": [],
        "mapping_status": "MAPPED",
        "occurrence_statistics": {
            "total_occurrences": 0,
            "media_count": 0,
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_propose_chebi_for_unmapped",
                "action": "CREATED_FROM_UNMAPPED_QUEUE",
                "changes": (
                    f"Created new ingredient from {source_id} with "
                    f"auto-curated CHEBI {chebi} ({label})"
                ),
                "new_status": "MAPPED",
                "llm_assisted": False,
            }
        ],
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"created {path.name} -> {chebi}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== {mode} ===\n")

    # 1) Re-curation patches (UPDATE)
    recur_patches = []
    if RECURATION_YAML.exists():
        recur_patches = yaml.safe_load(RECURATION_YAML.read_text()) or []
    high_recur = [p for p in recur_patches if p.get("confidence") == "HIGH"]
    print(f"Re-curation patches: {len(recur_patches)} total, {len(high_recur)} HIGH (applyable)")
    for p in recur_patches:
        marker = "APPLY" if p in high_recur else "SKIP"
        print(
            f"  [{marker}] {Path(p['file']).name} — {p['bad_chebi']} "
            f"-> {p['new_chebi'] or '—'} ({p['confidence']})"
        )
    print()

    # 2) Curation candidates (CREATE) — HIGH only
    candidates = []
    with CANDIDATES_TSV.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("confidence") == "HIGH" and r.get("candidate_1_chebi"):
                candidates.append(r)
    print(f"New-ingredient creates from HIGH candidates: {len(candidates)}")

    create_plan: list[tuple[str, str, str, str, Path]] = []
    skipped_creates: list[tuple[str, str, str]] = []
    for c in candidates:
        slug = _slug(c["preferred_term"])
        path = INGREDIENTS_DIR / f"{slug}.yaml"
        if path.exists():
            skipped_creates.append((slug, c["preferred_term"], "yaml already exists"))
            continue
        create_plan.append((c["source_id"], c["preferred_term"],
                            c["candidate_1_chebi"], c["candidate_1_label"], path))

    for src, term, chebi, label, path in create_plan:
        print(f"  [CREATE] {path.name} — {term} -> {chebi} ({label})")
    for slug, term, reason in skipped_creates:
        print(f"  [SKIP]   {slug}.yaml — {reason}")
    print()

    if not args.apply:
        print("DRY-RUN: no files changed. Rerun with --apply to commit.")
        return

    # APPLY
    print("--- Applying ---")
    up_ok = 0
    for p in high_recur:
        path = MIM_ROOT / p["file"]
        ok, msg = _update_existing_yaml(path, p)
        print(f"  UPDATE {path.name}: {'✓' if ok else '✗'} {msg}")
        if ok:
            up_ok += 1

    cr_ok = 0
    for src, term, chebi, label, path in create_plan:
        ok, msg = _create_new_yaml(path, src, term, chebi, label)
        print(f"  CREATE {path.name}: {'✓' if ok else '✗'} {msg}")
        if ok:
            cr_ok += 1

    print(f"\nDone. Updates: {up_ok}/{len(high_recur)}. Creates: {cr_ok}/{len(create_plan)}.")


if __name__ == "__main__":
    main()
