#!/usr/bin/env python3
"""Upgrade MIM `kgmicrobe.compound:*` placeholder primaries to real
ontology IDs via the multi-ontology cascade.

These records were imported with kgmicrobe.compound:* primaries in
earlier sessions because the resolver couldn't find a CHEBI/NCIT
match at the time. With MICRO and mesh now in the cascade (and
ontology indexes refreshed), many of them resolve.

Cascade order: CHEBI → NCIT → MICRO → mesh → FOODON → ENVO

Only HIGH (label-exact / synonym-exact) hits are auto-applied.
Each upgrade adds DATABASE_MATCH evidence + AUTO_UPGRADE_TO_*
curation_history.

Reuses scoring + OLS search from scripts/foodon_pass.py.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "placeholder_upgrade.tsv"
OUT_MD = OUT_DIR / "placeholder_upgrade.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foodon_pass import ols_search, score_fuzzy_match, upgrade_yaml  # noqa
from classify_ingredient_type import load_yaml  # noqa

# CHEBI first because antibiotics / secondary metabolites mostly live
# there. MICRO/mesh after for biological-reagent niches. FOODON/ENVO
# last (placeholders are rarely complex foods or env samples by this
# point — those got resolved by foodon_pass).
_CASCADE = (
    ("chebi", "CHEBI:"),
    ("ncit", "NCIT:"),
    ("micro", "MICRO:"),
    ("mesh", "mesh:"),
    ("foodon", "FOODON:"),
    ("envo", "ENVO:"),
)
RATE_DELAY = 0.25


def find_placeholder_yamls() -> list[tuple[Path, dict]]:
    """Return [(path, parsed_yaml)] for every MIM record whose primary
    is a kgmicrobe.compound:* placeholder."""
    out: list[tuple[Path, dict]] = []
    for path in sorted(INGREDIENTS.rglob("*.yaml")):
        record = load_yaml(path)
        if not record:
            continue
        ident = (record.get("identifier") or "").strip()
        if ident.startswith("kgmicrobe.compound:"):
            out.append((path, record))
    return out


def best_cascade_match(name: str) -> tuple[dict | None, str]:
    """Walk the cascade; return (HIGH_match_or_None, ontology_used)."""
    for ontology, prefix in _CASCADE:
        result = ols_search(name, ontology, prefix)
        time.sleep(RATE_DELAY)
        if result and not result.get("error"):
            if result["match"] in ("label-exact", "synonym-exact"):
                return result, ontology
    return None, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    # Verify the checkout before doing work; module-level roots stay
    # plain paths so importing this file never needs one (#176).
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = find_placeholder_yamls()
    if args.limit:
        targets = targets[: args.limit]
    print(f"kgmicrobe.compound: placeholders to scan: {len(targets)}")

    rows: list[tuple[str, str, str, str, str, str]] = []
    counts: dict[str, int] = {}
    upgraded = 0

    for i, (path, record) in enumerate(targets, 1):
        name = record.get("preferred_term") or path.stem
        prev = record.get("identifier", "")
        result, ontology = best_cascade_match(name)
        rel = str(path.relative_to(MIM_ROOT))

        if not result:
            counts["NO_HIT"] = counts.get("NO_HIT", 0) + 1
            rows.append((rel, prev, name, "NO_HIT", "", ""))
            print(f"  [{i}/{len(targets)}] {name}: NO_HIT")
            continue

        new_id = result["id"]
        new_label = result["label"]
        match = result["match"]
        verdict = "HIGH"
        counts[verdict] = counts.get(verdict, 0) + 1

        if args.apply:
            res = upgrade_yaml(path, new_id, new_label, match)
            action = "UPGRADED" if res == "upgraded" else "NO_CHANGE"
            if res == "upgraded":
                upgraded += 1
                counts["UPGRADED"] = counts.get("UPGRADED", 0) + 1
        else:
            action = "WOULD_UPGRADE"

        rows.append((rel, prev, name, verdict,
                     f"{new_id} ({new_label}) via {ontology} {match}",
                     action))
        print(f"  [{i}/{len(targets)}] {name}: HIGH → {new_id} via {ontology}")

    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["yaml_path", "previous_identifier", "preferred_term",
                    "verdict", "match", "action"])
        w.writerows(rows)

    md = ["# Placeholder upgrade — kgmicrobe.compound: → ontology\n",
          f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**",
          f"Placeholders scanned: **{len(targets)}**",
          f"{'Upgraded' if args.apply else 'Would upgrade'}: **{upgraded if args.apply else counts.get('HIGH', 0)}**",
          f"NO_HIT: **{counts.get('NO_HIT', 0)}**\n",
          "\n## Outcomes\n", "| verdict | count |", "|---|---:|"]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        md.append(f"| `{k}` | {v} |")
    md.append("\n\n## Successful matches\n")
    md.append("| YAML | Previous | Name | Match |")
    md.append("|---|---|---|---|")
    for rel, prev, name, conf, m, action in rows:
        if conf == "HIGH":
            md.append(f"| `{Path(rel).name}` | `{prev}` | {name} | {m} |")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print()
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:25s} {v}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
