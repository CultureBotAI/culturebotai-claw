#!/usr/bin/env python3
"""Mint a `kgmicrobe.ingredient:<slug>` custom term as the new primary
identifier for a MIM ingredient YAML. Preserves the parent ontology
relationship via skos:narrowMatch in the SSSOM emission and an
appended row in the custom-ingredients reference TSV.

Two modes:
  --slug <yaml-slug>     # mint a single record
  --from-tsv <path>      # batch: rows must have action==mint
                         # in workspace/reports/specificity_loss_review.tsv
                         # (column: 'action' added by curator)
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_write import dump_record  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients"
CUSTOM_TSV = MIM_ROOT / "data" / "custom" / "kgmicrobe_ingredients.tsv"

CUSTOM_HEADER = [
    "kgm_id", "preferred_term", "parent_ontology_id",
    "parent_ontology_label", "relation", "created_by",
    "created_at", "notes",
]


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return s.lower()[:60]


def ensure_custom_tsv() -> None:
    CUSTOM_TSV.parent.mkdir(parents=True, exist_ok=True)
    if not CUSTOM_TSV.exists():
        with open(CUSTOM_TSV, "w", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(CUSTOM_HEADER)


def append_custom_row(kgm_id: str, name: str, parent_id: str,
                       parent_label: str, notes: str) -> None:
    with open(CUSTOM_TSV, "a", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow([
            kgm_id, name, parent_id, parent_label, "rdfs:subClassOf",
            "mint_kgm_ingredient",
            _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            notes,
        ])


def find_yaml_by_slug(slug: str) -> Path | None:
    for sub in ("mapped", "unmapped"):
        p = INGREDIENTS / sub / f"{slug}.yaml"
        if p.is_file():
            return p
    return None


def mint_one(yaml_path: Path) -> dict:
    """Mint a kgmicrobe.ingredient: primary for the YAML at yaml_path.
    Returns a dict summarizing the change, or raises ValueError."""
    with open(yaml_path) as f:
        record = yaml.safe_load(f) or {}
    if not isinstance(record, dict):
        raise ValueError(f"{yaml_path}: not a YAML dict")
    ident = record.get("identifier", "")
    name = record.get("preferred_term") or yaml_path.stem
    if ident.startswith("kgmicrobe.ingredient:"):
        return {"yaml": str(yaml_path), "status": "already-minted",
                "kgm_id": ident}

    om = record.get("ontology_mapping") or {}
    parent_id = om.get("ontology_id") or ident
    parent_label = om.get("ontology_label") or ""
    if not parent_id or not any(parent_id.startswith(p) for p in
                                ("CHEBI:", "FOODON:", "ENVO:",
                                 "UBERON:", "NCIT:", "MICRO:", "mesh:")):
        raise ValueError(
            f"{yaml_path}: no usable parent ontology "
            f"(identifier={ident!r}, ontology_id={parent_id!r})")

    kgm_id = f"kgmicrobe.ingredient:{slugify(name)}"

    # Update the YAML: primary becomes the custom kgm: term; ontology_mapping
    # keeps the parent term but flagged NARROW_MATCH (we are narrower).
    record["identifier"] = kgm_id
    om["ontology_id"] = parent_id
    om["ontology_label"] = parent_label
    om["mapping_quality"] = "NARROW_MATCH"
    om.setdefault("evidence", []).append({
        "evidence_type": "CURATOR_JUDGMENT",
        "source": "specificity-loss-review (mint_kgm_ingredient)",
        "notes": (f"Minted {kgm_id} to preserve ingredient-level "
                  f"specificity beyond {parent_id} ({parent_label}). "
                  f"Parent relationship persists via "
                  f"skos:narrowMatch in SSSOM emission."),
    })
    record["mapping_status"] = "MAPPED"
    record.setdefault("curation_history", []).append({
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "curator": "mint_kgm_ingredient",
        "action": "MINT_KGM_INGREDIENT",
        "changes": (f"primary {ident} → {kgm_id}; "
                    f"ontology_mapping retains {parent_id} as "
                    f"NARROW_MATCH parent"),
        "llm_assisted": False,
    })

    with open(yaml_path, "w") as f:
        f.write(dump_record("mediaingredientmech", record))

    ensure_custom_tsv()
    append_custom_row(kgm_id, name, parent_id, parent_label,
                      f"minted from {yaml_path.relative_to(MIM_ROOT)} "
                      f"(was {ident})")

    return {"yaml": str(yaml_path), "status": "minted", "kgm_id": kgm_id,
            "parent": parent_id}


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--slug", help="MIM YAML stem (e.g. Vermont_Soil)")
    src.add_argument("--from-tsv", type=Path,
                     help="batch: rows with action=='mint' in this TSV")
    args = ap.parse_args()
    # Verify the checkout before doing work; module-level roots stay
    # plain paths so importing this file never needs one (#176).
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    if args.slug:
        yaml_path = find_yaml_by_slug(args.slug)
        if not yaml_path:
            print(f"Not found: {args.slug}.yaml", file=sys.stderr)
            return 2
        result = mint_one(yaml_path)
        print(result)
        return 0

    # Batch
    n_minted = n_skipped = 0
    with open(args.from_tsv) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if (r.get("action") or "").strip().lower() != "mint":
                n_skipped += 1
                continue
            yaml_path = MIM_ROOT / r["yaml_path"]
            if not yaml_path.is_file():
                print(f"  skip (missing): {yaml_path}")
                continue
            try:
                result = mint_one(yaml_path)
                print(f"  {result['status']}: {result.get('kgm_id', '')}")
                if result["status"] == "minted":
                    n_minted += 1
            except Exception as e:
                print(f"  error on {yaml_path.name}: {e}")
    print(f"\nMinted: {n_minted}, skipped (no action=mint): {n_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
