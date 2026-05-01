#!/usr/bin/env /opt/homebrew/bin/python3.13
"""FOODON-focused resolver pass for heuristic-complex MIM ingredients.

Walks the unmapped-inventory's "complex (heuristic)" bucket — names
matching the _COMPLEX_RE pattern (yeast extract, peptone, casein,
brain heart infusion, etc.) — and searches FOODON via OLS for each.

Outcomes per row:

  HIGH       label-exact match in FOODON (auto-applicable)
  HIGH       synonym-exact match in FOODON (auto-applicable)
  MEDIUM     fuzzy match (top OLS hit but not exact)
  NONE       no FOODON candidate

For each HIGH match, the script can either:
  a) UPGRADE_MIM_PRIMARY — when the name is already a MIM record
     with a kgmicrobe.compound:* / UNMAPPED_* / placeholder primary,
     re-point the identifier to the FOODON term
  b) CREATE_MIM_YAML — when no MIM record exists yet (rare; most
     heuristic-complex names already have a MIM home)

CLI:
  --apply    write YAMLs (default: dry-run + report only)
  --high-only   only act on HIGH matches (skip MEDIUM)

Outputs:
  workspace/reports/foodon_pass.{tsv,md}
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INVENTORY_TSV = REPO_ROOT / "workspace" / "reports" / "unmapped_inventory.tsv"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "foodon_pass.tsv"
OUT_MD = OUT_DIR / "foodon_pass.md"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
RATE_DELAY = 0.25  # 4 req/s


sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_ingredient_type import (  # noqa: E402
    _COMPLEX_RE, load_yaml, write_yaml, append_curation_event,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def ols_foodon_search(term: str) -> dict:
    """Returns {label, foodon_id, match} for the best hit, or {} if no
    hit. match ∈ {label-exact, synonym-exact, fuzzy-top}."""
    params = urllib.parse.urlencode({
        "q": term, "ontology": "foodon", "rows": 8,
        "exact": "false", "type": "class",
    })
    try:
        with urllib.request.urlopen(f"{OLS_SEARCH}?{params}", timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}
    n = _norm(term)
    docs = j.get("response", {}).get("docs", [])
    fuzzy_top = None
    for d in docs:
        if d.get("is_obsolete"):
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie or not curie.upper().startswith("FOODON:"):
            continue
        label = d.get("label", "")
        if _norm(label) == n:
            return {"foodon_id": curie, "label": label, "match": "label-exact"}
        if n in {_norm(s) for s in (d.get("synonym") or [])}:
            return {"foodon_id": curie, "label": label, "match": "synonym-exact"}
        if fuzzy_top is None:
            fuzzy_top = {"foodon_id": curie, "label": label, "match": "fuzzy-top"}
    return fuzzy_top or {}


def build_mim_name_index() -> dict[str, list[tuple[int, Path]]]:
    """Build a normalized-name → [(score, path), ...] index over all
    MIM ingredient YAMLs. Done once up front to avoid the 99 ×
    2,349-file walk that dominated the dry-run."""
    idx: dict[str, list[tuple[int, Path]]] = {}
    for path in (MIM_ROOT / "data" / "ingredients").rglob("*.yaml"):
        try:
            with open(path) as f:
                y = yaml.safe_load(f) or {}
        except Exception:
            continue
        pt = _norm(y.get("preferred_term") or "")
        if not pt:
            continue
        ident = y.get("identifier") or ""
        score = 0
        if ident.startswith("UNMAPPED_"):
            score = 3
        elif ident.startswith("kgmicrobe.compound:"):
            score = 2
        elif ident.startswith("FOODON:"):
            score = -1
        idx.setdefault(pt, []).append((score, path))
    return idx


def find_mim_yaml_by_name(name: str,
                          idx: dict[str, list[tuple[int, Path]]]
                          ) -> Path | None:
    norm = _norm(name)
    cands = idx.get(norm) or []
    if not cands:
        return None
    cands_sorted = sorted(cands, key=lambda x: -x[0])
    return cands_sorted[0][1] if cands_sorted[0][0] > 0 else None


def upgrade_yaml(path: Path, foodon_id: str, foodon_label: str,
                 match_type: str) -> str:
    """Upgrade an existing MIM YAML's primary identifier to FOODON.
    Returns 'upgraded' or 'no-change'."""
    record = load_yaml(path)
    if not record:
        return "no-change"
    prev_ident = record.get("identifier")
    if prev_ident == foodon_id:
        return "no-change"
    record["identifier"] = foodon_id
    om = record.setdefault("ontology_mapping", {})
    om["ontology_id"] = foodon_id
    om["ontology_label"] = foodon_label
    om["ontology_source"] = "FOODON"
    om["mapping_quality"] = (
        "EXACT_MATCH" if match_type in ("label-exact", "synonym-exact")
        else "LEXICAL_MATCH")
    om.setdefault("evidence", []).append({
        "evidence_type": "DATABASE_MATCH",
        "source": "FOODON via OLS search",
        "notes": f"Auto-upgraded from {prev_ident!r}; match={match_type}",
    })
    record["mapping_status"] = "MAPPED"
    append_curation_event(
        record, "AUTO_UPGRADE_TO_FOODON",
        f"primary {prev_ident} → {foodon_id} ({match_type})")
    write_yaml(path, record)
    return "upgraded"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--high-only", action="store_true",
                    help="skip MEDIUM (fuzzy-top) matches")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not INVENTORY_TSV.is_file():
        print("Run `just inventory-unmapped` first.", file=sys.stderr)
        return 2

    # Distinct heuristic-complex names from the inventory
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []  # (norm_key, display_name)
    with open(INVENTORY_TSV) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            name = r["name"]
            if not _COMPLEX_RE.search(name):
                continue
            n = r["norm_key"]
            if n in seen:
                continue
            seen.add(n)
            targets.append((n, name))
    if args.limit:
        targets = targets[: args.limit]
    print(f"Heuristic-complex distinct names: {len(targets)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Building MIM name index...")
    name_idx = build_mim_name_index()
    print(f"  indexed {sum(len(v) for v in name_idx.values())} records")

    rows: list[tuple[str, str, str, str, str, str]] = []
    counts: dict[str, int] = {}

    for i, (norm, name) in enumerate(targets, 1):
        result = ols_foodon_search(name)
        time.sleep(RATE_DELAY)

        if not result or result.get("error"):
            counts["NO_HIT"] = counts.get("NO_HIT", 0) + 1
            rows.append((name, "", "", "NO_HIT",
                         result.get("error", ""), ""))
            print(f"  [{i}/{len(targets)}] {name}: NO_HIT")
            continue

        match = result["match"]
        confidence = "HIGH" if match in ("label-exact", "synonym-exact") else "MEDIUM"
        counts[confidence] = counts.get(confidence, 0) + 1
        verdict = confidence

        if args.high_only and confidence == "MEDIUM":
            rows.append((name, result["foodon_id"], result["label"],
                         "MEDIUM_SKIPPED", match, ""))
            print(f"  [{i}/{len(targets)}] {name}: "
                  f"MEDIUM ({result['foodon_id']}) — skipped")
            continue

        # Find a MIM record to upgrade
        target_yaml = find_mim_yaml_by_name(name, name_idx)
        action = ""
        if target_yaml is None:
            action = "CREATE_NEW (deferred)"
        elif args.apply and confidence == "HIGH":
            res = upgrade_yaml(target_yaml, result["foodon_id"],
                               result["label"], match)
            action = "UPGRADED" if res == "upgraded" else "NO_CHANGE"
            if res == "upgraded":
                counts["UPGRADED"] = counts.get("UPGRADED", 0) + 1
        else:
            action = ("WOULD_UPGRADE" if confidence == "HIGH"
                      else "WOULD_REVIEW")

        rows.append((
            name, result["foodon_id"], result["label"],
            verdict, match,
            (str(target_yaml.relative_to(MIM_ROOT))
             if target_yaml else "(no MIM record)") + " | " + action
        ))
        print(f"  [{i}/{len(targets)}] {name}: "
              f"{confidence} → {result['foodon_id']} ({match})")

    # Reports
    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["name", "foodon_id", "foodon_label",
                    "confidence", "match_type", "target_yaml | action"])
        w.writerows(rows)

    md = ["# FOODON pass — heuristic-complex resolver\n",
          f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**\n",
          f"Distinct names processed: **{len(targets)}**\n",
          "\n## Verdicts\n",
          "| verdict | count |", "|---|---:|"]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        md.append(f"| `{k}` | {v} |")

    md.append("\n\n## HIGH-confidence matches\n")
    md.append("| Name | FOODON | Label | Match | Action |")
    md.append("|---|---|---|---|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf == "HIGH":
            md.append(f"| {name} | `{fid}` | {flabel} | {match} | {action} |")

    md.append("\n\n## MEDIUM-confidence (curator review)\n")
    md.append("| Name | FOODON | Label | Action |")
    md.append("|---|---|---|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf in ("MEDIUM", "MEDIUM_SKIPPED"):
            md.append(f"| {name} | `{fid}` | {flabel} | {action} |")

    md.append("\n\n## No FOODON hit\n")
    md.append("| Name |")
    md.append("|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf == "NO_HIT":
            md.append(f"| {name} |")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print()
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:25s} {v}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"         {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
