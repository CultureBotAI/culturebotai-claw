#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Adjudicate CultureMech ingredient→CHEBI assertions with two hard signals.

1. FORMULA: many ingredient names ARE chemical formulas ("KH2PO4",
   "MnCl2 x 4 H2O"). Comparing the element multiset of the name against the
   CHEBI entry's own molecular formula decides the case outright, with no
   reliance on token overlap.
2. DISAGREEMENT: where one surface form is mapped to several different CHEBIs
   across the corpus, at most one can be right. The formula/lexical winner
   adjudicates the rest.

Only assertions that FAIL a formula comparison, or lose to a formula-confirmed
sibling, are reported as WRONG. Everything else is left as REVIEW/OK so that a
name-vs-label mismatch alone never condemns a correct mapping.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

SP = Path(__file__).parent
AUDIT = SP / "chebi_semantic_audit.tsv"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else SP / "chebi_adjudicated.tsv"

ELEMENTS = (
    "Ac Ag Al Am Ar As At Au B Ba Be Bh Bi Bk Br C Ca Cd Ce Cf Cl Cm Cn Co Cr Cs Cu "
    "Db Ds Dy Er Es Eu F Fe Fl Fm Fr Ga Gd Ge H He Hf Hg Ho Hs I In Ir K Kr La Li Lr "
    "Lu Lv Mc Md Mg Mn Mo Mt N Na Nb Nd Ne Nh Ni No Np O Og Os P Pa Pb Pd Pm Po Pr Pt "
    "Pu Ra Rb Re Rf Rg Rh Rn Ru S Sb Sc Se Sg Si Sm Sn Sr Ta Tb Tc Te Th Ti Tl Tm Ts "
    "U V W Xe Y Yb Zn Zr"
).split()
ELEM_RE = re.compile(r"(" + "|".join(sorted(ELEMENTS, key=len, reverse=True)) + r")(\d*)")


def looks_like_formula(name: str) -> bool:
    """A name is formula-like if it has no lowercase-word runs outside elements."""
    core = re.sub(r"\s*[x·・]\s*\d*\s*H2O\s*$", "", name.strip(), flags=re.I)
    core = core.replace("(", "").replace(")", "").replace("·", "")
    if not core or len(core) > 30:
        return False
    if re.search(r"[a-z]{4,}", core):  # 'water', 'acid', 'glucose' → not a formula
        return False
    return bool(re.match(r"^[A-Z][A-Za-z0-9().·\s]*$", core)) and bool(re.search(r"[A-Z]", core))


def parse_formula(s: str) -> dict[str, int] | None:
    """Element multiset for a formula string; handles (X)n groups and n H2O hydrates."""
    s = s.strip()
    if not s:
        return None
    counts: dict[str, int] = defaultdict(int)

    # split trailing hydrate: "MnCl2 x 4 H2O", "MnCl2·4H2O", "CuSO4 x 5 H2O"
    m = re.search(r"[x·・*]\s*(\d*)\s*H2\s*O\s*$", s, flags=re.I)
    if m:
        n = int(m.group(1) or 1)
        counts["H"] += 2 * n
        counts["O"] += 1 * n
        s = s[: m.start()].strip()
    # leading-dot hydrate form "CaCl2.2H2O"
    m = re.match(r"^(.*?)\.\s*(\d*)\s*H2O$", s, flags=re.I)
    if m:
        n = int(m.group(2) or 1)
        counts["H"] += 2 * n
        counts["O"] += 1 * n
        s = m.group(1).strip()

    # expand parenthesised groups one level: (NH4)2 , (SO4)2
    def expand(mo):
        inner, mult = mo.group(1), int(mo.group(2) or 1)
        parts = []
        for e, n in ELEM_RE.findall(inner):
            parts.append(e + str(int(n or 1) * mult))
        return "".join(parts)

    prev = None
    while prev != s and "(" in s:
        prev = s
        s = re.sub(r"\(([A-Za-z0-9]+)\)(\d*)", expand, s)

    s = s.replace(" ", "")
    if not s:
        return dict(counts) or None
    pos, seen = 0, False
    while pos < len(s):
        mo = ELEM_RE.match(s, pos)
        if not mo:
            return None  # unparseable -> refuse to judge
        counts[mo.group(1)] += int(mo.group(2) or 1)
        pos = mo.end()
        seen = True
    return dict(counts) if seen else None


def norm_chebi_formula(f: str) -> dict[str, int] | None:
    """CHEBI formulas may be dotted adducts: 'C15H16N4.HCl', '2HO.Mg'."""
    if not f or "R" in f or "*" in f:
        return None
    total: dict[str, int] = defaultdict(int)
    for part in f.split("."):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)(.*)$", part)
        mult, body = (int(m.group(1)), m.group(2)) if m else (1, part)
        sub = parse_formula(body)
        if sub is None:
            return None
        for k, v in sub.items():
            total[k] += v * mult
    return dict(total) or None


def main() -> None:
    rows = list(csv.DictReader(AUDIT.open(), delimiter="\t"))

    from oaklib import get_adapter
    ad = get_adapter("sqlite:obo:chebi")

    cids = sorted({r["chebi_id"] for r in rows})
    print(f"fetching formulas for {len(cids)} CHEBI ids ...", flush=True)
    formula: dict[str, str] = {}
    for i, c in enumerate(cids):
        if i and i % 500 == 0:
            print(f"  {i}/{len(cids)}", flush=True)
        f = ""
        try:
            for k, v in (ad.entity_metadata_map(c) or {}).items():
                if "formula" in k.lower():
                    f = v[0] if isinstance(v, list) else v
                    break
        except Exception:
            pass
        formula[c] = f or ""

    # ---- per-assertion formula verdict ----
    # A hydrate mapped to its anhydrous CHEBI parent (NiCl2 x 6 H2O →
    # "nickel dichloride") is a DELIBERATE relaxation, not an error — the
    # kg-microbe loader does this on purpose via fuzzy_hydrate. So compare the
    # non-water skeleton (elements other than H/O) before condemning anything.
    def skeleton(d: dict[str, int]) -> dict[str, int]:
        return {k: v for k, v in d.items() if k not in ("H", "O")}

    for r in rows:
        name, cid = r["preferred_term"], r["chebi_id"]
        r["chebi_formula"] = formula.get(cid, "")
        r["formula_verdict"] = ""
        if looks_like_formula(name):
            want = parse_formula(name)
            got = norm_chebi_formula(r["chebi_formula"])
            if want and got:
                if want == got:
                    r["formula_verdict"] = "FORMULA_MATCH"
                elif skeleton(want) and skeleton(want) == skeleton(got):
                    # same non-water skeleton → hydration/protonation difference only
                    r["formula_verdict"] = "FORMULA_HYDRATE_RELAXED"
                elif set(skeleton(want)) and set(skeleton(want)) == set(skeleton(got)):
                    # Same ELEMENTS, wrong counts. Overwhelmingly this is the
                    # upstream subscript-stripping defect ("NaCO3" for Na2CO3,
                    # "ZnCl" for ZnCl2) — the CHEBI is right, the NAME is broken.
                    r["formula_verdict"] = "NAME_MANGLED_CHEBI_OK"
                else:
                    r["formula_verdict"] = "FORMULA_CONFLICT"
            elif want and not got:
                r["formula_verdict"] = "NO_CHEBI_FORMULA"

    # ---- group by surface form to find disagreement ----
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_name[r["preferred_term"].strip().lower()].append(r)

    def strength(r: dict) -> int:
        if r["formula_verdict"] in ("FORMULA_MATCH", "FORMULA_HYDRATE_RELAXED",
                                   "NAME_MANGLED_CHEBI_OK"):
            return 4
        if r["verdict"] == "EXACT":
            return 3
        if r["verdict"] == "PARTIAL":
            return 2
        if r["formula_verdict"] == "FORMULA_CONFLICT" or r["verdict"] == "ID_NOT_FOUND":
            return 0
        return 1

    for r in rows:
        r["final"] = ""
        r["correct_id"] = ""
        r["correct_label"] = ""

    for name, group in by_name.items():
        best = max(group, key=strength)
        bs = strength(best)
        for r in group:
            s = strength(r)
            if r["formula_verdict"] == "FORMULA_CONFLICT":
                r["final"] = "WRONG_FORMULA_CONFLICT"
            elif r["verdict"] == "ID_NOT_FOUND":
                r["final"] = "WRONG_ID_NOT_FOUND"
            elif len(group) > 1 and s < bs and bs >= 3:
                r["final"] = "WRONG_LOSES_TO_SIBLING"
            elif r["formula_verdict"] == "FORMULA_MATCH" or r["verdict"] == "EXACT":
                r["final"] = "OK"
            elif r["formula_verdict"] == "FORMULA_HYDRATE_RELAXED":
                r["final"] = "OK_HYDRATE_RELAXED"
            elif r["formula_verdict"] == "NAME_MANGLED_CHEBI_OK":
                r["final"] = "NAME_MANGLED_CHEBI_OK"
            elif r["verdict"] == "PARTIAL":
                r["final"] = "OK_PARTIAL"
            else:
                r["final"] = "REVIEW"
            if r["final"].startswith("WRONG") and bs >= 3 and best is not r:
                r["correct_id"] = best["chebi_id"]
                r["correct_label"] = best["oak_label"]

    cols = ["final", "preferred_term", "chebi_id", "oak_label", "chebi_formula",
            "formula_verdict", "correct_id", "correct_label", "n_occurrences",
            "mapping_quality", "label_copied_from_name", "verdict", "example_file"]
    order = {"WRONG_FORMULA_CONFLICT": 0, "WRONG_ID_NOT_FOUND": 1,
             "WRONG_LOSES_TO_SIBLING": 2, "REVIEW": 3, "OK_PARTIAL": 4,
             "NAME_MANGLED_CHEBI_OK": 4.5, "OK_HYDRATE_RELAXED": 5, "OK": 6}
    rows.sort(key=lambda r: (order.get(r["final"], 9), -int(r["n_occurrences"])))

    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    print(f"\n=== {len(rows)} assertions adjudicated ===")
    cnt, occ = defaultdict(int), defaultdict(int)
    for r in rows:
        cnt[r["final"]] += 1; occ[r["final"]] += int(r["n_occurrences"])
    for k in ("WRONG_FORMULA_CONFLICT", "WRONG_ID_NOT_FOUND", "WRONG_LOSES_TO_SIBLING",
              "REVIEW", "OK_PARTIAL", "NAME_MANGLED_CHEBI_OK",
              "OK_HYDRATE_RELAXED", "OK"):
        if cnt[k]:
            print(f"  {cnt[k]:5d}  {k:24s} ({occ[k]:6d} occurrences)")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
