"""
Sweep all MIM mapped ingredients through the P2.5 (kg-microbe disagreement)
and P4.4 (synonym enrichment) rules only. Produces markdown + JSON in
workspace/reports/.

Focused on the two kg-microbe rules to bound OLS API calls — other rules
(P2.1, P3.x, etc.) are not evaluated here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
MIM_ROOT = MIM_ROOT

from _lazy_import import LazyModule  # noqa: E402

# Imported on first use, not at import time, so --help works without a
# MediaIngredientMech checkout (#205).
_reviewer = LazyModule(
    "mediaingredientmech.validation.ingredient_reviewer",
    lambda: (MIM_ROOT / "src",),
    hint="Set MEDIAINGREDIENTMECH_ROOT to a MediaIngredientMech checkout.",
)
_kgm_dict = LazyModule(
    "mediaingredientmech.validation.kg_microbe_dict",
    lambda: (MIM_ROOT / "src",),
    hint="Set MEDIAINGREDIENTMECH_ROOT to a MediaIngredientMech checkout.",
)

WORKSPACE = REPO_ROOT / "workspace"
REPORT_DIR = WORKSPACE / "reports"


def load_ingredients():
    records = []
    for yaml_path in sorted((MIM_ROOT / "data/ingredients/mapped").glob("*.yaml")):
        try:
            with open(yaml_path) as f:
                rec = yaml.safe_load(f)
        except Exception:
            continue
        if not rec:
            continue
        if rec.get("mapping_status") != "MAPPED":
            continue
        rec["_source_file"] = yaml_path.name
        records.append(rec)
    return records


def review_one(reviewer: _reviewer.IngredientReviewer, record: dict):
    """Run ONLY the P2.5 and P4.4 checks; return list of plain-dict findings."""
    ontology_id = (record.get("ontology_mapping") or {}).get("ontology_id")
    ingredient_id = record.get("preferred_term", record["_source_file"])
    if not ontology_id:
        return []

    findings = []

    p25_issues, _ = reviewer._check_kg_microbe_disagreement(
        record, ontology_id, ingredient_id
    )
    for issue in p25_issues:
        findings.append(
            {
                "source_file": record["_source_file"],
                "rule_id": issue.rule_id,
                "priority": issue.priority,
                "preferred_term": record.get("preferred_term"),
                "mim_chebi": ontology_id,
                "message": issue.message,
                "evidence": issue.evidence,
            }
        )

    p44_issues, _ = reviewer._check_kg_microbe_synonym_enrichment(
        record, ontology_id, ingredient_id
    )
    for issue in p44_issues:
        findings.append(
            {
                "source_file": record["_source_file"],
                "rule_id": issue.rule_id,
                "priority": issue.priority,
                "preferred_term": record.get("preferred_term"),
                "mim_chebi": ontology_id,
                "message": issue.message,
                "evidence": issue.evidence,
            }
        )

    return findings


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    print("Loading kg-microbe dict...", flush=True)
    kg_dict = _kgm_dict.KgMicrobeDict()
    kg_dict.load()
    print(f"  {kg_dict.size} CHEBI entries loaded", flush=True)

    print("Loading MIM mapped ingredients...", flush=True)
    records = load_ingredients()
    print(f"  {len(records)} mapped ingredients", flush=True)

    reviewer = _reviewer.IngredientReviewer(kg_microbe_dict=kg_dict)

    print("Sweeping (parallel, 8 workers)...", flush=True)
    start = time.time()
    all_findings = []
    completed = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(review_one, reviewer, r): r for r in records}
        for fut in as_completed(futures):
            rec = futures[fut]
            try:
                all_findings.extend(fut.result())
            except Exception as e:
                print(f"  ERROR on {rec['_source_file']}: {e}", flush=True)
            completed += 1
            if completed % 50 == 0:
                elapsed = time.time() - start
                print(
                    f"  {completed}/{len(records)} in {elapsed:.0f}s "
                    f"({completed / max(elapsed, 0.1):.1f}/s)",
                    flush=True,
                )

    elapsed = time.time() - start
    print(f"Done in {elapsed:.0f}s. {len(all_findings)} findings.", flush=True)

    p25 = [f for f in all_findings if f["rule_id"] == _reviewer.RULE_P2_5]
    p44 = [f for f in all_findings if f["rule_id"] == _reviewer.RULE_P4_4]

    json_path = REPORT_DIR / "kg_microbe_sweep.json"
    with open(json_path, "w") as f:
        json.dump(
            {
                "summary": {
                    "total_ingredients": len(records),
                    "P2.5_disagreements": len(p25),
                    "P4.4_enrichment_candidates": len(p44),
                    "ingredients_with_p25": len({x["source_file"] for x in p25}),
                    "ingredients_with_p44": len({x["source_file"] for x in p44}),
                    "kg_microbe_dict_entries": kg_dict.size,
                    "elapsed_seconds": elapsed,
                },
                "p25_findings": p25,
                "p44_findings": p44,
            },
            f,
            indent=2,
            default=list,
        )
    print(f"JSON report: {json_path}", flush=True)

    md_path = REPORT_DIR / "kg_microbe_sweep.md"
    with open(md_path, "w") as f:
        f.write("# KG-Microbe Dictionary Cross-Reference Sweep\n\n")
        f.write(f"**Date:** 2026-04-18\n")
        f.write(f"**Ingredients reviewed:** {len(records)}\n")
        f.write(f"**kg-microbe dict entries:** {kg_dict.size}\n")
        f.write(f"**Sweep duration:** {elapsed:.0f}s\n\n")

        f.write("## Summary\n\n")
        f.write("| Rule | Findings | Distinct ingredients |\n")
        f.write("|------|---------:|---------------------:|\n")
        f.write(
            f"| P2.5 kg-microbe disagreement | {len(p25)} | "
            f"{len({x['source_file'] for x in p25})} |\n"
        )
        f.write(
            f"| P4.4 kg-microbe synonym enrichment | {len(p44)} | "
            f"{len({x['source_file'] for x in p44})} |\n\n"
        )

        f.write("## P2.5 Disagreements (needs OAK/OLS verification)\n\n")
        if not p25:
            f.write("_None_\n\n")
        else:
            by_file = {}
            for x in p25:
                by_file.setdefault(x["source_file"], []).append(x)
            for fname in sorted(by_file):
                entries = by_file[fname]
                first = entries[0]
                f.write(
                    f"### `{fname}` — `{first['preferred_term']}` "
                    f"→ MIM: `{first['mim_chebi']}`\n\n"
                )
                for e in entries:
                    ev = e["evidence"]
                    f.write(
                        f"- surface form `{ev.get('surface_form')}` — "
                        f"kg-microbe proposes `{ev.get('kg_microbe_chebi')}` "
                        f"({ev.get('kg_microbe_label')}), "
                        f"MIM has `{ev.get('mim_chebi')}` ({ev.get('mim_label')})\n"
                    )
                f.write("\n")

        f.write("## P4.4 Synonym Enrichment Candidates (top 30 by candidate count)\n\n")
        p44_sorted = sorted(
            p44,
            key=lambda x: x["evidence"].get("candidate_count", 0),
            reverse=True,
        )[:30]
        if not p44_sorted:
            f.write("_None_\n\n")
        else:
            f.write("| File | CHEBI | Candidates |\n")
            f.write("|------|-------|-----------:|\n")
            for x in p44_sorted:
                f.write(
                    f"| `{x['source_file']}` | {x['mim_chebi']} | "
                    f"{x['evidence'].get('candidate_count', 0)} |\n"
                )
            f.write("\n")

    print(f"Markdown report: {md_path}", flush=True)


if __name__ == "__main__":
    main()
