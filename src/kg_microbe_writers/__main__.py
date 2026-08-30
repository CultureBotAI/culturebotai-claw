"""`kg-microbe-writers audit` -- one Mech's YAML-writing scripts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_writers.audit import WriterProfile, as_tsv, audit

CLAW_ROOT = Path(__file__).resolve().parents[2]


def profile_for(settings) -> WriterProfile:
    return WriterProfile(
        search_dirs=tuple(settings["search_dirs"]),
        exclude=tuple(settings.get("exclude", ())),
        save_helpers=tuple(settings.get("save_helpers", ())),
        validators=tuple(settings.get("validators", ())),
        curation_markers=tuple(settings.get("curation_markers", ())),
    )


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-writers",
        description=(
            "List every script that writes a YAML record, and what it declares "
            "about doing it: whether it appends curation history, offers a "
            "dry-run or opt-in write, validates first, and is wired into just. "
            "A writer is detected five ways -- yaml.dump, a dump written to a "
            "path, the Mech's own save helper, an in-place edit of a globbed "
            "YAML, and a write to a path built from a .yaml name."
        ),
    )
    parser.add_argument("command", choices=["audit"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument(
        "--why",
        action="store_true",
        help="append the evidence that made each row a writer",
    )
    args = parser.parse_args(argv)

    capability = manifest.mechs[args.mech].capabilities.get("writer_audit")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} declares no writer audit: {reason}")
        return 0

    try:
        root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    rows = audit(root, profile_for(capability.settings))
    print(as_tsv(rows, target_kind=False), end="")
    if args.why:
        for row in rows:
            print(f"# {row.path}: {', '.join(row.evidence.reasons())}", file=sys.stderr)
    print(f"{args.mech}: {len(rows)} writers", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
