"""
Decide, for each TRUE_BUG P2.5 finding, whether MIM is wrong (needs fix) or
kg-microbe is wrong (no MIM action).

Method
------
For each finding we already have:
  mim_chebi  (what MIM currently stores)
  mim_label  (what MIM thinks that CHEBI means — from its own ontology_label)
  preferred_term   (the ingredient's canonical MIM name)

We re-fetch the *authoritative* OLS label for mim_chebi and compare it to
preferred_term using a stem-overlap heuristic.

Buckets
  MIM_WRONG        OLS label has no chemical-stem overlap with preferred_term
                   → MIM's CHEBI is pointed at an unrelated compound → fix
  MIM_OK           OLS label clearly matches preferred_term → MIM is fine,
                   kg-microbe is noise → no action
  AMBIGUOUS        partial overlap → manual review

Writes workspace/reports/kg_microbe_true_bugs_round_tripped.{json,md}.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPORT_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "culturebotai-claw/workspace/reports"
)

OLS_TERM_URL = (
    "https://www.ebi.ac.uk/ols4/api/ontologies/chebi/terms?iri={iri}"
)


def fetch_ols_label(chebi_id: str, cache: dict[str, str]) -> str:
    if chebi_id in cache:
        return cache[chebi_id]
    iri = "http://purl.obolibrary.org/obo/" + chebi_id.replace(":", "_")
    url = OLS_TERM_URL.format(iri=urllib.parse.quote(iri, safe=""))
    try:
        r = urllib.request.urlopen(url, timeout=30).read()
        d = json.loads(r)
        terms = d.get("_embedded", {}).get("terms", [])
        label = terms[0].get("label", "") if terms else ""
    except Exception as e:
        label = f"<ERROR:{e}>"
    cache[chebi_id] = label
    return label


def _stem_tokens(label: str) -> set[str]:
    s = label.lower()
    s = re.sub(r"\([0-9]+[+\-]\)", " ", s)
    s = re.sub(r"[()\[\],]", " ", s)
    tokens = re.split(r"[\s\-/·.]+", s)
    drop = {
        "", "acid", "ester", "salt", "ion", "ate", "ide", "anion", "cation",
        "hydrate", "anhydrous", "monohydrate", "dihydrate", "trihydrate",
        "tetrahydrate", "pentahydrate", "hexahydrate", "heptahydrate",
        "sodium", "potassium", "calcium", "magnesium", "ammonium", "iron",
        "copper", "zinc", "cobalt", "nickel", "manganese", "aluminium",
        "aluminum", "mercury", "free", "n", "alpha", "beta", "gamma",
        "l", "d", "dl", "r", "s", "dis", "the", "of", "and", "x",
        "chloride", "bromide", "iodide", "fluoride", "sulfate", "sulphate",
        "nitrate", "phosphate", "carbonate", "acetate",
    }
    stems = set()
    for t in tokens:
        # Strip D-/L-/DL- prefix ONLY when followed by a dash (or stripped at
        # tokenization time). Do NOT chop the leading letter off "lipoic",
        # "lysine", "dextrose", etc.
        t = re.sub(r"^(dl|[dl])-", "", t)
        t = re.sub(r"(ate|ic|ous|ium|yl)$", "", t)
        if len(t) >= 4 and t not in drop:
            stems.add(t)
    return stems


# Hand-curated synonyms that the stem-overlap heuristic can't see.
# Left side is normalized (lowercase, no punctuation); right side is a set of
# labels that the tool should consider "effectively identical" to the left.
MANUAL_SYNONYM_GROUPS: list[set[str]] = [
    {"dextrose", "d-glucose", "d-glucopyranose", "glucose"},
    {"cocl2", "cobalt dichloride", "cobalt(ii) chloride"},
    {"kh2po4", "potassium dihydrogen phosphate", "monopotassium phosphate"},
    {"k2hpo4", "dipotassium hydrogen phosphate", "dipotassium phosphate"},
    {"ki", "potassium iodide"},
    {"h2seo3", "selenous acid", "selenious acid"},
    {"hydrogen gas", "dihydrogen", "h2"},
    {"nitrogen gas", "dinitrogen", "n2"},
    {"niacin", "nicotinic acid", "vitamin b3"},
    {"na2b4o7 x 10 h2o", "disodium tetraborate decahydrate", "borax"},
    {"na2-ß-glycerolphosphate", "disodium glycerol 2-phosphate",
     "sodium glycerol 2-phosphate", "sodium beta-glycerophosphate"},
    {"thioctic acid", "(r)-lipoic acid", "alpha-lipoic acid", "lipoic acid"},
    {"alpha-lipoic acid", "lipoic acid", "(r)-lipoic acid"},
    {"sulphur", "sulfur", "sulfur atom", "polysulfur"},
    {"sn-glycero-3-phosphocholine", "choline alfoscerate", "alpha-gpc",
     "alpha-glycerylphosphorylcholine"},
    {"n-acetyl-muramic acid", "n-acetylmuramic acid",
     "aldehydo-n-acetylmuramic acid"},
]


def _in_synonym_group(a: str, b: str) -> bool:
    na = re.sub(r"\s+", " ", a.lower().strip())
    nb = re.sub(r"\s+", " ", b.lower().strip())
    for group in MANUAL_SYNONYM_GROUPS:
        gl = {g.lower() for g in group}
        if na in gl and nb in gl:
            return True
    return False


def classify(preferred_term: str, ols_label: str) -> tuple[str, str]:
    if ols_label.startswith("<ERROR"):
        return "AMBIGUOUS", f"ols-fetch-failed ({ols_label})"
    if not ols_label:
        return "AMBIGUOUS", "ols-no-term"

    pref = preferred_term.lower().strip()
    ols = ols_label.lower().strip()

    if pref == ols:
        return "MIM_OK", "labels-identical"

    pref_norm = re.sub(r"\s+", "", re.sub(r"[·\-_]", "", pref))
    ols_norm = re.sub(r"\s+", "", re.sub(r"[·\-_]", "", ols))
    if pref_norm == ols_norm:
        return "MIM_OK", "labels-identical-after-normalization"

    if _in_synonym_group(pref, ols):
        return "MIM_OK", "hand-curated-synonym-group"

    sp, so = _stem_tokens(pref), _stem_tokens(ols)
    shared = sp & so
    if shared:
        if shared == sp or shared == so:
            return "MIM_OK", f"full-stem-overlap={sorted(shared)[:3]}"
        return "AMBIGUOUS", f"partial-stem-overlap={sorted(shared)[:3]}"

    return "MIM_WRONG", "no-shared-stems"


def main():
    src = REPORT_DIR / "kg_microbe_sweep_triaged.json"
    data = json.loads(src.read_text())
    true_bugs = data["buckets"].get("TRUE_BUG", [])
    print(f"{len(true_bugs)} TRUE_BUG findings to round-trip...", flush=True)

    cache: dict[str, str] = {}

    results = []
    start = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {
            ex.submit(fetch_ols_label, f["mim_chebi"], cache): f for f in true_bugs
        }
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            ols_label = fut.result()
            bucket, rationale = classify(f["preferred_term"], ols_label)
            results.append(
                {
                    "source_file": f["source_file"],
                    "preferred_term": f["preferred_term"],
                    "mim_chebi": f["mim_chebi"],
                    "mim_label_stored": f["evidence"].get("mim_label", ""),
                    "ols_label_now": ols_label,
                    "kg_microbe_chebi": f["evidence"].get("kg_microbe_chebi"),
                    "kg_microbe_label": f["evidence"].get("kg_microbe_label"),
                    "decision": bucket,
                    "rationale": rationale,
                }
            )
            if i % 10 == 0:
                print(f"  {i}/{len(true_bugs)} in {time.time() - start:.0f}s", flush=True)

    elapsed = time.time() - start
    print(f"Done in {elapsed:.0f}s.", flush=True)

    by_bucket = defaultdict(list)
    for r in results:
        by_bucket[r["decision"]].append(r)

    out_json = REPORT_DIR / "kg_microbe_true_bugs_round_tripped.json"
    out_json.write_text(
        json.dumps(
            {
                "summary": {b: len(v) for b, v in by_bucket.items()},
                "elapsed_seconds": elapsed,
                "results": results,
            },
            indent=2,
        )
    )
    print(f"JSON: {out_json}")

    lines = []
    lines.append("# TRUE_BUG Round-Trip Decisions\n\n")
    lines.append("**Date:** 2026-04-18\n")
    lines.append(f"**Findings analyzed:** {len(results)}\n")
    lines.append(f"**OLS round-trip duration:** {elapsed:.0f}s\n\n")
    lines.append("## Summary\n\n")
    lines.append("| Decision | Count | Action |\n|---|---:|---|\n")
    action = {
        "MIM_WRONG": "**Fix MIM — remap CHEBI**",
        "MIM_OK": "No MIM action (kg-microbe wrong or harmless noise)",
        "AMBIGUOUS": "Manual review",
    }
    for b in ("MIM_WRONG", "AMBIGUOUS", "MIM_OK"):
        lines.append(
            f"| {b} | {len(by_bucket.get(b, []))} | {action.get(b, '')} |\n"
        )
    lines.append("\n")

    lines.append("## MIM_WRONG — needs remapping\n\n")
    mw = by_bucket.get("MIM_WRONG", [])
    if not mw:
        lines.append("_None_\n\n")
    else:
        lines.append(
            "| File | preferred_term | MIM stores | OLS says that CHEBI is | kg-microbe suggests |\n"
        )
        lines.append("|---|---|---|---|---|\n")
        for r in sorted(mw, key=lambda x: x["source_file"]):
            lines.append(
                f"| `{r['source_file']}` | {r['preferred_term']} | "
                f"`{r['mim_chebi']}` | {r['ols_label_now']} | "
                f"`{r['kg_microbe_chebi']}` ({r['kg_microbe_label']}) |\n"
            )
        lines.append("\n")

    lines.append("## AMBIGUOUS — manual review\n\n")
    amb = by_bucket.get("AMBIGUOUS", [])
    if not amb:
        lines.append("_None_\n\n")
    else:
        lines.append(
            "| File | preferred_term | OLS label | kg-microbe suggests | why ambiguous |\n"
        )
        lines.append("|---|---|---|---|---|\n")
        for r in sorted(amb, key=lambda x: x["source_file"]):
            lines.append(
                f"| `{r['source_file']}` | {r['preferred_term']} | "
                f"{r['ols_label_now']} | `{r['kg_microbe_chebi']}` "
                f"({r['kg_microbe_label']}) | {r['rationale']} |\n"
            )
        lines.append("\n")

    lines.append("## MIM_OK — no action (kg-microbe noise)\n\n")
    ok = by_bucket.get("MIM_OK", [])
    if not ok:
        lines.append("_None_\n\n")
    else:
        lines.append(f"_{len(ok)} findings where MIM's stored CHEBI ")
        lines.append("matches its preferred_term via OLS; the kg-microbe ")
        lines.append("disagreement is noise (synonym contamination). File list:_\n\n")
        for r in sorted(ok, key=lambda x: x["source_file"]):
            lines.append(
                f"- `{r['source_file']}` — {r['preferred_term']} "
                f"(`{r['mim_chebi']}` / OLS: {r['ols_label_now']})\n"
            )
        lines.append("\n")

    out_md = REPORT_DIR / "kg_microbe_true_bugs_round_tripped.md"
    out_md.write_text("".join(lines))
    print(f"Markdown: {out_md}")
    print()
    print("Final decisions:")
    for b in ("MIM_WRONG", "AMBIGUOUS", "MIM_OK"):
        print(f"  {b:12s} {len(by_bucket.get(b, []))}")


if __name__ == "__main__":
    main()
