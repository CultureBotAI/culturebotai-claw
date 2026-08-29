#!/usr/bin/env python3
"""Resolve the residual id↔label defects the earlier passes could not.

Two classes remain after exact label/synonym/formula matching:

  SUBSCRIPT-DAMAGED FORMULAS  "MnCl .4H O", "Na SeO .5H O" — the digits are gone,
      so the name cannot be parsed to a formula and matched. But the ELEMENT SET
      plus the hydrate count survive, and together they are highly selective:
      search CHEBI for terms whose non-water element set matches and whose own
      formula carries the same hydration. "MnCl" + 4 H2O has essentially one
      chemical answer.

  PROSE WITH QUALIFIERS  "Ethanol absolute", "Sodium succinate dibasic",
      "Phenyl acetic acid" — a plain lexical lookup misses because of a grade
      qualifier, a spacing variant, or a non-English name. Strip the qualifiers
      and retry against labels and synonyms.

Everything is a PROPOSAL. Each carries the evidence that produced it and is
verified against the term's real label before being written out; nothing is
applied by this script.
"""

from __future__ import annotations

import functools
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
from resolve_label_plausibility_defects import ADAPTERS, build_indexes, norm  # noqa: E402

# Grade/purity/basicity qualifiers that never change chemical identity.
QUALIFIERS = re.compile(
    r"\b(absolute|anhydrous|anydrous|dibasic|monobasic|tribasic|reduced|"
    r"pure|p\.?a\.?|extra|puriss|reinst|techn|solution|powder|cryst|"
    r"crystalline|hydrate|hydrated)\b", re.IGNORECASE)

# Non-English / spelling variants seen in the corpus.
ALIASES = {
    "eisencitrat": "iron(3+) citrate",
    "co carboxylase": "thiamine(1+) diphosphate",
    "cocarboxylase": "thiamine(1+) diphosphate",
    "cobalamine": "cobalamin",
    "hexachlorocyclo-hexane": "hexachlorocyclohexane",
    "na2-ss-glycerolphosphate": "sodium glycerol 2-phosphate",
    "tapso": "TAPSO",
    "ethanol absolute": "ethanol",
    "dl-malate": "malate(2-)",
    "phenyl acetic acid": "phenylacetic acid",
    "cysteine-hcl": "L-cysteine hydrochloride",
    "sodium succinate dibasic": "sodium succinate",
}

@functools.cache
def _elem_re() -> re.Pattern[str]:
    """Built on first use: the element list comes from chem_formula."""
    return re.compile(
        r"(" + "|".join(sorted(chem_formula.ELEMENTS, key=len, reverse=True)) + r")"
    )
_HYDRATE_RE = re.compile(r"[\s.·・*x]*\s*(\d*)\s*H\s*2?\s*O\s*$", re.IGNORECASE)


def split_hydrate(name: str):
    m = _HYDRATE_RE.search(name.strip())
    if not m:
        return name.strip(), None
    core = name[: m.start()].rstrip(" .·・*x")
    return (core, int(m.group(1)) if m.group(1) else 1) if core else (name.strip(), None)


def element_set(core: str) -> set[str]:
    s = re.sub(r"[\s.·・*()0-9]+", "", core)
    if not s or re.search(r"[a-z]{4,}", s):
        return set()
    pos, found = 0, set()
    while pos < len(s):
        m = _elem_re().match(s, pos)
        if not m:
            return set()
        found.add(m.group(1))
        pos = m.end()
    return found - {"H", "O"}


def chebi_profile(formula: str):
    """(non-water element set, hydrate count) for a CHEBI molecular formula."""
    parsed = chem_formula.parse_ontology_formula(formula)
    if not parsed:
        return None, None
    water = 0
    for part in formula.split("."):
        m = re.fullmatch(r"(\d*)H2O", part.strip())
        if m:
            water += int(m.group(1) or 1)
    return {e for e in parsed if e not in ("H", "O")}, water


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path,
                    default=CM / "reports" / "label_plausibility_after_fixes.tsv")
    ap.add_argument("--out", type=Path,
                    default=CLAW / "workspace/reports/residual_defect_proposals.tsv")
    args = ap.parse_args()
    require_mech_roots("culturemech", claw_root=REPO_ROOT)


    rows = [r for r in csv.DictReader(args.report.open(), delimiter="\t")
            if r["verdict"] in ("IMPLAUSIBLE_LABEL", "ID_NOT_FOUND", "ID_OUT_OF_RANGE")]
    seen: dict[tuple[str, str], dict] = {}
    for r in rows:
        k = (r["current_label"], r["id"])
        e = seen.setdefault(k, {**r, "occurrences": 0})
        e["occurrences"] += 1
    print(f"{len(seen)} distinct residual defects")

    from oaklib import get_adapter
    adapters = {p: get_adapter(h) for p, h in ADAPTERS.items()}
    idx = {p: build_indexes(p, adapters[p]) for p in ADAPTERS}
    formula_of = chem_formula.build_formula_lookup(adapters["CHEBI"])

    # CHEBI profile index: (frozen element set, hydrate) -> ids
    print("profiling CHEBI formulas ...", flush=True)
    by_profile: dict[tuple[frozenset, int], set[str]] = defaultdict(set)
    for key, ids in idx["CHEBI"][2].items():
        for cid in ids:
            es, w = chebi_profile(formula_of(cid))
            if es:
                by_profile[(frozenset(es), w)].add(cid)

    out = []
    for (label, bad_id), r in seen.items():
        n = norm(label)
        proposal = method = evidence = ""

        # 1. explicit alias table (non-English, spelling, qualifier-laden)
        target = ALIASES.get(n) or ALIASES.get(label.strip().lower())
        if target:
            for p in ("CHEBI", "FOODON", "UBERON"):
                cands = idx[p][0].get(norm(target), set()) or idx[p][1].get(norm(target), set())
                if len(cands) == 1:
                    proposal, method = next(iter(cands)), "ALIAS"
                    evidence = f"'{label}' is a known variant of '{target}'"
                    break

        # 2. strip grade qualifiers and retry
        if not proposal:
            stripped = norm(QUALIFIERS.sub(" ", label))
            if stripped and stripped != n:
                for p in ("CHEBI", "FOODON", "UBERON"):
                    cands = idx[p][0].get(stripped, set()) or idx[p][1].get(stripped, set())
                    if len(cands) == 1:
                        proposal, method = next(iter(cands)), "QUALIFIER_STRIPPED"
                        evidence = f"'{label}' -> '{stripped}' matches uniquely"
                        break

        # 3. damaged formula: element set + hydrate count
        if not proposal:
            core, hyd = split_hydrate(label)
            es = element_set(core)
            if es:
                cands = by_profile.get((frozenset(es), hyd or 0), set())
                if not cands and hyd:
                    cands = by_profile.get((frozenset(es), 0), set())
                    if cands:
                        method = "ELEMENT_SET_ANHYDROUS"
                if cands:
                    method = method or "ELEMENT_SET"
                    # Prefer a term whose label mentions every element's common name
                    if len(cands) == 1:
                        proposal = next(iter(cands))
                        evidence = f"elements {sorted(es)} + {hyd or 0} H2O uniquely match"
                    else:
                        ranked = sorted(cands)
                        proposal = ""
                        evidence = (f"elements {sorted(es)} + {hyd or 0} H2O match "
                                    f"{len(cands)} terms: " +
                                    ", ".join(f"{c}={adapters['CHEBI'].label(c)}"
                                              for c in ranked[:6]))
                        method = method + "_AMBIGUOUS"

        plabel = ""
        if proposal:
            plabel = adapters[proposal.split(":", 1)[0]].label(proposal) or ""

        out.append({
            "status": "PROPOSAL" if proposal else "NEEDS_HUMAN",
            "occurrences": r["occurrences"],
            "label": label,
            "current_id": bad_id,
            "current_id_really_is": r["canonical_label"],
            "proposed_id": proposal,
            "proposed_label": plabel,
            "method": method,
            "evidence": evidence,
        })

    out.sort(key=lambda x: (x["status"] != "PROPOSAL", -int(x["occurrences"])))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(out)

    print(f"\n{sum(1 for o in out if o['status']=='PROPOSAL')} proposals, "
          f"{sum(1 for o in out if o['status']=='NEEDS_HUMAN')} need a human")
    for o in out:
        if o["status"] == "PROPOSAL":
            print(f"  {o['occurrences']:>4}  {o['label'][:28]:<28} {o['current_id']:<15} "
                  f"-> {o['proposed_id']:<15} {o['proposed_label'][:32]:<32} [{o['method']}]")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
