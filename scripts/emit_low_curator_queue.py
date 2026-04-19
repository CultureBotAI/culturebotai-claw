#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Emit a curator-friendly TSV for the LOW-confidence hydrate-sibling
proposals (433 rows from workspace/reports/hydrate_sibling_proposals.json).

Each row shows: the (stem, hydration) group, a sample of candidate strings,
whether the top CHEBI is already used in MIM (so the curator knows whether
this is a "create new YAML" or "route to existing" case), and how many
UNRESOLVED synonyms are waiting on a decision.

Output: workspace/reports/mim_low_confidence_curation_queue.tsv
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
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
OUT_TSV = WORKSPACE / "reports/mim_low_confidence_curation_queue.tsv"

COLS = [
    "stem", "hydration", "candidate_count", "sample_candidates",
    "proposed_chebi", "proposed_label", "chebi_already_in_mim",
    "existing_mim_files", "source_files",
]


def _load_existing_chebi_index() -> dict[str, list[str]]:
    idx: dict[str, list[str]] = defaultdict(list)
    for path in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if chebi.startswith("CHEBI:"):
            idx[chebi].append(path.name)
    return idx


def main() -> None:
    proposals = json.loads(IN_JSON.read_text())["proposals"]
    low = [p for p in proposals if p["confidence"] == "LOW"]
    existing = _load_existing_chebi_index()

    # Sort by candidate_count desc — curator should tackle high-impact groups first.
    low.sort(key=lambda p: -p["candidate_count"])

    with OUT_TSV.open("w") as f:
        f.write("\t".join(COLS) + "\n")
        for p in low:
            chebi = p["chebi"]
            exist_files = existing.get(chebi, [])
            row = {
                "stem": p["stem"],
                "hydration": str(p["hydration"]) if p["hydration"] is not None else "?",
                "candidate_count": str(p["candidate_count"]),
                "sample_candidates": "|".join(p.get("sample_candidates", [])[:5]),
                "proposed_chebi": chebi,
                "proposed_label": p.get("label", ""),
                "chebi_already_in_mim": "yes" if exist_files else "no",
                "existing_mim_files": "|".join(exist_files[:3]) + (
                    f"|...+{len(exist_files) - 3}" if len(exist_files) > 3 else ""
                ),
                "source_files": "|".join(p.get("source_files", [])[:3]) + (
                    f"|...+{len(p.get('source_files', [])) - 3}"
                    if len(p.get("source_files", [])) > 3 else ""
                ),
            }
            f.write("\t".join(row[c] for c in COLS) + "\n")

    print(f"Wrote {OUT_TSV} ({len(low)} LOW proposals)")
    already = sum(1 for p in low if existing.get(p["chebi"]))
    print(f"  {already} proposals have CHEBI already in MIM (route to existing)")
    print(f"  {len(low) - already} proposals have novel CHEBI (create new YAML)")


if __name__ == "__main__":
    main()
