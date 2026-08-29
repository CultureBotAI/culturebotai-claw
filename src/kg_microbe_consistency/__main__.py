"""Report cross-record disagreement in a Mech corpus. Read-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .proposals import proposals_from_groups, render_markdown
from .scanner import (
    COMPARED_FIELDS,
    EXTRACTORS,
    ScannerError,
    build_report,
    scan_groups,
)


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
    parser.add_argument(
        "--shape",
        default="record-per-file",
        choices=sorted(EXTRACTORS),
        help=(
            "How records sit in the corpus. `record-per-file` suits "
            "MediaIngredientMech's ingredient YAMLs; `embedded-ingredients` "
            "reads CultureMech media, where each document holds many "
            "independently-grounded ingredients."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--propose",
        action="store_true",
        help=(
            "Also generate correct-by-analogy proposals. Read-only: a proposal "
            "is a document for a curator, never applied."
        ),
    )
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
        records, skipped, groups = scan_groups(
            Path(args.corpus), args.glob, args.shape
        )
    except ScannerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = build_report(Path(args.corpus), records, skipped, groups)

    if args.propose:
        proposed, surfaced = proposals_from_groups(groups)
        payload = {
            "root": str(args.corpus),
            "records_scanned": len(records),
            "files_skipped": skipped,
            "proposals": [item.as_dict() for item in proposed],
            "surfaced_without_proposal": [g.as_dict() for g in surfaced],
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(render_markdown(payload))
    elif args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"Scanned {report['records_scanned']} records; "
            f"{report['groups_matched']} matched group(s); "
            f"{report['groups_disagreeing']} disagree."
        )
        if report["groups_involving_llm_assisted"]:
            print(
                f"{report['groups_involving_llm_assisted']} of those involve an "
                f"LLM_ASSISTED grounding -- the class id-label correspondence "
                f"structurally cannot catch."
            )
        if report["files_skipped"]:
            print(
                f"Skipped {report['files_skipped']} file(s) with no usable "
                f"record shape. A corpus where everything is skipped is not a "
                f"clean corpus -- check --corpus and --glob.",
                file=sys.stderr,
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
