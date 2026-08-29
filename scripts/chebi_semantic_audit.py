#!/usr/bin/env python3
"""Semantic audit of CultureMech ingredient→CHEBI assertions.

The existing id↔label gate waives canonical-label matching for `term` /
`chebi_term` blocks and only checks that the id EXISTS. A hallucinated-but-real
CHEBI id therefore passes silently. This re-checks every assertion against
OAK's label + synonyms and flags the ones with no lexical support at all.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
CULTUREMECH_ROOT_PATH = Path(
    os.environ.get("CULTUREMECH_ROOT", REPO_ROOT.parent / "CultureMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
CM = CULTUREMECH_ROOT_PATH
DEFAULT_OUT = Path("chebi_semantic_audit.tsv")

STOP = {
    "acid", "salt", "solution", "water", "x", "of", "and", "the", "a",
    "hydrate", "anhydrous", "dihydrate", "monohydrate", "reduced",
}


def norm_tokens(s: str) -> set[str]:
    s = s.lower()
    s = s.replace("α", "alpha").replace("β", "beta").replace("·", " ")
    toks = {t for t in re.split(r"[^a-z0-9]+", s) if t and t not in STOP}
    return toks


def walk(node, out: list, path: str = ""):
    """Yield dicts that look like {id: <curie>, label: <str>} plus context."""
    if isinstance(node, dict):
        nid, nlab = node.get("id"), node.get("label")
        if isinstance(nid, str) and isinstance(nlab, str) and ":" in nid:
            out.append((nid.strip(), nlab.strip(), path))
        for k, v in node.items():
            walk(v, out, k)
    elif isinstance(node, list):
        for v in node:
            walk(v, out, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # This script has always taken its destination positionally, by reading
    # sys.argv directly. Declaring it keeps that working now that arguments
    # are parsed -- a bare parser rejected it as unrecognized.
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_OUT,
        help=f"where to write the audit (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args()
    out = args.output
    require_mech_roots("culturemech", claw_root=REPO_ROOT)

    # ---- 1. harvest every (chebi_id, asserted_label, preferred_term, quality) ----
    assertions: dict[tuple[str, str], dict] = {}
    files = sorted(CM.glob("data/merge_yaml/**/*.yaml")) + sorted(
        CM.glob("data/normalized_yaml/**/*.yaml")
    )
    print(f"scanning {len(files)} CultureMech YAMLs ...", flush=True)

    for i, p in enumerate(files):
        if i and i % 4000 == 0:
            print(f"  {i}/{len(files)}", flush=True)
        try:
            doc = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for ing in doc.get("ingredients") or []:
            if not isinstance(ing, dict):
                continue
            pref = (ing.get("preferred_term") or "").strip()
            term = ing.get("term")
            if not isinstance(term, dict):
                continue
            cid = (term.get("id") or "").strip()
            lab = (term.get("label") or "").strip()
            if not cid.startswith("CHEBI:"):
                continue
            qual = ((ing.get("curation_metadata") or {}).get("mapping_quality") or "").strip()
            key = (pref, cid)
            rec = assertions.setdefault(key, {
                "preferred_term": pref, "chebi_id": cid, "asserted_label": lab,
                "qualities": set(), "n_files": 0, "example_file": str(p.relative_to(CM)),
            })
            rec["qualities"].add(qual)
            rec["n_files"] += 1

    print(f"unique (preferred_term, CHEBI) assertions: {len(assertions)}")

    # ---- 2. resolve every distinct CHEBI once via OAK ----
    cids = sorted({v["chebi_id"] for v in assertions.values()})
    print(f"resolving {len(cids)} distinct CHEBI ids via OAK ...", flush=True)
    from oaklib import get_adapter
    ad = get_adapter("sqlite:obo:chebi")
    obsolete = set(ad.obsoletes())
    info: dict[str, dict] = {}
    for j, c in enumerate(cids):
        if j and j % 500 == 0:
            print(f"  {j}/{len(cids)}", flush=True)
        lab = ad.label(c)
        try:
            als = {a for a in ad.entity_aliases(c) if a}
        except Exception:
            als = set()
        info[c] = {"label": lab or "", "aliases": als, "obsolete": c in obsolete}

    # ---- 3. classify ----
    rows = []
    for (pref, cid), rec in assertions.items():
        oi = info[cid]
        if not oi["label"]:
            verdict, why = "ID_NOT_FOUND", "CHEBI id absent from OAK"
        else:
            ptok = norm_tokens(pref)
            support = [oi["label"], *oi["aliases"]]
            best = 0.0
            for s in support:
                stok = norm_tokens(s)
                if not stok or not ptok:
                    continue
                ov = len(ptok & stok) / max(1, min(len(ptok), len(stok)))
                best = max(best, ov)
            if best >= 0.99:
                verdict, why = "EXACT", "preferred_term matches label/synonym"
            elif best >= 0.5:
                verdict, why = "PARTIAL", f"token overlap {best:.2f}"
            else:
                verdict, why = "NO_LEXICAL_SUPPORT", f"token overlap {best:.2f}"
        rows.append({
            "verdict": verdict,
            "preferred_term": pref,
            "chebi_id": cid,
            "oak_label": oi["label"],
            "asserted_label": rec["asserted_label"],
            "label_copied_from_name": "YES" if rec["asserted_label"] == pref else "no",
            "mapping_quality": "|".join(sorted(q for q in rec["qualities"] if q)),
            "n_occurrences": rec["n_files"],
            "obsolete": "YES" if oi["obsolete"] else "",
            "why": why,
            "example_file": rec["example_file"],
        })

    order = {"ID_NOT_FOUND": 0, "NO_LEXICAL_SUPPORT": 1, "PARTIAL": 2, "EXACT": 3}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -r["n_occurrences"]))

    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(rows)

    print(f"\n=== {len(rows)} unique assertions ===")
    counts = defaultdict(int); occ = defaultdict(int)
    for r in rows:
        counts[r["verdict"]] += 1; occ[r["verdict"]] += r["n_occurrences"]
    for k in ("ID_NOT_FOUND", "NO_LEXICAL_SUPPORT", "PARTIAL", "EXACT"):
        if counts[k]:
            print(f"  {counts[k]:5d}  {k:20s} ({occ[k]} ingredient occurrences)")

    bad = [r for r in rows if r["verdict"] in ("NO_LEXICAL_SUPPORT", "ID_NOT_FOUND")]
    print("\n=== by mapping_quality among suspect rows ===")
    q = defaultdict(int)
    for r in bad:
        q[r["mapping_quality"] or "(none)"] += 1
    for k, v in sorted(q.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5d}  {k}")
    print(f"\n  of suspect rows, label copied from ingredient name: "
          f"{sum(1 for r in bad if r['label_copied_from_name']=='YES')}/{len(bad)}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
