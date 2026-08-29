#!/usr/bin/env python3
"""
Apply ROUTE_* resolutions from disambiguate_p44_hydration.py — adds each
re-routed synonym to its correct MIM hydrate/anhydrous YAML.

Only resolutions with resolution ∈ {ROUTE_TO_HYDRATE, ROUTE_TO_ANHYDROUS,
ROUTE_TO_UNKNOWN_HYDRATE} are applied. AMBIGUOUS_TARGETS and UNRESOLVED
are left for human curation.

Guards: skip if candidate text is already present on the target
(preferred_term / ontology_label / any existing synonym).

Modes:
  --dry-run (default)  print the plan per file
  --apply              actually write YAMLs
"""

from __future__ import annotations

import os
import sys
import argparse
import json
from collections import defaultdict
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
MIM_MAPPED_DIR = MIM_ROOT / "data/ingredients/mapped"
WORKSPACE = REPO_ROOT / "workspace"
IN_JSON = WORKSPACE / "reports/p44_hydration_resolution.json"

ROUTABLE = {"ROUTE_TO_HYDRATE", "ROUTE_TO_ANHYDROUS", "ROUTE_TO_UNKNOWN_HYDRATE"}
TIMESTAMP = datetime.now(timezone.utc).isoformat()


def _apply_to_yaml(path: Path, candidates: list[str], source_files: list[str]) -> int:
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        return 0

    existing = {
        (s.get("synonym_text", "") or "").strip().lower()
        for s in (doc.get("synonyms") or [])
        if isinstance(s, dict)
    }
    existing.add(str(doc.get("preferred_term", "")).strip().lower())
    existing.add(
        str((doc.get("ontology_mapping") or {}).get("ontology_label", ""))
        .strip().lower()
    )

    new = []
    added = []
    for c in candidates:
        if c.strip().lower() in existing:
            continue
        new.append({
            "synonym_text": c,
            "synonym_type": "EXACT_SYNONYM",
            "source": "kg_microbe_via_hydration_routing",
        })
        added.append(c)
        existing.add(c.strip().lower())

    if not new:
        return 0

    doc.setdefault("synonyms", []).extend(new)
    preview = ", ".join(added[:5])
    if len(added) > 5:
        preview += f", ... ({len(added) - 5} more)"
    source_preview = ", ".join(sorted(set(source_files))[:3])
    if len(set(source_files)) > 3:
        source_preview += f", ... (+{len(set(source_files)) - 3} more)"

    doc.setdefault("curation_history", []).append({
        "timestamp": TIMESTAMP,
        "curator": "audit_p44_hydration_routing",
        "action": "ADDED_SYNONYMS_VIA_HYDRATION_ROUTING",
        "changes": (
            f"Added {len(added)} synonyms re-routed from anhydrous/hydrate "
            f"sibling records ({source_preview}): {preview}"
        ),
        "new_status": doc.get("mapping_status", "MAPPED"),
        "llm_assisted": False,
    })
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return len(added)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)


    data = json.loads(IN_JSON.read_text())
    routable = [r for r in data["resolutions"] if r["resolution"] in ROUTABLE]
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(routable)} routable resolutions\n")

    # Group by target_file so we touch each YAML once.
    by_target: dict[str, list[dict]] = defaultdict(list)
    for r in routable:
        by_target[r["target_file"]].append(r)

    total_cands = 0
    total_ok = 0
    for target, rs in sorted(by_target.items()):
        path = MIM_MAPPED_DIR / target
        if not path.exists():
            print(f"  [MISSING] {target}")
            continue
        cands = [r["candidate"] for r in rs]
        sources = [r["source_file"] for r in rs]
        total_cands += len(cands)

        if args.apply:
            n = _apply_to_yaml(path, cands, sources)
            total_ok += n
            print(f"  [APPLY]  {target}: +{n}/{len(cands)}")
        else:
            preview = ", ".join(cands[:3])
            if len(cands) > 3:
                preview += f", ... ({len(cands) - 3} more)"
            print(f"  [PLAN]   {target}: +{len(cands)} ({preview})")

    print()
    if args.apply:
        print(f"DONE. {total_ok}/{total_cands} synonyms added across {len(by_target)} files.")
    else:
        print(f"DRY-RUN. Would add up to {total_cands} synonyms across {len(by_target)} files.")


if __name__ == "__main__":
    main()
