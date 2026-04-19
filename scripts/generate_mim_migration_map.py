#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Build a migration map: old MediaIngredientMech:000xxx numeric IDs that
kg-microbe still xrefs → current MIM:<slug> IDs (where determinable).

Input: workspace/reports/kgm_mim_audit.tsv (KGM_ONLY rows)
Output: workspace/reports/mim_numeric_namespace_migration.{tsv,md}

Actions:
  migrate     exactly one current MIM subject_id has the same CHEBI  → safe rename
  ambiguous   multiple MIM subject_ids share the CHEBI               → curator picks
  orphan      no current MIM subject_id has this CHEBI               → MIM has dropped
                                                                       this chemical; announce
                                                                       deprecation or add back
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
AUDIT_TSV = WORKSPACE / "reports/kgm_mim_audit.tsv"
MIM_SSSOM = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv"
)
OUT_TSV = WORKSPACE / "reports/mim_numeric_namespace_migration.tsv"
OUT_MD = WORKSPACE / "reports/mim_numeric_namespace_migration.md"

COLS = [
    "old_id", "kgm_chebi", "kgm_label", "new_mim_id",
    "new_mim_label", "action", "confidence", "ambiguous_candidates",
]


def load_mim_chebi_index() -> dict[str, list[tuple[str, str]]]:
    """CHEBI -> list of (mim_subject_id, subject_label)."""
    idx: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with MIM_SSSOM.open() as f:
        header: list[str] | None = None
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if header is None:
                header = parts
                continue
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            row = dict(zip(header, parts))
            obj = row.get("object_id", "")
            if not obj.startswith("CHEBI:"):
                continue
            idx[obj].append((row["subject_id"], row.get("subject_label", "")))
    return idx


def load_kgm_only_rows() -> list[dict]:
    with AUDIT_TSV.open() as f:
        return [r for r in csv.DictReader(f, delimiter="\t") if r["bucket"] == "KGM_ONLY"]


def classify(row: dict, mim_index: dict[str, list[tuple[str, str]]]) -> dict:
    kgm_chebi = row.get("kgm_chebi", "")
    mim_id = row.get("mim_id", "")
    kgm_label = row.get("kgm_label", "")

    if not kgm_chebi:
        return {
            "old_id": mim_id, "kgm_chebi": "", "kgm_label": kgm_label,
            "new_mim_id": "", "new_mim_label": "",
            "action": "orphan", "confidence": "low",
            "ambiguous_candidates": "",
        }

    candidates = mim_index.get(kgm_chebi, [])
    if len(candidates) == 1:
        new_id, new_label = candidates[0]
        # Higher confidence when the kgm label matches the MIM subject_label.
        match_strong = kgm_label and new_label and kgm_label.lower() in {
            new_label.lower(), new_label.lower().replace(" ", "-"),
        }
        return {
            "old_id": mim_id, "kgm_chebi": kgm_chebi, "kgm_label": kgm_label,
            "new_mim_id": new_id, "new_mim_label": new_label,
            "action": "migrate",
            "confidence": "high" if match_strong else "medium",
            "ambiguous_candidates": "",
        }
    elif len(candidates) > 1:
        return {
            "old_id": mim_id, "kgm_chebi": kgm_chebi, "kgm_label": kgm_label,
            "new_mim_id": "", "new_mim_label": "",
            "action": "ambiguous", "confidence": "low",
            "ambiguous_candidates": "|".join(f"{c[0]}" for c in candidates),
        }
    else:
        return {
            "old_id": mim_id, "kgm_chebi": kgm_chebi, "kgm_label": kgm_label,
            "new_mim_id": "", "new_mim_label": "",
            "action": "orphan", "confidence": "low",
            "ambiguous_candidates": "",
        }


def write_tsv(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in COLS) + "\n")


def write_md(path: Path, rows: list[dict]) -> None:
    by_action = defaultdict(int)
    by_confidence = defaultdict(int)
    for r in rows:
        by_action[r["action"]] += 1
        by_confidence[r["confidence"]] += 1

    out: list[str] = []
    out.append("# MIM Numeric-Namespace Migration Map")
    out.append("")
    out.append(f"**Total KGM_ONLY rows:** {len(rows)}")
    out.append("")

    out.append("## Action distribution")
    out.append("")
    out.append("| Action | Count |")
    out.append("|---|---:|")
    for a in ("migrate", "ambiguous", "orphan"):
        out.append(f"| {a} | {by_action.get(a, 0)} |")
    out.append("")

    out.append("## Confidence distribution")
    out.append("")
    out.append("| Confidence | Count |")
    out.append("|---|---:|")
    for c in ("high", "medium", "low"):
        out.append(f"| {c} | {by_confidence.get(c, 0)} |")
    out.append("")

    migrate_high = [r for r in rows if r["action"] == "migrate" and r["confidence"] == "high"][:20]
    if migrate_high:
        out.append("## Sample HIGH-confidence migrations (first 20)")
        out.append("")
        out.append("| Old id | CHEBI | kg-microbe label | → | New MIM id |")
        out.append("|---|---|---|---|---|")
        for r in migrate_high:
            out.append(
                f"| `{r['old_id']}` | {r['kgm_chebi']} | {r['kgm_label']} | → | `{r['new_mim_id']}` |"
            )
        out.append("")

    orphans = [r for r in rows if r["action"] == "orphan"][:15]
    if orphans:
        out.append("## Sample orphans (first 15) — MIM no longer covers this CHEBI")
        out.append("")
        out.append("| Old id | CHEBI | kg-microbe label |")
        out.append("|---|---|---|")
        for r in orphans:
            out.append(f"| `{r['old_id']}` | {r['kgm_chebi']} | {r['kgm_label']} |")
        out.append("")

    ambiguous = [r for r in rows if r["action"] == "ambiguous"][:10]
    if ambiguous:
        out.append("## Sample ambiguous (first 10)")
        out.append("")
        out.append("| Old id | CHEBI | Candidates |")
        out.append("|---|---|---|")
        for r in ambiguous:
            out.append(f"| `{r['old_id']}` | {r['kgm_chebi']} | {r['ambiguous_candidates']} |")
        out.append("")

    path.write_text("\n".join(out) + "\n")


def main() -> None:
    print("[1/3] Loading MIM SSSOM CHEBI index")
    mim_index = load_mim_chebi_index()
    print(f"      {len(mim_index)} unique CHEBIs in MIM")

    print("[2/3] Loading KGM_ONLY audit rows")
    rows = load_kgm_only_rows()
    print(f"      {len(rows)} rows")

    classified = [classify(r, mim_index) for r in rows]

    write_tsv(OUT_TSV, classified)
    write_md(OUT_MD, classified)
    print(f"[3/3] Wrote {OUT_TSV}")
    print(f"      Wrote {OUT_MD}")

    print("\nAction breakdown:")
    for a in ("migrate", "ambiguous", "orphan"):
        print(f"  {a:10s} {sum(1 for c in classified if c['action'] == a)}")


if __name__ == "__main__":
    main()
