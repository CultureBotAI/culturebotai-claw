"""`kg-microbe-sssom check` -- judge one Mech's SSSOM mapping files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_sssom.contract import SsssomProfile, check_file, summarise

CLAW_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-sssom",
        description=(
            "Check a Mech's SSSOM mapping files against the contract the fleet "
            "already keeps: the eight columns every published file carries, a "
            "curie_map that covers the prefixes actually used, columns that are "
            "either SSSOM slots or declared extensions, confidences in 0..1, and "
            "no mapping asserted twice. Rows that record no match are expected "
            "to have no object and are not findings."
        ),
    )
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument(
        "--path",
        type=Path,
        action="append",
        help="check this file instead of the manifest's globs (repeatable)",
    )
    args = parser.parse_args(argv)

    capability = manifest.mechs[args.mech].capabilities.get("sssom_export")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} publishes no SSSOM: {reason}")
        return 0

    paths = list(args.path or [])
    if not paths:
        try:
            root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        for pattern in capability.settings["mapping_globs"]:
            paths.extend(sorted(root.glob(pattern)))

    if not paths:
        print(f"{args.mech}: no SSSOM files matched", file=sys.stderr)
        return 2

    profile = SsssomProfile(extensions=tuple(capability.settings.get("extensions", ())))
    total = 0
    for path in paths:
        findings = check_file(path, profile)
        total += len(findings)
        counts = summarise(findings)
        print(f"{path}: {counts or 'clean'}")
        for finding in findings[:20]:
            print(f"  {finding}", file=sys.stderr)
        if len(findings) > 20:
            print(f"  ... and {len(findings) - 20} more", file=sys.stderr)
    print(f"{args.mech}: {len(paths)} file(s), {total} finding(s)")
    return 1 if total else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
