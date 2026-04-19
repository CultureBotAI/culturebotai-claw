#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Emit a merge plan for the MERGEABLE_DUPES from the MIM duplicate-CHEBI
consolidation queue.

For each duplicate-CHEBI group where two or more YAMLs share the same
hydration state, pick one "winner" and mark the rest as "losers" to be
merged in.

Winner selection (deterministic, no ties):
  1. Highest occurrence_statistics.total_occurrences (most-cited record)
  2. Tie-break: preferred_term looks human-readable (contains a word
     character plus a space — distinguishes "Magnesium sulfate heptahydrate"
     from formula-like slugs "Mgso47h2o")
  3. Tie-break: longest preferred_term (usually more specific/descriptive)
  4. Tie-break: alphabetical (deterministic)

For each merge, enumerate what would be combined:
  - synonyms       union-dedup across winner + losers
  - curation_history  concatenated in chronological order
  - occurrence_statistics  summed
  - chemical_properties   winner's kept; losers' values flagged if they differ

Output:
  workspace/reports/mim_merge_plan.tsv     one row per winner, with losers listed
  workspace/reports/mim_merge_plan.md      human-readable summary

No files are deleted or modified — the plan is generated only.
"""

from __future__ import annotations

import re
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
OUT_TSV = WORKSPACE / "reports/mim_merge_plan.tsv"
OUT_MD = WORKSPACE / "reports/mim_merge_plan.md"

# Hydration parser — inlined (same as disambiguate_p44_hydration.py).
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


WORD_LIKE_RE = re.compile(r"\b[A-Za-z]{3,}\b")


def _is_word_form(pt: str) -> bool:
    """True when preferred_term looks like a descriptive name (not a formula slug)."""
    if not pt:
        return False
    words = WORD_LIKE_RE.findall(pt)
    return len(words) >= 2


def _score(y: dict) -> tuple:
    """Sort key: higher is better (negated for ascending sort)."""
    return (
        -y["occurrences"],             # most-cited first
        -int(_is_word_form(y["pt"])),  # word-form preferred
        -len(y["pt"] or ""),           # more descriptive
        y["file"],                     # deterministic
    )


def _load_yamls_by_chebi() -> dict[str, list[dict]]:
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
            "file": path.name,
            "pt": pt,
            "hydration": hydr,
            "occurrences": ((doc.get("occurrence_statistics") or {})
                            .get("total_occurrences", 0)),
            "synonym_count": len(doc.get("synonyms") or []),
            "cas_rn": (doc.get("chemical_properties") or {}).get("cas_rn", ""),
        })
    return by_chebi


def main() -> None:
    by_chebi = _load_yamls_by_chebi()

    merges: list[dict] = []
    for chebi, yamls in by_chebi.items():
        if len(yamls) < 2:
            continue
        # Group by hydration count; we only merge YAMLs with the SAME state.
        by_hyd: dict[int | None, list[dict]] = defaultdict(list)
        for y in yamls:
            by_hyd[y["hydration"]].append(y)
        for hyd, group in by_hyd.items():
            if hyd is None or len(group) < 2:
                continue
            ranked = sorted(group, key=_score)
            winner = ranked[0]
            losers = ranked[1:]
            merges.append({
                "chebi": chebi,
                "hydration": hyd,
                "winner": winner["file"],
                "winner_pt": winner["pt"],
                "winner_occ": winner["occurrences"],
                "winner_cas_rn": winner["cas_rn"],
                "losers": [l["file"] for l in losers],
                "loser_pts": [l["pt"] for l in losers],
                "total_occurrences": sum(y["occurrences"] for y in group),
                "total_synonyms_pre": sum(y["synonym_count"] for y in group),
                "cas_rn_conflicts": sorted({y["cas_rn"] for y in group if y["cas_rn"]}),
            })

    # Summary
    print(f"{len(merges)} merge operations planned "
          f"({sum(len(m['losers']) for m in merges)} YAMLs to collapse)")

    # TSV
    cols = ["chebi", "hydration", "winner", "winner_pt", "winner_occ",
            "loser_count", "losers", "loser_pts",
            "total_occurrences", "total_synonyms_pre", "cas_rn_conflicts"]
    with OUT_TSV.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for m in sorted(merges, key=lambda x: -x["total_occurrences"]):
            f.write("\t".join([
                m["chebi"],
                str(m["hydration"]),
                m["winner"],
                m["winner_pt"],
                str(m["winner_occ"]),
                str(len(m["losers"])),
                "|".join(m["losers"]),
                "|".join(m["loser_pts"]),
                str(m["total_occurrences"]),
                str(m["total_synonyms_pre"]),
                "|".join(m["cas_rn_conflicts"]),
            ]) + "\n")
    print(f"Wrote {OUT_TSV}")

    # MD
    out = [
        "# MIM Merge Plan\n",
        f"**Proposed merge operations:** {len(merges)}\n",
        f"**YAMLs to collapse:** {sum(len(m['losers']) for m in merges)} "
        f"(of 758 in duplicate-CHEBI groups)\n\n",
        "Each row is one merge. The **winner** is the YAML that keeps "
        "its slug; losers' synonyms, curation_history, and occurrence "
        "counts roll into the winner. Winner = highest occurrences, "
        "tie-break by word-form preferred_term, then term length, then "
        "alphabetical.\n\n",
        "CAS-RN conflicts are flagged — if two records disagree on "
        "chemical_properties.cas_rn, a curator must pick before merging.\n\n",
    ]

    # Group merges by risk tier.
    safe = [m for m in merges if len(m["cas_rn_conflicts"]) <= 1]
    risky = [m for m in merges if len(m["cas_rn_conflicts"]) > 1]

    out.append(f"## Safe merges ({len(safe)}) — ≤1 distinct CAS-RN across group\n\n")
    out.append("| CHEBI | Hydration | Winner | Losers | Loser count | Total occ |")
    out.append("|---|---|---|---|---:|---:|")
    for m in sorted(safe, key=lambda x: -x["total_occurrences"]):
        losers_preview = ", ".join(f"`{l}`" for l in m["losers"][:3])
        if len(m["losers"]) > 3:
            losers_preview += f", +{len(m['losers']) - 3} more"
        out.append(
            f"| {m['chebi']} | {m['hydration']} | `{m['winner']}` "
            f"({m['winner_pt']}) | {losers_preview} | {len(m['losers'])} | "
            f"{m['total_occurrences']} |"
        )
    out.append("")

    if risky:
        out.append(f"## Risky merges ({len(risky)}) — >1 distinct CAS-RN "
                   f"across group (curator decision)\n\n")
        out.append("| CHEBI | Hydration | Winner | Losers | CAS-RN values |")
        out.append("|---|---|---|---|---|")
        for m in sorted(risky, key=lambda x: -x["total_occurrences"]):
            out.append(
                f"| {m['chebi']} | {m['hydration']} | `{m['winner']}` | "
                f"{', '.join(f'`{l}`' for l in m['losers'])} | "
                f"{', '.join(m['cas_rn_conflicts'])} |"
            )
        out.append("")

    out.append("## What a merge does (when applied)\n\n")
    out.append("For each `(winner, [losers])` pair:\n")
    out.append("1. Union-dedup `synonyms` from all records into winner.\n")
    out.append("2. Concatenate `curation_history` entries in timestamp order.\n")
    out.append("3. Sum `occurrence_statistics.{total_occurrences, media_count}`.\n")
    out.append("4. Keep winner's `chemical_properties`; flag any CAS-RN "
               "divergence in a new curation_history entry.\n")
    out.append("5. Add a `MERGED_FROM_DUPLICATES` curation_history entry "
               "listing the loser filenames.\n")
    out.append("6. Delete loser YAML files (git rm).\n\n")
    out.append("Apply step is a separate script (not yet written) — "
               "this plan is no-apply by design.\n")

    OUT_MD.write_text("\n".join(out) + "\n")
    print(f"Wrote {OUT_MD}")

    if risky:
        print(f"  {len(safe)} safe, {len(risky)} risky (CAS-RN conflicts)")


if __name__ == "__main__":
    main()
