#!/usr/bin/env python3
"""
Bidirectional MIM ↔ kg-microbe ingredient mapping audit.

Joins the canonical MIM SSSOM (MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv)
against kg-microbe's unified chemical dictionary
(kg-microbe/mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz) and classifies every
(label, CHEBI) assertion into one of four reconciliation buckets:

    AGREE      both sides map the surface form to the same CHEBI
    DISAGREE   both sides know the surface form but map to different CHEBIs
    MIM_ONLY   MIM has a mapping; kg-microbe does not recognize the surface form
    KGM_ONLY   kg-microbe xrefs a MIM ingredient ID that MIM's SSSOM no longer publishes

Per-row flags are layered on top of the bucket:

    DEPRECATED_CHEBI   the CHEBI is marked obsolete in OAK
    LABEL_DRIFT        the side's object_label is not OAK's label or a known alias
    DUPLICATE          multiple MIM rows share the same CHEBI
    PREFIX_IRREGULAR   object_id does not start with an expected ontology prefix

Outputs:
  workspace/reports/kgm_mim_audit.tsv   — one row per reconciliation unit
  workspace/reports/kgm_mim_audit.md    — human-readable summary
  workspace/reports/kgm_pr_candidates.tsv — actionable subset, one row per
                                            suggested kg-microbe PR
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from kgm_unified_mappings import (
    KGM_UNIFIED_SSSOM,
    load_kgm_compound_placeholders,
    load_kgm_entity_index,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

# ---------- paths ----------

REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)
KGM_ROOT_PATH = Path(os.environ.get("KGMICROBE_ROOT", REPO_ROOT.parent / "kg-microbe"))

MIM_SSSOM = MIM_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"
KGM_DICT = KGM_UNIFIED_SSSOM
KGM_MEDIADIVE_UNMAPPED = (
    KGM_ROOT_PATH / "mappings" / "mediadive_unmapped_ingredients_to_curate.tsv"
)
REPORT_DIR = REPO_ROOT / "workspace" / "reports"
AUDIT_TSV = REPORT_DIR / "kgm_mim_audit.tsv"
AUDIT_MD = REPORT_DIR / "kgm_mim_audit.md"
PR_TSV = REPORT_DIR / "kgm_pr_candidates.tsv"
CURATION_QUEUE_TSV = REPORT_DIR / "mim_curation_queue.tsv"

EXPECTED_PREFIXES = ("CHEBI:", "FOODON:", "UBERON:", "ENVO:")
CURIE_RE = re.compile(r"^[A-Z][A-Za-z0-9_.]*:[A-Za-z0-9_\-]+$")
POLLUTION_THRESHOLD = 500  # mirrors KgMicrobeDict


# ---------- loaders ----------

def load_mim_sssom(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as f:
        header: list[str] | None = None
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if header is None:
                header = parts
                continue
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts)))
    return rows


def load_kgm_dict(path: Path) -> dict[str, dict]:
    """Return CHEBI -> {canonical_name, formula, synonyms:set, xrefs:set, sources:str}."""
    if not path.exists():
        raise SystemExit(
            f"kg-microbe unified mapping not found: {path}\n"
            "Regenerate it in kg-microbe with:\n"
            "  poetry run python scripts/consolidate_chemical_mappings.py"
        )
    return load_kgm_entity_index(path)


def build_kgm_synonym_index(kgm: dict[str, dict]) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = defaultdict(set)
    for cid, e in kgm.items():
        if e.get("_polluted"):
            if e["canonical_name"]:
                idx[e["canonical_name"].lower()].add(cid)
            continue
        terms = set(e["synonyms"])
        if e["canonical_name"]:
            terms.add(e["canonical_name"])
        for t in terms:
            idx[t.lower()].add(cid)
    return idx


def load_mediadive_unmapped(path: Path) -> list[dict]:
    """Load MediaDive-unmapped ingredients, with occurrence counts."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open() as f:
        header = f.readline().rstrip("\n").split("\t")
        col = {name: i for i, name in enumerate(header)}
        for raw in f:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            try:
                occ = int(parts[col["occurrences"]]) if parts[col["occurrences"]] else 0
            except ValueError:
                occ = 0
            rows.append({
                "source_id": parts[col["id"]].strip(),
                "preferred_term": parts[col["preferred_term"]].strip(),
                "occurrences": occ,
                "sources": "mediadive_unmapped",
                "origin": "mediadive.ingredient",
            })
    return rows


def build_kgm_mim_xref_index(kgm: dict[str, dict]) -> dict[str, set[str]]:
    """MIM:<subject_id> -> set of kg-microbe CHEBI IDs that reference it."""
    idx: dict[str, set[str]] = defaultdict(set)
    for cid, e in kgm.items():
        for x in e["xrefs"]:
            if x.startswith("MIM:") or x.startswith("MediaIngredientMech:"):
                idx[x].add(cid)
    return idx


# ---------- OAK lookup ----------

def build_oak_index(chebi_ids: set[str]) -> dict[str, dict]:
    """Return CHEBI -> {label, obsolete, aliases (lower set)}."""
    from oaklib import get_adapter
    adapter = get_adapter("sqlite:obo:chebi")
    obsoletes = set(adapter.obsoletes())
    out: dict[str, dict] = {}
    for cid in chebi_ids:
        label = adapter.label(cid)
        aliases = {a.lower() for a in adapter.entity_aliases(cid) if a}
        if label:
            aliases.add(label.lower())
        out[cid] = {
            "label": label,
            "obsolete": cid in obsoletes,
            "aliases": aliases,
        }
    return out


# ---------- reconciliation ----------

BUCKETS = ("AGREE", "DISAGREE", "MIM_ONLY", "KGM_ONLY", "UNMAPPED_PENDING_CURATION")


def reconcile(
    mim_rows: list[dict],
    kgm: dict[str, dict],
    kgm_syn: dict[str, set[str]],
    kgm_mim_xref: dict[str, set[str]],
    oak: dict[str, dict],
    unmapped_rows: list[dict] | None = None,
    mim_label_set: set[str] | None = None,
) -> list[dict]:
    out: list[dict] = []

    # Pre-compute MIM duplicates by CHEBI (across all rows, CHEBI and FOODON).
    mim_chebi_counts: dict[str, int] = defaultdict(int)
    for r in mim_rows:
        mim_chebi_counts[r["object_id"]] += 1

    covered_mim_ids: set[str] = set()

    # Pass 1: MIM-driven
    for r in mim_rows:
        mim_id = r["subject_id"]
        mim_label = r["subject_label"]
        obj_id = r["object_id"]
        obj_label = r["object_label"]
        covered_mim_ids.add(mim_id)

        # Only classify CHEBI rows against kg-microbe (kg-microbe is CHEBI-scoped).
        if not obj_id.startswith("CHEBI:"):
            bucket = "MIM_ONLY"
            kgm_chebi = ""
            kgm_label = ""
            note = "non-CHEBI mapping (kg-microbe dict is CHEBI-only)"
        else:
            kgm_by_label = kgm_syn.get(mim_label.lower(), set())
            kgm_entry = kgm.get(obj_id)

            # P2.5-style semantics: a surface-form → CHEBI mapping is a
            # DISAGREE whenever kg-microbe's synonym index returns ANY CHEBI
            # other than MIM's pick (even if MIM's is also in the set — that
            # still means kg-microbe has a competing candidate for this form).
            if kgm_by_label:
                others = kgm_by_label - {obj_id}
                if not others:
                    # kg-microbe agrees exactly: {obj_id} == kgm_by_label
                    bucket = "AGREE"
                    kgm_chebi = obj_id
                    note = "label resolves to same CHEBI in kg-microbe"
                elif obj_id in kgm_by_label:
                    bucket = "DISAGREE"
                    kgm_chebi = sorted(others)[0]
                    kgm_label_hint = kgm.get(kgm_chebi, {}).get("canonical_name", "")
                    note = (
                        f"kg-microbe has both {obj_id} AND {kgm_chebi} "
                        f"({kgm_label_hint}) for '{mim_label}'"
                    )
                else:
                    bucket = "DISAGREE"
                    kgm_chebi = sorted(others)[0]
                    kgm_label_hint = kgm.get(kgm_chebi, {}).get("canonical_name", "")
                    note = (
                        f"kg-microbe maps '{mim_label}' to {kgm_chebi} "
                        f"({kgm_label_hint}); MIM says {obj_id} ({obj_label})"
                    )
            elif kgm_entry:
                bucket = "AGREE"
                kgm_chebi = obj_id
                note = "kg-microbe has the CHEBI; label not indexed as a synonym"
            else:
                bucket = "MIM_ONLY"
                kgm_chebi = ""
                note = "kg-microbe does not index this surface form or CHEBI"

            kgm_label = kgm.get(kgm_chebi, {}).get("canonical_name", "") if kgm_chebi else ""

        # Flags
        flags = []
        oak_rec = oak.get(obj_id, {})
        if oak_rec.get("obsolete"):
            flags.append("DEPRECATED_CHEBI")
        if obj_id.startswith("CHEBI:") and oak_rec:
            aliases = oak_rec.get("aliases") or set()
            if obj_label and obj_label.lower() not in aliases:
                flags.append("LABEL_DRIFT")
        if mim_chebi_counts.get(obj_id, 0) > 1:
            flags.append("DUPLICATE")
        if not obj_id.startswith(EXPECTED_PREFIXES):
            flags.append("PREFIX_IRREGULAR")

        out.append({
            "mim_id": mim_id,
            "mim_label": mim_label,
            "mim_chebi": obj_id,
            "mim_object_label": obj_label,
            "kgm_chebi": kgm_chebi,
            "kgm_label": kgm_label,
            "oak_label": oak_rec.get("label", ""),
            "bucket": bucket,
            "flags": ",".join(flags),
            "confidence": r.get("confidence", ""),
            "mapping_justification": r.get("mapping_justification", ""),
            "notes": note,
        })

    # Pass 2b: UNMAPPED_PENDING_CURATION — kg-microbe/MediaDive entries with
    # no CHEBI anywhere. Mark already-covered-by-MIM forms separately so we
    # don't re-queue them.
    for u in (unmapped_rows or []):
        label = u["preferred_term"]
        already_in_mim = bool(mim_label_set) and label.lower() in (mim_label_set or set())
        out.append({
            "mim_id": "",
            "mim_label": label,
            "mim_chebi": "",
            "mim_object_label": "",
            "kgm_chebi": u["source_id"],
            "kgm_label": label,
            "oak_label": "",
            "bucket": "UNMAPPED_PENDING_CURATION",
            "flags": "ALREADY_IN_MIM" if already_in_mim else "",
            "confidence": "",
            "mapping_justification": "",
            "notes": (
                f"{u['origin']} placeholder; occurrences={u['occurrences']}; "
                f"source_id={u['source_id']}"
            ),
        })

    # Pass 2: KGM_ONLY — kg-microbe xrefs a MIM id that MIM's SSSOM doesn't publish.
    for mim_ref, kgm_chebis in sorted(kgm_mim_xref.items()):
        # Normalize to compare with MIM subject_ids (MIM publishes as MIM:<id>).
        normalized = mim_ref.replace("MediaIngredientMech:", "MIM:")
        if normalized in covered_mim_ids:
            continue
        for kgm_chebi in sorted(kgm_chebis):
            e = kgm[kgm_chebi]
            oak_rec = oak.get(kgm_chebi, {})
            flags = []
            if oak_rec.get("obsolete"):
                flags.append("DEPRECATED_CHEBI")
            out.append({
                "mim_id": normalized,
                "mim_label": "",
                "mim_chebi": "",
                "mim_object_label": "",
                "kgm_chebi": kgm_chebi,
                "kgm_label": e["canonical_name"],
                "oak_label": oak_rec.get("label", ""),
                "bucket": "KGM_ONLY",
                "flags": ",".join(flags),
                "confidence": "",
                "mapping_justification": "",
                "notes": f"kg-microbe xrefs {mim_ref}; not in published MIM SSSOM",
            })

    return out


# ---------- writers ----------

AUDIT_COLS = [
    "mim_id", "mim_label", "mim_chebi", "mim_object_label",
    "kgm_chebi", "kgm_label", "oak_label",
    "bucket", "flags", "confidence", "mapping_justification", "notes",
]


def write_tsv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with path.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")).replace("\t", " ").replace("\n", " ") for c in cols) + "\n")


def write_markdown(path: Path, rows: list[dict]) -> None:
    by_bucket: dict[str, int] = defaultdict(int)
    by_flag: dict[str, int] = defaultdict(int)
    for r in rows:
        by_bucket[r["bucket"]] += 1
        for f in (r["flags"] or "").split(","):
            if f:
                by_flag[f] += 1

    disagree_rows = [r for r in rows if r["bucket"] == "DISAGREE"][:25]
    mim_only_rows = [r for r in rows if r["bucket"] == "MIM_ONLY"][:10]
    kgm_only_rows = [r for r in rows if r["bucket"] == "KGM_ONLY"][:10]

    with path.open("w") as f:
        f.write("# MIM ↔ kg-microbe Reconciliation Audit\n\n")
        f.write(f"Total rows: **{len(rows)}**\n\n")
        f.write("## Bucket distribution\n\n")
        f.write("| Bucket | Count |\n|---|---:|\n")
        for b in BUCKETS:
            f.write(f"| {b} | {by_bucket.get(b, 0)} |\n")
        f.write("\n## Flag distribution\n\n")
        f.write("| Flag | Count |\n|---|---:|\n")
        for flag in ("DEPRECATED_CHEBI", "LABEL_DRIFT", "DUPLICATE", "PREFIX_IRREGULAR"):
            f.write(f"| {flag} | {by_flag.get(flag, 0)} |\n")

        def dump(title: str, rs: list[dict]) -> None:
            if not rs:
                return
            f.write(f"\n## {title} (first {len(rs)})\n\n")
            f.write("| MIM id | MIM label | MIM CHEBI | kg-microbe CHEBI | kg-microbe label | Flags | Notes |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for r in rs:
                f.write("| {} | {} | {} | {} | {} | {} | {} |\n".format(
                    r["mim_id"], r["mim_label"], r["mim_chebi"],
                    r["kgm_chebi"], r["kgm_label"], r["flags"], r["notes"],
                ))

        dump("DISAGREE", disagree_rows)
        dump("MIM_ONLY", mim_only_rows)
        dump("KGM_ONLY", kgm_only_rows)

        unmapped_rows = [r for r in rows if r["bucket"] == "UNMAPPED_PENDING_CURATION"][:15]
        dump("UNMAPPED_PENDING_CURATION", unmapped_rows)


def write_curation_queue(path: Path, rows: list[dict]) -> None:
    """Sorted MIM curation backlog: every UNMAPPED_PENDING_CURATION row,
    ordered by occurrence count descending. One row per suggestion.
    """
    cols = ["source_id", "preferred_term", "occurrences", "origin",
            "already_in_mim", "action"]
    queue: list[tuple[int, dict]] = []
    for r in rows:
        if r["bucket"] != "UNMAPPED_PENDING_CURATION":
            continue
        notes = r["notes"] or ""
        occ = 0
        for part in notes.split(";"):
            part = part.strip()
            if part.startswith("occurrences="):
                try:
                    occ = int(part.split("=", 1)[1])
                except ValueError:
                    pass
        source_id = r["kgm_chebi"]
        origin = source_id.split(":", 1)[0] if ":" in source_id else ""
        already = "yes" if "ALREADY_IN_MIM" in (r["flags"] or "") else "no"
        action = (
            "link-to-existing-MIM-record" if already == "yes"
            else "curate-new-MIM-ingredient-with-chebi"
        )
        queue.append((occ, {
            "source_id": source_id,
            "preferred_term": r["mim_label"],
            "occurrences": str(occ),
            "origin": origin,
            "already_in_mim": already,
            "action": action,
        }))
    queue.sort(key=lambda x: (-x[0], x[1]["preferred_term"].lower()))

    with path.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for _, row in queue:
            f.write("\t".join(row[c] for c in cols) + "\n")


def write_pr_candidates(path: Path, rows: list[dict]) -> None:
    """Actionable subset for upstream kg-microbe PR filing.

    Rules:
      - DISAGREE rows → propose kg-microbe adopt MIM's CHEBI. If the
        OLS round-trip report exists (kgm_mim_disagree_roundtrip.json)
        and classifies the row as MIM_WRONG, invert the direction:
        propose MIM adopt kg-microbe's CHEBI.
      - KGM_ONLY rows with kg-microbe CHEBI marked DEPRECATED_CHEBI → propose removal.
      - Any DEPRECATED_CHEBI on MIM side → propose MIM update (out of scope
        for kg-microbe PR, but listed for full accounting).
    """
    cols = ["node_id", "current_chebi", "proposed_chebi", "reason",
            "roundtrip_verdict", "evidence"]

    # Load OLS round-trip verdicts keyed by (mim_chebi, kgm_chebi) if present.
    rt_path = REPORT_DIR / "kgm_mim_disagree_roundtrip.json"
    verdict_by_pair: dict[tuple[str, str], str] = {}
    if rt_path.exists():
        try:
            rt = json.loads(rt_path.read_text())
            for r in rt.get("results", []):
                verdict_by_pair[(r.get("mim_chebi", ""), r.get("kg_microbe_chebi", ""))] = r.get("decision", "")
        except Exception:
            pass

    with path.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            verdict = ""
            if r["bucket"] == "DISAGREE":
                verdict = verdict_by_pair.get((r["mim_chebi"], r["kgm_chebi"]), "")
                # MIM_WRONG → MIM should adopt kg-microbe's CHEBI.
                # MIM_OK → kg-microbe should adopt MIM's CHEBI (the default direction).
                # AMBIGUOUS or unknown → keep default direction but flag verdict.
                if verdict == "MIM_WRONG":
                    reason = "MIM-wrong-kg-microbe-right (OLS round-trip)"
                    current, proposed = r["mim_chebi"], r["kgm_chebi"]
                    node = r["mim_label"]
                elif verdict == "MIM_OK":
                    reason = "kg-microbe-noise-MIM-confirmed (OLS round-trip)"
                    current, proposed = r["kgm_chebi"], r["mim_chebi"]
                    node = r["mim_label"]
                else:
                    reason = "kg-microbe-disagrees-with-MIM"
                    current, proposed = r["kgm_chebi"], r["mim_chebi"]
                    node = r["mim_label"]
                f.write("\t".join([
                    node, current, proposed, reason, verdict, r["notes"],
                ]) + "\n")
            elif "DEPRECATED_CHEBI" in (r["flags"] or "") and r["bucket"] == "KGM_ONLY":
                f.write("\t".join([
                    r["kgm_label"], r["kgm_chebi"], "",
                    "kg-microbe-uses-deprecated-chebi", "", r["notes"],
                ]) + "\n")


def main() -> None:
    argparse.ArgumentParser(
        description=(
            "Bidirectional MIM <-> kg-microbe ingredient mapping audit. Reads "
            "MediaIngredientMech (MEDIAINGREDIENTMECH_ROOT) and kg-microbe "
            f"(KGMICROBE_ROOT); writes to {REPORT_DIR}."
        )
    ).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    print(f"[1/7] Loading MIM SSSOM from {MIM_SSSOM}")
    mim_rows = load_mim_sssom(MIM_SSSOM)
    print(f"      {len(mim_rows)} rows")

    print(f"[2/7] Loading kg-microbe dict from {KGM_DICT}")
    kgm = load_kgm_dict(KGM_DICT)
    print(f"      {len(kgm)} CHEBI entries")

    print("[3/7] Loading kg-microbe/MediaDive unmapped ingredient queues")
    unmapped_rows = (
        load_kgm_compound_placeholders(KGM_DICT)
        + load_mediadive_unmapped(KGM_MEDIADIVE_UNMAPPED)
    )
    print(f"      {len(unmapped_rows)} unmapped candidates")

    print("[4/7] Building kg-microbe synonym + xref indexes")
    kgm_syn = build_kgm_synonym_index(kgm)
    kgm_mim_xref = build_kgm_mim_xref_index(kgm)
    print(f"      {len(kgm_syn)} synonyms, {len(kgm_mim_xref)} MIM xrefs")

    print("[5/7] Collecting unique CHEBIs for OAK lookup")
    unique_chebis: set[str] = set()
    for r in mim_rows:
        if r["object_id"].startswith("CHEBI:"):
            unique_chebis.add(r["object_id"])
    for mim_ref, kgm_chebis in kgm_mim_xref.items():
        normalized = mim_ref.replace("MediaIngredientMech:", "MIM:")
        if not any(mr["subject_id"] == normalized for mr in mim_rows):
            unique_chebis.update(kgm_chebis)
    print(f"      {len(unique_chebis)} CHEBIs to look up in OAK")

    print("[6/7] Running OAK lookups")
    oak = build_oak_index(unique_chebis)

    print("[7/7] Reconciling and writing outputs")
    mim_label_set = {r["subject_label"].lower() for r in mim_rows if r["subject_label"]}
    results = reconcile(
        mim_rows, kgm, kgm_syn, kgm_mim_xref, oak,
        unmapped_rows=unmapped_rows,
        mim_label_set=mim_label_set,
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_tsv(AUDIT_TSV, results, AUDIT_COLS)
    write_markdown(AUDIT_MD, results)
    write_pr_candidates(PR_TSV, results)
    write_curation_queue(CURATION_QUEUE_TSV, results)

    print(f"\nWrote {AUDIT_TSV}")
    print(f"Wrote {AUDIT_MD}")
    print(f"Wrote {PR_TSV}")
    print(f"Wrote {CURATION_QUEUE_TSV}")

    # One-line summary to stdout
    by_bucket: dict[str, int] = defaultdict(int)
    for r in results:
        by_bucket[r["bucket"]] += 1
    print("\nBucket summary:", json.dumps({b: by_bucket[b] for b in BUCKETS}))


if __name__ == "__main__":
    main()
