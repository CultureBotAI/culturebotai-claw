#!/usr/bin/env python3
"""Merge every Mech's METPO proposal cohorts into one aggregate ROBOT template.

    python scripts/fleet_metpo_aggregate.py [--out DIR] [--json] [--check]

METPO proposals are minted per Mech and submitted upstream, but nothing has
ever looked at them together. Two Mechs propose classes today -- TraitMech in
eleven cohorts and CommunityMech in three -- from one shared numeric ID space
that the canonical rules describe as "pick the next unused `1007NNN` slot".
That instruction is only satisfiable by someone who can see every slot already
taken, and no Mech can see another's.

The result is already a defect rather than a risk. Measured on the corpora this
script was written against, eight IDs carry two different terms:

    METPO:1007214  interspecies electron transfer
    METPO:1007214  direct interspecies electron transfer community

Both are CommunityMech's, in different cohorts, and submitting both would hand
METPO contradictory definitions for the same identifier. Nothing reported it
because nothing reads two cohorts at once.

So the aggregate is the product, and the collision report is the reason to
build it. A run that merges cleanly is worth having; a run that refuses is
worth more.

## What "merged" means here

Cohorts are **additive, not successive**. TraitMech's `v1`..`v11` are separate
proposal batches: measured across all eleven, the union of class IDs (160) is
exactly the sum of the per-cohort counts, and no two consecutive cohorts share
an ID. So every cohort contributes, and a version number is provenance rather
than a supersession marker. A merge that kept only the newest cohort would drop
145 of TraitMech's 160 proposed classes.

Exit codes: 0 aggregate written and no collision, 1 a collision or an
incomplete read, 2 bad usage or an unresolvable repository.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from kg_microbe_fleet import FleetManifest, FleetManifestError, load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root

CLAW_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY = "metpo_proposal"

#: The two ROBOT template kinds a Mech may publish, and the settings key that
#: locates each. Both are optional per Mech: CommunityMech publishes classes in
#: every cohort and properties in two of three.
KINDS = {
    "classes": "class_glob",
    "properties": "property_glob",
}

DEFAULT_GLOBS = {
    "classes": "proposals/*/metpo_proposal_classes_robot.tsv",
    "properties": "proposals/*/metpo_proposal_properties_robot.tsv",
}

PROVENANCE_COLUMNS = ("kind", "proposed_id", "label", "mech", "cohort", "source")


class AggregateError(RuntimeError):
    pass


def declaring_mechs(manifest: FleetManifest | None = None) -> list[str]:
    """Mech keys whose manifest entry enables the capability, in manifest order.

    Membership is the manifest's to decide. A list here would be the drift
    #131 exists to remove, and would silently omit a Mech that started
    proposing.
    """
    manifest = manifest or load_fleet_manifest()
    keys = []
    for key, mech in manifest.mechs.items():
        capability = mech.capabilities.get(CAPABILITY)
        status = getattr(capability, "status", None) or (
            capability.get("status") if isinstance(capability, dict) else None
        )
        if status == "enabled":
            keys.append(key)
    return keys


def _settings(manifest: FleetManifest, key: str) -> dict:
    capability = manifest.mechs[key].capabilities.get(CAPABILITY)
    settings = getattr(capability, "settings", None)
    if settings is None and isinstance(capability, dict):
        settings = capability.get("settings")
    return dict(settings or {})


def read_template(path: Path) -> tuple[tuple[str, ...], tuple[str, ...], list[dict]]:
    """A ROBOT template's header row, template row, and data rows.

    A ROBOT template's second line is not data: it carries the OWL mapping for
    each column (`A IAO:0000115`, `SC %`). Reading it as a row would emit a
    class whose label is literally `LABEL`, which is the kind of thing that
    only fails once it reaches the ontology.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    if len(rows) < 2:
        raise AggregateError(f"{path} has no ROBOT template row")
    header = tuple(cell.strip() for cell in rows[0])
    template = tuple(cell.strip() for cell in rows[1])
    data = [
        dict(zip(header, row + [""] * (len(header) - len(row))))
        for row in rows[2:]
        if any(cell.strip() for cell in row)
    ]
    return header, template, data


def collect(
    manifest: FleetManifest | None = None,
    claw_root: Path = CLAW_ROOT,
) -> dict:
    """Read every declaring Mech's cohorts, recording each failure by name."""

    manifest = manifest or load_fleet_manifest()
    keys = declaring_mechs(manifest)
    result: dict = {
        "capability": CAPABILITY,
        "mechs_declaring": keys,
        "mechs_read": [],
        "cohorts": defaultdict(list),
        "rows": {kind: [] for kind in KINDS},
        "shape": {},
        "errors": {},
    }
    # Read everything first, then decide which ROBOT shape is the fleet's.
    # Taking the first file seen would let whichever cohort sorts earliest
    # define the standard, so a single malformed template would refuse every
    # correct one -- which is what the first version of this did, caught by
    # `test_a_cohort_whose_template_row_disagrees_is_refused_not_merged`.
    read: list[tuple[str, str, str, Path, tuple, tuple, list[dict]]] = []
    for key in keys:
        try:
            root = resolve_mech_root(key, claw_root=claw_root)
        except MechRootError as exc:
            result["errors"][key] = str(exc)[:200]
            continue
        settings = _settings(manifest, key)
        result["mechs_read"].append(key)
        for kind, setting_name in KINDS.items():
            pattern = settings.get(setting_name, DEFAULT_GLOBS[kind])
            for path in sorted(root.glob(pattern)):
                cohort = path.parent.name
                try:
                    header, template, data = read_template(path)
                except (AggregateError, OSError, UnicodeError) as exc:
                    result["errors"][f"{key}:{cohort}:{kind}"] = str(exc)[:200]
                    continue
                read.append(
                    (kind, key, cohort, path.relative_to(root), header, template, data)
                )

    for kind in KINDS:
        shapes = Counter(
            (header, template)
            for entry_kind, _, _, _, header, template, _ in read
            if entry_kind == kind
        )
        if not shapes:
            continue
        ranked = shapes.most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            # No majority means no basis for calling either one the deviation.
            result["errors"][f"{kind}:shape"] = (
                f"{len(ranked)} ROBOT template shapes are equally common; "
                f"nothing here can say which is the fleet's"
            )
            continue
        header, template = ranked[0][0]
        result["shape"][kind] = {"header": header, "template": template}

    for kind, key, cohort, relative, header, template, data in read:
        shape = result["shape"].get(kind)
        if shape is None:
            continue
        if (header, template) != (shape["header"], shape["template"]):
            # Merging templates that disagree would silently drop or misalign
            # columns; the aggregate would look fine and mean something else.
            result["errors"][f"{key}:{cohort}:{kind}"] = (
                "ROBOT template shape differs from the rest of the fleet"
            )
            continue
        if cohort not in result["cohorts"][key]:
            result["cohorts"][key].append(cohort)
        for row in data:
            result["rows"][kind].append(
                {**row, "_mech": key, "_cohort": cohort, "_source": str(relative)}
            )
    result["cohorts"] = dict(result["cohorts"])
    return result


def _identity(row: dict) -> tuple[str, str]:
    return row.get("proposed_id", "").strip(), row.get("label", "").strip()


def find_collisions(rows: list[dict]) -> dict:
    """Where one identifier means two things, or one thing has two identifiers.

    Both directions matter and they are not the same defect. An ID with two
    labels hands METPO contradictory definitions for one term. A label with two
    IDs mints the same term twice, so downstream data splits across identifiers
    that will never be reconciled.
    """
    by_id: dict[str, set[str]] = defaultdict(set)
    by_label: dict[str, set[str]] = defaultdict(set)
    where: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        proposed_id, label = _identity(row)
        if not proposed_id:
            continue
        by_id[proposed_id].add(label)
        if label:
            by_label[label].add(proposed_id)
        where[(proposed_id, label)].append(f"{row['_mech']}:{row['_cohort']}")

    return {
        "id_means_two_things": {
            proposed_id: sorted(labels)
            for proposed_id, labels in sorted(by_id.items())
            if len(labels) > 1
        },
        "label_has_two_ids": {
            label: sorted(ids)
            for label, ids in sorted(by_label.items())
            if len(ids) > 1
        },
        "repeated_identical_rows": {
            f"{proposed_id} {label}": sorted(sources)
            for (proposed_id, label), sources in sorted(where.items())
            if len(sources) > 1
        },
    }


def merged_rows(rows: list[dict], header: tuple[str, ...]) -> list[dict]:
    """One row per distinct ID+label, ordered by ID so two runs diff cleanly."""
    seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = _identity(row)
        seen.setdefault(key, {name: row.get(name, "") for name in header})
    return [seen[key] for key in sorted(seen)]


def write_aggregate(data: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for kind in KINDS:
        shape = data["shape"].get(kind)
        if not shape or not data["rows"][kind]:
            continue
        header, template = shape["header"], shape["template"]
        path = out_dir / f"metpo_fleet_aggregate_{kind}_robot.tsv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(header)
            writer.writerow(template)
            for row in merged_rows(data["rows"][kind], header):
                writer.writerow([row.get(name, "") for name in header])
        written.append(path)

    provenance = out_dir / "metpo_fleet_aggregate_provenance.tsv"
    with provenance.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(PROVENANCE_COLUMNS), delimiter="\t",
            lineterminator="\n", extrasaction="ignore",
        )
        writer.writeheader()
        for kind in KINDS:
            for row in sorted(
                data["rows"][kind],
                key=lambda r: (_identity(r), r["_mech"], r["_cohort"]),
            ):
                proposed_id, label = _identity(row)
                writer.writerow({
                    "kind": kind, "proposed_id": proposed_id, "label": label,
                    "mech": row["_mech"], "cohort": row["_cohort"],
                    "source": row["_source"],
                })
    written.append(provenance)
    return written


def render(data: dict, collisions: dict[str, dict]) -> str:
    lines: list[str] = []
    totals = {kind: len(rows) for kind, rows in data["rows"].items()}
    distinct = {
        kind: len({_identity(row) for row in rows})
        for kind, rows in data["rows"].items()
    }
    cohorts = sum(len(names) for names in data["cohorts"].values())

    lines.append(
        "METPO proposals across the fleet: "
        + ", ".join(
            f"{totals[kind]} {kind} rows in {cohorts} cohorts" for kind in ("classes",)
        )
    )
    lines.append("")
    for kind in KINDS:
        if totals[kind]:
            lines.append(
                f"  {kind:<11} rows={totals[kind]:<5} distinct id+label={distinct[kind]}"
            )
    lines.append("")
    lines.append(f"{'MECH':<22}{'COHORTS':<9}{'CLASSES':>9}{'PROPERTIES':>12}")
    for key in data["mechs_declaring"]:
        if key in data["errors"]:
            lines.append(f"{key:<22}{'FAILED':<9}")
            continue
        counts = {
            kind: sum(1 for row in data["rows"][kind] if row["_mech"] == key)
            for kind in KINDS
        }
        lines.append(
            f"{key:<22}{len(data['cohorts'].get(key, [])):<9}"
            f"{counts['classes']:>9}{counts['properties']:>12}"
        )

    lines.append("")
    lines.append("Collisions")
    clean = True
    for kind in KINDS:
        found = collisions.get(kind, {})
        for proposed_id, labels in found.get("id_means_two_things", {}).items():
            clean = False
            lines.append(
                f"  ID MEANS TWO THINGS  {kind}  {proposed_id}: "
                + " | ".join(labels)
            )
        for label, ids in found.get("label_has_two_ids", {}).items():
            clean = False
            lines.append(
                f"  LABEL HAS TWO IDS    {kind}  {label!r}: " + ", ".join(ids)
            )
    if clean:
        lines.append("  none -- every identifier means one thing across the fleet")

    lines.append("")
    lines.append("Coverage")
    declaring = ", ".join(data["mechs_declaring"]) or "none"
    lines.append(f"  declared by the manifest: {declaring}")
    read = ", ".join(data["mechs_read"]) or "none"
    lines.append(f"  read: {read}")
    for name, error in data["errors"].items():
        lines.append(f"  {name}: ERROR: {error}")
    if data["errors"]:
        lines.append(
            "  INCOMPLETE: the aggregate omits the repositories above, so its "
            "collision report is a lower bound"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleet_metpo_aggregate")
    ap.add_argument("--out", type=Path,
                    default=CLAW_ROOT / "workspace" / "metpo",
                    help="where the aggregate templates land")
    ap.add_argument("--check", action="store_true",
                    help="report only; write no files")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    try:
        data = collect()
    except FleetManifestError as exc:
        print(f"fleet manifest failed validation: {exc}", file=sys.stderr)
        return 2

    collisions = {kind: find_collisions(data["rows"][kind]) for kind in KINDS}
    written: list[Path] = []
    if not args.check and any(data["rows"].values()):
        written = write_aggregate(data, args.out)

    if args.as_json:
        print(json.dumps({
            "snapshot_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(
                timespec="seconds"),
            "mechs_declaring": data["mechs_declaring"],
            "mechs_read": data["mechs_read"],
            "cohorts": data["cohorts"],
            "counts": {k: len(v) for k, v in data["rows"].items()},
            "collisions": collisions,
            "errors": data["errors"],
            "written": [str(path) for path in written],
        }, indent=2, sort_keys=True))
    else:
        print(render(data, collisions))
        for path in written:
            print(f"\nWrote {path}")

    has_collision = any(
        found.get("id_means_two_things") or found.get("label_has_two_ids")
        for found in collisions.values()
    )
    return 1 if (has_collision or data["errors"]) else 0


if __name__ == "__main__":
    sys.exit(main())
