#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Merge per-shard outputs from `resolve_unmapped.py` into a single
report and (optionally) apply HIGH-confidence upgrades."""
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
SHARDS_DIR = REPO_ROOT / "workspace" / "results" / "resolve_unmapped"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "resolve_unmapped.tsv"
OUT_MD = OUT_DIR / "resolve_unmapped.md"


def load_all_shards() -> list[dict]:
    rows: list[dict] = []
    for shard_path in sorted(SHARDS_DIR.glob("shard_*.jsonl")):
        with open(shard_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def upgrade_unmapped_to_ontology(yaml_path: Path, new_id: str,
                                 new_label: str, ontology: str,
                                 match_type: str,
                                 matched_via: str) -> str:
    """Re-point an UNMAPPED_* record's primary identifier to the new
    ontology term. Returns 'upgraded' / 'no-change' / 'error:<reason>'."""
    try:
        with open(yaml_path) as f:
            record = yaml.safe_load(f) or {}
    except Exception as e:
        return f"error:{type(e).__name__}"
    if not isinstance(record, dict):
        return "error:not-a-dict"
    prev = record.get("identifier", "")
    if prev == new_id:
        return "no-change"
    if not prev.startswith("UNMAPPED_"):
        return "error:not-an-UNMAPPED-record"

    record["identifier"] = new_id
    om = record.setdefault("ontology_mapping", {})
    om["ontology_id"] = new_id
    om["ontology_label"] = new_label
    om["ontology_source"] = ontology.upper()
    om["mapping_quality"] = "EXACT_MATCH"
    om.setdefault("evidence", []).append({
        "evidence_type": "DATABASE_MATCH",
        "source": f"{ontology.upper()} via OLS search (resolve_unmapped)",
        "notes": (f"Auto-upgraded from {prev}; matched via {matched_via!r} "
                  f"(name normalization); {match_type}"),
    })
    record["mapping_status"] = "MAPPED"
    record.setdefault("curation_history", []).append({
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "curator": "resolve_unmapped",
        "action": f"AUTO_UPGRADE_TO_{ontology.upper()}",
        "changes": (f"primary {prev} → {new_id} via name "
                    f"normalization to {matched_via!r}"),
        "llm_assisted": False,
    })
    with open(yaml_path, "w") as f:
        yaml.safe_dump(record, f, default_flow_style=False,
                       allow_unicode=True, sort_keys=False)
    return "upgraded"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="apply HIGH upgrades to MIM YAMLs")
    args = ap.parse_args()

    rows = load_all_shards()
    if not rows:
        print(f"No shard outputs in {SHARDS_DIR}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {"HIGH": 0, "NO_HIT": 0}
    upgraded = no_change = errored = 0

    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["yaml_path", "previous_identifier", "preferred_term",
                    "verdict", "matched_via", "ontology_id",
                    "ontology_label", "match_type", "ontology", "action"])

        for row in sorted(rows, key=lambda r: r["yaml_path"]):
            verdict = row["verdict"]
            counts[verdict] = counts.get(verdict, 0) + 1
            match = row.get("match") or {}
            matched_via = match.get("matched_via", "")
            new_id = match.get("id", "")
            new_label = match.get("label", "")
            match_type = match.get("match", "")
            ontology = match.get("ontology", "")
            action = ""

            if verdict == "HIGH" and args.apply:
                yaml_path = MIM_ROOT / row["yaml_path"]
                res = upgrade_unmapped_to_ontology(
                    yaml_path, new_id, new_label, ontology,
                    match_type, matched_via)
                action = res
                if res == "upgraded":
                    upgraded += 1
                elif res == "no-change":
                    no_change += 1
                else:
                    errored += 1
            elif verdict == "HIGH":
                action = "WOULD_UPGRADE"

            w.writerow([row["yaml_path"], row["previous_identifier"],
                        row["preferred_term"], verdict, matched_via,
                        new_id, new_label, match_type, ontology, action])

    md = ["# resolve_unmapped — merged shard results\n",
          f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**",
          f"Shards merged: **{len(list(SHARDS_DIR.glob('shard_*.jsonl')))}**",
          f"Records reviewed: **{len(rows)}**\n",
          "\n## Verdicts\n",
          "| verdict | count |", "|---|---:|"]
    for k in sorted(counts, key=lambda x: -counts[x]):
        md.append(f"| `{k}` | {counts[k]} |")
    if args.apply:
        md.append("\n## Apply summary\n")
        md.append(f"- Upgraded: **{upgraded}**")
        md.append(f"- No-change (already at target): {no_change}")
        md.append(f"- Errors: {errored}")

    md.append("\n\n## HIGH matches by ontology\n")
    md.append("| Ontology | Count |\n|---|---:|")
    by_onto: dict[str, int] = {}
    for row in rows:
        if row["verdict"] == "HIGH":
            o = (row.get("match") or {}).get("ontology", "?")
            by_onto[o] = by_onto.get(o, 0) + 1
    for o in sorted(by_onto, key=lambda x: -by_onto[x]):
        md.append(f"| {o} | {by_onto[o]} |")

    md.append("\n\n## Successful matches (sample, first 50)\n")
    md.append("| Name | Matched via | → ID | Label | Ontology |")
    md.append("|---|---|---|---|---|")
    n = 0
    for row in sorted(rows, key=lambda r: r["yaml_path"]):
        if row["verdict"] != "HIGH":
            continue
        m = row.get("match") or {}
        md.append(
            f"| {row['preferred_term']} | `{m.get('matched_via','')}` | "
            f"`{m.get('id','')}` | {m.get('label','')} | "
            f"{m.get('ontology','')} |")
        n += 1
        if n >= 50:
            break

    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"Merged {len(rows)} records from "
          f"{len(list(SHARDS_DIR.glob('shard_*.jsonl')))} shards")
    for k in sorted(counts, key=lambda x: -counts[x]):
        print(f"  {k}: {counts[k]}")
    if args.apply:
        print(f"  Upgraded: {upgraded} (no-change={no_change}, "
              f"errors={errored})")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"         {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
