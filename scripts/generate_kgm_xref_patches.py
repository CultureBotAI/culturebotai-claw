#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Emit kg-microbe xref patches: per-CHEBI deltas that bring kg-microbe's
unified_chemical_mappings.tsv.gz in sync with MIM's current published
SSSOM namespace.

Two patch sources:

  a) MIM's published SSSOM
     For each MIM:<slug> + CHEBI pair, ensure kg-microbe's CHEBI row lists
     MIM:<slug> among its xrefs. If missing, an ADD patch is emitted.

  b) Migration map (from scripts/generate_mim_migration_map.py)
     For each old MediaIngredientMech:000xxx that kg-microbe still xrefs:
       - if action=migrate → REPLACE old -> new MIM:<slug>
       - if action=orphan  → REMOVE (old id no longer corresponds to any MIM record)
       - if action=ambiguous → flag only (curator must pick)

Output:
  workspace/patches/kgm_xref_patches.tsv
  workspace/patches/kgm_xref_patches.md
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

from kgm_unified_mappings import KGM_UNIFIED_SSSOM, load_kgm_entity_index

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
MIM_SSSOM = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv"
)
KGM_DICT = KGM_UNIFIED_SSSOM
MIGRATION_TSV = WORKSPACE / "reports/mim_numeric_namespace_migration.tsv"
PATCHES_DIR = WORKSPACE / "patches"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from kg_microbe_patches import (  # noqa: E402
    LEDGER_FILENAME,
    LedgerError,
    describe,
    record,
    staleness,
)

OUT_TSV = PATCHES_DIR / "kgm_xref_patches.tsv"
OUT_MD = PATCHES_DIR / "kgm_xref_patches.md"

COLS = ["kgm_chebi", "current_xrefs", "add_xrefs", "remove_xrefs", "action", "notes"]


def load_mim_sssom_chebi_to_mim() -> dict[str, list[str]]:
    """CHEBI -> list of MIM subject_ids in current published SSSOM."""
    idx: dict[str, list[str]] = defaultdict(list)
    with MIM_SSSOM.open() as f:
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
            row = dict(zip(header, parts))
            if row.get("object_id", "").startswith("CHEBI:"):
                idx[row["object_id"]].append(row["subject_id"])
    return idx


def load_kgm_xrefs() -> dict[str, set[str]]:
    """kg-microbe CHEBI -> current xrefs set."""
    if not KGM_DICT.exists():
        raise SystemExit(
            f"kg-microbe unified mapping not found: {KGM_DICT}\n"
            "Regenerate it in kg-microbe with:\n"
            "  poetry run python scripts/consolidate_chemical_mappings.py"
        )
    out: dict[str, set[str]] = defaultdict(set)
    for cid, entry in load_kgm_entity_index(KGM_DICT).items():
        out[cid].update(entry["xrefs"])
    return out


def load_migration_map() -> list[dict]:
    with MIGRATION_TSV.open() as f:
        return list(csv.DictReader(f, delimiter="\t"))


def build_patches(
    mim_idx: dict[str, list[str]],
    kgm_xrefs: dict[str, set[str]],
    migration: list[dict],
) -> list[dict]:
    patches: dict[str, dict] = {}

    def _get(chebi: str) -> dict:
        if chebi not in patches:
            patches[chebi] = {
                "kgm_chebi": chebi,
                "current_xrefs": kgm_xrefs.get(chebi, set()),
                "add": set(),
                "remove": set(),
                "notes": [],
            }
        return patches[chebi]

    # Source (a): ensure every MIM:<slug> is in kg-microbe's xrefs for its CHEBI.
    for chebi, mim_ids in mim_idx.items():
        current = kgm_xrefs.get(chebi, set())
        for mim_id in mim_ids:
            if mim_id not in current:
                p = _get(chebi)
                p["add"].add(mim_id)
                p["notes"].append(f"add {mim_id} (MIM SSSOM asserts this mapping)")

    # Source (b): apply migration decisions for old MediaIngredientMech:000xxx ids.
    for r in migration:
        chebi = r["kgm_chebi"]
        old_id = r["old_id"]  # MIM:000xxx (normalized in audit) — kg-microbe uses MediaIngredientMech:000xxx
        new_id = r.get("new_mim_id", "")
        action = r["action"]
        if not chebi:
            continue

        # In kg-microbe's xrefs the ID is MediaIngredientMech:000xxx.
        kgm_legacy = old_id.replace("MIM:", "MediaIngredientMech:")

        if action == "migrate":
            p = _get(chebi)
            p["remove"].add(kgm_legacy)
            if new_id and new_id not in kgm_xrefs.get(chebi, set()):
                p["add"].add(new_id)
            p["notes"].append(f"migrate {kgm_legacy} -> {new_id}")
        elif action == "orphan":
            p = _get(chebi)
            p["remove"].add(kgm_legacy)
            p["notes"].append(f"remove orphan {kgm_legacy} (MIM no longer covers this CHEBI)")
        elif action == "ambiguous":
            p = _get(chebi)
            p["notes"].append(
                f"FLAG: {kgm_legacy} is ambiguous — candidates: {r['ambiguous_candidates']}"
            )

    # Realize into output rows.
    out_rows: list[dict] = []
    for chebi in sorted(patches):
        p = patches[chebi]
        action = (
            "add_only" if p["add"] and not p["remove"]
            else "remove_only" if p["remove"] and not p["add"]
            else "replace" if p["add"] and p["remove"]
            else "flag"
        )
        out_rows.append({
            "kgm_chebi": chebi,
            "current_xrefs": "|".join(sorted(p["current_xrefs"])),
            "add_xrefs": "|".join(sorted(p["add"])),
            "remove_xrefs": "|".join(sorted(p["remove"])),
            "action": action,
            "notes": "; ".join(p["notes"]),
        })
    return out_rows


def write_tsv(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")).replace("\t", " ") for c in COLS) + "\n")


def write_md(path: Path, rows: list[dict]) -> None:
    by_action: dict[str, int] = defaultdict(int)
    for r in rows:
        by_action[r["action"]] += 1

    out: list[str] = []
    out.append("# kg-microbe Xref Patches")
    out.append("")
    out.append(f"**Total patch rows:** {len(rows)}")
    out.append("")
    out.append("## Action distribution")
    out.append("")
    out.append("| Action | Count |")
    out.append("|---|---:|")
    for a in ("add_only", "replace", "remove_only", "flag"):
        out.append(f"| {a} | {by_action.get(a, 0)} |")
    out.append("")

    samples = [r for r in rows if r["action"] == "replace"][:15]
    if samples:
        out.append("## Sample REPLACE patches (first 15)")
        out.append("")
        out.append("| kg-microbe CHEBI | Remove | Add | Notes |")
        out.append("|---|---|---|---|")
        for r in samples:
            out.append(
                f"| {r['kgm_chebi']} | `{r['remove_xrefs']}` | "
                f"`{r['add_xrefs']}` | {r['notes'][:120]} |"
            )
        out.append("")

    path.write_text("\n".join(out) + "\n")


def main() -> None:
    print("[1/4] Loading MIM SSSOM CHEBI -> MIM id index")
    mim_idx = load_mim_sssom_chebi_to_mim()
    print(f"      {len(mim_idx)} CHEBIs, {sum(len(v) for v in mim_idx.values())} MIM ids")

    print("[2/4] Loading kg-microbe xrefs")
    kgm_xrefs = load_kgm_xrefs()
    print(f"      {len(kgm_xrefs)} CHEBIs with xrefs")

    print("[3/4] Loading migration map")
    migration = load_migration_map()
    print(f"      {len(migration)} migration entries")

    rows = build_patches(mim_idx, kgm_xrefs, migration)
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)

    # Staleness of the PREVIOUS artifact, checked before overwriting it. The
    # file in the repository was four months old with nothing saying so (#129
    # item 4).
    outdated_by = staleness(OUT_TSV, [MIM_SSSOM, KGM_DICT])

    write_tsv(OUT_TSV, rows)
    write_md(OUT_MD, rows)
    print(f"[4/4] Wrote {OUT_TSV}")
    print(f"      Wrote {OUT_MD}")

    if outdated_by:
        names = ", ".join(Path(p).name for p in outdated_by)
        print(f"      (the previous patch set predated {names})")

    # Record the set so an unapplied backlog is visible. This tracks; applying
    # means changing kg-microbe, a separate repository and a separate decision.
    #
    # The ledger is bookkeeping and the patches are the product, so a corrupt
    # ledger warns rather than failing a generation that already succeeded
    # (#195). record() itself stays strict for callers that want the history.
    try:
        entry, verdict = record(
            PATCHES_DIR / LEDGER_FILENAME,
        # Fingerprint the exact rows the TSV publishes, so the ledger tracks
        # what a reader is asked to act on rather than an internal shape.
            ["\t".join(str(r.get(c, "")) for c in COLS) for r in rows],
        )
    except LedgerError as exc:
        print(
            f"      (patch ledger unavailable: {exc}; the patches above are "
            f"unaffected. Delete {PATCHES_DIR / LEDGER_FILENAME} to start a new "
            f"history.)"
        )
    else:
        print(f"      {describe(entry, verdict)}")


if __name__ == "__main__":
    main()
