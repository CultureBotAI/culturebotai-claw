#!/usr/bin/env python3
"""
Apply MEDIUM-confidence unmapped candidates, but only those that pass
a stem-overlap verification against the CHEBI's canonical label.

The MEDIUM bucket in mim_curation_candidates.tsv is "single lexical
OLS hit, not exact label match". That set has a high false-positive
rate (e.g. "Cow manure" → "anthraniloyl-CoA") because the OLS search
returned a chemical whose label shares a substring token but isn't
what the curator meant.

Filter each MEDIUM row with the same stem-overlap classifier used by
round_trip_true_bugs.py. Only MIM_OK verdicts (clean semantic match)
get turned into new MIM YAMLs; the rest go to a review markdown.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from round_trip_true_bugs import classify, fetch_ols_label  # noqa: E402
from apply_mim_chebi_fixes import _slug, _create_new_yaml  # type: ignore  # noqa: E402


def _load_existing_chebi_index() -> dict[str, list[str]]:
    """CHEBI -> list of existing MIM YAML filenames using that CHEBI."""
    idx: dict[str, list[str]] = {}
    for path in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if chebi and chebi.startswith("CHEBI:"):
            idx.setdefault(chebi, []).append(path.name)
    return idx


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
MIM_MAPPED_DIR = MIM_ROOT / "data/ingredients/mapped"
WORKSPACE = REPO_ROOT / "workspace"
CANDIDATES_TSV = WORKSPACE / "reports/mim_curation_candidates.tsv"
REVIEW_MD = WORKSPACE / "reports/medium_candidates_reviewed.md"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)


    rows = []
    with CANDIDATES_TSV.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("confidence") == "MEDIUM" and r.get("candidate_1_chebi"):
                rows.append(r)
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(rows)} MEDIUM rows\n")

    existing_chebi = _load_existing_chebi_index()

    cache: dict[str, str] = {}
    accepted = []
    rejected = []
    for r in rows:
        term = r["preferred_term"]
        chebi = r["candidate_1_chebi"]
        chebi_label = r.get("candidate_1_label", "")
        ols_label = fetch_ols_label(chebi, cache) or chebi_label
        bucket, rationale = classify(term, ols_label)
        if bucket == "MIM_OK":
            accepted.append({**r, "_bucket": bucket, "_rationale": rationale,
                             "_ols_label": ols_label})
        else:
            rejected.append({**r, "_bucket": bucket, "_rationale": rationale,
                             "_ols_label": ols_label})

    print(f"Verification: {len(accepted)} accepted, {len(rejected)} rejected\n")
    for a in accepted:
        print(f"  [ACCEPT] {a['source_id']}: {a['preferred_term']} "
              f"→ {a['candidate_1_chebi']} ({a.get('_ols_label', '')})")
    for r in rejected[:5]:
        print(f"  [REJECT] {r['source_id']}: {r['preferred_term']} "
              f"→ {r['candidate_1_chebi']} ({r.get('_ols_label', '')}) [{r.get('_rationale', '')}]")
    if len(rejected) > 5:
        print(f"  ... ({len(rejected) - 5} more rejected)")

    # Write review markdown
    lines = ["# MEDIUM Candidates — Verification Review\n",
             f"Total MEDIUM: {len(rows)}\n",
             f"Accepted (stem-overlap match): {len(accepted)}\n",
             f"Rejected: {len(rejected)}\n\n",
             "## Rejected (curator review needed)\n",
             "| Source | Preferred term | Proposed CHEBI | OLS label | Rationale |",
             "|---|---|---|---|---|"]
    for r in rejected:
        lines.append(
            f"| `{r['source_id']}` | {r['preferred_term']} | "
            f"`{r['candidate_1_chebi']}` | {r.get('_ols_label', '')} | {r.get('_rationale', '')} |"
        )
    REVIEW_MD.write_text("\n".join(lines) + "\n")
    print(f"\nReview markdown: {REVIEW_MD}")

    if not args.apply:
        print("\nDRY-RUN: no files created.")
        return

    # Apply accepted — create new MIM YAMLs, guarding against slug/CHEBI collision.
    created = 0
    for a in accepted:
        chebi = a["candidate_1_chebi"]
        if chebi in existing_chebi:
            print(f"  [SKIP] CHEBI {chebi} already in MIM ({existing_chebi[chebi][0]})")
            continue
        slug = _slug(a["preferred_term"])
        path = MIM_MAPPED_DIR / f"{slug}.yaml"
        if path.exists():
            print(f"  [SKIP] {path.name} already exists")
            continue
        ok, msg = _create_new_yaml(path, a["source_id"], a["preferred_term"],
                                   chebi, a.get("_ols_label") or a["candidate_1_label"])
        marker = "✓" if ok else "✗"
        print(f"  [CREATE] {path.name}: {marker} {msg}")
        if ok:
            created += 1

    print(f"\nDONE. Created {created}/{len(accepted)} MIM YAMLs.")


if __name__ == "__main__":
    main()
