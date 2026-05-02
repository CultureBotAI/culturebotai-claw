#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Merge v2 shard outputs from `resolve_unmapped_v2.py`. Applies HIGH
matches (any-ontology label/synonym-exact); reports STEM_MATCH
candidates for curator review."""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
SHARDS_DIR = REPO_ROOT / "workspace" / "results" / "resolve_unmapped_v2"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "resolve_unmapped_v2.tsv"
OUT_MD = OUT_DIR / "resolve_unmapped_v2.md"


def load_all_shards() -> list[dict]:
    rows: list[dict] = []
    for p in sorted(SHARDS_DIR.glob("shard_*.jsonl")):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def upgrade_unmapped(yaml_path: Path, new_id: str, new_label: str,
                     ontology: str, match_type: str,
                     matched_via: str, strategy: str) -> str:
    try:
        with open(yaml_path) as f:
            record = yaml.safe_load(f) or {}
    except Exception as e:
        return f"error:{type(e).__name__}"
    if not isinstance(record, dict):
        return "error:not-dict"
    prev = record.get("identifier", "")
    if not prev.startswith("UNMAPPED_"):
        return "error:not-an-UNMAPPED-record"

    record["identifier"] = new_id
    om = record.setdefault("ontology_mapping", {})
    om["ontology_id"] = new_id
    om["ontology_label"] = new_label
    om["ontology_source"] = ontology.upper()
    # stem-match → LEXICAL_MATCH (renders as skos:closeMatch in SSSOM);
    # any-onto-exact → EXACT_MATCH
    om["mapping_quality"] = ("LEXICAL_MATCH" if strategy == "stem-match"
                             else "EXACT_MATCH")
    om.setdefault("evidence", []).append({
        "evidence_type": "DATABASE_MATCH",
        "source": (f"{ontology.upper()} via OLS (resolve_unmapped_v2 "
                   f"strategy={strategy})"),
        "notes": (f"Auto-upgraded from {prev}; matched via {matched_via!r}; "
                  f"{match_type}"),
    })
    record["mapping_status"] = "MAPPED"
    record.setdefault("curation_history", []).append({
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "curator": "resolve_unmapped_v2",
        "action": f"AUTO_UPGRADE_TO_{ontology.upper()}",
        "changes": (f"primary {prev} → {new_id} "
                    f"(strategy={strategy})"),
        "llm_assisted": False,
    })
    with open(yaml_path, "w") as f:
        yaml.safe_dump(record, f, default_flow_style=False,
                       allow_unicode=True, sort_keys=False)
    return "upgraded"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="apply HIGH upgrades")
    ap.add_argument("--apply-stem", action="store_true",
                    help="ALSO apply STEM_MATCH (medium confidence)")
    args = ap.parse_args()

    rows = load_all_shards()
    if not rows:
        print(f"No shards in {SHARDS_DIR}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {"HIGH": 0, "STEM_MATCH": 0, "NO_HIT": 0}
    upgraded = 0

    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["yaml_path", "previous_identifier", "preferred_term",
                    "verdict", "matched_via", "strategy", "ontology_id",
                    "ontology_label", "ontology", "match_type", "action"])
        for row in sorted(rows, key=lambda r: r["yaml_path"]):
            verdict = row["verdict"]
            counts[verdict] = counts.get(verdict, 0) + 1
            m = row.get("match") or {}
            via = m.get("matched_via", "")
            strategy = m.get("strategy", "")
            new_id = m.get("id", "")
            new_label = m.get("label", "")
            ontology = m.get("ontology", "")
            match_type = m.get("match", "")
            action = ""

            if (verdict == "HIGH" and args.apply) or (
                    verdict == "STEM_MATCH" and args.apply_stem):
                yaml_path = MIM_ROOT / row["yaml_path"]
                if yaml_path.is_file():
                    res = upgrade_unmapped(
                        yaml_path, new_id, new_label, ontology,
                        match_type, via, strategy)
                    action = res
                    if res == "upgraded":
                        upgraded += 1
                else:
                    action = "missing"
            elif verdict == "HIGH":
                action = "WOULD_UPGRADE"
            elif verdict == "STEM_MATCH":
                action = "WOULD_REVIEW"

            w.writerow([row["yaml_path"], row["previous_identifier"],
                        row["preferred_term"], verdict, via, strategy,
                        new_id, new_label, ontology, match_type, action])

    md = ["# resolve_unmapped_v2 — aggressive cascade results\n",
          f"Mode: HIGH={'APPLY' if args.apply else 'DRY-RUN'}, "
          f"STEM_MATCH={'APPLY' if args.apply_stem else 'REVIEW-ONLY'}\n",
          f"Records reviewed: **{len(rows)}**",
          f"Upgraded this run: **{upgraded}**\n",
          "\n## Verdicts\n", "| verdict | count |", "|---|---:|"]
    for k in sorted(counts, key=lambda x: -counts[x]):
        md.append(f"| `{k}` | {counts[k]} |")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"Reviewed {len(rows)}")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"Upgraded: {upgraded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
