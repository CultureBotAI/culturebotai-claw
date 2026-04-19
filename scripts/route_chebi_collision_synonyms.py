#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Route UNRESOLVED P4.4 candidates into existing MIM YAMLs when the
target CHEBI is already present in MIM (CHEBI-collision case).

Flow:
  1. Load HIGH-confidence hydrate-sibling proposals that got blocked
     by CHEBI collision (workspace/reports/hydrate_sibling_proposals.json).
  2. For each blocked proposal, look up the existing MIM YAMLs that
     use the same CHEBI.
  3. For each UNRESOLVED candidate in the group, compute its hydration
     count and match to the MIM YAML whose preferred_term (or filename)
     has the same hydration count.
  4. If exactly one match → add the candidate as an EXACT_SYNONYM there.
     Else → flag for human review.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

MIM_MAPPED_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients/mapped"
)
WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
IN_JSON = WORKSPACE / "reports/hydrate_sibling_proposals.json"
IN_RESOLUTION = WORKSPACE / "reports/p44_hydration_resolution.json"
FLAGS_MD = WORKSPACE / "reports/chebi_collision_routing_flags.md"

TIMESTAMP = datetime.now(timezone.utc).isoformat()

# Hydration parser (copied from disambiguate_p44_hydration.py — small enough
# to keep inline rather than factor into a shared module).
WORD_HYDRATES = {
    "anhydrous": 0,
    "monohydrate": 1, "hemihydrate": 1,
    "dihydrate": 2, "trihydrate": 3, "tetrahydrate": 4,
    "pentahydrate": 5, "hexahydrate": 6, "heptahydrate": 7,
    "octahydrate": 8, "nonahydrate": 9, "decahydrate": 10,
    "dodecahydrate": 12, "octadecahydrate": 18,
}
NUM_HYDRATE_RE = re.compile(
    r"(?:[x×.·・]\s*(\d+)\s*h(?:\s?\(|2)?o\b)|(?:(\d+)\s*h2o)",
    re.IGNORECASE,
)
HYDRATE_GENERIC = re.compile(r"\bhydrate\b", re.IGNORECASE)


def hydration_count(text: str) -> int | None:
    if not text:
        return None
    low = text.lower()
    for word, n in WORD_HYDRATES.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            return n
    m = NUM_HYDRATE_RE.search(text)
    if m:
        g = m.group(1) or m.group(2)
        try:
            return int(g)
        except (TypeError, ValueError):
            pass
    if HYDRATE_GENERIC.search(text):
        return -1
    return None


def _load_mim_by_chebi() -> dict[str, list[dict]]:
    """CHEBI -> list of {file, preferred_term, hydration}."""
    idx: dict[str, list[dict]] = defaultdict(list)
    for path in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        if not chebi.startswith("CHEBI:"):
            continue
        pt = doc.get("preferred_term", "") or ""
        pt_hydr = hydration_count(pt)
        file_hydr = hydration_count(path.stem)
        hydr = pt_hydr if pt_hydr is not None else file_hydr
        idx[chebi].append({
            "file": path.name, "preferred_term": pt, "hydration": hydr,
        })
    return idx


def _apply_synonyms(path: Path, candidates: list[str], source_files: list[str]) -> int:
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        return 0
    existing = {
        (s.get("synonym_text", "") or "").strip().lower()
        for s in (doc.get("synonyms") or [])
        if isinstance(s, dict)
    }
    existing.add(str(doc.get("preferred_term", "")).strip().lower())
    existing.add(
        str((doc.get("ontology_mapping") or {}).get("ontology_label", ""))
        .strip().lower()
    )

    new = []
    added = []
    for c in candidates:
        if c.strip().lower() in existing:
            continue
        new.append({
            "synonym_text": c, "synonym_type": "EXACT_SYNONYM",
            "source": "kg_microbe_via_chebi_collision_routing",
        })
        added.append(c)
        existing.add(c.strip().lower())

    if not new:
        return 0

    doc.setdefault("synonyms", []).extend(new)
    preview = ", ".join(added[:5])
    if len(added) > 5:
        preview += f", ... ({len(added) - 5} more)"
    source_preview = ", ".join(sorted(set(source_files))[:3])
    if len(set(source_files)) > 3:
        source_preview += f", ... (+{len(set(source_files)) - 3} more)"

    doc.setdefault("curation_history", []).append({
        "timestamp": TIMESTAMP,
        "curator": "audit_chebi_collision_routing",
        "action": "ADDED_SYNONYMS_VIA_CHEBI_COLLISION_ROUTING",
        "changes": (
            f"Added {len(added)} synonyms routed to this record because it "
            f"already has the proposed CHEBI and its hydration state matches "
            f"the candidates (sources: {source_preview}): {preview}"
        ),
        "new_status": doc.get("mapping_status", "MAPPED"),
        "llm_assisted": False,
    })
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return len(added)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-medium", action="store_true",
                    help="Also route MEDIUM-confidence proposal candidates.")
    args = ap.parse_args()

    data = json.loads(IN_JSON.read_text())
    levels = ("HIGH", "MEDIUM") if args.include_medium else ("HIGH",)
    high = [p for p in data["proposals"] if p["confidence"] in levels]
    mim_by_chebi = _load_mim_by_chebi()

    # UNRESOLVED rows keyed by candidate text (to rebuild per-candidate hydration info).
    unresolved = json.loads(IN_RESOLUTION.read_text())["resolutions"]
    unresolved_by_cand = {r["candidate"]: r for r in unresolved}

    # Only work on HIGH proposals that collide with existing MIM CHEBIs.
    routing_plan: list[dict] = []
    flagged: list[dict] = []

    for p in high:
        chebi = p["chebi"]
        existing = mim_by_chebi.get(chebi, [])
        if len(existing) == 0:
            continue  # not a collision; handled by apply_hydrate_siblings.py
        # Existing records sharing this CHEBI.
        candidates = p.get("all_candidates") or p.get("sample_candidates") or []

        for cand in candidates:
            # Each UNRESOLVED row has a precomputed hydration for the candidate
            # string; fall back to parsing the string if missing.
            u = unresolved_by_cand.get(cand)
            cand_hydr = u.get("cand_hydration") if u else hydration_count(cand)
            source_file = u.get("source_file", "") if u else ""

            # Match existing MIM records by hydration.
            targets = [e for e in existing if e["hydration"] == cand_hydr]
            if len(targets) == 1:
                routing_plan.append({
                    "candidate": cand, "source_file": source_file,
                    "chebi": chebi, "target_file": targets[0]["file"],
                    "target_hydration": targets[0]["hydration"],
                })
            elif len(targets) > 1:
                flagged.append({
                    "candidate": cand, "source_file": source_file,
                    "chebi": chebi,
                    "reason": f"{len(targets)} MIM records match hydration={cand_hydr}: "
                              + ", ".join(t["file"] for t in targets[:3]),
                })
            else:
                flagged.append({
                    "candidate": cand, "source_file": source_file,
                    "chebi": chebi,
                    "reason": f"no MIM record matches hydration={cand_hydr}; "
                              f"existing: " + ", ".join(
                                  f"{e['file']}(h={e['hydration']})" for e in existing[:3]
                              ),
                })

    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: "
          f"{len(routing_plan)} routable, {len(flagged)} flagged\n")

    # Group the routable plan by target file.
    by_target: dict[str, list[dict]] = defaultdict(list)
    for r in routing_plan:
        by_target[r["target_file"]].append(r)

    total_ok = 0
    for target, rs in sorted(by_target.items()):
        path = MIM_MAPPED_DIR / target
        if not path.exists():
            print(f"  [MISSING] {target}")
            continue
        cands = [r["candidate"] for r in rs]
        sources = [r["source_file"] for r in rs]
        if args.apply:
            n = _apply_synonyms(path, cands, sources)
            total_ok += n
            print(f"  [APPLY]  {target}: +{n}/{len(cands)}")
        else:
            preview = ", ".join(cands[:3])
            if len(cands) > 3:
                preview += f", ... ({len(cands) - 3} more)"
            print(f"  [PLAN]   {target}: +{len(cands)} ({preview})")

    # Write flags
    if flagged:
        lines = ["# CHEBI-Collision Routing Flags\n",
                 f"**Total flagged:** {len(flagged)}\n\n",
                 "| Candidate | From | CHEBI | Reason |",
                 "|---|---|---|---|"]
        for f in flagged:
            lines.append(
                f"| `{f['candidate']}` | `{f['source_file']}` | "
                f"{f['chebi']} | {f['reason']} |"
            )
        FLAGS_MD.write_text("\n".join(lines) + "\n")
        print(f"\nFlagged → {FLAGS_MD}")

    if args.apply:
        print(f"\nDONE. {total_ok} synonyms added across {len(by_target)} files.")
    else:
        print(f"\nDRY-RUN. Would add up to {len(routing_plan)} synonyms across "
              f"{len(by_target)} files.")


if __name__ == "__main__":
    main()
