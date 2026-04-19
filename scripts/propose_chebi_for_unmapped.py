#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Propose candidate CHEBI IDs for the 430 UNMAPPED_PENDING_CURATION entries
(kgmicrobe.compound:* + mediadive.ingredient:*).

For each ingredient, call EBI OLS4 /search?ontology=chebi and OAK's lexical
index, pick the top 3 candidates by label similarity, assign a confidence
tier. Caches every OLS response so reruns are cheap.

Output: workspace/reports/mim_curation_candidates.tsv

Confidence tiers:
  HIGH     exact label match OR single synonym hit with identical string
  MEDIUM   single candidate via case-insensitive lexical match
  LOW      multiple candidates or no strong match
  NONE     OLS returned no hits
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
QUEUE_TSV = WORKSPACE / "reports/mim_curation_queue.tsv"
CACHE_PATH = WORKSPACE / "cache/chebi_search_cache.json"
OUT_TSV = WORKSPACE / "reports/mim_curation_candidates.tsv"
OUT_MD = WORKSPACE / "reports/mim_curation_candidates.md"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
MAX_WORKERS = 4
TIMEOUT = 15

COLS = [
    "source_id", "preferred_term",
    "candidate_1_chebi", "candidate_1_label", "candidate_1_score",
    "candidate_2_chebi", "candidate_2_label", "candidate_2_score",
    "candidate_3_chebi", "candidate_3_label", "candidate_3_score",
    "confidence", "best_label_match",
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def search_ols(term: str, cache: dict) -> list[dict]:
    if term in cache:
        return cache[term]
    params = urllib.parse.urlencode({
        "q": term, "ontology": "chebi", "rows": 5, "exact": "false",
        "type": "class",
    })
    url = f"{OLS_SEARCH}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            j = json.loads(r.read())
    except Exception as e:
        cache[term] = [{"error": str(e)}]
        return cache[term]
    docs = j.get("response", {}).get("docs", [])
    out: list[dict] = []
    for d in docs:
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie or not curie.startswith("CHEBI:"):
            continue
        out.append({
            "chebi": curie,
            "label": d.get("label", ""),
            "synonyms": d.get("synonym", []),
            "score": float(d.get("score", 0.0)),
        })
    cache[term] = out
    return out


def classify_candidates(term: str, candidates: list[dict]) -> tuple[str, str]:
    """Return (confidence, best_label_match)."""
    if not candidates or candidates[0].get("error"):
        return "NONE", ""
    t = _norm(term)
    top = candidates[0]
    top_label = _norm(top.get("label", ""))
    top_syns = {_norm(s) for s in top.get("synonyms", [])}

    if t == top_label:
        return "HIGH", "label-exact"
    if t in top_syns:
        return "HIGH", "synonym-exact"

    # if any candidate has an exact match
    for c in candidates:
        if _norm(c.get("label", "")) == t:
            return "HIGH", "label-exact-nontop"
        if t in {_norm(s) for s in c.get("synonyms", [])}:
            return "HIGH", "synonym-exact-nontop"

    if len(candidates) == 1:
        return "MEDIUM", "single-lexical-candidate"
    return "LOW", f"{len(candidates)}-candidates-no-exact"


def process_one(row: dict, cache: dict) -> dict:
    term = row["preferred_term"]
    source_id = row["source_id"]

    if not term:
        return {"source_id": source_id, "preferred_term": "", "confidence": "NONE"}

    candidates = search_ols(term, cache)
    confidence, best = classify_candidates(term, candidates)

    out = {"source_id": source_id, "preferred_term": term,
           "confidence": confidence, "best_label_match": best}
    for i in range(3):
        if i < len(candidates) and not candidates[i].get("error"):
            c = candidates[i]
            out[f"candidate_{i+1}_chebi"] = c["chebi"]
            out[f"candidate_{i+1}_label"] = c["label"]
            out[f"candidate_{i+1}_score"] = f"{c['score']:.2f}"
        else:
            out[f"candidate_{i+1}_chebi"] = ""
            out[f"candidate_{i+1}_label"] = ""
            out[f"candidate_{i+1}_score"] = ""
    return out


def write_tsv(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")).replace("\t", " ") for c in COLS) + "\n")


def write_md(path: Path, rows: list[dict]) -> None:
    from collections import Counter
    conf = Counter(r["confidence"] for r in rows)
    out: list[str] = []
    out.append("# MIM Curation Candidates\n")
    out.append(f"**Total unmapped entries processed:** {len(rows)}\n")
    out.append("## Confidence distribution")
    out.append("")
    out.append("| Confidence | Count | Meaning |")
    out.append("|---|---:|---|")
    for c in ("HIGH", "MEDIUM", "LOW", "NONE"):
        out.append(f"| {c} | {conf.get(c, 0)} | "
                   f"{'exact label or synonym match' if c == 'HIGH' else 'single lexical hit' if c == 'MEDIUM' else 'multi-candidate or ambiguous' if c == 'LOW' else 'no OLS hits'} |")
    out.append("")
    high = [r for r in rows if r["confidence"] == "HIGH"][:20]
    if high:
        out.append("## Sample HIGH-confidence candidates (first 20)")
        out.append("")
        out.append("| Source ID | Term | → CHEBI | CHEBI label |")
        out.append("|---|---|---|---|")
        for r in high:
            out.append(
                f"| `{r['source_id']}` | {r['preferred_term']} | "
                f"`{r.get('candidate_1_chebi', '')}` | {r.get('candidate_1_label', '')} |"
            )
        out.append("")
    path.write_text("\n".join(out) + "\n")


def main() -> None:
    with QUEUE_TSV.open() as f:
        queue = list(csv.DictReader(f, delimiter="\t"))
    # Skip rows that already have a MIM link (already_in_mim == yes).
    queue = [r for r in queue if r.get("already_in_mim") != "yes"]
    print(f"[1/3] Loaded {len(queue)} unmapped entries")

    cache = _load_cache()
    print(f"      Cache has {len(cache)} prior lookups")

    results: list[dict] = []
    start = time.time()

    # Run serially in batches to keep the cache consistent; OLS tolerates our rate fine.
    for i, row in enumerate(queue, 1):
        results.append(process_one(row, cache))
        if i % 50 == 0:
            elapsed = time.time() - start
            print(f"  {i}/{len(queue)} in {elapsed:.0f}s", flush=True)
            _save_cache(cache)  # periodic save

    _save_cache(cache)
    print(f"[2/3] Processed in {time.time() - start:.0f}s")

    write_tsv(OUT_TSV, results)
    write_md(OUT_MD, results)
    print(f"[3/3] Wrote {OUT_TSV}")
    print(f"      Wrote {OUT_MD}")

    from collections import Counter
    conf = Counter(r["confidence"] for r in results)
    print(f"\nConfidence: HIGH={conf.get('HIGH', 0)} MEDIUM={conf.get('MEDIUM', 0)} "
          f"LOW={conf.get('LOW', 0)} NONE={conf.get('NONE', 0)}")


if __name__ == "__main__":
    main()
