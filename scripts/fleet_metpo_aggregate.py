#!/usr/bin/env python3
"""Merge manifest-enabled Mech proposal cohorts without discarding assertions.

Outputs are review artifacts; release reconciliation and ROBOT reasoning remain
separate submission checks. Exit 1 signals incomplete input or conflicts.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import io
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


def declarations(manifest: FleetManifest) -> dict:
    """Keep the whole fleet denominator, including reasons for exclusions."""
    result = {}
    for key, mech in manifest.mechs.items():
        capability = mech.capabilities.get(CAPABILITY)
        def value(name):
            return capability.get(name) if isinstance(capability, dict) else getattr(
                capability, name, None
            )
        result[key] = {"status": value("status"), "reason": value("reason")}
    return result


def read_template(
    path: Path, *, content: bytes | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], list[dict]]:
    """A ROBOT template's header row, template row, and data rows.

    A ROBOT template's second line is not data: it carries the OWL mapping for
    each column (`A IAO:0000115`, `SC %`). Reading it as a row would emit a
    class whose label is literally `LABEL`, which is the kind of thing that
    only fails once it reaches the ontology.
    """
    content = path.read_bytes() if content is None else content
    with io.StringIO(content.decode("utf-8"), newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", strict=True)
        try:
            rows = list(reader)
        except csv.Error as exc:
            raise AggregateError(f"{path}:{reader.line_num}: invalid TSV: {exc}") from exc
    if len(rows) < 2:
        raise AggregateError(f"{path} has no ROBOT template row")
    header = tuple(cell.strip() for cell in rows[0])
    template = tuple(cell.strip() for cell in rows[1])
    if not all(header) or len(set(header)) != len(header) or not {"proposed_id", "label"} <= set(header):
        raise AggregateError(f"{path}: duplicate or missing identity columns")
    if any(name.startswith("_") for name in header):
        # Underscore keys carry provenance and are excluded from assertion
        # comparisons. Accepting them from a source would overwrite or hide data.
        raise AggregateError(f"{path}: underscore-prefixed columns are reserved for metadata")
    if len(template) != len(header):
        raise AggregateError(f"{path}: template/header column count differs")
    if template[header.index("proposed_id")] != "ID" or template[header.index("label")] != "LABEL":
        raise AggregateError(f"{path}: missing ROBOT ID/LABEL directives")
    for number, row in enumerate(rows[2:], 3):
        if len(row) > len(header):
            raise AggregateError(f"{path}:{number}: excess columns")
        if tuple(row) == template or tuple(row) == header:
            raise AggregateError(f"{path}:{number}: repeated header/template row")
        if any(cell.strip() for cell in row) and (
            len(row) <= max(header.index("proposed_id"), header.index("label"))
            or not row[header.index("proposed_id")].strip()
            or not row[header.index("label")].strip()
        ):
            raise AggregateError(f"{path}:{number}: missing proposed_id or label")
    data = [
        dict(zip(header, row + [""] * (len(header) - len(row))))
        for row in rows[2:]
        if any(cell.strip() for cell in row)
    ]
    # The supported class extension only adds related synonyms and renames
    # the exact-synonym column. Normalize these known equivalent schemas.
    exact = "A oboInOwl:hasExactSynonym SPLIT=|"
    related = "A oboInOwl:hasRelatedSynonym SPLIT=|"
    if "synonyms" in header and template[header.index("synonyms")] == exact:
        if "exact_synonyms" in header:
            raise AggregateError(f"{path}: both synonyms and exact_synonyms columns")
        header = tuple("exact_synonyms" if name == "synonyms" else name for name in header)
        for row in data:
            row["exact_synonyms"] = row.pop("synonyms")
    if "exact_synonyms" in header and "related_synonyms" not in header:
        header += ("related_synonyms",)
        template += (related,)
        for row in data:
            row["related_synonyms"] = ""
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
        "declarations": declarations(manifest),
        "mechs_declaring": keys,
        "mechs_read": [],
        "cohorts": defaultdict(list),
        "rows": {kind: [] for kind in KINDS},
        "shape": {},
        "errors": {},
        "sources": [],
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
        matched = 0
        for kind, setting_name in KINDS.items():
            pattern = settings.get(setting_name, DEFAULT_GLOBS[kind])
            for path in sorted(root.glob(pattern)):
                matched += 1
                cohort = path.parent.name
                try:
                    content = path.read_bytes()
                    header, template, data = read_template(path, content=content)
                    digest = hashlib.sha256(content).hexdigest()
                except (AggregateError, OSError, UnicodeError) as exc:
                    result["errors"][f"{key}:{cohort}:{kind}"] = str(exc)[:200]
                    continue
                result["sources"].append({
                    "mech": key, "cohort": cohort, "kind": kind,
                    "path": str(path), "sha256": digest, "rows": len(data),
                })
                read.append(
                    (kind, key, cohort, path.relative_to(root), header, template, data)
                )

        if not matched:
            result["errors"][key] = "enabled proposer has no matching proposal templates"

    for kind in KINDS:
        shapes = Counter(
            (header, template)
            for entry_kind, _, _, _, header, template, _ in read
            if entry_kind == kind
        )
        if not shapes:
            continue
        ranked = shapes.most_common()
        if len(ranked) > 1 and ranked[0][1] * 2 <= sum(shapes.values()):
            # No majority means no basis for calling either one the deviation.
            result["errors"][f"{kind}:shape"] = (
                f"{len(ranked)} ROBOT template shapes have no strict majority (possibly equally common); "
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


def find_kind_collisions(data: dict) -> dict[str, list[str]]:
    """A proposed identifier cannot declare both a class and a property."""
    ids = {kind: {_identity(row)[0] for row in rows}
           for kind, rows in data["rows"].items()}
    return {identifier: sorted(KINDS) for identifier in sorted(
        ids["classes"] & ids["properties"]
    )}


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

    variants: dict[tuple[str, str], set[tuple]] = defaultdict(set)
    for row in rows:
        variants[_identity(row)].add(tuple(sorted(
            (key, value) for key, value in row.items() if not key.startswith("_")
        )))
    return {
        "conflicting_rows": {
            f"{identity[0]} {identity[1]}": sorted(where[identity])
            for identity, values in sorted(variants.items()) if len(values) > 1
        },
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
            if len(sources) > 1 and len(variants[(proposed_id, label)]) == 1
        },
    }


def merged_rows(rows: list[dict], header: tuple[str, ...]) -> list[dict]:
    """Deduplicate complete rows only; preserve disagreements for review."""
    seen = {tuple(row.get(name, "") for name in header) for row in rows}
    return [dict(zip(header, values)) for values in sorted(seen)]


def write_aggregate(data: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for kind in KINDS:
        path = out_dir / f"metpo_fleet_aggregate_{kind}_robot.tsv"
        shape = data["shape"].get(kind)
        if not shape or not data["rows"][kind]:
            # A failed rerun must not leave a previous successful template
            # masquerading as this run's output. Only remove our own filename.
            path.unlink(missing_ok=True)
            continue
        header, template = shape["header"], shape["template"]
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
        for identity, sources in found.get("conflicting_rows", {}).items():
            clean = False
            lines.append(f"  ROW CONTENT DIFFERS  {kind}  {identity}: " + ", ".join(sources))
    for identifier in find_kind_collisions(data):
        clean = False
        lines.append(f"  CLASS/PROPERTY ID REUSE  {identifier}")
    if clean:
        lines.append("  none in the rows read (release reconciliation is separate)")

    lines.append("")
    lines.append("Coverage")
    declaring = ", ".join(data["mechs_declaring"]) or "none"
    lines.append(f"  declared by the manifest: {declaring}")
    read = ", ".join(data["mechs_read"]) or "none"
    lines.append(f"  read: {read}")
    for key, declaration in data.get("declarations", {}).items():
        if declaration["status"] != "enabled":
            reason = declaration["reason"] or "no reason recorded"
            lines.append(f"  excluded: {key} ({declaration['status']}): {reason}")
    for name, error in data["errors"].items():
        lines.append(f"  {name}: ERROR: {error}")
    if data["errors"]:
        lines.append(
            "  INCOMPLETE: some proposal inputs were omitted, so the "
            "collision report is a lower bound"
        )
    return "\n".join(lines)


def has_conflicts(collisions: dict) -> bool:
    return any(
        found.get("id_means_two_things") or found.get("label_has_two_ids")
        or found.get("conflicting_rows")
        for found in collisions.values()
    )


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
    kind_collisions = find_kind_collisions(data)
    blocked = bool(has_conflicts(collisions) or kind_collisions or data["errors"])
    written: list[Path] = []
    report = {
            "snapshot_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(
                timespec="seconds"),
            "mechs_declaring": data["mechs_declaring"],
            "declarations": data["declarations"],
            "mechs_read": data["mechs_read"],
            "cohorts": data["cohorts"],
            "counts": {k: len(v) for k, v in data["rows"].items()},
            "collisions": collisions,
            "kind_collisions": kind_collisions,
            "errors": data["errors"],
            "sources": data["sources"],
            "merge_status": "blocked" if blocked else "clean",
            "submission_status": "not_assessed",
    }
    if not args.check:
        try:
            # Invalidate the old verdict before touching its templates. If a
            # later output write fails, stale "clean" metadata must not certify
            # a partial new bundle. A completed report is written last.
            for name in ("metpo_fleet_aggregate_report.json", "proposal.md"):
                (args.out / name).unlink(missing_ok=True)
            written = write_aggregate(data, args.out)
            narrative = args.out / "proposal.md"
            narrative.write_text(
                "# Merged Mech METPO proposal — review draft\n\n"
                + f"Snapshot: {report['snapshot_utc']}\n\n"
                + f"Mechanical merge: **{report['merge_status']}**. "
                + "Submission readiness: **not assessed**.\n\n```text\n"
                + render(data, collisions) + "\n```\n\n"
                + "Before submission, reconcile every cohort with the current METPO release "
                + "and pending kg-microbe proposals; resolve reused IDs and labels, verify "
                + "parents/domain/range, review definitions and citations, and run ROBOT "
                + "template plus ELK reasoning. Cohort versions are additive unless their "
                + "curated lifecycle says otherwise.\n\n"
                + "`metpo_fleet_aggregate_report.json` records source paths and SHA-256 "
                + "digests. Consult each source cohort's `proposal.md` and optional "
                + "`metpo_proposal_mappings.sssom.tsv` for narrative and mapping evidence; "
                + "these are not converted to ontology assertions by this merger.\n",
                encoding="utf-8",
            )
            written.extend([narrative, args.out / "metpo_fleet_aggregate_report.json"])
            report["written"] = [str(path) for path in written]
            written[-1].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
        except OSError as exc:
            print(f"aggregate output failed: {exc}", file=sys.stderr)
            return 2
    report["written"] = [str(path) for path in written]
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(data, collisions))
        for path in written:
            print(f"\nWrote {path}")

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
