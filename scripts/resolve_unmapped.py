#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Multi-ontology cascading resolver for the 595 MIM `unmapped/` records.

Walks every YAML in `MediaIngredientMech/data/ingredients/unmapped/`,
applies a richer name-normalization layer (hydrate-stripping,
manufacturer-parenthetical stripping, role-qualifier stripping,
Greek prefix variants), and runs OLS cascade across CHEBI / NCIT /
FOODON / MICRO / mesh / ENVO / UBERON.

Sharded for parallel agent-team execution: pass `--shard N --total M`
to process only shard N of M (deterministic by sorted path).

Outputs per-shard JSONL. A merge step (separate script) consolidates.

Read-only; never writes to MIM YAMLs. Use a separate apply pass
after curator review.
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
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
UNMAPPED_DIR = MIM_ROOT / "data" / "ingredients" / "unmapped"
OUT_DIR = REPO_ROOT / "workspace" / "results" / "resolve_unmapped"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
RATE_DELAY = 0.25

# Cascade order: CHEBI first (most specific), then domain ontologies
CASCADE = (
    ("chebi", "CHEBI:"),
    ("ncit", "NCIT:"),
    ("foodon", "FOODON:"),
    ("micro", "MICRO:"),
    ("mesh", "mesh:"),
    ("envo", "ENVO:"),
    ("uberon", "UBERON:"),
)


# ---------- name normalization ----------

# Manufacturer / brand parentheticals
_BRAND_RE = re.compile(
    r"\s*\(\s*(?:Difco|BBL|Oxoid|Sigma|Fluka|Acros|Merck|BD|Nissui|"
    r"Becton[ -]Dickinson|Atlas|Aldrich|sigma)\s*\)",
    re.IGNORECASE,
)

# Hydrate suffixes: " x N H2O", " · N H2O", "·NH2O", " hydrate"
_HYDRATE_RE = re.compile(
    r"\s*(?:[xX·]\s*\d*\s*H2O|·H2O|\s+(?:mono|di|tri|tetra|penta|hexa|"
    r"hepta|octa|nona|deca)?hydrate)\b",
    re.IGNORECASE,
)

# Role qualifiers in parens: "(carbon source)", "(nitrogen source)", etc.
_ROLE_RE = re.compile(
    r"\s*\(\s*(?:carbon|nitrogen|phosphorus|sulfur|sulphur|trace|"
    r"buffer|chelating|gelling|reducing|sterilizing|growth|energy)"
    r"\s+(?:source|agent|element)\s*\)",
    re.IGNORECASE,
)

# "no. NN" suffixes
_NO_SUFFIX_RE = re.compile(r"\s+(?:no\.?|nr\.?|number)\s*\d+\b", re.IGNORECASE)

# Greek prefix variants
_GREEK = [
    ("alpha-", "α-"),
    ("beta-", "β-"),
    ("gamma-", "γ-"),
    ("delta-", "δ-"),
    ("epsilon-", "ε-"),
    ("(R)-", ""),    # try without stereo
    ("(S)-", ""),
    ("(E)-", ""),
    ("(Z)-", ""),
    ("L-", ""),       # try without enantiomer
    ("D-", ""),
]


def normalize_name(name: str) -> list[str]:
    """Return a list of search candidates derived from the name,
    most-likely-to-match first. The original name is always first."""
    candidates = [name.strip()]

    # Strip brand
    n1 = _BRAND_RE.sub("", name).strip()
    if n1 != name and n1 not in candidates:
        candidates.append(n1)

    # Strip hydrate
    n2 = _HYDRATE_RE.sub("", n1).strip()
    if n2 != n1 and n2 not in candidates:
        candidates.append(n2)

    # Strip role qualifier
    n3 = _ROLE_RE.sub("", n2).strip()
    if n3 != n2 and n3 not in candidates:
        candidates.append(n3)

    # Strip "no. NN"
    n4 = _NO_SUFFIX_RE.sub("", n3).strip()
    if n4 != n3 and n4 not in candidates:
        candidates.append(n4)

    # Greek prefix swaps (apply on top of n4)
    for src, dst in _GREEK:
        if src in n4:
            v = n4.replace(src, dst).strip()
            if v and v not in candidates:
                candidates.append(v)

    return candidates


# ---------- OLS cascade ----------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def ols_search_one(term: str, ontology: str, expected_prefix: str) -> dict:
    params = urllib.parse.urlencode({
        "q": term, "ontology": ontology, "rows": 5,
        "exact": "false", "type": "class",
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
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie or not curie.upper().startswith(expected_prefix.upper()):
            continue
        label = d.get("label", "")
        if _norm(label) == n:
            return {"id": curie, "label": label, "match": "label-exact",
                    "ontology": ontology}
        if n in {_norm(s) for s in (d.get("synonym") or [])}:
            return {"id": curie, "label": label, "match": "synonym-exact",
                    "ontology": ontology}
    return {}


def cascade_resolve(name: str) -> dict:
    """Try cascade across ontologies; return first label/synonym-exact
    HIGH match or {}."""
    for ontology, prefix in CASCADE:
        result = ols_search_one(name, ontology, prefix)
        time.sleep(RATE_DELAY)
        if result:
            return result
    return {}


# ---------- driver ----------

def collect_targets(shard: int, total_shards: int) -> list[Path]:
    files = sorted(UNMAPPED_DIR.glob("*.yaml"))
    return [p for i, p in enumerate(files) if i % total_shards == shard]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--total", type=int, default=1,
                    help="total number of shards")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

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
            except Exception as e:
                continue
            name = record.get("preferred_term") or path.stem
            ident = record.get("identifier", "")

            # Try original name first, then normalized variants
            candidates = normalize_name(name)
            best: dict = {}
            tried: list[str] = []
            for cand in candidates:
                tried.append(cand)
                hit = cascade_resolve(cand)
                if hit:
                    best = {**hit, "matched_via": cand}
                    break

            verdict = "HIGH" if best else "NO_HIT"
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

            if i % 20 == 0 or verdict == "HIGH":
                print(f"  [{i}/{len(targets)}] {name[:50]}: "
                      f"{verdict}{(' → ' + best.get('id','')) if best else ''}")

    print()
    print(f"shard {args.shard} done.")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
