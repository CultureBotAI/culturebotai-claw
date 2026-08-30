#!/usr/bin/env python3
"""Apply verified grounding corrections and name repairs to CultureMech YAMLs.

Two independent edit kinds, each gated on its own confidence:

  CORRECTION   ``term.id`` points at the wrong ontology term -> replace the id.
               The ``label`` is NOT touched: it carries the curator-intended
               recipe name, which is the whole reason the label waiver exists.

  NAME_REPAIR  the grounding is right but the name lost its subscripts ->
               rewrite ``preferred_term`` and the sibling ``term.label``.

Edits are matched on the exact (preferred_term, term.id) pair, so an ingredient
that happens to share a name but carries a different grounding is left alone.

Dry-run by default; ``--apply`` writes. Text-level edits preserve formatting,
comments and key order — a YAML round-trip would reflow 26,000 files.
"""

from __future__ import annotations

import os
import argparse
import csv
import re
import sys
from collections import Counter
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


def load_edits(resolutions: Path, repairs: Path, min_conf: str):
    """-> (corrections, renames) keyed by (preferred_term, term_id)."""
    corrections: dict[tuple[str, str], dict] = {}
    for r in csv.DictReader(resolutions.open(), delimiter="\t"):
        if r["resolution"] != "CORRECTION" or not r["proposed_id"]:
            continue
        if min_conf == "HIGH" and r["confidence"] != "HIGH":
            continue
        corrections[(r["asserted_label"], r["asserted_id"])] = {
            "new_id": r["proposed_id"], "new_label_hint": r["proposed_label"],
            "confidence": r["confidence"], "method": r["method"],
        }

    renames: dict[tuple[str, str], dict] = {}
    if repairs.exists():
        for r in csv.DictReader(repairs.open(), delimiter="\t"):
            if not r["repaired_name"] or r["confidence"] == "NONE":
                continue
            if min_conf == "HIGH" and r["confidence"] != "HIGH":
                continue
            renames[(r["damaged_name"], r["ontology_id"])] = {
                "new_name": r["repaired_name"], "confidence": r["confidence"],
            }
    return corrections, renames


def edit_file(path: Path, corrections, renames, apply: bool):
    """Return (n_id_edits, n_name_edits, notes)."""
    try:
        original = path.read_text()
    except Exception:
        return 0, 0, []
    loader = safe_loader()
    try:
        doc = yaml.load(original, Loader=loader)
    except Exception:
        return 0, 0, []
    if not isinstance(doc, dict):
        return 0, 0, []

    # Defects are keyed by the (id, label) pair the VALIDATOR walks, so the
    # applier has to walk the same way. Two things follow:
    #   * the label is the one inside the term block, not the ingredient's
    #     preferred_term ("preferred_term: Tryptone" over "label: tryptone");
    #   * groundings are not only under `ingredients[].term` — normalized_yaml
    #     carries them under `composition[].chebi_term` too. Walking just
    #     `ingredients` silently skipped an entire surface.
    targets: list[tuple[tuple[str, str], str]] = []

    def walk(node, parent_preferred: str = ""):
        if isinstance(node, dict):
            cid = node.get("id")
            lab = node.get("label")
            if isinstance(cid, str) and isinstance(lab, str):
                key = (lab.strip(), cid.strip())
                if key in corrections or key in renames:
                    targets.append((key, parent_preferred))
            preferred = (node.get("preferred_term") or "").strip() or parent_preferred
            for v in node.values():
                walk(v, preferred)
        elif isinstance(node, list):
            for v in node:
                walk(v, parent_preferred)

    walk(doc)
    if not targets:
        return 0, 0, []
    # De-duplicate: the same (label, id) may occur many times in one file; the
    # regex substitutions below are global, so process each key once.
    seen_keys = set()
    deduped = []
    for key, pref in targets:
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append((key, pref))
    targets = deduped

    text = original
    n_id = n_name = 0
    notes = []
    for (term_label, cid), preferred in targets:
        key = (term_label, cid)
        if key in corrections:
            new_id = corrections[key]["new_id"]
            # Anchor on the id and its sibling label so only this grounding is
            # touched, whichever order the two keys appear in.
            pats = [
                re.compile(r"(id:\s*)" + re.escape(cid) +
                           r"(\s*\n[ \t]+label:\s*" + re.escape(term_label) + r"\s*(?:\n|$))"),
                re.compile(r"(label:\s*" + re.escape(term_label) +
                           r"\s*\n[ \t]+id:\s*)" + re.escape(cid) + r"\b"),
            ]
            k = 0
            for i, pat in enumerate(pats):
                if i == 0:
                    text, ki = pat.subn(lambda m: m.group(1) + new_id + m.group(2), text)
                else:
                    text, ki = pat.subn(lambda m: m.group(1) + new_id, text)
                k += ki
            n_id += k
            if k:
                notes.append(f"id  {term_label!r}: {cid} -> {new_id} (x{k})")
        if key in renames:
            new_name = renames[key]["new_name"]
            pat = re.compile(r"([ \t]+label:\s*)" + re.escape(term_label) + r"(?=\s*\n)")
            text, k1 = pat.subn(lambda m: m.group(1) + new_name, text)
            k2 = 0
            if preferred and preferred.lower() == term_label.lower():
                pat2 = re.compile(r"(preferred_term:\s*)" + re.escape(preferred) + r"(?=\s*\n)")
                text, k2 = pat2.subn(lambda m: m.group(1) + new_name, text)
            n_name += k1
            if k1:
                notes.append(f"name {term_label!r} -> {new_name!r} (preferred_term: {k2})")

    if (n_id or n_name) and apply and text != original:
        # Never write something that no longer parses.
        try:
            yaml.load(text, Loader=loader)
        except Exception as exc:
            return 0, 0, [f"REFUSED {path.name}: edit broke YAML ({exc})"]
        path.write_text(text)
    return n_id, n_name, notes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resolutions", type=Path,
                    default=CLAW / "workspace/reports/label_defect_resolutions.tsv")
    ap.add_argument("--repairs", type=Path,
                    default=CLAW / "workspace/reports/name_repairs.tsv")
    ap.add_argument("--confidence", choices=["HIGH", "ALL"], default="HIGH")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()
    require_mech_roots("culturemech", claw_root=REPO_ROOT)


    corrections, renames = load_edits(args.resolutions, args.repairs, args.confidence)
    print(f"{len(corrections)} id corrections, {len(renames)} name repairs "
          f"(confidence={args.confidence})")

    files = sorted(CM.glob("data/merge_yaml/**/*.yaml")) + \
        sorted(CM.glob("data/normalized_yaml/**/*.yaml"))
    print(f"scanning {len(files)} files ...{'' if args.apply else '  [DRY RUN]'}", flush=True)

    tot_id = tot_name = touched = 0
    per_edit = Counter()
    problems = []
    for i, p in enumerate(files):
        if i and i % 8000 == 0:
            print(f"  {i}/{len(files)}", flush=True)
        n_id, n_name, notes = edit_file(p, corrections, renames, args.apply)
        if n_id or n_name:
            touched += 1
            tot_id += n_id
            tot_name += n_name
            for note in notes:
                per_edit[note.split(":")[0]] += 1
        problems += [n for n in notes if n.startswith("REFUSED")]

    print(f"\nfiles touched : {touched}")
    print(f"id corrections: {tot_id}")
    print(f"name repairs  : {tot_name}")
    if problems:
        print(f"\n{len(problems)} REFUSED:")
        for p_ in problems[:10]:
            print("  " + p_)
    if not args.apply:
        print("\n(dry run — rerun with --apply to write)")


if __name__ == "__main__":
    main()
