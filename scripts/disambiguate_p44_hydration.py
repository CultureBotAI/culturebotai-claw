#!/usr/bin/env python3
"""
Resolve hydration-state-mismatch AMBIGUOUS candidates from P4.4.

The P4.4 reviewer flags candidates like "Sodium acetate·3H2O" as AMBIGUOUS
when they're proposed for an anhydrous record (e.g. `1_M_Sodium_Acetate.yaml`),
because merging hydrate and anhydrous synonyms on the same record would
corrupt both. The correct action is to route the synonym to the matching
hydrate record if one exists.

This script:
  1. Builds a MIM index keyed by (compound-stem, hydration-count).
  2. For each hydration-mismatch AMBIGUOUS candidate, parses its hydration
     count and looks up the matching hydrate/anhydrous MIM record.
  3. If exactly one MIM record matches → emit a CLEAN_ADD for THAT record.
  4. If zero or >1 matches → leave AMBIGUOUS.

Output:
  workspace/reports/p44_hydration_resolution.json
  workspace/reports/p44_hydration_resolution.md

Apply the resolved synonyms with apply_p44_synonym_enrichment.py — this
script only emits proposals; no MIM YAML is touched here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
WORKSPACE = REPO_ROOT / "workspace"
MIM_MAPPED_DIR = MIM_ROOT / "data/ingredients/mapped"
IN_REVIEW = WORKSPACE / "reports/kg_microbe_p44_enrichment_review.json"
OUT_JSON = WORKSPACE / "reports/p44_hydration_resolution.json"
OUT_MD = WORKSPACE / "reports/p44_hydration_resolution.md"

# Word-based hydration markers; maps to count of H2O molecules.
WORD_HYDRATES = {
    "anhydrous": 0,
    "monohydrate": 1, "hemihydrate": 1,   # hemi ~ 0.5 but treated as "has-hydrate"
    "dihydrate": 2,
    "trihydrate": 3,
    "tetrahydrate": 4,
    "pentahydrate": 5,
    "hexahydrate": 6,
    "heptahydrate": 7,
    "octahydrate": 8,
    "nonahydrate": 9,
    "decahydrate": 10,
    "dodecahydrate": 12,
    "octadecahydrate": 18,
}

# Numeric hydrate patterns — capture the integer before H2O.
# Covers: "x 2 H2O", "·3H2O", "・3H2O", ". 6 H2O", "· 2H2O", ".3H2O"
NUM_HYDRATE_RE = re.compile(
    r"(?:[x×.·・]\s*(\d+)\s*h(?:\s?\(|2)?o\b)|(?:(\d+)\s*h2o)",
    re.IGNORECASE,
)
HYDRATE_GENERIC = re.compile(r"\bhydrate\b", re.IGNORECASE)

# Strip concentration / molarity prefixes so stem matching works.
CONC_PREFIX_RE = re.compile(
    r"^\s*(?:\d+(?:[.,]\d+)?\s*(?:m|mm|mmol|μm|um|µm|n|mol)\b\s*)+",
    re.IGNORECASE,
)

# Stem punctuation cleanup.
_STRIP_PUNCT = re.compile(r"[^\w\s]")


def hydration_count(text: str) -> int | None:
    """Return N for N-hydrate, 0 for anhydrous, None if no marker present."""
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
        return -1  # unknown-count hydrate; still "has hydrate"
    return None


def strip_hydration(text: str) -> str:
    """Remove hydration markers for stem computation."""
    if not text:
        return ""
    out = text
    for word in WORD_HYDRATES:
        out = re.sub(rf"\b{re.escape(word)}\b", " ", out, flags=re.IGNORECASE)
    out = NUM_HYDRATE_RE.sub(" ", out)
    out = HYDRATE_GENERIC.sub(" ", out)
    return out


def compound_stem(text: str) -> str:
    """Normalize to a canonical stem for matching across MIM records."""
    if not text:
        return ""
    s = strip_hydration(text)
    s = CONC_PREFIX_RE.sub("", s)
    s = _STRIP_PUNCT.sub(" ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    # Drop trailing standalone "x" left over from "x N H2O"
    s = re.sub(r"\bx\b", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def load_mim_index() -> dict[tuple[str, int | None], list[dict]]:
    """Map (stem, hydration_count) → list of MIM records (file, preferred_term, chebi)."""
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return {}

    idx: dict[tuple[str, int | None], list[dict]] = defaultdict(list)
    for path in sorted(MIM_MAPPED_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("mapping_status") != "MAPPED":
            continue
        pt = doc.get("preferred_term", "") or ""
        chebi = (doc.get("ontology_mapping") or {}).get("ontology_id", "")
        # Use preferred_term + filename signals. Filename often has hydration
        # info the preferred_term omits (e.g. Na2-edta_X_2_H2o.yaml).
        file_hydr = hydration_count(path.stem)
        pt_hydr = hydration_count(pt)
        hydr = pt_hydr if pt_hydr is not None else file_hydr
        stem = compound_stem(pt) or compound_stem(path.stem)
        rec = {"file": path.name, "preferred_term": pt, "chebi": chebi,
               "hydration": hydr}
        idx[(stem, hydr)].append(rec)
    return idx


def resolve(finding: dict, decision: dict,
            mim_index: dict[tuple[str, int | None], list[dict]]) -> dict:
    """Try to route a hydration-mismatch AMBIGUOUS to a better MIM record."""
    cand = decision["candidate"]
    source_file = finding.get("source_file", "")
    mim_file = MIM_MAPPED_DIR / source_file
    pt = finding.get("preferred_term", "") or ""

    cand_hydr = hydration_count(cand)
    stem = compound_stem(cand)
    out = {
        "source_file": source_file,
        "candidate": cand,
        "source_preferred_term": pt,
        "cand_hydration": cand_hydr,
        "cand_stem": stem,
        "resolution": "UNRESOLVED",
        "target_file": "",
        "target_chebi": "",
        "rationale": "",
    }

    if stem == "" or cand_hydr is None:
        out["rationale"] = "could not parse candidate stem/hydration"
        return out

    # Look up by exact (stem, hydration) match.
    targets = mim_index.get((stem, cand_hydr), [])
    # Avoid routing back to the originating record.
    targets = [t for t in targets if t["file"] != source_file]

    if len(targets) == 1:
        t = targets[0]
        out["resolution"] = "ROUTE_TO_HYDRATE" if cand_hydr not in (0, -1) else "ROUTE_TO_ANHYDROUS"
        out["target_file"] = t["file"]
        out["target_chebi"] = t["chebi"]
        out["rationale"] = f"exactly one MIM record matches stem={stem!r}, hydration={cand_hydr}"
    elif len(targets) > 1:
        out["resolution"] = "AMBIGUOUS_TARGETS"
        out["rationale"] = (
            f"{len(targets)} MIM records match stem={stem!r}, hydration={cand_hydr}: "
            + ", ".join(t["file"] for t in targets[:3])
        )
    else:
        # No hydration-match. Try fuzzy: same stem but unknown-count hydrate.
        if cand_hydr != -1:
            fuzzy = mim_index.get((stem, -1), [])
            fuzzy = [t for t in fuzzy if t["file"] != source_file]
            if len(fuzzy) == 1:
                t = fuzzy[0]
                out["resolution"] = "ROUTE_TO_UNKNOWN_HYDRATE"
                out["target_file"] = t["file"]
                out["target_chebi"] = t["chebi"]
                out["rationale"] = "matched to unknown-count hydrate MIM record"
                return out
        out["rationale"] = f"no MIM record with stem={stem!r}, hydration={cand_hydr}"
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    print("[1/4] Loading P4.4 review")
    review = json.loads(IN_REVIEW.read_text())
    print("[2/4] Indexing MIM YAMLs by (stem, hydration)")
    mim_index = load_mim_index()
    print(f"      {sum(len(v) for v in mim_index.values())} MIM records in "
          f"{len(mim_index)} (stem, hydration) buckets")

    print("[3/4] Resolving hydration-mismatch AMBIGUOUS rows")
    resolutions: list[dict] = []
    hyd_total = 0
    for f in review["per_finding"]:
        for dec in f["decisions"]:
            if dec.get("bucket") != "AMBIGUOUS":
                continue
            if dec.get("rationale") != "hydration-state-mismatch":
                continue
            hyd_total += 1
            resolutions.append(resolve(f, dec, mim_index))

    from collections import Counter
    by_res = Counter(r["resolution"] for r in resolutions)
    print(f"      {hyd_total} hydration-mismatch rows processed")
    for k, v in by_res.most_common():
        print(f"      {k}: {v}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "summary": dict(by_res),
        "total": hyd_total,
        "resolutions": resolutions,
    }, indent=2))
    print(f"[4/4] Wrote {OUT_JSON}")

    # Markdown
    lines = [
        "# P4.4 Hydration-State Disambiguation\n",
        f"**Total hydration-mismatch rows:** {hyd_total}\n\n",
        "## Resolution distribution\n",
        "| Resolution | Count | Meaning |",
        "|---|---:|---|",
    ]
    meaning = {
        "ROUTE_TO_HYDRATE": "candidate is hydrate; single matching hydrate MIM record found",
        "ROUTE_TO_ANHYDROUS": "candidate is anhydrous; single matching anhydrous MIM record found",
        "ROUTE_TO_UNKNOWN_HYDRATE": "matched to a MIM record with generic 'hydrate' marker",
        "AMBIGUOUS_TARGETS": "multiple MIM records match — curator picks",
        "UNRESOLVED": "no matching MIM record; synonym has no home",
    }
    for res in ("ROUTE_TO_HYDRATE", "ROUTE_TO_ANHYDROUS",
                "ROUTE_TO_UNKNOWN_HYDRATE", "AMBIGUOUS_TARGETS", "UNRESOLVED"):
        lines.append(f"| {res} | {by_res.get(res, 0)} | {meaning.get(res, '')} |")
    lines.append("")

    # Sample routable
    routable = [r for r in resolutions if r["resolution"].startswith("ROUTE_")]
    if routable:
        lines.append(f"## Sample routable (first 15 of {len(routable)})\n")
        lines.append("| Candidate | From | → Target | Target CHEBI |")
        lines.append("|---|---|---|---|")
        for r in routable[:15]:
            lines.append(
                f"| `{r['candidate']}` | `{r['source_file']}` | → "
                f"`{r['target_file']}` | {r['target_chebi']} |"
            )
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"      Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
