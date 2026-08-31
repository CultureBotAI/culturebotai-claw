"""`kg-microbe-source-queue check` -- judge one Mech's data-source queue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_source_queue.contract import (
    SourceQueueProfile,
    check_queue,
    summarise,
)

CLAW_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-source-queue",
        description=(
            "Check a Mech's curation/source_queue.tsv: the eleven columns both "
            "existing queues share, one spelling for each licence class, and the "
            "adoption gate -- an ADOPTED source must have terms someone checked "
            "and the date they checked them. A candidate that intends to seed "
            "before its licence is read is not a finding; that is what "
            "verification is for."
        ),
    )
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)

    capability = manifest.mechs[args.mech].capabilities.get("source_queue")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} keeps no source queue: {reason}")
        return 0

    path = args.path
    if path is None:
        try:
            root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        path = root / capability.settings["queue_path"]
    if not path.is_file():
        print(f"{args.mech}: no source queue at {path}", file=sys.stderr)
        return 2

    profile = SourceQueueProfile(
        extensions=tuple(capability.settings.get("extensions", ())),
        required_when_adopted=tuple(
            capability.settings.get("required_when_adopted", ())
        ),
    )
    findings = check_queue(path, profile)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    print(f"{args.mech}: {summarise(findings) or 'clean'}")
    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
