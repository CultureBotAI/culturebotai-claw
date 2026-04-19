#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Classify the 220 MIM CHEBIs-with-multiple-YAMLs into three groups:

  LEGITIMATE_VARIANTS  YAMLs differ in hydration state → keep (all valid
                       records mapping different surface forms to a shared
                       parent CHEBI).

  MERGEABLE_DUPES      YAMLs have the same normalized hydration state →
                       candidate for consolidation (two records for
                       effectively the same ingredient).

  MIXED                At least one YAML has an unknown hydration state;
                       needs curator inspection.

Output: workspace/reports/mim_duplicate_consolidation_queue.tsv
        workspace/reports/mim_duplicate_consolidation_queue.md

The TSV is sorted: MERGEABLE_DUPES first (highest-impact), then MIXED,
then LEGITIMATE_VARIANTS.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

MIM_MAPPED_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients/mapped"
)
WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
OUT_TSV = WORKSPACE / "reports/mim_duplicate_consolidation_queue.tsv"
OUT_MD = WORKSPACE / "reports/mim_duplicate_consolidation_queue.md"

# Hydration parser (same as in disambiguate_p44_hydration.py).
WORD_HYDRATES = {
    "anhydrous": 0,
    "monohydrate": 1, "hemihydrate": 1,
    "dihydrate": 2, "trihydrate": 3, "tetrahydrate": 4,
    "pentahydrate": 5, "hexahydrate": 6, "heptahydrate": 7,
    "octahydrate": 8, "nonahydrate": 9, "decahydrate": 10,
    "dodecahydrate": 12, "octadecahydrate": 18,
}
NUM_HYDRATE_RE = re.compile(
    r"(?:[x×.·・]\s*(\d+)\s*h(?:\s?\(|2)?o\b)|(?:(\d+)\s*h2o)",
    re.IGNORECASE,
)
HYDRATE_GENERIC = re.compile(r"\bhydrate\b", re.IGNORECASE)


def hydration_count(text: str) -> int | None:
    if not text:
        return None
    low = text.lower()
    for word, n in WORD_HYDRATES.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            return n
    m = NUM_HYDRATE_RE.search(text)
    if m:
        g = m.group(1) or m.group(2)
        try:
            return int(g)
        except (TypeError, ValueError):
            pass
    if HYDRATE_GENERIC.search(text):
        return -1
    return None


def main() -> None:
    by_chebi: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(MIM_MAPPED_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if not chebi.startswith("CHEBI:"):
            continue
        pt = doc.get("preferred_term", "") or ""
        pt_hydr = hydration_count(pt)
        file_hydr = hydration_count(path.stem)
        hydr = pt_hydr if pt_hydr is not None else file_hydr
        by_chebi[chebi].append({
            "file": path.name, "preferred_term": pt, "hydration": hydr,
            "occurrence": ((doc.get("occurrence_statistics") or {})
                           .get("total_occurrences", 0)),
        })

    dups = {k: v for k, v in by_chebi.items() if len(v) > 1}
    print(f"{len(dups)} CHEBIs with >1 MIM YAML "
          f"({sum(len(v) for v in dups.values())} YAMLs total)")

    rows = []
    for chebi, yamls in dups.items():
        hydrs = [y["hydration"] for y in yamls]
        unknown_count = sum(1 for h in hydrs if h is None)
        hydr_counter = Counter(h for h in hydrs if h is not None)

        # Classification:
        if unknown_count > 0:
            kind = "MIXED"
        elif all(v == 1 for v in hydr_counter.values()):
            kind = "LEGITIMATE_VARIANTS"  # every YAML has unique hydration state
        else:
            kind = "MERGEABLE_DUPES"     # two or more YAMLs share a hydration state

        # Build a per-hydration grouping of which files collide.
        by_hydr: dict[int | None, list[str]] = defaultdict(list)
        for y in yamls:
            by_hydr[y["hydration"]].append(y["file"])
        mergeable_groups = [files for h, files in by_hydr.items()
                            if h is not None and len(files) > 1]

        rows.append({
            "chebi": chebi,
            "yaml_count": len(yamls),
            "kind": kind,
            "hydration_states": "|".join(
                f"{h if h is not None else '?'}:{cnt}"
                for h, cnt in Counter(hydrs).most_common()
            ),
            "mergeable_group_count": len(mergeable_groups),
            "mergeable_files": "|".join(
                ",".join(g) for g in mergeable_groups
            ),
            "all_files": "|".join(y["file"] for y in yamls),
            "total_occurrences": sum(y["occurrence"] for y in yamls),
        })

    # Sort: MERGEABLE_DUPES first, then MIXED, then LEGITIMATE. Secondary: yaml_count desc.
    kind_order = {"MERGEABLE_DUPES": 0, "MIXED": 1, "LEGITIMATE_VARIANTS": 2}
    rows.sort(key=lambda r: (kind_order.get(r["kind"], 9), -r["yaml_count"]))

    cols = ["chebi", "kind", "yaml_count", "hydration_states",
            "mergeable_group_count", "mergeable_files",
            "total_occurrences", "all_files"]

    with OUT_TSV.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")
    print(f"Wrote {OUT_TSV}")

    # Markdown
    kind_counts = Counter(r["kind"] for r in rows)
    out = ["# MIM Duplicate-CHEBI Consolidation Queue\n",
           f"**Total duplicate-CHEBI groups:** {len(rows)}\n",
           f"**Total MIM YAMLs involved:** {sum(r['yaml_count'] for r in rows)}\n\n",
           "## Kind distribution\n",
           "| Kind | Count | Meaning |",
           "|---|---:|---|",
           f"| MERGEABLE_DUPES | {kind_counts.get('MERGEABLE_DUPES', 0)} | "
           f"≥2 YAMLs with matching hydration state — candidate consolidation |",
           f"| MIXED | {kind_counts.get('MIXED', 0)} | at least one YAML "
           f"has unknown hydration — curator inspection |",
           f"| LEGITIMATE_VARIANTS | {kind_counts.get('LEGITIMATE_VARIANTS', 0)} | "
           f"all YAMLs have distinct hydration states — keep as-is |",
           ""]

    mergeable = [r for r in rows if r["kind"] == "MERGEABLE_DUPES"]
    if mergeable:
        out.append(f"## Top 20 MERGEABLE_DUPES by total_occurrences\n")
        out.append("| CHEBI | # YAMLs | Hydration states | Mergeable groups | Occ |")
        out.append("|---|---:|---|---|---:|")
        for r in sorted(mergeable, key=lambda x: -x["total_occurrences"])[:20]:
            out.append(
                f"| {r['chebi']} | {r['yaml_count']} | "
                f"{r['hydration_states']} | {r['mergeable_files']} | "
                f"{r['total_occurrences']} |"
            )

    OUT_MD.write_text("\n".join(out) + "\n")
    print(f"Wrote {OUT_MD}")

    print("\nKind distribution:")
    for k, v in kind_counts.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
