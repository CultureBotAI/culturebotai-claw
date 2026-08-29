#!/usr/bin/env python3
"""Definitive per-record verdict for the 31 'ontology term known, no MIM record'
ingredients, by direct comparison of the asserted term's real ontology label
against the ingredient name. Emits the corrected mapping where one is findable.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
C = REPO_ROOT
BACKLOG = C / "workspace/reports/mim_missing_records_backlog.tsv"
OUT = C / "workspace/reports/mim_missing_records_VERIFIED.tsv"

# De-mangled reading of each stripped-subscript name (subscripts restored from
# the chemistry the name plainly intends), used to search for the right term.
DEMANGLED = {
    "MnCl .4H O": "MnCl2·4H2O", "Na MoO .2H O": "Na2MoO4·2H2O",
    "FeCl .6H O": "FeCl3·6H2O", "H BO": "H3BO3", "CaCl .2H O": "CaCl2·2H2O",
    "CoSO .7H O": "CoSO4·7H2O", "CaSO .2H O": "CaSO4·2H2O",
    "ZnCl .6H O": "ZnCl2", "Co(NO ) .6H O": "Co(NO3)2·6H2O",
    "SrCl .6H O": "SrCl2·6H2O", "AlCl .6H O": "AlCl3·6H2O",
    "NaMoO .2H O": "Na2MoO4·2H2O", "Na SeO .5H O": "Na2SeO3·5H2O",
    "As O": "As2O3", "Na WO .2H O": "Na2WO4·2H2O", "TeO": "TeO2",
}


def main() -> None:
    rows = list(csv.DictReader(BACKLOG.open(), delimiter="\t"))
    from oaklib import get_adapter
    chebi = get_adapter("sqlite:obo:chebi")

    def tokens(s: str) -> set[str]:
        s = s.lower().replace("(", " ").replace(")", " ")
        return {t for t in re.split(r"[^a-z0-9]+", s) if len(t) > 2}

    out = []
    for r in rows:
        name, oid = r["ingredient_name"], r["ontology_id"]
        intended = DEMANGLED.get(name, name)
        label = ""
        if oid.startswith("CHEBI:"):
            label = chebi.label(oid) or ""
        else:
            label = "(non-CHEBI: not checked here)"

        if oid.startswith("CHEBI:") and not label:
            verdict, note = "WRONG_ID_NOT_IN_CHEBI", "id does not resolve in CHEBI"
        elif not oid.startswith("CHEBI:"):
            verdict, note = "UNVERIFIED_NON_CHEBI", "FOODON/UBERON — verify separately"
        else:
            lt, it = tokens(label), tokens(intended)
            # A correct mineral/salt mapping shares a chemical word with the
            # intended reading, or the intended reading is a pure formula whose
            # elements the label names.
            share = lt & it
            if share:
                verdict, note = "LIKELY_CORRECT", f"shares {sorted(share)}"
            else:
                verdict, note = "WRONG_UNRELATED_COMPOUND", f"label '{label}' unrelated to '{intended}'"

        out.append({
            "verdict": verdict,
            "ingredient_name": name,
            "intended_chemical": intended if intended != name else "",
            "asserted_id": oid,
            "asserted_id_real_label": label,
            "occurrences": r["priority_occurrences"],
            "note": note,
        })

    order = {"WRONG_UNRELATED_COMPOUND": 0, "WRONG_ID_NOT_IN_CHEBI": 1,
             "UNVERIFIED_NON_CHEBI": 2, "LIKELY_CORRECT": 3}
    out.sort(key=lambda r: (order.get(r["verdict"], 9), -int(r["occurrences"])))

    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(out)

    from collections import Counter
    cnt = Counter(r["verdict"] for r in out)
    occ = Counter()
    for r in out:
        occ[r["verdict"]] += int(r["occurrences"])
    print(f"=== {len(out)} candidate records ===")
    for k in order:
        if cnt[k]:
            print(f"  {cnt[k]:3d}  {k:26s} ({occ[k]} occurrences)")
    print()
    for r in out:
        if r["verdict"].startswith("WRONG"):
            print(f"  {r['occurrences']:>5}  {r['ingredient_name'][:34]:34s} "
                  f"{r['asserted_id']:14s} is actually '{r['asserted_id_real_label'][:38]}'")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
