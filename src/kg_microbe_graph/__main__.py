"""`kg-microbe-graph coverage` -- causal-graph coverage for one Mech or the fleet."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_graph.coverage import (
    CAPABILITY,
    CoverageConfig,
    CoverageConfigError,
    CoverageError,
    CoverageReport,
    collect,
)

CLAW_ROOT = Path(__file__).resolve().parents[2]


def _revision(root: Path) -> str:
    """Which commit was read, for stderr: a local checkout can lag origin.

    Best effort and never part of the JSON. A snapshot extracted with
    `git archive` has no repository, and that is a legitimate thing to read.
    """
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "not a git checkout (a snapshot?)"
    return f"HEAD {head}" + (", with uncommitted changes" if dirty else "")


def _summary_row(key: str, report: CoverageReport) -> str:
    data = report.as_dict()
    coverage = data["coverage"]

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{100 * value:5.1f}%"

    mechanistic = coverage["with_mechanistic_graph"]
    return (
        f"{key:<20} {data['records']:>8} {data['exempt']['records']:>7} "
        f"{coverage['eligible']:>8} {coverage['with_graph']:>8} "
        f"{pct(coverage['fraction_with_graph']):>7} "
        f"{'-' if mechanistic is None else mechanistic:>8} "
        f"{pct(coverage['fraction_mechanistic']):>7} "
        f"{coverage['edgeless_only']:>8} {data['graphs']['total']:>7} "
        f"{data['structure']['graphs_with_findings']:>8}"
    )


SUMMARY_HEADER = (
    f"{'mech':<20} {'records':>8} {'exempt':>7} {'eligible':>8} {'w/graph':>8} "
    f"{'':>7} {'mechan.':>8} {'':>7} {'edgeless':>8} {'graphs':>7} {'flagged':>8}"
)


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-graph",
        description=(
            "Report what fraction of a Mech's records carry a causal graph, which "
            "records are declared not to need one, how many graphs each record "
            "has, and what the graphs' structure looks like. Deterministic JSON."
        ),
    )
    parser.add_argument("command", choices=["coverage"])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--mech", choices=sorted(manifest.mechs))
    target.add_argument(
        "--all", action="store_true",
        help="every Mech that enables the capability; the rest are named with their reason",
    )
    parser.add_argument(
        "--root", type=Path,
        help="read this directory instead of the configured checkout, e.g. a "
             "`git archive origin/main` snapshot (single --mech only)",
    )
    parser.add_argument(
        "--sample", type=int,
        help="read only the first N records, in sorted order, for a large corpus",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="print a table instead of JSON",
    )
    args = parser.parse_args(argv)
    if args.root is not None and args.all:
        parser.error("--root names one checkout; use it with --mech")

    keys = list(manifest.mechs) if args.all else [args.mech]
    reports: dict[str, CoverageReport] = {}
    not_enabled: dict[str, str] = {}
    unavailable: dict[str, str] = {}

    for key in keys:
        mech = manifest.mechs[key]
        capability = mech.capabilities.get(CAPABILITY)
        if capability is None or not capability.is_enabled:
            status = capability.status if capability is not None else "undeclared"
            reason = getattr(capability, "reason", "") or "not declared in the manifest"
            not_enabled[key] = f"{status}: {reason}"
            continue
        try:
            config = CoverageConfig.from_settings(capability.settings)
        except CoverageConfigError as exc:
            print(f"{key}: {CAPABILITY} is declared incorrectly: {exc}", file=sys.stderr)
            return 2
        try:
            root = args.root or resolve_mech_root(key, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            unavailable[key] = str(exc)
            continue
        print(f"{key}: reading {root.name} ({_revision(root)})", file=sys.stderr)
        try:
            reports[key] = collect(
                key, root, list(mech.record_globs), config, sample=args.sample
            )
        except CoverageError as exc:
            unavailable[key] = str(exc)
            continue
        print(f"{key}: {reports[key].parser_note()}", file=sys.stderr)

    if not args.all:
        key = keys[0]
        if key in not_enabled:
            print(f"{key} reports no causal-graph coverage: {not_enabled[key]}")
            return 0
        if key in unavailable:
            print(unavailable[key], file=sys.stderr)
            return 2

    if args.summary:
        print(SUMMARY_HEADER)
        for key, report in reports.items():
            print(_summary_row(key, report))
        for key, why in not_enabled.items():
            print(f"{key:<20} {why}")
        for key, why in unavailable.items():
            print(f"{key:<20} UNAVAILABLE: {why}")
    elif args.all:
        payload: dict[str, Any] = {
            "reports": {key: report.as_dict() for key, report in reports.items()},
            "not_enabled": dict(sorted(not_enabled.items())),
            "unavailable": dict(sorted(unavailable.items())),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(reports[keys[0]].to_json(), end="")

    # A record that could not be read or did not have the declared shape is
    # excluded from every count above, and a fleet run that skipped a Mech is
    # not the fleet: either way the numbers are incomplete, and say so.
    incomplete = bool(unavailable) or any(
        report.unreadable or report.malformed for report in reports.values()
    )
    return 1 if incomplete else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
