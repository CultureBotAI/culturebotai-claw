#!/usr/bin/env python3
"""Resolve the live MediaDive unmapped backlog against CHEBI / FOODON / UBERON.

Runs the 202 still-unmapped ``mediadive.ingredient:*`` nodes from the current
kg-microbe merge through exact label / synonym / formula matching, using the
same indexes as ``resolve_label_plausibility_defects.py``.

Deliberately conservative: only exact matches are proposed. Fuzzy matching is
what produced the hallucinated groundings this whole exercise exists to clean
up, so anything that does not match exactly is left for a curator with its
triage bucket attached rather than being guessed at.
"""

from __future__ import annotations

import os
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
CM = Path(
    os.environ.get("CULTUREMECH_ROOT", REPO_ROOT.parent / "CultureMech")
)
KGM_ROOT_PATH = Path(
    os.environ.get("KGMICROBE_ROOT", REPO_ROOT.parent / "kg-microbe")
)
CLAW = REPO_ROOT
sys.path.insert(0, str(CLAW / "scripts"))

from _lazy_import import LazyModule  # noqa: E402

# Imported on first use, not at import time, so --help works without a
# CultureMech checkout (#205).
chem_formula = LazyModule(
    "chem_formula",
    lambda: (CM / "scripts", REPO_ROOT / "scripts"),
    hint="Set CULTUREMECH_ROOT to a checkout that has scripts/chem_formula.py.",
)
from resolve_label_plausibility_defects import (  # noqa: E402
    ADAPTERS, build_indexes, formula_key, norm,
)


def bucket(name: str) -> str:
    low = name.lower()
    if re.search(r"\b(broth|agar|medium|media|base|infusion|bouillon)\b", low) or \
       re.search(r"cm\s?0?\d{3,4}", low):
        return "COMMERCIAL_MEDIUM"
    if re.search(r"x\s*n?\s*\d*\s*h2o|·|\d\s*h\s*o$", low) or \
       (re.match(r"^[A-Z][a-z]?[A-Z0-9(]", name) and re.search(r"\d", name)):
        return "FORMULA_NOTATION"
    if re.search(r"\b(extract|peptone|tryptone|digest|hydrolysate|meal|flour|powder|"
                 r"serum|blood|bile|milk|yeast|liver|brain|heart|manure|soil|leaves|"
                 r"potato|juice|paste|rumen)\b", low):
        return "COMPLEX_BIOLOGICAL"
    if re.search(r"\b(solution|buffer|supplement|concentrate|mix|mixture|source|"
                 r"elements|minerals|vitamins|salts)\b", low):
        return "MIXTURE_UNDERSPECIFIED"
    return "OTHER"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nodes", type=Path,
                    default=KGM_ROOT_PATH / "data/transformed/mediadive/nodes.tsv")
    ap.add_argument("--out", type=Path,
                    default=CLAW / "workspace/reports/mediadive_backlog_resolutions.tsv")
    args = ap.parse_args()
    require_mech_roots("culturemech", claw_root=REPO_ROOT)


    live: list[tuple[str, str]] = []
    with args.nodes.open(newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if (r.get("id") or "").startswith("mediadive.ingredient:"):
                live.append((r["id"], (r.get("name") or "").strip()))
    print(f"live unmapped MediaDive nodes: {len(live)}")

    from oaklib import get_adapter
    adapters = {p: get_adapter(h) for p, h in ADAPTERS.items()}
    idx = {}
    for prefix in ADAPTERS:
        print(f"indexing {prefix} ...", flush=True)
        idx[prefix] = build_indexes(prefix, adapters[prefix])

    out = []
    for node_id, name in live:
        n = norm(name)
        proposal = method = ""
        # Chemicals first, then food, then anatomy — matches how these
        # ingredients are actually typed.
        for prefix in ("CHEBI", "FOODON", "UBERON"):
            by_label, by_syn, _ = idx[prefix]
            if len(by_label.get(n, ())) == 1:
                proposal, method = next(iter(by_label[n])), "LABEL_EXACT"
                break
            if len(by_syn.get(n, ())) == 1:
                proposal, method = next(iter(by_syn[n])), "SYNONYM_EXACT"
                break
        if not proposal and chem_formula.looks_like_formula(name):
            key = formula_key(chem_formula.parse_formula(name))
            cands = idx["CHEBI"][2].get(key, set()) if key else set()
            if len(cands) == 1:
                proposal, method = next(iter(cands)), "FORMULA"

        label = ""
        if proposal:
            label = adapters[proposal.split(":", 1)[0]].label(proposal) or ""

        out.append({
            "status": "RESOLVED" if proposal else "NEEDS_CURATION",
            "node_id": node_id,
            "name": name,
            "proposed_id": proposal,
            "proposed_label": label,
            "method": method,
            "bucket": bucket(name) if not proposal else "",
        })

    out.sort(key=lambda r: (r["status"] != "RESOLVED", r["bucket"], r["name"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(out)

    res = [r for r in out if r["status"] == "RESOLVED"]
    print(f"\n=== {len(out)} nodes: {len(res)} resolved, {len(out) - len(res)} need curation ===")
    for k, v in Counter(r["method"] for r in res).most_common():
        print(f"  {v:4d}  {k}")
    print("\n  remaining by bucket:")
    for k, v in Counter(r["bucket"] for r in out if not r["proposed_id"]).most_common():
        print(f"  {v:4d}  {k}")
    print("\n  sample resolutions:")
    for r in res[:15]:
        print(f"    {r['name'][:38]:38s} -> {r['proposed_id']:16s} {r['proposed_label'][:34]}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
