#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Create new MIM sibling YAMLs for HIGH-confidence hydrate/anhydrous
proposals, and route the UNRESOLVED P4.4 candidates into them.

Input:  workspace/reports/hydrate_sibling_proposals.json  (HIGH only)
Output: data/ingredients/mapped/<Slug>.yaml  (new files)

Each new YAML is seeded with:
  - identifier + ontology_mapping.ontology_id = proposed CHEBI
  - preferred_term = CHEBI label (title-case)
  - all UNRESOLVED candidate strings as EXACT_SYNONYMs (source=kg_microbe)
  - curation_history entry = CREATED_FROM_HYDRATE_SIBLING_PROPOSAL

Guards:
  - refuses to overwrite an existing slug (reports it)
  - only HIGH confidence is acted on; MEDIUM/LOW/NONE stay in the file
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

MIM_MAPPED_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients/mapped"
)
WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
IN_JSON = WORKSPACE / "reports/hydrate_sibling_proposals.json"

TIMESTAMP = datetime.now(timezone.utc).isoformat()


def _slug(label: str) -> str:
    cleaned = re.sub(r"[^\w\s()\-]", "", label).strip()
    parts = [p for p in re.split(r"\s+", cleaned) if p]
    return "_".join(p[0].upper() + p[1:] if p else "" for p in parts) or "Unnamed"


def _create_yaml(path: Path, proposal: dict) -> tuple[bool, str]:
    if path.exists():
        return False, f"{path.name} already exists"

    cands = proposal.get("all_candidates") or proposal.get("sample_candidates") or []
    # Use the CHEBI label for preferred_term; fall back to the first candidate.
    label = proposal.get("label") or (cands[0] if cands else path.stem)
    chebi = proposal["chebi"]
    sources = proposal.get("source_files", [])

    doc = {
        "identifier": chebi,
        "preferred_term": label,
        "ontology_mapping": {
            "ontology_id": chebi,
            "ontology_label": label,
            "ontology_source": "CHEBI",
            "mapping_quality": "EXACT_MATCH",
            "evidence": [
                {
                    "evidence_type": "LEXICAL_MATCH",
                    "source": "hydrate_sibling_proposal",
                    "notes": (
                        f"Auto-created to receive hydration-routing "
                        f"synonyms re-routed from: "
                        f"{', '.join(sorted(set(sources))[:3])}"
                        + (f" (+{len(set(sources)) - 3} more)" if len(set(sources)) > 3 else "")
                    ),
                }
            ],
        },
        "synonyms": [
            {"synonym_text": c, "synonym_type": "EXACT_SYNONYM",
             "source": "kg_microbe_via_hydration_routing"}
            for c in sorted(set(cands))
        ],
        "mapping_status": "MAPPED",
        "occurrence_statistics": {
            "total_occurrences": len(cands),
            "media_count": 0,
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_hydrate_sibling_creator",
                "action": "CREATED_FROM_HYDRATE_SIBLING_PROPOSAL",
                "changes": (
                    f"Created new MIM record for {chebi} ({label}); "
                    f"seeded with {len(cands)} synonyms from P4.4 "
                    f"UNRESOLVED hydration-mismatch queue"
                ),
                "new_status": "MAPPED",
                "llm_assisted": False,
            }
        ],
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"created {path.name} with {len(cands)} synonyms -> {chebi}"


def _load_existing_chebi_index() -> dict[str, list[str]]:
    """CHEBI -> list of existing MIM YAML filenames using that CHEBI."""
    idx: dict[str, list[str]] = {}
    for path in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if chebi and chebi.startswith("CHEBI:"):
            idx.setdefault(chebi, []).append(path.name)
    return idx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data = json.loads(IN_JSON.read_text())
    high = [p for p in data["proposals"] if p["confidence"] == "HIGH"]
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(high)} HIGH proposals\n")

    # Index existing MIM YAMLs by CHEBI so we skip creating duplicates.
    existing = _load_existing_chebi_index()
    print(f"Indexed {sum(len(v) for v in existing.values())} existing MIM YAMLs "
          f"({len(existing)} unique CHEBIs)\n")

    # Dedupe by CHEBI — two groups can propose the same CHEBI (synonym-only
    # differences). Merge their candidate lists into one new YAML per CHEBI.
    by_chebi: dict[str, dict] = {}
    for p in high:
        chebi = p["chebi"]
        if chebi not in by_chebi:
            by_chebi[chebi] = {
                "chebi": chebi, "label": p["label"],
                "all_candidates": [], "source_files": [],
            }
        by_chebi[chebi]["all_candidates"].extend(p.get("all_candidates", []))
        by_chebi[chebi]["source_files"].extend(p.get("source_files", []))

    ok = 0
    skipped = 0
    chebi_collisions = 0
    for chebi, merged in sorted(by_chebi.items()):
        slug = _slug(merged["label"])
        path = MIM_MAPPED_DIR / f"{slug}.yaml"
        n_cands = len(set(merged["all_candidates"]))

        if path.exists():
            print(f"  [SKIP]   {path.name} — already exists")
            skipped += 1
            continue

        if chebi in existing:
            print(f"  [SKIP]   {path.name} — CHEBI {chebi} already used by "
                  f"{len(existing[chebi])} existing MIM yaml(s): "
                  f"{', '.join(existing[chebi][:3])}")
            chebi_collisions += 1
            continue

        if args.apply:
            done, msg = _create_yaml(path, merged)
            marker = "✓" if done else "✗"
            print(f"  [APPLY]  {path.name}: {marker} {msg}")
            if done:
                ok += 1
        else:
            print(f"  [PLAN]   {path.name} ← {chebi} ({merged['label']}), "
                  f"+{n_cands} synonyms from {len(set(merged['source_files']))} sources")

    print()
    if args.apply:
        print(f"DONE. Created {ok}/{len(by_chebi)} YAMLs "
              f"({skipped} slug collisions, {chebi_collisions} CHEBI collisions).")
    else:
        print(f"DRY-RUN. Would create {len(by_chebi) - skipped - chebi_collisions} "
              f"YAMLs ({skipped} slug collisions, {chebi_collisions} CHEBI collisions).")


if __name__ == "__main__":
    main()
