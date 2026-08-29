#!/usr/bin/env python3
"""
Report MIM records that share a CHEBI ID — a signal of duplicate
ingredient entries that should be consolidated.

Surfaces two distinct signals:

  a) Multiple MIM YAMLs with the same ontology_id in ontology_mapping.
     (Intentional for hydrate/anhydrous pairs sharing a CHEBI parent;
      unintentional for exact duplicates.)

  b) HIGH-confidence hydrate-sibling proposals that were NOT created
     because their target CHEBI was already used in MIM. These mark
     the compounds where hydration-specific synonyms should be routed
     to an existing record rather than becoming a new one.

Output: workspace/reports/mim_chebi_duplication_review.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
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
PROPOSALS = WORKSPACE / "reports/hydrate_sibling_proposals.json"
OUT_MD = WORKSPACE / "reports/mim_chebi_duplication_review.md"


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    # (a) All MIM YAMLs grouped by CHEBI
    by_chebi: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in sorted(MIM_MAPPED_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if chebi.startswith("CHEBI:"):
            by_chebi[chebi].append((path.name, doc.get("preferred_term", "")))

    dups = {k: v for k, v in by_chebi.items() if len(v) > 1}
    print(f"{len(dups)} CHEBIs used by >1 MIM YAML")

    # (b) HIGH hydrate-sibling proposals that collided with existing CHEBIs
    proposals = json.loads(PROPOSALS.read_text())["proposals"]
    high_collisions = []
    for p in proposals:
        if p["confidence"] != "HIGH":
            continue
        chebi = p["chebi"]
        if chebi in by_chebi and len(by_chebi[chebi]) >= 1:
            # Collision = CHEBI was already in MIM (any count).
            high_collisions.append({
                "chebi": chebi, "label": p["label"],
                "existing": by_chebi[chebi],
                "unresolved_candidates": p.get("all_candidates", []),
                "source_files": p.get("source_files", []),
                "cand_count": p.get("candidate_count", 0),
            })

    # Write report
    out = ["# MIM CHEBI Duplication Review\n"]
    out.append("## (a) CHEBIs with multiple MIM YAMLs\n")
    out.append(f"**Total:** {len(dups)} CHEBIs ({sum(len(v) for v in dups.values())} YAMLs)\n")
    out.append("These are often legitimate hydrate/anhydrous pairs sharing the\n"
               "same parent CHEBI, but some are true duplicates needing\n"
               "consolidation. Worth a one-time curator pass.\n")
    out.append("| CHEBI | # YAMLs | Files |")
    out.append("|---|---:|---|")
    for chebi in sorted(dups, key=lambda c: -len(dups[c]))[:50]:
        files = ", ".join(f"`{f[0]}`" for f in dups[chebi][:4])
        if len(dups[chebi]) > 4:
            files += f", ... (+{len(dups[chebi]) - 4} more)"
        out.append(f"| {chebi} | {len(dups[chebi])} | {files} |")
    out.append("")

    out.append("## (b) HIGH-confidence hydrate-sibling proposals blocked by CHEBI collision\n")
    out.append(f"**Total:** {len(high_collisions)} (representing "
               f"{sum(c['cand_count'] for c in high_collisions)} UNRESOLVED synonyms)\n")
    out.append("Each row below has a well-resolved CHEBI but MIM already uses it\n"
               "elsewhere — usually because hydration variants were pre-created\n"
               "under the same parent CHEBI. The synonyms need to be routed to\n"
               "whichever existing YAML matches the specific hydration state.\n")
    out.append("| CHEBI | Label | Existing MIM files | # UNRESOLVED candidates |")
    out.append("|---|---|---|---:|")
    for c in sorted(high_collisions, key=lambda x: -x["cand_count"]):
        files = ", ".join(f"`{f[0]}`" for f in c["existing"][:3])
        if len(c["existing"]) > 3:
            files += f", ... (+{len(c['existing']) - 3} more)"
        out.append(f"| {c['chebi']} | {c['label']} | {files} | {c['cand_count']} |")
    out.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(out) + "\n")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
