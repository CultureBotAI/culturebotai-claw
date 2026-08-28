#!/usr/bin/env python3
"""Inventory every "unmapped / pending-curation" ingredient surface across
the four repos (MIM, kg-microbe, CultureMech, CommunityMech) and emit a
unified report keyed by normalized name.

The goal is to know — at any point in time — exactly which chemicals
are still waiting for an authoritative MIM mapping, where they came
from, and whether the same name shows up in multiple repos (which
makes it a higher priority for MIM curation).

Run via `just inventory-unmapped` — see skill `unmapped-inventory`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech"))
KGM_ROOT = Path(os.environ.get(
    "KGMICROBE_ROOT",
    REPO_ROOT.parent / "kg-microbe"))
CULTUREMECH_ROOT = Path(os.environ.get(
    "CULTUREMECH_ROOT",
    REPO_ROOT.parent / "CultureMech"))
COMMUNITYMECH_ROOT = Path(os.environ.get(
    "COMMUNITYMECH_ROOT",
    REPO_ROOT.parent / "CommunityMech" / "CommunityMech"))

OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "unmapped_inventory.tsv"
OUT_MD = OUT_DIR / "unmapped_inventory.md"


_NORM_RE = re.compile(r"[^a-z0-9]+")


def normalize(name: str) -> str:
    return _NORM_RE.sub("_", name.strip().lower()).strip("_")


@dataclass
class Row:
    source: str           # e.g. "MIM:unmapped", "kgm:metatraits"
    name: str             # human-readable
    norm: str             # normalized key for cross-source overlap
    status: str           # UNMAPPED | PLACEHOLDER | CAS_FALLBACK | UNMAPPED_INGREDIENT
    current_id: str       # whatever ID the source has (may be empty)
    extra: dict = field(default_factory=dict)


# ---------- Source loaders ---------------------------------------------------

def load_mim_unmapped() -> Iterable[Row]:
    d = MIM_ROOT / "data" / "ingredients" / "unmapped"
    if not d.is_dir():
        return
    for p in sorted(d.glob("*.yaml")):
        try:
            with open(p) as f:
                y = yaml.safe_load(f) or {}
        except Exception:
            continue
        name = y.get("preferred_term") or p.stem
        ident = y.get("identifier", "")
        yield Row(
            source="MIM:unmapped/",
            name=name,
            norm=normalize(name),
            status="UNMAPPED",
            current_id=ident,
            extra={"yaml": str(p.relative_to(MIM_ROOT))},
        )


def load_mim_mapped_placeholders() -> Iterable[Row]:
    """MIM ingredients in mapped/ that primary on kgmicrobe.compound: or cas:.
    These are 'half-mapped' — they have an identifier but not a real
    ontology term, so they still count as curation-pending for the
    'MIM is the single source of truth' goal."""
    d = MIM_ROOT / "data" / "ingredients" / "mapped"
    if not d.is_dir():
        return
    for p in sorted(d.glob("*.yaml")):
        try:
            with open(p) as f:
                y = yaml.safe_load(f) or {}
        except Exception:
            continue
        ident = y.get("identifier", "")
        if not ident:
            continue
        if ident.startswith("kgmicrobe.compound:"):
            status = "PLACEHOLDER"
        elif ident.startswith("cas:"):
            status = "CAS_FALLBACK"
        else:
            continue
        name = y.get("preferred_term") or p.stem
        yield Row(
            source="MIM:mapped/" + status.lower(),
            name=name,
            norm=normalize(name),
            status=status,
            current_id=ident,
            extra={"yaml": str(p.relative_to(MIM_ROOT))},
        )


def load_kgm_metatraits_unmapped() -> Iterable[Row]:
    p = KGM_ROOT / "docs" / "metatraits" / "unmapped_compounds.tsv"
    if not p.is_file():
        return
    with open(p) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            name = r.get("label_token", "")
            yield Row(
                source="kgm:metatraits/unmapped",
                name=name,
                norm=normalize(name),
                status="PLACEHOLDER",
                current_id=r.get("placeholder_id", ""),
                extra={"edge_count": r.get("edge_count", ""),
                       "predicate": r.get("predicate", "")},
            )


def load_kgm_mediadive_unmapped() -> Iterable[Row]:
    p = KGM_ROOT / "mappings" / "mediadive_unmapped_ingredients_to_curate.tsv"
    if not p.is_file():
        return
    with open(p) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            name = r.get("preferred_term", "")
            if not name:
                continue
            yield Row(
                source="kgm:mediadive/unmapped",
                name=name,
                norm=normalize(name),
                status="UNMAPPED",
                current_id=r.get("id", ""),
                extra={"occurrences": r.get("occurrences", "")},
            )


def load_culturemech_pending() -> Iterable[Row]:
    p = CULTUREMECH_ROOT / "data" / "import_tracking" / \
        "new_solution_ingredients_vs_mediaingredientmech.tsv"
    if not p.is_file():
        return
    with open(p) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            status_raw = (r.get("MediaIngredientMech Status") or "").strip()
            if "NEW" not in status_raw and "Not in" not in status_raw:
                continue
            name = r.get("Preferred Term", "")
            if not name:
                continue
            yield Row(
                source="culturemech:new-solution-ingredients",
                name=name,
                norm=normalize(name),
                status="UNMAPPED_INGREDIENT",
                current_id=r.get("CHEBI ID", ""),
                extra={"chebi_label": r.get("CHEBI Label", ""),
                       "source_solution": r.get("Source Solution", "")},
            )


def load_communitymech_unmapped() -> Iterable[Row]:
    p = COMMUNITYMECH_ROOT / "reports" / "ingredient_mapping.csv"
    if not p.is_file():
        return
    seen: set[str] = set()
    with open(p) as f:
        reader = csv.DictReader(f)
        for r in reader:
            if (r.get("status") or "").strip() != "unmapped":
                continue
            name = r.get("ingredient_name", "")
            if not name:
                continue
            n = normalize(name)
            # CommunityMech rows repeat the same ingredient across communities
            if n in seen:
                continue
            seen.add(n)
            yield Row(
                source="communitymech:ingredient_mapping",
                name=name,
                norm=n,
                status="UNMAPPED",
                current_id="",
                extra={},
            )


# (label, loader, the repository root the loader reads, the variable that sets it).
# The root is declared here so an absent one is REPORTED rather than silently
# contributing zero rows: every loader returns early when its directory is
# missing, which produced a well-formed report whose totals were quietly
# conditioned on which checkouts happened to exist (#161).
SOURCES: list[tuple[str, callable, Path, str]] = [
    ("MIM:unmapped", load_mim_unmapped, MIM_ROOT, "MEDIAINGREDIENTMECH_ROOT"),
    ("MIM:mapped-placeholder", load_mim_mapped_placeholders, MIM_ROOT,
     "MEDIAINGREDIENTMECH_ROOT"),
    ("kgm:metatraits", load_kgm_metatraits_unmapped, KGM_ROOT, "KGMICROBE_ROOT"),
    ("kgm:mediadive", load_kgm_mediadive_unmapped, KGM_ROOT, "KGMICROBE_ROOT"),
    ("culturemech:pending", load_culturemech_pending, CULTUREMECH_ROOT,
     "CULTUREMECH_ROOT"),
    ("communitymech:unmapped", load_communitymech_unmapped, COMMUNITYMECH_ROOT,
     "COMMUNITYMECH_ROOT"),
]


@dataclass
class Coverage:
    """Whether a source was actually read, and why not when it was not."""

    label: str
    root: Path
    variable: str
    present: bool
    rows: int

    @property
    def state(self) -> str:
        if not self.present:
            return "ABSENT"
        return "read" if self.rows else "empty"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-sources",
        metavar="LABEL",
        action="append",
        default=[],
        help=(
            "Fail when this source's repository root is absent, instead of "
            "reporting a smaller inventory. Repeatable; use in CI so a checkout "
            "regression cannot silently narrow the report."
        ),
    )
    parser.add_argument(
        "--require-all-sources",
        action="store_true",
        help="Fail when any declared source root is absent.",
    )
    args = parser.parse_args(argv)

    known = {label for label, _, _, _ in SOURCES}
    unknown = sorted(set(args.require_sources) - known)
    if unknown:
        print(
            f"error: unknown source(s) {unknown}; choose from "
            f"{', '.join(sorted(known))}",
            file=sys.stderr,
        )
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[Row] = []
    counts: dict[str, int] = {}
    coverage: list[Coverage] = []
    for label, fn, root, variable in SOURCES:
        n = 0
        for row in fn():
            rows.append(row)
            n += 1
        counts[label] = n
        coverage.append(Coverage(label, root, variable, root.is_dir(), n))
        print(f"  {label:38s}  {n:>5d} rows")

    print("\nSource coverage:")
    for entry in coverage:
        detail = f"set {entry.variable}" if not entry.present else str(entry.root)
        print(f"  {entry.label:38s}  {entry.state:>6s}  {detail}")

    absent = [entry for entry in coverage if not entry.present]
    if absent:
        print(
            f"\nWARNING: {len(absent)} source(s) were not read, so the totals "
            f"below cover only the sources marked read/empty above."
        )

    required = set(args.require_sources)
    if args.require_all_sources:
        required |= known
    missing = sorted(entry.label for entry in absent if entry.label in required)
    if missing:
        print(
            f"error: required source(s) absent: {missing}. Their repository "
            f"roots are not directories, so the inventory would silently under-"
            f"report rather than fail.",
            file=sys.stderr,
        )
        return 1

    # Cross-source overlap by normalized name
    by_norm: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_norm[r.norm].append(r)

    multi = {n: rs for n, rs in by_norm.items() if len({r.source for r in rs}) > 1}

    # Emit TSV
    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        for entry in coverage:
            w.writerow([f"# coverage\t{entry.label}\t{entry.state}\t"
                        f"{entry.root if entry.present else entry.variable}"])
        w.writerow(["source", "name", "norm_key", "status", "current_id",
                    "n_other_sources", "other_sources", "extra_json"])
        for r in rows:
            others = [x.source for x in by_norm[r.norm] if x.source != r.source]
            w.writerow([
                r.source, r.name, r.norm, r.status, r.current_id,
                len(set(others)),
                "|".join(sorted(set(others))),
                json.dumps(r.extra, sort_keys=True) if r.extra else "",
            ])

    # Emit markdown summary
    md: list[str] = []
    md.append("# Unmapped Ingredient Inventory\n")

    # Coverage first: the totals below mean nothing without knowing which
    # sources produced them, and an archived artifact must carry that with it
    # rather than relying on the console log of the run that made it (#161).
    md.append("## Source coverage\n")
    if absent:
        md.append(
            f"> **Partial inventory.** {len(absent)} of {len(coverage)} sources "
            f"were not read; every total below excludes them.\n"
        )
    md.append("| Source | State | Root or missing variable |")
    md.append("|---|---|---|")
    for entry in coverage:
        detail = f"`{entry.variable}` not set to a directory" if not entry.present \
            else f"`{entry.root}`"
        md.append(f"| `{entry.label}` | {entry.state} | {detail} |")
    md.append("")

    scope = "across the sources read above" if absent else "across all sources"
    md.append(f"Total rows {scope}: **{len(rows)}**\n")
    md.append(f"Distinct normalized names: **{len(by_norm)}**\n")
    md.append(f"Names appearing in 2+ sources: **{len(multi)}** (priority targets)\n")
    md.append("\n## Per-source row counts\n")
    md.append("| Source | Rows | Status mix |")
    md.append("|---|---:|---|")
    by_src_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_src_status[r.source][r.status] += 1
    for src in sorted(by_src_status):
        mix = ", ".join(f"{k}={v}" for k, v in sorted(by_src_status[src].items()))
        total = sum(by_src_status[src].values())
        md.append(f"| `{src}` | {total} | {mix} |")

    md.append("\n## Top cross-source overlaps (priority MIM curation targets)\n")
    md.append("Names that appear in 2+ sources — fixing these in MIM "
              "propagates the most value downstream.\n")
    md.append("| Name | Sources | n |")
    md.append("|---|---|---:|")
    multi_sorted = sorted(
        multi.items(),
        key=lambda kv: (-len({r.source for r in kv[1]}), kv[0]),
    )
    for n, rs in multi_sorted[:30]:
        srcs = sorted({r.source for r in rs})
        any_name = next(iter(rs)).name
        md.append(f"| {any_name} | {', '.join(srcs)} | {len(srcs)} |")
    if len(multi_sorted) > 30:
        md.append(f"\n*(... {len(multi_sorted) - 30} more cross-source rows in TSV)*\n")

    md.append("\n## Single-source items (per-source breakdown)\n")
    md.append("Items that only one source flags — lower priority but still "
              "part of MIM's mandate as the single source of truth.\n")
    single: dict[str, int] = defaultdict(int)
    for n, rs in by_norm.items():
        if len({r.source for r in rs}) == 1:
            single[next(iter(rs)).source] += 1
    md.append("| Source | Single-source rows |")
    md.append("|---|---:|")
    for src in sorted(single):
        md.append(f"| `{src}` | {single[src]} |")

    md.append("\n## Next steps\n")
    md.append("Feed these rows into MIM via `ingredient-mapping`:\n")
    md.append("- `kgm:metatraits` rows → `python scripts/import_ingredients.py --source kgm-metatraits --apply`")
    md.append("- `kgm:mediadive` rows → `python scripts/import_ingredients.py --source mim-queue --apply`")
    md.append("- `culturemech:pending` rows → currently no source loader; add one or curate manually via MIM")
    md.append("- `communitymech:unmapped` rows → currently no source loader; add one or use `mim-queue`")
    md.append("- `MIM:mapped-placeholder` PLACEHOLDER+CAS_FALLBACK rows → re-run `import_ingredients.py` after a CHEBI release; rows that resolve get auto-promoted")
    md.append("\nAfter ingestion, run `just publish-sssom` to propagate to consumers.\n")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"\nWrote {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(REPO_ROOT)}")
    print(f"\n{len(rows)} total rows / {len(by_norm)} distinct names / "
          f"{len(multi)} cross-source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
