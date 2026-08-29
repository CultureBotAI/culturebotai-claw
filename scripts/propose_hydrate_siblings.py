#!/usr/bin/env python3
"""
For each UNRESOLVED (stem, hydration) group from the hydration
disambiguator, search OLS for a CHEBI ID that matches the hydrate/anhydrous
form, so a new MIM sibling YAML can be created.

Input:  workspace/reports/p44_hydration_resolution.json  (UNRESOLVED rows)
Output: workspace/reports/hydrate_sibling_proposals.{json,md}
        workspace/cache/chebi_search_cache.json           (shared cache)

For each group we try two OLS queries in sequence:

  1. The first candidate string literally (e.g. "CaCl2 x 2 H2O") — often
     matches as a CHEBI synonym directly.
  2. Stem + hydration word (e.g. "calcium chloride dihydrate").

HIGH-confidence = exact label or synonym match on a non-obsolete CHEBI term.
Anything less is MEDIUM/LOW/NONE and left for human review.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = REPO_ROOT / "workspace"
IN_JSON = WORKSPACE / "reports/p44_hydration_resolution.json"
OUT_JSON = WORKSPACE / "reports/hydrate_sibling_proposals.json"
OUT_MD = WORKSPACE / "reports/hydrate_sibling_proposals.md"
CACHE = WORKSPACE / "cache/chebi_search_cache.json"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"

HYDRATE_WORD = {
    0: "anhydrous",
    1: "monohydrate",
    2: "dihydrate",
    3: "trihydrate",
    4: "tetrahydrate",
    5: "pentahydrate",
    6: "hexahydrate",
    7: "heptahydrate",
    8: "octahydrate",
    9: "nonahydrate",
    10: "decahydrate",
    12: "dodecahydrate",
    18: "octadecahydrate",
    -1: "hydrate",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2))


def search_ols(query: str, cache: dict) -> list[dict]:
    if query in cache:
        return cache[query]
    params = urllib.parse.urlencode({
        "q": query, "ontology": "chebi", "rows": 5,
        "exact": "false", "type": "class",
    })
    url = f"{OLS_SEARCH}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        cache[query] = [{"error": str(e)}]
        return cache[query]
    out = []
    for d in j.get("response", {}).get("docs", []):
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie.startswith("CHEBI:"):
            continue
        out.append({
            "chebi": curie, "label": d.get("label", ""),
            "synonyms": d.get("synonym", []),
            "is_obsolete": bool(d.get("is_obsolete")),
            "score": float(d.get("score", 0)),
        })
    cache[query] = out
    return out


def classify(query: str, candidates: list[dict]) -> tuple[str, str, dict | None]:
    if not candidates or (len(candidates) == 1 and candidates[0].get("error")):
        return "NONE", "no hits", None
    non_obs = [c for c in candidates if not c.get("is_obsolete")]
    if not non_obs:
        return "NONE", "only obsolete", None
    q = _norm(query)
    for c in non_obs:
        if _norm(c.get("label", "")) == q:
            return "HIGH", "label-exact", c
    for c in non_obs:
        if q in {_norm(s) for s in c.get("synonyms", [])}:
            return "HIGH", "synonym-exact", c
    if len(non_obs) == 1:
        return "MEDIUM", "single candidate", non_obs[0]
    return "LOW", f"{len(non_obs)} candidates, no exact", non_obs[0]


def main() -> None:
    data = json.loads(IN_JSON.read_text())
    unresolved = [r for r in data["resolutions"] if r["resolution"] == "UNRESOLVED"]
    print(f"[1/3] {len(unresolved)} UNRESOLVED rows")

    by_pair: dict[tuple[str, int | None], list[dict]] = defaultdict(list)
    for r in unresolved:
        by_pair[(r["cand_stem"], r["cand_hydration"])].append(r)
    print(f"      {len(by_pair)} unique (stem, hydration) pairs")

    cache = _load_cache()
    print(f"      Cache has {len(cache)} prior lookups")

    proposals = []
    start = time.time()
    # Sort key: None hydration sorts last.
    sort_key = lambda kv: (kv[0][0], 999 if kv[0][1] is None else kv[0][1])
    for i, ((stem, hydr), rows) in enumerate(sorted(by_pair.items(), key=sort_key), 1):
        # Try the literal candidate text first (often matches CHEBI synonym).
        literal = rows[0]["candidate"]
        candidates = search_ols(literal, cache)
        conf, rationale, best = classify(literal, candidates)
        used_query = literal

        # Fallback: stem + hydration word.
        if conf != "HIGH":
            hyd_word = HYDRATE_WORD.get(hydr) if hydr is not None else None
            q2 = f"{stem} {hyd_word}".strip() if hyd_word else stem
            if q2 and q2 != literal:
                c2 = search_ols(q2, cache)
                conf2, rationale2, best2 = classify(q2, c2)
                if conf2 == "HIGH" or (conf2 in ("MEDIUM", "LOW") and conf == "NONE"):
                    conf, rationale, best = conf2, rationale2, best2
                    used_query = q2
                    candidates = c2

        proposals.append({
            "stem": stem,
            "hydration": hydr,
            "candidate_count": len(rows),
            "sample_candidates": [r["candidate"] for r in rows[:5]],
            "all_candidates": [r["candidate"] for r in rows],
            "source_files": sorted({r["source_file"] for r in rows}),
            "query": used_query,
            "confidence": conf,
            "rationale": rationale,
            "chebi": best["chebi"] if best else "",
            "label": best["label"] if best else "",
            "is_obsolete": bool(best and best.get("is_obsolete")),
        })

        if i % 50 == 0:
            _save_cache(cache)
            print(f"  {i}/{len(by_pair)} in {time.time() - start:.0f}s", flush=True)

    _save_cache(cache)
    print(f"[2/3] Processed {len(by_pair)} groups in {time.time() - start:.0f}s")

    from collections import Counter
    by_conf = Counter(p["confidence"] for p in proposals)
    print("Confidence:", dict(by_conf))

    OUT_JSON.write_text(json.dumps({"summary": dict(by_conf),
                                    "proposals": proposals}, indent=2))

    # Markdown
    lines = [
        "# Hydrate Sibling Proposals\n",
        f"**Unique (stem, hydration) groups:** {len(proposals)}\n",
        f"**Total UNRESOLVED candidates covered:** "
        f"{sum(p['candidate_count'] for p in proposals)}\n\n",
        "## Confidence distribution\n",
        "| Confidence | Groups | Candidates covered |",
        "|---|---:|---:|",
    ]
    for c in ("HIGH", "MEDIUM", "LOW", "NONE"):
        grp = sum(1 for p in proposals if p["confidence"] == c)
        cand = sum(p["candidate_count"] for p in proposals if p["confidence"] == c)
        lines.append(f"| {c} | {grp} | {cand} |")

    high = [p for p in proposals if p["confidence"] == "HIGH"][:25]
    if high:
        lines.append(f"\n## Sample HIGH proposals (first {len(high)})\n")
        lines.append("| Stem | Hydration | → CHEBI | Label | Candidate count |")
        lines.append("|---|---|---|---|---:|")
        for p in high:
            lines.append(
                f"| {p['stem']} | {p['hydration']} | `{p['chebi']}` | "
                f"{p['label']} | {p['candidate_count']} |"
            )
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"[3/3] Wrote {OUT_JSON}")
    print(f"      Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
