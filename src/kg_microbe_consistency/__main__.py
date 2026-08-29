"""Report cross-record disagreement in a Mech corpus. Read-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .scanner import COMPARED_FIELDS, ScannerError, scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kg-microbe-consistency",
        description=__doc__,
    )
    parser.add_argument(
        "--corpus", required=True,
        help="Directory of record YAMLs, e.g. <MIM>/data/ingredients.",
    )
    parser.add_argument("--glob", default="**/*.yaml")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--fail-on-findings", action="store_true",
        help=(
            "Exit 1 when any group disagrees. Off by default: a disagreement is "
            "a question for a curator, and several are legitimate distinctions "
            "rather than defects."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = scan(Path(args.corpus), args.glob)
    except ScannerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"Scanned {report['records_scanned']} records; "
            f"{report['groups_matched']} matched group(s); "
            f"{report['groups_disagreeing']} disagree."
        )
        print(f"Compared fields: {', '.join(COMPARED_FIELDS)}\n")
        for finding in report["findings"]:
            print(f"[{finding['matched_on']}] {finding['key']}")
            for record in finding["records"]:
                print(f"    {record['preferred_term']!r} — {record['identifier']}")
            for disagreement in finding["disagreements"]:
                print(f"  -> {disagreement['field']} differs:")
                for value, paths in disagreement["values"].items():
                    print(f"       {value}  ({len(paths)} record(s))")
            print()

    if args.fail_on_findings and report["groups_disagreeing"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
