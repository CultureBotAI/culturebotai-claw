#!/usr/bin/env python3
"""Print one line of verified Mech progress from the tracker's saved evidence."""
from __future__ import annotations

import argparse
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mech_progress_publish import read_remote

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_progress import ProgressError, read_json, validate_bundle

MAX_AGE_SECONDS = 15 * 60
FUTURE_TOLERANCE_SECONDS = 60


def _quantity(count: int, singular: str) -> str:
    return f"{count} {singular}{'' if count == 1 else 's'}"


def format_summary(snapshot: dict[str, Any]) -> str:
    """Format an already validated snapshot; never derive goals from PR counts."""
    totals = snapshot["totals"]
    states = f"{totals['merged_prs']} merged, {totals['open_prs']} open"
    if totals["closed_prs"]:
        states += f", {totals['closed_prs']} closed without merge"
    return (
        f"{_quantity(len(snapshot['repositories']), 'Mech')}, "
        f"{_quantity(totals['unique_prs'], 'PR')} ({states}), "
        f"{_quantity(totals['completed_goals'], 'completed goal')}, "
        f"{_quantity(totals['completed_cycles'], 'completed cycle')}"
    )


def freshness_warnings(snapshot: dict[str, Any], now: datetime) -> list[str]:
    """Check collection age and underlying observations independently."""
    if now.utcoffset() is None:
        raise ProgressError("current time must include a timezone")
    warnings = []

    def age(timestamp: str) -> float:
        return (now - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()

    generated_at = snapshot["generated_at"]
    snapshot_age = age(generated_at)
    if snapshot_age > MAX_AGE_SECONDS:
        warnings.append(f"snapshot is older than 15 minutes (generated {generated_at})")
    elif snapshot_age < -FUTURE_TOLERANCE_SECONDS:
        warnings.append(f"snapshot timestamp is in the future (generated {generated_at})")

    stale, unobserved, future = [], [], []
    for row in snapshot["repositories"]:
        observed = row.get("last_observed_at")
        if observed is None:
            unobserved.append(row["name"])
        elif age(observed) > MAX_AGE_SECONDS:
            stale.append(row["name"])
        elif age(observed) < -FUTURE_TOLERANCE_SECONDS:
            future.append(row["name"])
    for label, names in (
        ("Mech observations older than 15 minutes", stale),
        ("Mechs without observations", unobserved),
        ("Mech observations dated in the future", future),
    ):
        if names:
            warnings.append(f"{label}: {', '.join(names)}")
    return warnings


def main(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--bundle", type=Path, default=Path("workspace/progress-publisher/bundle.json"),
        help="local atomic tracker bundle (default: workspace/progress-publisher/bundle.json)",
    )
    source.add_argument(
        "--published", action="store_true",
        help="read the pinned GitHub data branch through gh instead of local state",
    )
    parser.add_argument(
        "--manifest", type=Path,
        help="producer's fleet manifest (default: bundle-adjacent fleet.yaml when present, otherwise packaged fleet)",
    )
    args = parser.parse_args(argv)
    try:
        adjacent_manifest = args.bundle.parent / "fleet.yaml"
        manifest_path = args.manifest
        if manifest_path is None:
            try:
                adjacent_manifest.lstat()
            except FileNotFoundError:
                pass
            else:
                manifest_path = adjacent_manifest
        if manifest_path is not None and not stat.S_ISREG(manifest_path.lstat().st_mode):
            raise ProgressError("pinned manifest must be a regular file")
        manifest = load_fleet_manifest(manifest_path)
        if args.published:
            _, bundle = read_remote(manifest=manifest)
            if bundle is None:
                raise ProgressError("no published progress bundle exists")
        else:
            bundle = read_json(args.bundle)
        history, snapshot = bundle["history"], bundle["snapshot"]
        if not isinstance(history, dict) or not isinstance(snapshot, dict):
            raise ProgressError("bundle must contain history and snapshot objects")
        validate_bundle(history, snapshot, manifest)
        warnings = freshness_warnings(snapshot, now or datetime.now(timezone.utc))
        summary = format_summary(snapshot)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Progress unavailable: {error}", file=sys.stderr)
        return 1

    print(summary)
    for warning in warnings:
        print(f"Warning: {warning}. Counts are last verified, not fully current.", file=sys.stderr)
    return 3 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
