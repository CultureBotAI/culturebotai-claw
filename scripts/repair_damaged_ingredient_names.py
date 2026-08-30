#!/usr/bin/env python3
"""Repair subscript-damaged ingredient names from their intact corpus twins.

CultureMech's scraped recipes lost subscript glyphs on some ingredient names
("CoCl .6H O" for CoCl2·6H2O). The grounding is usually still correct — only the
display name is broken.

The repair is NOT synthesised from the ontology's molecular formula. Rendering
"Cl2Co" from CHEBI's Hill-notation formula would be chemically right and
editorially wrong: this repo deliberately keeps human-facing recipe names, whose
house style is "CoCl2 x 6 H2O" (1,841 occurrences) — cation first, hydrate
spelled out. So the repair is *learned from the corpus itself*: find the intact
name that shares the damaged name's element skeleton AND hydrate count AND
ontology grounding, and adopt it verbatim.

That makes every repair an existing, curator-written string rather than a
generated one, and it carries its own evidence: how many times the corpus
already spells it that way.
"""

from __future__ import annotations

import os
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from kg_microbe_corpus.loader import safe_loader


REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
CM = Path(
    os.environ.get("CULTUREMECH_ROOT", REPO_ROOT.parent / "CultureMech")
)
CLAW = REPO_ROOT

# Hydrate tail in either the damaged ("... .6H O") or intact ("... x 6 H2O",
# "·6H2O", "26H2O") spelling. Anchored so it cannot match inside a formula body
# the way a bare "H2O" substring test does — that bug turned H2O4P into a
# spurious monohydrate.
_HYDRATE_RE = re.compile(
    r"[\s.·・*x]*\s*(\d*)\s*H\s*2?\s*O\s*$", re.IGNORECASE
)


def split_hydrate(name: str) -> tuple[str, int | None]:
    """('CoCl .6H O') -> ('CoCl', 6); ('ZnCl') -> ('ZnCl', None)."""
    s = name.strip()
    m = _HYDRATE_RE.search(s)
    if not m:
        return s, None
    core = s[: m.start()].rstrip(" .·・*x")
    if not core:
        return s, None
    count = int(m.group(1)) if m.group(1) else 1
    return core, count


def skeleton(core: str) -> str:
    """Element letters of the anhydrous core, digits and separators removed."""
    s = re.sub(r"[\s.·・*]+", "", core)
    s = re.sub(r"\d+", "", s)
    s = s.replace("(", "").replace(")", "")
    if not s or re.search(r"[a-z]{4,}", s):
        return ""
    return s


def harvest_corpus() -> dict[tuple[str, int | None, str], Counter]:
    """(skeleton, hydrate_n, ontology_id) -> Counter of spellings seen."""
    index: dict[tuple[str, int | None, str], Counter] = defaultdict(Counter)
    files = sorted(CM.glob("data/merge_yaml/**/*.yaml")) + \
        sorted(CM.glob("data/normalized_yaml/**/*.yaml"))
    print(f"harvesting spellings from {len(files)} CultureMech YAMLs ...", flush=True)
    loader = safe_loader()
    for i, p in enumerate(files):
        if i and i % 8000 == 0:
            print(f"  {i}/{len(files)}", flush=True)
        try:
            doc = yaml.load(p.read_text(), Loader=loader)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for ing in doc.get("ingredients") or []:
            if not isinstance(ing, dict):
                continue
            name = (ing.get("preferred_term") or "").strip()
            term = ing.get("term")
            if not name or not isinstance(term, dict):
                continue
            cid = (term.get("id") or "").strip()
            if not cid:
                continue
            core, n = split_hydrate(name)
            sk = skeleton(core)
            if sk:
                index[(sk, n, cid)][name] += 1
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resolutions", type=Path,
                    default=CLAW / "workspace/reports/label_defect_resolutions.tsv")
    ap.add_argument("--out", type=Path,
                    default=CLAW / "workspace/reports/name_repairs.tsv")
    args = ap.parse_args()
    require_mech_roots("culturemech", claw_root=REPO_ROOT)


    rows = [r for r in csv.DictReader(args.resolutions.open(), delimiter="\t")
            if r["resolution"] == "EXCEPTION_LABEL_DAMAGED"]
    index = harvest_corpus()

    sys.path.insert(0, str(CM / "scripts"))
    import chem_formula  # noqa: E402
    from oaklib import get_adapter
    formula_of = chem_formula.build_formula_lookup(get_adapter("sqlite:obo:chebi"))
    print(f"indexed {len(index)} (skeleton, hydrate, id) groups")

    out = []
    for r in rows:
        damaged, cid = r["asserted_label"], r["asserted_id"]
        core, n = split_hydrate(damaged)
        sk = skeleton(core)
        cands = Counter(index.get((sk, n, cid), Counter()))
        cands.pop(damaged, None)
        # Any spelling still carrying the damage is not a repair.
        for spelling in list(cands):
            if re.search(r"[A-Za-z]\s+[A-Z]|\s\.", spelling) and not re.search(r"\d", spelling):
                cands.pop(spelling, None)

        # Widen beyond the exact id to pick up the corpus's DOMINANT spelling
        # rather than a rare same-id variant ("MgSO4 x 7 H2O" beats "MgSO4·7H2O").
        #
        # But widen only across ids that are the SAME COMPOUND by molecular
        # formula. A shared skeleton is not enough: NaH2PO4 and Na2HPO4 both
        # reduce to "NaHPO", so widening on skeleton alone would relabel
        # monosodium phosphate as the disodium salt — the very confusion the
        # lost subscripts caused in the first place.
        equivalent = {cid}
        base = formula_of(cid)
        if base:
            base_parsed = chem_formula.parse_ontology_formula(base)
            for (_sk2, _n2, other) in index:
                if other in equivalent or not other.startswith("CHEBI:"):
                    continue
                other_f = formula_of(other)
                if other_f and base_parsed and \
                        chem_formula.parse_ontology_formula(other_f) == base_parsed:
                    equivalent.add(other)

        wide = Counter()
        for (sk2, n2, cid2), spellings in index.items():
            if (sk2, n2) == (sk, n) and cid2 in equivalent:
                wide.update(spellings)
        wide.pop(damaged, None)
        for spelling in list(wide):
            if re.search(r"[A-Za-z]\s+[A-Z]|\s\.", spelling) and not re.search(r"\d", spelling):
                wide.pop(spelling, None)
        cands = wide or cands

        repair = support = ""
        confidence = "NONE"
        method = ""
        if cands:
            repair, support = cands.most_common(1)[0]
            total = sum(cands.values())
            confidence = "HIGH" if support / total >= 0.6 else "MEDIUM"
            method = "corpus twin (same skeleton + hydrate)"
        elif n is not None:
            # No twin at this hydration. Borrow the anhydrous body spelling and
            # re-attach the hydrate in the corpus's dominant join style, so the
            # result is still house style rather than invented notation.
            anhydrous = Counter()
            for (sk2, n2, _cid), spellings in index.items():
                if sk2 == sk and n2 is None:
                    anhydrous.update(spellings)
            joins = Counter()
            for (sk2, n2, _cid), spellings in index.items():
                if n2 is not None:
                    for sp, ct in spellings.items():
                        if re.search(r"\sx\s\d+\sH2O$", sp):
                            joins["x_spaced"] += ct
                        elif re.search(r"·\d*H2O$", sp):
                            joins["dot"] += ct
            if anhydrous:
                body, support = anhydrous.most_common(1)[0]
                style = joins.most_common(1)[0][0] if joins else "x_spaced"
                repair = f"{body} x {n} H2O" if style == "x_spaced" else f"{body}·{n}H2O"
                confidence = "MEDIUM"
                method = f"composed: corpus body '{body}' + hydrate in dominant style"
        out.append({
            "confidence": confidence,
            "occurrences": r["occurrences"],
            "damaged_name": damaged,
            "repaired_name": repair,
            "ontology_id": cid,
            "ontology_label": r["asserted_id_really_is"],
            "method": method,
            "corpus_support": support,
            "alternatives": " | ".join(f"{k}({v})" for k, v in cands.most_common()[1:4]),
            "skeleton": sk,
            "hydrate": "" if n is None else n,
        })

    order = {"HIGH": 0, "MEDIUM": 1, "NONE": 2}
    out.sort(key=lambda r: (order[r["confidence"]], -int(r["occurrences"])))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(out)

    print(f"\n=== {len(out)} damaged names ===")
    for k, v in Counter(r["confidence"] for r in out).most_common():
        print(f"  {v:3d}  {k}")
    print()
    for r in out:
        arrow = r["repaired_name"] or "(no corpus twin — needs manual repair)"
        print(f"  [{r['confidence']:6s}] {r['damaged_name']:<26} -> {arrow:<20} "
              f"{r['ontology_id']:<15} support={r['corpus_support']}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
