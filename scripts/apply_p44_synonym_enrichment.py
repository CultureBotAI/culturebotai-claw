"""
Apply the CLEAN_ADD candidates from the P4.4 enrichment review to the MIM
ingredient YAMLs.

Prerequisite
------------
Run scripts/review_p44_synonym_enrichment.py first.  This script reads the
resulting workspace/reports/kg_microbe_p44_enrichment_review.json and only
acts on entries whose bucket is CLEAN_ADD.  AMBIGUOUS / DUPLICATE / NOISE
entries are never applied automatically.

What it does
------------
For each MIM YAML that owns one or more CLEAN_ADD candidates:
  1. Appends one `synonyms` entry per candidate:
       - synonym_text: <candidate>
         synonym_type: EXACT_SYNONYM
         source: kg_microbe
  2. Appends one `curation_history` entry recording the batch:
       - timestamp: 2026-04-18T00:00:00+00:00
         curator: cbclaw_kg_microbe_sweep
         action: ADDED_SYNONYMS
         changes: Added N synonyms from kg-microbe P4.4 enrichment: ...
         new_status: MAPPED
         llm_assisted: true

Modes
-----
--dry-run    (default) Print a per-file plan, touch nothing.
--apply      Actually write YAMLs.  Still refuses to run if the review file
             is older than the sweep JSON — that catches the case where the
             sweep was rerun but the review wasn't, so the CLEAN_ADD list
             could be stale.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from collections import defaultdict
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
CLAW_ROOT = REPO_ROOT
MIM_ROOT = MIM_ROOT
REPORT_DIR = CLAW_ROOT / "workspace" / "reports"
INGREDIENTS_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"

REVIEW_JSON = REPORT_DIR / "kg_microbe_p44_enrichment_review.json"
SWEEP_JSON = REPORT_DIR / "kg_microbe_sweep.json"

TIMESTAMP = "2026-04-18T00:00:00+00:00"


def _load_clean_adds() -> dict[str, list[str]]:
    """Return {source_file: [candidates, ...]} for CLEAN_ADD only."""
    data = json.loads(REVIEW_JSON.read_text())
    clean: dict[str, list[str]] = defaultdict(list)
    for f in data["per_finding"]:
        seen: set[str] = set()
        for d in f["decisions"]:
            if d["bucket"] != "CLEAN_ADD":
                continue
            c = d["candidate"].strip()
            if c.lower() in seen:
                continue
            seen.add(c.lower())
            clean[f["source_file"]].append(c)
    return clean


def _apply_to_yaml(path: Path, candidates: list[str]) -> int:
    """Mutate the YAML document in place. Returns number of synonyms added."""
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        return 0

    # Skip candidates that are already on the record after reading it fresh
    # — guards against a rerun that would duplicate entries.
    existing_texts = {
        (s.get("synonym_text", "") or "").strip().lower()
        for s in (doc.get("synonyms") or [])
        if isinstance(s, dict)
    }
    existing_texts.add(str(doc.get("preferred_term", "")).strip().lower())
    existing_texts.add(
        str((doc.get("ontology_mapping") or {}).get("ontology_label", ""))
        .strip()
        .lower()
    )

    new_entries = []
    added = []
    for c in candidates:
        if c.strip().lower() in existing_texts:
            continue
        new_entries.append(
            {
                "synonym_text": c,
                "synonym_type": "EXACT_SYNONYM",
                "source": "kg_microbe",
            }
        )
        added.append(c)
        existing_texts.add(c.strip().lower())

    if not new_entries:
        return 0

    doc.setdefault("synonyms", []).extend(new_entries)

    preview = ", ".join(added[:5])
    if len(added) > 5:
        preview += f", ... ({len(added) - 5} more)"
    doc.setdefault("curation_history", []).append(
        {
            "timestamp": TIMESTAMP,
            "curator": "cbclaw_kg_microbe_sweep",
            "action": "ADDED_SYNONYMS",
            "changes": (
                f"Added {len(added)} synonyms from kg-microbe P4.4 "
                f"enrichment: {preview}"
            ),
            "new_status": doc.get("mapping_status", "MAPPED"),
            "llm_assisted": True,
        }
    )

    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return len(added)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N files (alphabetical). Useful for piloting.",
    )
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)


    if not REVIEW_JSON.exists():
        print(f"MISSING: {REVIEW_JSON}", file=sys.stderr)
        print("Run scripts/review_p44_synonym_enrichment.py first.", file=sys.stderr)
        sys.exit(2)

    if SWEEP_JSON.exists():
        if SWEEP_JSON.stat().st_mtime > REVIEW_JSON.stat().st_mtime:
            print(
                "REFUSING: sweep JSON is newer than review JSON. "
                "Rerun scripts/review_p44_synonym_enrichment.py first.",
                file=sys.stderr,
            )
            sys.exit(2)

    clean_by_file = _load_clean_adds()
    files = sorted(clean_by_file)
    if args.limit:
        files = files[: args.limit]

    total_files = len(files)
    total_cands = sum(len(clean_by_file[f]) for f in files)
    print(
        f"{'DRY-RUN' if not args.apply else 'APPLY'}: "
        f"{total_files} files, {total_cands} candidate synonyms"
    )
    print()

    applied_files = 0
    applied_cands = 0
    for i, src in enumerate(files, 1):
        path = INGREDIENTS_DIR / src
        cands = clean_by_file[src]
        if not path.exists():
            print(f"  [SKIP] {src} — YAML not found")
            continue

        if args.apply:
            n = _apply_to_yaml(path, cands)
            if n:
                applied_files += 1
                applied_cands += n
                if i % 50 == 0 or i == total_files:
                    print(f"  [{i}/{total_files}] +{n}  {src}")
        else:
            preview = ", ".join(cands[:3])
            if len(cands) > 3:
                preview += f", ... ({len(cands) - 3} more)"
            if i <= 10 or i % 100 == 0 or i == total_files:
                print(f"  [{i}/{total_files}] {src} (+{len(cands)}: {preview})")

    print()
    if args.apply:
        print(
            f"APPLIED: {applied_cands} synonyms across {applied_files} files."
        )
    else:
        print(
            f"DRY-RUN: would add {total_cands} synonyms across "
            f"{total_files} files. Rerun with --apply to commit."
        )


if __name__ == "__main__":
    main()
