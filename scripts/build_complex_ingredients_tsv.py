#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Build workspace/reports/complex_ingredients.tsv.gz — the concrete artifact
proposed in docs/proposals/kg_microbe_dict_extend_beyond_chebi.md.

Schema mirrors kg-microbe's unified_chemical_mappings.tsv.gz:
  id, category, canonical_name, formula, synonyms, xrefs, sources

Contents: one row per non-CHEBI MIM ingredient (currently 19 FOODON/ENVO
entries). Ready to be added to kg-microbe's mappings/ alongside the
existing CHEBI-only unified_chemical_mappings.tsv.gz.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
from pathlib import Path

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
MIM_SSSOM = MIM_ROOT / "mappings/ingredient_mappings.sssom.tsv"
OUT_GZ = WORKSPACE / "reports/complex_ingredients.tsv.gz"
OUT_TSV_PREVIEW = WORKSPACE / "reports/complex_ingredients_preview.tsv"
# Canonical published copies in the MIM repo.
PUBLISH_GZ = MIM_ROOT / "mappings/complex_ingredients.tsv.gz"
PUBLISH_TSV = MIM_ROOT / "mappings/complex_ingredients.tsv"

COLS = ["id", "category", "canonical_name", "formula", "synonyms", "xrefs", "sources"]

CATEGORY_FOR_PREFIX = {
    "FOODON": "biolink:ChemicalMixture",
    "ENVO":   "biolink:EnvironmentalMaterial",
    "UBERON": "biolink:AnatomicalEntity",
}


def load_non_chebi_mim() -> list[dict]:
    """Read MIM SSSOM; return non-CHEBI rows grouped per object_id."""
    rows: list[dict] = []
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
            if obj.startswith("CHEBI:"):
                continue
            if not obj:
                continue
            rows.append(row)
    return rows


def build() -> list[dict]:
    mim_rows = load_non_chebi_mim()
    # Group by object_id — multiple MIM records can share the same FOODON/ENVO target.
    by_obj: dict[str, dict] = {}
    for r in mim_rows:
        obj = r["object_id"]
        prefix = obj.split(":", 1)[0]
        category = CATEGORY_FOR_PREFIX.get(prefix, "biolink:NamedThing")

        rec = by_obj.get(obj)
        if rec is None:
            rec = {
                "id": obj,
                "category": category,
                "canonical_name": r.get("object_label", "") or "",
                "formula": "",
                "_labels": set(),
                "_xrefs": set(),
                "_sources": set(),
            }
            by_obj[obj] = rec

        # Surface form label from MIM
        if r.get("subject_label"):
            rec["_labels"].add(r["subject_label"])
        # Other column: pipe-delimited alternative labels from the MIM YAML
        other = r.get("other", "") or ""
        if other:
            for label in other.split("|"):
                label = label.strip()
                if label:
                    rec["_labels"].add(label)

        # Xrefs: MIM subject_id itself (which MIM ingredient this came from)
        rec["_xrefs"].add(r["subject_id"])

        # Source pipeline: derive from the SSSOM source column
        src = r.get("source", "") or ""
        for part in src.split("|"):
            part = part.strip()
            if part.startswith("MIM:") or part.startswith("kgm:"):
                rec["_sources"].add(part)

    out: list[dict] = []
    for obj in sorted(by_obj):
        rec = by_obj[obj]
        out.append({
            "id": rec["id"],
            "category": rec["category"],
            "canonical_name": rec["canonical_name"],
            "formula": rec["formula"],
            "synonyms": "|".join(sorted(rec["_labels"])),
            "xrefs": "|".join(sorted(rec["_xrefs"])),
            "sources": "|".join(sorted(rec["_sources"])) or "mediaingredientmech_reviewed",
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true",
                    help="Also copy the artifact into MediaIngredientMech/mappings/ "
                         "as the canonical published location consumed by kg-microbe.")
    args = ap.parse_args()

    rows = build()
    print(f"Built {len(rows)} complex-ingredient rows")

    OUT_GZ.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(OUT_GZ, "wt", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in COLS) + "\n")
    print(f"Wrote {OUT_GZ} ({OUT_GZ.stat().st_size} bytes)")

    # Human-readable preview (uncompressed, one file so curators can open it)
    with OUT_TSV_PREVIEW.open("w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in COLS) + "\n")
    print(f"Wrote {OUT_TSV_PREVIEW}")

    if args.publish:
        shutil.copy(OUT_GZ, PUBLISH_GZ)
        shutil.copy(OUT_TSV_PREVIEW, PUBLISH_TSV)
        print(f"Published → {PUBLISH_GZ}")
        print(f"Published → {PUBLISH_TSV}")

    # Summary
    from collections import Counter
    by_prefix = Counter(r["id"].split(":", 1)[0] for r in rows)
    print("\nBy ontology:")
    for p, n in by_prefix.most_common():
        print(f"  {p}: {n}")


if __name__ == "__main__":
    main()
