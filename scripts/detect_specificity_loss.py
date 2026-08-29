#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Detect MIM mappings where the ontology term is more general than the
named ingredient (e.g., "Vermont Soil" → ENVO:00001998 "soil").

For each flagged record, we:
  1. Recognize the QUALIFIER tokens (the words in the name that
     aren't in the ontology label) — these are what makes the
     ingredient specific.
  2. Categorize the loss type (geographic, treatment, formulation,
     stereo, hydrate, brand, generic).
  3. Suggest minting a `kgmicrobe.ingredient:<slug>` custom term that
     subclasses the parent ontology term, preserving the specificity
     in MIM-side data while keeping the parent reference for KG
     downstream consumers.

Read-only; emits a review report. Curator decides which to mint.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients" / "mapped"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "specificity_loss_review.tsv"
OUT_MD = OUT_DIR / "specificity_loss_review.md"

# Stop tokens that don't carry specificity (matched the foodon_pass list)
_STOP = frozenset({
    "the", "a", "an", "of", "and", "or", "in", "on", "with",
    "from", "by", "to", "as", "for",
    "no", "nr", "type", "grade", "form",
})

# Heuristics for qualifier categorization
_GEO_HINTS = re.compile(
    r"\b(?:vermont|california|atlantic|pacific|kefir|bayan|"
    r"iberian|mediterranean|kentucky|amazon|alpine|baltic|"
    r"sahara|gobi|maine|texas|florida|hawaii|oregon|alaska|"
    r"british|scottish|irish|french|german|"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?:soil|water|sediment|sea|river|lake))\b",
    re.IGNORECASE,
)
_TREATMENT_HINTS = frozenset({
    "pasteurized", "filtered", "boiled", "autoclaved", "sterilized",
    "dried", "dehydrated", "fresh", "frozen", "cooked", "raw",
    "processed", "milled", "ground", "powder", "powdered",
})
_FORMULATION_HINTS = re.compile(r"\b(?:stock|m|%|in|with)\b", re.IGNORECASE)
_STEREO_RE = re.compile(r"^\((?:[REZSL]|R/S|S-|R-)\)-")
_HYDRATE_RE = re.compile(
    r"(?:[xX·]\s*\d*\s*H2O|·H2O|\s+(?:mono|di|tri|tetra|penta|"
    r"hexa|hepta|octa|nona|deca)?hydrate)\b",
    re.IGNORECASE,
)
_BRAND_RE = re.compile(
    r"\(\s*(?:Difco|BBL|Oxoid|Sigma|Fluka|Acros|Merck|BD|Nissui|"
    r"Becton[ -]Dickinson|Atlas|Aldrich)\s*\)",
    re.IGNORECASE,
)


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z][A-Za-z0-9-]+", (s or "").lower())
            if t not in _STOP]


def categorize_qualifiers(name: str, label: str,
                          extra_tokens: list[str]) -> str:
    """Pick a qualifier category for the tokens that are in NAME but
    not in LABEL. Helps curators batch-decide."""
    n = name.lower()
    if _STEREO_RE.search(name):
        return "STEREO"
    if _HYDRATE_RE.search(name):
        return "HYDRATE"
    if _BRAND_RE.search(name):
        return "BRAND"
    if any(t in _TREATMENT_HINTS for t in extra_tokens):
        return "TREATMENT"
    # Capitalized proper-noun-looking adjective (Vermont, Bayan etc.)
    for t in re.findall(r"[A-Z][a-z]+", name):
        if t.lower() not in _tokens(label):
            return "GEOGRAPHIC_OR_PROPER"
    if "(" in name and ")" in name:
        return "FORMULATION_OR_QUALIFIER"
    if extra_tokens:
        return "DESCRIPTIVE_QUALIFIER"
    return "OTHER"


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return s.lower()[:60]


def main() -> int:
    # Verify the checkout before doing work; module-level roots stay
    # plain paths so importing this file never needs one (#176).
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    n_scanned = 0
    for path in sorted(INGREDIENTS.glob("*.yaml")):
        try:
            with open(path) as f:
                y = yaml.safe_load(f) or {}
        except Exception:
            continue
        n_scanned += 1
        if args.limit and n_scanned > args.limit:
            break

        ident = y.get("identifier") or ""
        # Skip placeholder-primary records (cas:, kgmicrobe.compound:,
        # UNMAPPED_*) — they have no ontology term to compare against.
        if not any(ident.startswith(p) for p in
                   ("CHEBI:", "FOODON:", "ENVO:", "UBERON:", "NCIT:",
                    "MICRO:", "mesh:")):
            continue
        om = y.get("ontology_mapping") or {}
        label = om.get("ontology_label") or ""
        name = y.get("preferred_term") or ""
        if not name or not label:
            continue
        if name.strip().lower() == label.strip().lower():
            continue   # identical — no specificity loss

        name_tok = set(_tokens(name))
        label_tok = set(_tokens(label))
        if not name_tok or not label_tok:
            continue
        # Specificity loss when label tokens ⊂ name tokens AND name has
        # extra tokens. Strict subset.
        if not (label_tok < name_tok):
            continue
        extra = sorted(name_tok - label_tok)
        if not extra:
            continue

        category = categorize_qualifiers(name, label, extra)
        suggested_kgm_id = f"kgmicrobe.ingredient:{slugify(name)}"
        rows.append({
            "yaml_path": str(path.relative_to(MIM_ROOT)),
            "identifier": ident,
            "preferred_term": name,
            "ontology_label": label,
            "extra_qualifiers": ",".join(extra),
            "category": category,
            "suggested_kgm_id": suggested_kgm_id,
            "parent_ontology_id": om.get("ontology_id") or ident,
            "parent_ontology_label": label,
            "current_quality": om.get("mapping_quality") or "",
        })

    # Emit TSV
    with open(OUT_TSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "yaml_path", "identifier", "preferred_term", "ontology_label",
            "extra_qualifiers", "category", "suggested_kgm_id",
            "parent_ontology_id", "parent_ontology_label",
            "current_quality",
        ], delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Emit MD
    md = ["# Specificity-loss review\n",
          f"Scanned: **{n_scanned}** mapped records",
          f"Flagged: **{len(rows)}**\n"]
    from collections import Counter
    by_cat = Counter(r["category"] for r in rows)
    md.append("\n## Distribution by category\n")
    md.append("| Category | Count | Action |\n|---|---:|---|")
    advice = {
        "GEOGRAPHIC_OR_PROPER":
            "MINT — the proper-noun adjective is a real specificity",
        "TREATMENT":
            "REVIEW — sometimes degenerate (sterilized water = water), sometimes meaningful (filtered seawater ≠ seawater)",
        "STEREO":
            "USUALLY KEEP — stereo loss for media context is acceptable; flag only if the curator wants to track enantiomers separately",
        "HYDRATE":
            "USUALLY KEEP — hydrate form rarely affects media-as-ingredient identity",
        "BRAND":
            "USUALLY KEEP — brand-stripped already; flag for clean-up if brand info matters for reproducibility",
        "FORMULATION_OR_QUALIFIER":
            "REVIEW — concentration / role / form qualifiers; case-by-case",
        "DESCRIPTIVE_QUALIFIER":
            "REVIEW — generic descriptive words; case-by-case",
        "OTHER":
            "REVIEW",
    }
    for cat, n in by_cat.most_common():
        md.append(f"| {cat} | {n} | {advice.get(cat, '')} |")

    md.append("\n\n## Sample (first 25, sorted by category)\n")
    md.append("| Name | Currently → | Extra qualifiers | Suggested mint | Category |")
    md.append("|---|---|---|---|---|")
    rows_sorted = sorted(rows, key=lambda r: (r["category"], r["preferred_term"]))
    for r in rows_sorted[:25]:
        md.append(
            f"| {r['preferred_term']} | `{r['identifier']}` ({r['ontology_label']}) "
            f"| {r['extra_qualifiers']} | `{r['suggested_kgm_id']}` "
            f"| {r['category']} |")

    md.append("\n\n## How to mint")
    md.append("""
For each row a curator approves:

1. **Update the MIM YAML**: set `identifier` to the suggested
   `kgmicrobe.ingredient:<slug>`. Keep `ontology_mapping.ontology_id`
   pointing to the parent ontology term but change
   `mapping_quality: NARROW_MATCH` (this MIM term is narrower than
   the parent). Add an evidence entry citing the parent relationship.

2. **Append a row** to `MediaIngredientMech/data/custom/kgmicrobe_ingredients.tsv`
   with columns:
     - `kgm_id` (e.g. `kgmicrobe.ingredient:vermont_soil`)
     - `preferred_term`
     - `parent_ontology_id`
     - `parent_ontology_label`
     - `relation` (default `rdfs:subClassOf` for ontology parents)
     - `created_by`, `created_at`, `notes`

3. **Re-run** `just build-sssom` — the SSSOM emitter will produce a
   `skos:narrowMatch` row from the kgm.ingredient term to the parent.
   Downstream KGX consumers turn this into a subclass edge.
""")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"Scanned: {n_scanned} mapped records")
    print(f"Flagged: {len(rows)}")
    print()
    for cat, n in by_cat.most_common():
        print(f"  {n:5d}  {cat}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"         {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
