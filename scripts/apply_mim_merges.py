#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Apply SAFE merges from workspace/reports/mim_merge_plan.tsv — collapses
duplicate MIM YAMLs into their winner.

For each SAFE merge row (≤1 distinct CAS-RN across the group):
  1. Load winner + losers.
  2. Union-dedup `synonyms`; ALSO add each loser's `preferred_term` as
     a synonym so CultureMech/MediaDive surface-form matching still
     resolves to the winner.
  3. Concatenate `curation_history` in timestamp order.
  4. Sum `occurrence_statistics.{total_occurrences, media_count}`.
  5. Preserve winner's `chemical_properties`; if any loser had a CAS-RN
     that the winner lacks, copy it in.
  6. Append a MERGED_FROM_DUPLICATES curation_history entry listing
     the loser filenames.
  7. Write winner; git rm each loser file.

RISKY merges (>1 distinct CAS-RN) are always skipped — these need a
curator to pick the authoritative CAS-RN first.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
MIM_MAPPED_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"
WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
PLAN_TSV = WORKSPACE / "reports/mim_merge_plan.tsv"

TIMESTAMP = datetime.now(timezone.utc).isoformat()


def _load_plan() -> list[dict]:
    rows = []
    with PLAN_TSV.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows.append(r)
    return rows


def _is_safe(row: dict) -> bool:
    conflicts = [c for c in (row.get("cas_rn_conflicts") or "").split("|") if c]
    return len(conflicts) <= 1


def _merge_synonyms(winner_doc: dict, loser_docs: list[dict],
                    loser_preferred_terms: list[str]) -> int:
    """Add all loser synonyms + loser preferred_terms to winner. Return delta."""
    existing = {
        (s.get("synonym_text", "") or "").strip().lower()
        for s in (winner_doc.get("synonyms") or [])
        if isinstance(s, dict)
    }
    existing.add(str(winner_doc.get("preferred_term", "")).strip().lower())
    existing.add(
        str((winner_doc.get("ontology_mapping") or {}).get("ontology_label", ""))
        .strip().lower()
    )

    new_synonyms: list[dict] = []

    # First: add each loser's preferred_term as a synonym (critical for
    # preserving CultureMech/MediaDive surface-form matching).
    for pt in loser_preferred_terms:
        key = (pt or "").strip().lower()
        if not key or key in existing:
            continue
        existing.add(key)
        new_synonyms.append({
            "synonym_text": pt,
            "synonym_type": "EXACT_SYNONYM",
            "source": "merged_from_duplicate_mim_record",
        })

    # Then: union loser synonyms lists.
    for ldoc in loser_docs:
        for s in (ldoc.get("synonyms") or []):
            if not isinstance(s, dict):
                continue
            txt = (s.get("synonym_text", "") or "").strip()
            if not txt:
                continue
            key = txt.lower()
            if key in existing:
                continue
            existing.add(key)
            new_synonyms.append({
                "synonym_text": txt,
                "synonym_type": s.get("synonym_type", "EXACT_SYNONYM"),
                "source": s.get("source", "merged_from_duplicate_mim_record"),
            })

    winner_doc.setdefault("synonyms", []).extend(new_synonyms)
    return len(new_synonyms)


def _merge_curation_history(winner_doc: dict, loser_docs: list[dict]) -> None:
    """Concatenate curation_history in chronological order; dedup identical entries."""
    entries = list(winner_doc.get("curation_history") or [])
    seen = {(e.get("timestamp"), e.get("action"), e.get("changes"))
            for e in entries if isinstance(e, dict)}
    for ldoc in loser_docs:
        for e in (ldoc.get("curation_history") or []):
            if not isinstance(e, dict):
                continue
            key = (e.get("timestamp"), e.get("action"), e.get("changes"))
            if key in seen:
                continue
            seen.add(key)
            entries.append(e)
    # Sort by timestamp string (ISO format sorts lexicographically).
    entries.sort(key=lambda e: e.get("timestamp", ""))
    winner_doc["curation_history"] = entries


def _sum_occurrences(winner_doc: dict, loser_docs: list[dict]) -> None:
    stats = winner_doc.get("occurrence_statistics") or {}
    total = int(stats.get("total_occurrences", 0) or 0)
    media = int(stats.get("media_count", 0) or 0)
    for ldoc in loser_docs:
        s = ldoc.get("occurrence_statistics") or {}
        total += int(s.get("total_occurrences", 0) or 0)
        media += int(s.get("media_count", 0) or 0)
    winner_doc["occurrence_statistics"] = {
        "total_occurrences": total,
        "media_count": media,
    }


def _reconcile_chemical_properties(winner_doc: dict, loser_docs: list[dict]) -> None:
    """If winner lacks a CAS-RN but a loser has one, promote it in."""
    w_props = winner_doc.get("chemical_properties") or {}
    if not w_props.get("cas_rn"):
        for ldoc in loser_docs:
            l_props = ldoc.get("chemical_properties") or {}
            if l_props.get("cas_rn"):
                w_props["cas_rn"] = l_props["cas_rn"]
                if l_props.get("data_source"):
                    w_props["data_source"] = l_props["data_source"]
                if l_props.get("retrieval_date"):
                    w_props["retrieval_date"] = l_props["retrieval_date"]
                break
    if w_props:
        winner_doc["chemical_properties"] = w_props


def _append_merge_entry(winner_doc: dict, loser_files: list[str]) -> None:
    winner_doc.setdefault("curation_history", []).append({
        "timestamp": TIMESTAMP,
        "curator": "audit_mim_merge",
        "action": "MERGED_FROM_DUPLICATES",
        "changes": (
            f"Absorbed {len(loser_files)} duplicate MIM record(s) into this "
            f"one: {', '.join(loser_files)}. Synonyms, curation_history, "
            f"and occurrence counts were unioned/summed; winner selected "
            f"by highest occurrence count with preferred_term readability tie-break."
        ),
        "new_status": winner_doc.get("mapping_status", "MAPPED"),
        "llm_assisted": False,
    })


def _apply_one(winner_name: str, loser_names: list[str], apply: bool) -> dict:
    winner_path = MIM_MAPPED_DIR / winner_name
    loser_paths = [MIM_MAPPED_DIR / n for n in loser_names]

    missing = [p.name for p in [winner_path, *loser_paths] if not p.exists()]
    if missing:
        return {"status": "SKIP", "reason": f"missing files: {', '.join(missing)}",
                "added_synonyms": 0, "deleted": 0}

    winner_doc = yaml.safe_load(winner_path.read_text())
    loser_docs = [yaml.safe_load(p.read_text()) for p in loser_paths]

    if not isinstance(winner_doc, dict) or any(not isinstance(d, dict) for d in loser_docs):
        return {"status": "SKIP", "reason": "non-dict yaml doc",
                "added_synonyms": 0, "deleted": 0}

    loser_pts = [d.get("preferred_term", "") for d in loser_docs]

    added = _merge_synonyms(winner_doc, loser_docs, loser_pts)
    _merge_curation_history(winner_doc, loser_docs)
    _sum_occurrences(winner_doc, loser_docs)
    _reconcile_chemical_properties(winner_doc, loser_docs)
    _append_merge_entry(winner_doc, loser_names)

    if not apply:
        return {"status": "PLAN", "reason": "",
                "added_synonyms": added, "deleted": 0}

    winner_path.write_text(yaml.safe_dump(winner_doc, sort_keys=False,
                                          allow_unicode=True))
    deleted = 0
    for p in loser_paths:
        subprocess.run(["git", "rm", "-q", str(p)],
                       cwd=str(MIM_ROOT), check=True)
        deleted += 1
    return {"status": "DONE", "reason": "",
            "added_synonyms": added, "deleted": deleted}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = _load_plan()
    safe = [r for r in rows if _is_safe(r)]
    risky = [r for r in rows if not _is_safe(r)]

    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: "
          f"{len(safe)} SAFE merges ({len(risky)} RISKY skipped)\n")

    total_added = 0
    total_deleted = 0
    failures = 0
    for r in sorted(safe, key=lambda x: -int(x["total_occurrences"])):
        winner = r["winner"]
        losers = [l for l in r["losers"].split("|") if l]
        result = _apply_one(winner, losers, args.apply)
        marker = {"DONE": "✓", "PLAN": "•", "SKIP": "✗"}.get(result["status"], "?")
        print(f"  [{result['status']:4s}] {marker} {winner:45s} "
              f"← {len(losers)} loser(s) | +{result['added_synonyms']} syns"
              + (f", -{result['deleted']} files" if args.apply else "")
              + (f" ({result['reason']})" if result["reason"] else ""))
        total_added += result["added_synonyms"]
        total_deleted += result["deleted"]
        if result["status"] == "SKIP":
            failures += 1

    print()
    if args.apply:
        print(f"DONE. {total_added} synonyms merged, {total_deleted} YAMLs "
              f"deleted, {failures} skipped.")
        print("Next: `just build-sssom && just validate-sssom && just "
              "review-sssom && just publish-sssom`.")
    else:
        print(f"DRY-RUN. Would add {total_added} synonyms and delete "
              f"{sum(len([l for l in r['losers'].split('|') if l]) for r in safe)} "
              f"files across {len(safe)} merges.")


if __name__ == "__main__":
    main()
