"""`kg-microbe-corpus report` -- one comparable corpus report per Mech."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_corpus.statistics import CorpusError, collect
from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root

CLAW_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-corpus",
        description=(
            "Report one Mech's corpus in the shape every Mech reports: record "
            "and byte counts per declared glob, and how each declared field is "
            "populated. Deterministic JSON, so two releases can be diffed."
        ),
    )
    parser.add_argument("command", choices=["report"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument(
        "--sample",
        type=int,
        help="read only the first N records, in sorted order, for a large corpus",
    )
    args = parser.parse_args(argv)

    mech = manifest.mechs[args.mech]
    capability = mech.capabilities.get("corpus_statistics")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} reports no corpus statistics: {reason}")
        return 0

    try:
        root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        report = collect(
            args.mech,
            root,
            list(mech.record_globs),
            capability.settings.get("fields", ()),
            sample=args.sample,
        )
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # stderr, so stdout stays pure JSON for piping, and the artifact stays
    # machine-independent while a slow run still explains itself (#233).
    print(report.parser_note(), file=sys.stderr)
    print(report.to_json(), end="")
    # An unreadable record is a finding, not a footnote: it is excluded from
    # every count above, so a report that stayed silent about it would
    # understate the corpus without saying so.
    return 1 if report.unreadable else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
