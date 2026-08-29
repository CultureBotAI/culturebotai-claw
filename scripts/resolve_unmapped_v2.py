#!/usr/bin/env /opt/homebrew/bin/python3.13
"""More aggressive multi-strategy resolver for the still-unmapped MIM
records. Builds on resolve_unmapped.py (v1) which found 59/595 HIGH
hits via cascading per-ontology label/synonym-exact search.

V2 adds three additional strategies for the 536 v1 NO_HITs:

  1. ANY-ONTOLOGY exact: OLS search without ontology filter. Catches
     records where the term is in an ontology we don't enumerate
     (e.g., HP, MONDO, GO, BTO, DOID).
  2. PARTIAL-NAME exact: strip trailing single token / number / letter
     (e.g., "atrop-abyssomicin C" → "atrop-abyssomicin"). Catches
     congeners that don't have individual ontology terms.
  3. STEM-MATCH: if a candidate label is a substring of the name,
     accept as STEM_MATCH (medium confidence).

Sharded for parallel execution; output to
workspace/results/resolve_unmapped_v2/shard_N_of_M.jsonl.
"""
from __future__ import annotations

import argparse
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

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
UNMAPPED_DIR = MIM_ROOT / "data" / "ingredients" / "unmapped"
OUT_DIR = REPO_ROOT / "workspace" / "results" / "resolve_unmapped_v2"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
RATE_DELAY = 0.20

# Ontologies the v2 strategies target (when filtered). Includes the
# v1 cascade plus broader coverage that often hits clinical /
# microbiology / biology terms.
TARGETED_ONTOLOGIES = (
    "chebi", "ncit", "foodon", "micro", "mesh", "envo", "uberon",
    "go", "bto", "doid", "hp", "mondo",
)

# Reusable normalizers
_TRAILING_SINGLE_CHAR = re.compile(r"\s+[A-Z]$")
_TRAILING_NUMBER = re.compile(r"\s+\d+$")
_TRAILING_NO_SUFFIX = re.compile(r"\s+(?:no\.?|nr\.?)\s*\d+$", re.IGNORECASE)
_STEREO_RE = re.compile(r"^\((?:[REZSL]|R/S|S-|R-)\)-")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def normalize_v2(name: str) -> list[str]:
    """V2 candidate generators: returns list of name variants to try."""
    candidates = [name.strip()]
    n = name.strip()

    # Strip trailing single capital letter (congener marker)
    m = _TRAILING_SINGLE_CHAR.sub("", n).strip()
    if m and m != n:
        candidates.append(m)
    # Strip trailing number / "no. NN"
    for pat in (_TRAILING_NUMBER, _TRAILING_NO_SUFFIX):
        m2 = pat.sub("", n).strip()
        if m2 and m2 not in candidates:
            candidates.append(m2)
    # Strip stereo prefix
    m3 = _STEREO_RE.sub("", n).strip()
    if m3 and m3 not in candidates:
        candidates.append(m3)
    return candidates


def ols_any_ontology(term: str) -> dict:
    """Search OLS without ontology filter; return first non-obsolete
    label-exact / synonym-exact match in any of TARGETED_ONTOLOGIES."""
    params = urllib.parse.urlencode({
        "q": term, "rows": 12, "exact": "false", "type": "class",
    })
    try:
        with urllib.request.urlopen(
                f"{OLS_SEARCH}?{params}", timeout=15) as r:
            j = json.loads(r.read())
    except Exception:
        return {}
    n = _norm(term)
    for d in j.get("response", {}).get("docs", []):
        if d.get("is_obsolete"):
            continue
        onto = (d.get("ontology_prefix") or "").lower()
        if onto not in TARGETED_ONTOLOGIES:
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie:
            continue
        label = d.get("label", "")
        if _norm(label) == n:
            return {"id": curie, "label": label, "match": "label-exact",
                    "ontology": onto}
        if n in {_norm(s) for s in (d.get("synonym") or [])}:
            return {"id": curie, "label": label, "match": "synonym-exact",
                    "ontology": onto}
    return {}


def ols_stem_match(term: str) -> dict:
    """Looser: search OLS, for each non-obsolete candidate, accept if
    the normalized label is a contiguous substring of the term name
    AND the label has ≥ 2 non-stop tokens (avoid trivial single-word
    matches). Returns STEM_MATCH (medium confidence)."""
    params = urllib.parse.urlencode({
        "q": term, "rows": 12, "exact": "false", "type": "class",
    })
    try:
        with urllib.request.urlopen(
                f"{OLS_SEARCH}?{params}", timeout=15) as r:
            j = json.loads(r.read())
    except Exception:
        return {}
    n = _norm(term)
    for d in j.get("response", {}).get("docs", []):
        if d.get("is_obsolete"):
            continue
        onto = (d.get("ontology_prefix") or "").lower()
        if onto not in TARGETED_ONTOLOGIES:
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie:
            continue
        label = d.get("label", "")
        l = _norm(label)
        # ≥2 alpha tokens to avoid "soil"-style trivials
        if len(re.findall(r"[a-z]{2,}", l)) < 2:
            continue
        if l and l in n:
            return {"id": curie, "label": label, "match": "stem-substring",
                    "ontology": onto}
    return {}


def collect_targets(shard: int, total: int) -> list[Path]:
    files = sorted(UNMAPPED_DIR.glob("*.yaml"))
    return [p for i, p in enumerate(files) if i % total == shard]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--total", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    # Verify the checkout before doing work; module-level roots stay
    # plain paths so importing this file never needs one (#176).
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    out_path = OUT_DIR / f"shard_{args.shard}_of_{args.total}.jsonl"
    targets = collect_targets(args.shard, args.total)
    if args.limit:
        targets = targets[: args.limit]
    print(f"shard {args.shard}/{args.total}: {len(targets)} records")

    counts: dict[str, int] = {}
    with open(out_path, "w") as out_f:
        for i, path in enumerate(targets, 1):
            try:
                with open(path) as f:
                    record = yaml.safe_load(f) or {}
            except Exception:
                continue
            name = record.get("preferred_term") or path.stem
            ident = record.get("identifier", "")

            # Strategy 1: any-ontology exact on each name variant
            best: dict = {}
            tried: list[str] = []
            verdict = "NO_HIT"
            for v in normalize_v2(name):
                tried.append(v)
                hit = ols_any_ontology(v)
                time.sleep(RATE_DELAY)
                if hit:
                    best = {**hit, "matched_via": v, "strategy": "any-onto-exact"}
                    verdict = "HIGH"
                    break

            # Strategy 2: stem match (medium) — only if no exact hit
            if not best:
                hit = ols_stem_match(name)
                time.sleep(RATE_DELAY)
                if hit:
                    best = {**hit, "matched_via": name, "strategy": "stem-match"}
                    verdict = "STEM_MATCH"

            counts[verdict] = counts.get(verdict, 0) + 1
            row = {
                "yaml_path": str(path.relative_to(MIM_ROOT)),
                "previous_identifier": ident,
                "preferred_term": name,
                "candidates_tried": tried,
                "verdict": verdict,
                "match": best,
            }
            out_f.write(json.dumps(row) + "\n")
            out_f.flush()
            if verdict in ("HIGH", "STEM_MATCH") or i % 20 == 0:
                tag = (f' → {best.get("id","")} ({best.get("ontology","")})'
                       if best else '')
                print(f"  [{i}/{len(targets)}] {name[:50]}: {verdict}{tag}")

    print(f"\nshard {args.shard} done.")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
