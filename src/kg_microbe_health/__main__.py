"""`kg-microbe-health report` -- what one repository costs to carry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_health.repository import (
    DEFAULT_LARGE_FILE_BYTES,
    DEFAULT_LARGEST,
    HealthError,
    measure,
)

CLAW_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-health",
        description=(
            "Report a repository's tracked weight: how many files, how large, "
            "where it sits by top-level directory and by extension, and which "
            "files dominate. Measured from git, so the answer is the same on "
            "any machine and in CI."
        ),
    )
    parser.add_argument("command", choices=["report"])
    parser.add_argument(
        "--mech",
        required=True,
        choices=sorted(manifest.mechs) + ["claw"],
        help="a Mech, or `claw` for this repository",
    )
    parser.add_argument("--largest", type=int, default=DEFAULT_LARGEST)
    parser.add_argument(
        "--large-file-bytes", type=int, default=DEFAULT_LARGE_FILE_BYTES
    )
    args = parser.parse_args(argv)

    if args.mech == "claw":
        root = CLAW_ROOT
    else:
        try:
            root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    try:
        report = measure(
            args.mech,
            root,
            largest=args.largest,
            large_file_bytes=args.large_file_bytes,
        )
    except HealthError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(report.to_json(), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
