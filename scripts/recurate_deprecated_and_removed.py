#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Re-curate the 6 MIM ingredients whose CHEBI is either obsolete (3 rows from
mim_deprecated_chebi_patches.yaml) or removed entirely from CHEBI (3 rows
from mim_label_drift_patches.yaml with CHEBI_REMOVED).

The original patch files used CHEBI's mechanical term-replaced-by axioms,
which in practice are semantically unsound for MIM's ingredients
(e.g. CHEBI:8150 → phospholipid for Bacto_Soytone, which is a peptone).

This script searches OLS for each MIM preferred_term and picks the best
candidate CHEBI, emitting a revised patch file
workspace/patches/mim_chebi_recuration_patches.yaml with HIGH/MEDIUM/LOW
confidence per row.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
MIM_MAPPED_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients/mapped"
)
OUT_YAML = WORKSPACE / "patches/mim_chebi_recuration_patches.yaml"
OUT_MD = WORKSPACE / "reports/mim_chebi_recuration_summary.md"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"

# Six items: (slug, preferred_term, bad_chebi, reason)
TARGETS: list[tuple[str, str, str, str]] = [
    ("Bacto_Soytone", "Bacto-soytone", "CHEBI:8150", "obsolete"),
    ("Soytone", "Soytone", "CHEBI:8150", "obsolete"),
    ("Chebi1", "Chebi1 (placeholder)", "CHEBI:1", "obsolete"),
    ("Casein", "Casein", "CHEBI:3448", "removed"),
    ("Catalase", "Catalase", "CHEBI:3463", "removed"),
    ("Diaminopimelic_Acid", "Diaminopimelic acid", "CHEBI:23674", "removed"),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def search_ols(term: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": term, "ontology": "chebi", "rows": 5,
        "exact": "false", "type": "class",
    })
    url = f"{OLS_SEARCH}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        return [{"error": str(e)}]
    out = []
    for d in j.get("response", {}).get("docs", []):
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie.startswith("CHEBI:"):
            continue
        out.append({
            "chebi": curie,
            "label": d.get("label", ""),
            "synonyms": d.get("synonym", []),
            "is_obsolete": bool(d.get("is_obsolete")),
            "score": float(d.get("score", 0)),
        })
    return out


def classify(term: str, candidates: list[dict]) -> tuple[str, str, dict | None]:
    """Return (confidence, reason, best_candidate_or_None)."""
    if not candidates or (len(candidates) == 1 and candidates[0].get("error")):
        return "NONE", "no OLS hits", None
    non_obs = [c for c in candidates if not c.get("is_obsolete")]
    if not non_obs:
        return "NONE", "only obsolete candidates", None

    t = _norm(term)
    for c in non_obs:
        if _norm(c["label"]) == t:
            return "HIGH", "label-exact", c
    for c in non_obs:
        if t in {_norm(s) for s in c.get("synonyms", [])}:
            return "HIGH", "synonym-exact", c
    if len(non_obs) == 1:
        return "MEDIUM", "single lexical candidate", non_obs[0]
    return "LOW", f"{len(non_obs)} non-obsolete candidates", non_obs[0]


def build_patches() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    patches: list[dict] = []

    for slug, term, bad, reason in TARGETS:
        yaml_path = MIM_MAPPED_DIR / f"{slug}.yaml"
        if not yaml_path.exists():
            continue

        candidates = search_ols(term)
        time.sleep(0.2)
        confidence, rationale, best = classify(term, candidates)

        patch = {
            "file": f"data/ingredients/mapped/{slug}.yaml",
            "mim_id": f"MIM:{slug}",
            "mim_label": term,
            "bad_chebi": bad,
            "bad_chebi_reason": reason,
            "new_chebi": best["chebi"] if best else "",
            "new_label": best["label"] if best else "",
            "confidence": confidence,
            "rationale": rationale,
            "candidates": [
                {"chebi": c["chebi"], "label": c["label"],
                 "is_obsolete": c.get("is_obsolete", False)}
                for c in candidates[:3] if "error" not in c
            ],
            "proposed_curation_entry": {
                "timestamp": now,
                "curator": "audit_recurate_chebi",
                "action": (
                    "FIXED_OBSOLETE_CHEBI" if reason == "obsolete"
                    else "FIXED_REMOVED_CHEBI"
                ),
                "changes": (
                    f"Replaced {bad} ({reason} in CHEBI) with {best['chebi']} ({best['label']})"
                    if best else
                    f"{bad} is {reason} in CHEBI; no HIGH-confidence replacement found"
                ),
                "new_status": "MAPPED" if confidence == "HIGH" else "NEEDS_REVIEW",
                "llm_assisted": False,
            },
        }
        patches.append(patch)
    return patches


def write_yaml(path: Path, patches: list[dict]) -> None:
    try:
        import yaml
        path.write_text(yaml.safe_dump(patches, sort_keys=False))
    except ImportError:
        path.write_text("\n".join(json.dumps(p) for p in patches) + "\n")


def write_md(path: Path, patches: list[dict]) -> None:
    out = ["# MIM CHEBI Re-curation Summary\n",
           f"**Total patches:** {len(patches)}\n\n",
           "| MIM file | preferred_term | Bad CHEBI | → | New CHEBI | Label | Confidence |\n",
           "|---|---|---|---|---|---|---|\n"]
    for p in patches:
        out.append(
            f"| `{Path(p['file']).name}` | {p['mim_label']} | "
            f"`{p['bad_chebi']}` ({p['bad_chebi_reason']}) | → | "
            f"`{p['new_chebi'] or '—'}` | {p['new_label'] or '—'} | "
            f"**{p['confidence']}** |\n"
        )
    path.write_text("".join(out))


def main() -> None:
    print(f"[1/2] Re-curating {len(TARGETS)} CHEBIs via OLS search")
    patches = build_patches()
    print(f"      {len(patches)} patches built")

    OUT_YAML.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(OUT_YAML, patches)
    write_md(OUT_MD, patches)
    print(f"[2/2] Wrote {OUT_YAML}")
    print(f"      Wrote {OUT_MD}")

    from collections import Counter
    conf = Counter(p["confidence"] for p in patches)
    print(f"\nConfidence: HIGH={conf.get('HIGH', 0)} MEDIUM={conf.get('MEDIUM', 0)} "
          f"LOW={conf.get('LOW', 0)} NONE={conf.get('NONE', 0)}")


if __name__ == "__main__":
    main()
