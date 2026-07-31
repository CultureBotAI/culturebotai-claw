"""CLI: scaffold and validate append-only history records.

    python -m kg_microbe_history new --kind record --slug <SLUG> ...
    python -m kg_microbe_history validate <path-or-dir>

`new` prints the bare record path as its final stdout line so callers can capture
it; everything human-facing goes to stderr.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

from .scaffold import (
    ACTOR_TYPES,
    EVENT_TYPES,
    KIND_DIRS,
    OUTCOMES,
    build_record,
    new_history_path,
    write_record,
)

DEFAULT_SCHEMA_REL = "shared/history/history.yaml"


def _add_new_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--kind", required=True, choices=sorted(KIND_DIRS))
    ap.add_argument("--slug", default="", help="target identifier / directory name")
    ap.add_argument(
        "--path",
        default="",
        help="repo-relative path to the target; required for --kind other",
    )
    ap.add_argument(
        "--target-root",
        default="",
        help="directory the target lives in, used to derive --path from --slug",
    )
    ap.add_argument("--event", default="EDIT", choices=EVENT_TYPES)
    ap.add_argument("--outcome", default="changed", choices=OUTCOMES)
    ap.add_argument("--summary", required=True, help="one short line")
    ap.add_argument(
        "--details",
        default="",
        help="the substance; if omitted a TODO placeholder is written for you to edit",
    )
    ap.add_argument("--sections", default="", help="comma-separated")
    ap.add_argument("--actor-name", default="claude-code")
    ap.add_argument("--actor-type", default="ai_agent", choices=ACTOR_TYPES)
    ap.add_argument("--model", default="")
    ap.add_argument("--agent-tool", default="")
    ap.add_argument("--agent-version", default="")
    ap.add_argument("--issue", action="append", default=[])
    ap.add_argument("--pr", action="append", default=[])
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--history-root", default="history")
    ap.add_argument("--force", action="store_true")


def cmd_new(args: argparse.Namespace) -> int:
    target_path = args.path
    if not target_path:
        if args.kind == "other":
            print(
                "error: --path is required for --kind other (the target cannot be "
                "derived from a slug)",
                file=sys.stderr,
            )
            return 2
        if not args.slug:
            print("error: provide --slug or --path", file=sys.stderr)
            return 2
        root = args.target_root.rstrip("/")
        target_path = f"{root}/{args.slug}.yaml" if root else f"{args.slug}.yaml"

    history_root = Path(args.history_root)
    path, session_id, timestamp = new_history_path(
        history_root, args.kind, args.slug or Path(target_path).stem, args.actor_name
    )

    details = args.details or (
        "TODO: replace this placeholder before committing.\n"
        "What was done, what evidence or provider was used, how it was validated, "
        "and anything deliberately left undone."
    )
    try:
        record = build_record(
            kind=args.kind,
            slug=args.slug,
            target_path=target_path,
            session_id=session_id,
            timestamp=timestamp,
            summary=args.summary,
            details=details,
            event=args.event,
            outcome=args.outcome,
            sections=[s.strip() for s in args.sections.split(",") if s.strip()],
            actor_name=args.actor_name,
            actor_type=args.actor_type,
            model=args.model or None,
            agent_tool=args.agent_tool or None,
            agent_version=args.agent_version or None,
            issues=args.issue,
            prs=args.pr,
            urls=args.url,
        )
        written = write_record(path, record, force=args.force)
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote history record: {written}", file=sys.stderr)
    if not args.details:
        print(
            "Next: replace the 'details' placeholder, then run: "
            f"just validate-history {written}",
            file=sys.stderr,
        )
    print(written)  # machine-capturable final stdout line
    return 0


def _iter_records(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(p for p in target.rglob("*.yaml"))
    return [target]


def cmd_validate(args: argparse.Namespace) -> int:
    schema = Path(args.schema)
    if not schema.is_file():
        print(
            f"error: history schema not found at '{schema}'. Pass --schema, or set "
            "CLAW_ROOT so the default resolves.",
            file=sys.stderr,
        )
        return 2

    records = _iter_records(Path(args.target))
    if not records:
        print(f"No history records found under {args.target}", file=sys.stderr)
        return 0

    # Structural pre-check first: it produces far clearer errors than linkml for
    # the mistakes people actually make (missing details, empty events).
    failures = 0
    for record_path in records:
        try:
            data = yaml.safe_load(record_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(f"FAIL {record_path}: unparseable YAML: {exc}", file=sys.stderr)
            failures += 1
            continue
        if not isinstance(data, dict):
            print(f"FAIL {record_path}: top level is not a mapping", file=sys.stderr)
            failures += 1
            continue
        events = data.get("events") or []
        if not events:
            print(f"FAIL {record_path}: events must have at least one entry", file=sys.stderr)
            failures += 1
            continue
        if any(not (e.get("details") or "").strip() for e in events):
            print(f"FAIL {record_path}: every event needs a non-empty details", file=sys.stderr)
            failures += 1
            continue
        actors = (data.get("session") or {}).get("actors") or []
        if not actors:
            print(f"FAIL {record_path}: session.actors must have at least one entry", file=sys.stderr)
            failures += 1

    if failures:
        print(f"{failures} record(s) failed structural checks", file=sys.stderr)
        return 1

    if args.structural_only:
        print(f"OK (structural): {len(records)} record(s)", file=sys.stderr)
        return 0

    cmd = [
        "linkml-validate",
        "--schema",
        str(schema),
        "--target-class",
        "HistoryRecord",
        *[str(p) for p in records],
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print(
            "error: linkml-validate not on PATH. Install it, or pass "
            "--structural-only to run just the built-in checks.",
            file=sys.stderr,
        )
        return 2
    if proc.stdout.strip():
        print(proc.stdout.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        if proc.stderr.strip():
            print(proc.stderr.rstrip(), file=sys.stderr)
        return proc.returncode
    print(f"OK: {len(records)} record(s) valid", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kg_microbe_history", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    ap_new = sub.add_parser("new", help="scaffold a new record")
    _add_new_args(ap_new)
    ap_new.set_defaults(func=cmd_new)

    ap_val = sub.add_parser("validate", help="validate a record or directory")
    ap_val.add_argument("target", help="record path or directory (e.g. history/)")
    ap_val.add_argument("--schema", default=DEFAULT_SCHEMA_REL)
    ap_val.add_argument(
        "--structural-only",
        action="store_true",
        help="skip linkml-validate; run only the built-in checks",
    )
    ap_val.set_defaults(func=cmd_validate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
