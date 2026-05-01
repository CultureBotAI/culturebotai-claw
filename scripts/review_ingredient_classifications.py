#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Curator-review report for MIM ingredient_type classifications.

Two buckets surfaced for human review in a single TSV + Markdown:

  1. Records currently classified as UNDEFINED_MIXTURE — verify the
     auto-classification is correct (some FOODON/ENVO records may be
     edge cases the curator wants to override).

  2. Records with no ingredient_type set (mostly UNMAPPED_NNNN) —
     suggest a classification using the same heuristic regexes as
     scripts/classify_ingredient_type.py against the preferred_term.

The companion TSV has an `action` column the curator marks (`keep`,
`override:<NEW_TYPE>`, `defer`); a tiny follow-up script will read
the marked TSV and write YAMLs.

Task C of the curation follow-up plan.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "ingredient_classification_review.tsv"
OUT_MD = OUT_DIR / "ingredient_classification_review.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_ingredient_type import (  # noqa: E402
    load_yaml, _COMPLEX_RE, _SOLUTION_RE, _MEDIUM_RE,
)


def suggest_for_unset(record: dict) -> tuple[str, str]:
    """Returns (suggested_type, rationale) for an unset record.
    Suggested is "" if no strong heuristic match — leave as
    needs-curator."""
    name = (record.get("preferred_term") or "").strip()
    ident = (record.get("identifier") or "")
    m = _COMPLEX_RE.search(name)
    if m:
        return "UNDEFINED_MIXTURE", f"name matches complex pattern {m.group(0)!r}"
    m = _SOLUTION_RE.search(name)
    if m:
        return "STOCK_SOLUTION", f"name matches solution pattern {m.group(0)!r}"
    m = _MEDIUM_RE.search(name)
    if m:
        return "DEFINED_MEDIUM", f"name matches medium pattern {m.group(0)!r}"
    if ident.startswith("UNMAPPED_"):
        return "", "no pattern match; needs curator (likely chemical)"
    return "", "no heuristic suggestion"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()  # no flags yet; placeholder for future filtering
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str, str, str, str, str, str]] = []
    n_undefined = n_unset = n_unset_with_suggestion = 0

    for path in sorted(INGREDIENTS.rglob("*.yaml")):
        record = load_yaml(path)
        if not record:
            continue
        rel = str(path.relative_to(MIM_ROOT))
        ident = record.get("identifier") or ""
        name = record.get("preferred_term") or path.stem
        current = record.get("ingredient_type") or ""

        if current == "UNDEFINED_MIXTURE":
            n_undefined += 1
            rows.append((
                rel, ident, name, current, "(confirm)",
                "auto-classified; spot-check expected behavior", ""))
        elif not current:
            n_unset += 1
            suggestion, rationale = suggest_for_unset(record)
            if suggestion:
                n_unset_with_suggestion += 1
            rows.append((
                rel, ident, name, "", suggestion or "(needs curator)",
                rationale, ""))
        # else: SINGLE_INGREDIENT, STOCK_SOLUTION, DEFINED_MEDIUM —
        # high-confidence; no review needed

    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["yaml_path", "identifier", "preferred_term",
                    "current_type", "suggested_type", "rationale",
                    "action"])
        w.writerows(rows)

    md = ["# Ingredient classification — curator review\n",
          f"Total rows for review: **{len(rows)}**",
          f"  - currently UNDEFINED_MIXTURE (verify): **{n_undefined}**",
          f"  - unset (suggest+verify): **{n_unset}**",
          f"     of which {n_unset_with_suggestion} have a heuristic suggestion\n",
          "\n## How to use\n",
          "Open the companion TSV (`ingredient_classification_review.tsv`).",
          "Mark each row's `action` column with one of:",
          "- `keep` — accept current/suggested type as-is",
          "- `override:SINGLE_INGREDIENT` (or any other enum value) — override",
          "- `defer` — skip; revisit later",
          "\nA follow-up script `apply_classification_overrides.py` (next session)",
          "consumes the marked TSV and writes the YAMLs.\n",
          "\n## Records currently UNDEFINED_MIXTURE (sample)\n",
          "| YAML | Identifier | Name | Rationale |",
          "|---|---|---|---|"]
    sample = [r for r in rows if r[3] == "UNDEFINED_MIXTURE"][:20]
    for r in sample:
        md.append(f"| `{Path(r[0]).name}` | `{r[1]}` | {r[2]} | {r[5]} |")
    md.append("\n*(see TSV for full list)*\n")
    md.append("\n## Records with auto-suggested type (sample)\n")
    md.append("| YAML | Identifier | Name | Suggested | Rationale |")
    md.append("|---|---|---|---|---|")
    sample2 = [r for r in rows if not r[3] and r[4] not in ("(needs curator)", "")][:20]
    for r in sample2:
        md.append(f"| `{Path(r[0]).name}` | `{r[1]}` | {r[2]} | `{r[4]}` | {r[5]} |")
    md.append("\n*(see TSV for full list)*\n")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"Total rows for review: {len(rows)}")
    print(f"  UNDEFINED_MIXTURE (verify): {n_undefined}")
    print(f"  unset (suggest+verify):     {n_unset}")
    print(f"    with suggestion:          {n_unset_with_suggestion}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"         {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
