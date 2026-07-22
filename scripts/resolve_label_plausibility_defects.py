#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Propose a correct ontology term for every id↔label plausibility defect.

Consumes the drift report from
``CultureMech/scripts/validate_id_label_correspondence.py`` and, for each flagged
(label, id) pair, tries to find the term the label actually denotes. Every
proposal carries the evidence that produced it so a curator can accept or reject
without re-deriving it.

Resolution strategies, strongest first:

  LABEL_EXACT     the ingredient name is the canonical label of some term
  SYNONYM_EXACT   the name is an exact synonym of some term
  FORMULA         the name parses as a formula matching exactly one term's
                  molecular formula
  SKELETON        the name is subscript-damaged ("MnCl .4H O"); its letter
                  skeleton matches a name elsewhere in the corpus that the gate
                  ACCEPTED, so the accepted term carries over
  CORPUS_AGREE    the same surface form is grounded elsewhere in the corpus to a
                  term that the gate accepted

Pairs where the asserted term already looks right (the gate over-fired on a
damaged label or a spelling variant) are emitted as EXCEPTION rows for the
validator's ``exceptions:`` allow-list rather than as corrections.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

KGH = Path("/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe")
CM = KGH / "CultureMech"
sys.path.insert(0, str(CM / "scripts"))
import chem_formula  # noqa: E402

ADAPTERS = {
    "CHEBI": "sqlite:obo:chebi",
    "FOODON": "sqlite:obo:foodon",
    "UBERON": "sqlite:obo:uberon",
}


def norm(text: str) -> str:
    s = (text or "").strip().lower()
    s = (s.replace("α", "alpha").replace("β", "beta")
           .replace("γ", "gamma").replace("ß", "beta"))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def letter_skeleton(text: str) -> str:
    """Element letters only — collapses 'MnCl .4H O' and 'MnCl2 x 4 H2O'.

    Drops digits, separators and the hydrate 'x' so a subscript-damaged formula
    and its intact twin land on the same key. Returns '' for prose.
    """
    core = re.sub(r"[\s.·・*]+", "", (text or "").strip())
    core = re.sub(r"\d+", "", core)
    core = re.sub(r"(?<=[a-zA-Z])x(?=[A-Z])", "", core)
    if not core or re.search(r"[a-z]{4,}", core):
        return ""
    return core


def build_indexes(prefix: str, adapter):
    """(normalized label -> ids, normalized synonym -> ids, formula -> ids)."""
    by_label: dict[str, set[str]] = defaultdict(set)
    by_syn: dict[str, set[str]] = defaultdict(set)
    by_formula: dict[str, set[str]] = defaultdict(set)

    from sqlalchemy import text as sqltext

    engine = getattr(adapter, "engine", None)
    if engine is None:
        return by_label, by_syn, by_formula

    with engine.connect() as conn:
        for subj, val in conn.execute(sqltext(
            "SELECT subject, value FROM statements "
            "WHERE predicate='rdfs:label' AND value IS NOT NULL"
        )):
            if subj and subj.startswith(prefix + ":") and val:
                by_label[norm(val)].add(subj)
        for subj, val in conn.execute(sqltext(
            "SELECT subject, value FROM statements "
            "WHERE predicate IN ('oio:hasExactSynonym','oio:hasRelatedSynonym') "
            "AND value IS NOT NULL"
        )):
            if subj and subj.startswith(prefix + ":") and val:
                by_syn[norm(val)].add(subj)
        if prefix == "CHEBI":
            for subj, val in conn.execute(sqltext(
                "SELECT subject, value FROM statements "
                "WHERE predicate='chemrof:generalized_empirical_formula' "
                "AND value IS NOT NULL"
            )):
                if subj and val:
                    parsed = chem_formula.parse_ontology_formula(val)
                    if parsed:
                        key = "".join(f"{k}{v}" for k, v in sorted(parsed.items()))
                        by_formula[key].add(subj)
    return by_label, by_syn, by_formula


def formula_key(counts: dict[str, int] | None) -> str:
    return "".join(f"{k}{v}" for k, v in sorted(counts.items())) if counts else ""


_ELEM_TOKEN_RE = re.compile(
    r"(" + "|".join(sorted(chem_formula.ELEMENTS, key=len, reverse=True)) + r")"
)


def element_set(text: str) -> set[str]:
    """Element symbols named by a (possibly subscript-damaged) formula label.

    Water's H and O are dropped: a hydrate grounded to its anhydrous parent is
    legitimate, so they carry no discriminating signal.
    """
    core = re.sub(r"[\s.·・*x]+", "", (text or "").strip())
    core = re.sub(r"\d+", "", core)
    if not core or re.search(r"[a-z]{4,}", core):
        return set()
    pos, found = 0, set()
    while pos < len(core):
        m = _ELEM_TOKEN_RE.match(core, pos)
        if not m:
            return set()  # unparseable — refuse to judge
        found.add(m.group(1))
        pos = m.end()
    return found - {"H", "O"}


def asserted_still_plausible(label: str, asserted_formula: str) -> bool:
    """True when a damaged label still names the asserted term's own elements.

    'NaH PO .2H O' grounded to sodium dihydrogenphosphate shares the {Na,P}
    skeleton, so the grounding is fine and only the NAME is broken — proposing a
    different phosphate would make it worse, because the lost subscripts are
    exactly what distinguishes NaH2PO4 from Na2HPO4.
    """
    want = element_set(label)
    got = chem_formula.parse_ontology_formula(asserted_formula)
    if not want or not got:
        return False
    return want == {e for e in got if e not in ("H", "O")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path,
                    default=CM / "reports" / "label_plausibility_2026-07-19.tsv")
    ap.add_argument("--adjudicated", type=Path,
                    default=KGH / "culturebotai-claw/workspace/reports/chebi_adjudicated.tsv",
                    help="Corpus-wide (name, CHEBI) adjudication used as the source "
                         "of trustworthy groundings for skeleton transfer.")
    ap.add_argument("--out", type=Path,
                    default=KGH / "culturebotai-claw/workspace/reports/label_defect_resolutions.tsv")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.report.open(), delimiter="\t"))
    flagged = [r for r in rows if r["verdict"] in
               ("IMPLAUSIBLE_LABEL", "ID_NOT_FOUND", "ID_OUT_OF_RANGE",
                "LABEL_SUBSCRIPTS_LOST")]

    # Trustworthy groundings we can transfer onto a damaged twin.
    #
    # These must come from the CORPUS, not from the drift report: the report
    # contains only FAILING pairs, so harvesting "accepted" rows from it yields
    # nothing. `chebi_adjudicated.tsv` carries every (name, CHEBI) assertion in
    # CultureMech together with the formula-based verdict, so the rows it marks
    # good are exactly the intact twins a damaged name should inherit from.
    accepted: dict[str, set[str]] = defaultdict(set)
    accepted_skel: dict[str, set[str]] = defaultdict(set)
    flagged_pairs = {(r["current_label"], r["id"]) for r in flagged}
    good = {"OK", "OK_PARTIAL", "OK_HYDRATE_RELAXED", "NAME_MANGLED_CHEBI_OK"}
    if args.adjudicated.exists():
        for a in csv.DictReader(args.adjudicated.open(), delimiter="\t"):
            if a.get("final") not in good:
                continue
            name, cid = a["preferred_term"], a["chebi_id"]
            if (name, cid) in flagged_pairs:
                continue
            accepted[norm(name)].add(cid)
            if (sk := letter_skeleton(name)):
                accepted_skel[sk].add(cid)
        print(f"accepted groundings: {len(accepted)} names, "
              f"{len(accepted_skel)} formula skeletons")
    else:
        print(f"WARNING: {args.adjudicated} absent — skeleton/corpus transfer disabled",
              file=sys.stderr)

    from oaklib import get_adapter
    chebi_formula_of = chem_formula.build_formula_lookup(get_adapter(ADAPTERS["CHEBI"]))
    idx = {}
    for prefix, handle in ADAPTERS.items():
        print(f"indexing {prefix} ...", flush=True)
        idx[prefix] = build_indexes(prefix, get_adapter(handle))
        print(f"  {len(idx[prefix][0])} labels, {len(idx[prefix][1])} synonyms, "
              f"{len(idx[prefix][2])} formulas", flush=True)

    # Distinct defects only — one proposal per (label, id).
    seen: dict[tuple[str, str], dict] = {}
    for r in flagged:
        key = (r["current_label"], r["id"])
        e = seen.setdefault(key, {**r, "occurrences": 0})
        e["occurrences"] += 1

    out = []
    for (label, bad_id), r in seen.items():
        prefix = bad_id.split(":", 1)[0]
        n = norm(label)
        proposal = method = evidence = ""

        # The gate over-fired: asserted term is already right.
        if r["verdict"] == "LABEL_SUBSCRIPTS_LOST":
            verdict, method = "EXCEPTION_LABEL_DAMAGED", "subscripts lost; grounding correct"
        elif prefix == "CHEBI" and asserted_still_plausible(
            label, chebi_formula_of(bad_id)
        ):
            # Damaged NAME, sound grounding. Never "correct" these — the missing
            # subscripts are what distinguish the candidates from each other.
            verdict = "EXCEPTION_LABEL_DAMAGED"
            method = "damaged name retains the asserted term's element skeleton"
            evidence = f"{bad_id} formula {chebi_formula_of(bad_id)} matches label elements"
        else:
            # 1/2. exact label or synonym in the SAME ontology first, then any.
            search_order = [prefix] + [p for p in ADAPTERS if p != prefix]
            for p in search_order:
                if p not in idx:
                    continue
                by_label, by_syn, _ = idx[p]
                if len(by_label.get(n, ())) == 1:
                    proposal, method = next(iter(by_label[n])), "LABEL_EXACT"
                    evidence = f"'{label}' is the canonical label of {proposal}"
                    break
                if len(by_syn.get(n, ())) == 1:
                    proposal, method = next(iter(by_syn[n])), "SYNONYM_EXACT"
                    evidence = f"'{label}' is an exact synonym of {proposal}"
                    break
            # 3. formula match (CHEBI only)
            if not proposal and chem_formula.looks_like_formula(label):
                key_f = formula_key(chem_formula.parse_formula(label))
                cands = idx["CHEBI"][2].get(key_f, set()) if key_f else set()
                if len(cands) == 1:
                    proposal, method = next(iter(cands)), "FORMULA"
                    evidence = f"parsed formula {key_f} uniquely matches {proposal}"
            # 4. skeleton transfer from an accepted, intact twin
            if not proposal and (sk := letter_skeleton(label)):
                cands = accepted_skel.get(sk, set()) - {bad_id}
                if len(cands) == 1:
                    proposal, method = next(iter(cands)), "SKELETON"
                    evidence = f"letter skeleton '{sk}' matches accepted grounding"
            # 5. same surface form accepted elsewhere in the corpus
            if not proposal:
                cands = accepted.get(n, set()) - {bad_id}
                if len(cands) == 1:
                    proposal, method = next(iter(cands)), "CORPUS_AGREE"
                    evidence = "same name grounded to this term elsewhere, gate-accepted"

            if proposal and proposal == bad_id:
                verdict, method = "EXCEPTION_GATE_OVERFIRED", method
                proposal = ""
            elif proposal:
                verdict = "CORRECTION"
            else:
                verdict = "NEEDS_CURATION"

        # LABEL_EXACT/SYNONYM_EXACT/FORMULA identify the term directly. SKELETON
        # and CORPUS_AGREE infer it from a neighbour, which cannot resolve
        # stoichiometry a damaged name has lost (EDTA-Na2 vs -Na3), so they are
        # proposals for a curator rather than safe auto-applies.
        confidence = {"LABEL_EXACT": "HIGH", "SYNONYM_EXACT": "HIGH",
                      "FORMULA": "HIGH"}.get(method, "MEDIUM" if proposal else "")

        out.append({
            "resolution": verdict,
            "confidence": confidence,
            "occurrences": r["occurrences"],
            "asserted_label": label,
            "asserted_id": bad_id,
            "asserted_id_really_is": r["canonical_label"],
            "proposed_id": proposal,
            "method": method,
            "evidence": evidence,
            "gate_verdict": r["verdict"],
            "surface": r["surface"],
        })

    # Fill proposed labels in one pass.
    adapters = {p: get_adapter(h) for p, h in ADAPTERS.items()}
    for o in out:
        if o["proposed_id"]:
            p = o["proposed_id"].split(":", 1)[0]
            if p in adapters:
                o["proposed_label"] = adapters[p].label(o["proposed_id"]) or ""
        o.setdefault("proposed_label", "")

    # For groundings we have CONFIRMED correct, the remaining defect is the NAME.
    # We deliberately do NOT auto-render a replacement: the repo's product
    # decision is to keep human-facing formula names, and mechanically emitting
    # Hill-notation ("Cl2Co") would both violate that and drop conventional
    # cation-first ordering. Give the curator the term's own label and formula —
    # everything needed to write "CoCl2 x 6 H2O" — and let them write it.
    for o in out:
        o["repair_reference"] = ""
        if o["resolution"] != "EXCEPTION_LABEL_DAMAGED":
            continue
        f = chebi_formula_of(o["asserted_id"])
        o["repair_reference"] = (
            f"{o['asserted_id_really_is']} [{f}]" if f else o["asserted_id_really_is"]
        )

    order = {"CORRECTION": 0, "NEEDS_CURATION": 1,
             "EXCEPTION_GATE_OVERFIRED": 2, "EXCEPTION_LABEL_DAMAGED": 3}
    out.sort(key=lambda r: (order.get(r["resolution"], 9), -int(r["occurrences"])))

    cols = ["resolution", "confidence", "occurrences", "asserted_label", "asserted_id",
            "asserted_id_really_is", "proposed_id", "proposed_label", "method",
            "evidence", "repair_reference", "gate_verdict", "surface"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader(); w.writerows(out)

    counts, occ = defaultdict(int), defaultdict(int)
    for o in out:
        counts[o["resolution"]] += 1
        occ[o["resolution"]] += int(o["occurrences"])
    print(f"\n=== {len(out)} distinct defects ===")
    for k in order:
        if counts[k]:
            print(f"  {counts[k]:4d}  {k:26s} ({occ[k]} occurrences)")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
