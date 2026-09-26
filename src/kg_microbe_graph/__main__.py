"""`kg-microbe-graph coverage` -- causal-graph coverage for one Mech or the fleet."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, claw_root, resolve_mech_root
from kg_microbe_graph.coverage import (
    CAPABILITY,
    CoverageConfig,
    CoverageConfigError,
    CoverageError,
    CoverageReport,
    collect,
)

CLAW_ROOT = claw_root()
SNAPSHOT = "not a git checkout (a snapshot?)"
MAX_NAMED = 5


def _git(root: Path, *args: str, timeout: int) -> str:
    """Read-only git: no optional locks, no fsmonitor, no inherited repo env.

    A plain `git status` refreshes the index and so rewrites `.git/index` in
    the Mech checkout -- a write from a tool that promises none (#472).
    """
    env = {
        key: value for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}
    }
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
        capture_output=True, text=True, timeout=timeout, check=True, env=env,
    ).stdout.strip()


def _glob_directory(pattern: str) -> str:
    """The fixed directory a record glob starts from: `data/traits` for
    `data/traits/**/*.yaml`."""
    fixed = []
    for part in Path(pattern).parts:
        if any(char in part for char in "*?["):
            break
        fixed.append(part)
    if fixed and fixed[-1] == Path(pattern).name:
        fixed.pop()
    return "/".join(fixed) or "."


def _revision(root: Path, globs: Sequence[str]) -> str:
    """Which commit was read, for stderr: a local checkout can lag origin.

    Best effort and never part of the JSON. Answered only when `root` is
    itself the top of a git checkout. A snapshot extracted with `git archive`
    has no repository of its own, and asking git inside one answers for
    whatever repository encloses it -- claw's, when the snapshot sits in
    claw's workspace (#472).
    """
    try:
        top = _git(root, "rev-parse", "--show-toplevel", timeout=30)
        if Path(top).resolve() != Path(root).resolve():
            return SNAPSHOT
        head = _git(root, "rev-parse", "--short", "HEAD", timeout=30)
        # Untracked files count: a new record under the globs is read and
        # counted, so a tree holding one is not the commit named above.
        changed = _git(
            root, "status", "--porcelain", "--untracked-files=normal", "--",
            *sorted({_glob_directory(pattern) for pattern in globs}),
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return "revision unknown: git timed out"
    except (OSError, subprocess.SubprocessError):
        return SNAPSHOT
    return f"HEAD {head}" + (", with uncommitted changes under the record globs" if changed else "")


def _summary_row(key: str, report: CoverageReport) -> str:
    data = report.as_dict()
    coverage = data["coverage"]

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{100 * value:5.1f}%"

    mechanistic = coverage["with_mechanistic_graph"]
    # A sampled row is a different corpus; mark it where the number is read.
    records = f"{data['records']}{'*' if data['sampled'] else ''}"
    return (
        f"{key:<20} {records:>8} {data['exempt']['records']:>7} "
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


def _excluded(key: str, report: CoverageReport) -> str | None:
    """One stderr line naming what a report left out, or None."""
    left_out = report.excluded
    if not left_out:
        return None
    named = "; ".join(left_out[:MAX_NAMED])
    more = f"; and {len(left_out) - MAX_NAMED} more" if len(left_out) > MAX_NAMED else ""
    return (
        f"{key}: excluded {len(report.unreadable)} unreadable, {len(report.empty)} "
        f"empty and {len(report.malformed)} malformed file(s): {named}{more}"
    )


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


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
        "--sample", type=_positive,
        help="read only the first N records, in sorted order, for a large corpus",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="print a table instead of JSON",
    )
    parser.add_argument(
        "--jobs", type=_positive, default=min(8, os.cpu_count() or 1),
        help="processes to parse a large corpus with (default: up to 8); the "
             "report is identical for any value",
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
        globs = list(mech.record_globs)
        print(f"{key}: reading {root.name} ({_revision(root, globs)})", file=sys.stderr)
        try:
            reports[key] = collect(
                key, root, globs, config, sample=args.sample, jobs=args.jobs
            )
        except CoverageError as exc:
            unavailable[key] = str(exc)
            continue
        print(f"{key}: {reports[key].parser_note()}", file=sys.stderr)
        excluded = _excluded(key, reports[key])
        if excluded:
            print(excluded, file=sys.stderr)

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
        if args.sample is not None:
            print(f"* sampled: the first {args.sample} records only, not the corpus")
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
    incomplete = bool(unavailable) or any(report.excluded for report in reports.values())
    return 1 if incomplete else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
