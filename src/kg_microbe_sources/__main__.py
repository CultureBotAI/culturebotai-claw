"""`kg-microbe-sources check` -- validate a Mech's source catalogue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_sources.catalogue import CatalogueError, load_blocks, validate

CLAW_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-sources",
        description=(
            "Validate a Mech's download.yaml source catalogue: every source "
            "names itself, its licence and its seeder, and every file of a "
            "multi-file source says which file it is."
        ),
    )
    parser.add_argument("command", choices=["check"])
    parser.add_argument(
        "--mech",
        required=True,
        choices=sorted(manifest.mechs),
        help="which Mech's catalogue to read",
    )
    parser.add_argument(
        "--seeder-glob",
        default="seed_*.py",
        help=(
            "how this repository names its seeder scripts, for the "
            "unreferenced-seeder sweep (default: %(default)s)"
        ),
    )
    args = parser.parse_args(argv)

    # A Mech without a catalogue is a recorded decision, not a missing file.
    # Reporting "No such file or directory" would read as breakage and say
    # nothing about why, where the manifest already carries the reason.
    capability = manifest.mechs[args.mech].capabilities.get("source_catalogue")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} declares no source catalogue: {reason}")
        return 0

    try:
        root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    catalogue = root / "download.yaml"
    try:
        blocks = load_blocks(catalogue)
    except CatalogueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    report = validate(
        blocks, seeder_dir=root / "scripts", seeder_glob=args.seeder_glob
    )

    statuses: dict[str, int] = {}
    for block in blocks:
        status = block.get("status") if isinstance(block, dict) else None
        if isinstance(status, str) and status:
            statuses[status] = statuses.get(status, 0) + 1
    summary = ", ".join(f"{n} {s}" for s, n in sorted(statuses.items()))
    print(f"{args.mech}/download.yaml: {len(blocks)} block(s) ({summary})")

    for finding in report.warnings:
        print(f"  WARN:  {finding}")
    for finding in report.errors:
        print(f"  ERROR: {finding}")

    if report.errors:
        print(f"\n{len(report.errors)} error(s).")
        return 1
    print(f"\nOK ({len(report.warnings)} warning(s)).")
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
