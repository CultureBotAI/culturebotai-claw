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
from importlib.resources import files
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


def _default_schema_path() -> str:
    """Return the claw-authoritative schema packaged with governance."""

    return str(
        files("kg_microbe_governance").joinpath("artifacts/schema/history.yaml")
    )


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


# Kinds whose target is reliably a YAML file, so a path can be derived from a
# slug. Everything else (mappings are .sssom.tsv, reports .md, infrastructure a
# justfile or workflow) must say where its target actually lives — records are
# append-only, so a guessed extension is permanently wrong (#30).
YAML_KINDS = {"record", "schema"}


def cmd_new(args: argparse.Namespace) -> int:
    target_path = args.path
    if target_path and args.target_root:
        print(
            "error: --target-root and --path are mutually exclusive; --path already "
            "gives the full location",
            file=sys.stderr,
        )
        return 2
    if not target_path:
        if args.kind not in YAML_KINDS:
            print(
                f"error: --path is required for --kind {args.kind}. Only "
                f"{'/'.join(sorted(YAML_KINDS))} targets can have a path derived from "
                "a slug; everything else is not reliably a .yaml file.",
                file=sys.stderr,
            )
            return 2
        if not args.slug:
            print("error: provide --slug or --path", file=sys.stderr)
            return 2
        root = args.target_root.strip().rstrip("/")
        target_path = f"{root}/{args.slug}.yaml" if root else f"{args.slug}.yaml"

    # target.path is metadata — it is never opened — but a record claiming a
    # target outside the repo weakens the audit trail it exists to provide (#28).
    if Path(target_path).is_absolute() or ".." in Path(target_path).parts:
        print(
            f"error: --path must be repo-relative and must not escape the repo "
            f"root, got '{target_path}'",
            file=sys.stderr,
        )
        return 2

    history_root = Path(args.history_root)
    # Strip every suffix, not just the last: Path.stem leaves "foo.sssom" for
    # foo.sssom.tsv, which would file the same target under two directories
    # depending on whether --slug or --path was used (#30).
    derived = Path(target_path).name
    while True:
        stem = Path(derived).stem
        if stem == derived:
            break
        derived = stem
    try:
        path, session_id, timestamp = new_history_path(
            history_root, args.kind, args.slug or derived, args.actor_name
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

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


PLACEHOLDER_PREFIX = "TODO: replace this placeholder"


def _iter_records(target: Path) -> list[Path]:
    if target.is_dir():
        # Both extensions: a record saved as .yml would otherwise be silently
        # unvalidated, which is the exact failure mode this gate exists to stop.
        return sorted(
            p for p in target.rglob("*") if p.suffix in {".yaml", ".yml"} and p.is_file()
        )
    return [target]


def _structural_problem(data: object) -> str | None:
    """Return a human-readable reason the record is malformed, or None.

    Every access is defensive: a scalar where a mapping belongs used to raise and
    abort the whole scan, losing the results for every other record (#31).
    """
    if not isinstance(data, dict):
        return "top level is not a mapping"
    session = data.get("session")
    if not isinstance(session, dict):
        return "session must be a mapping"
    actors = session.get("actors")
    if not isinstance(actors, list) or not actors:
        return "session.actors must have at least one entry"
    events = data.get("events")
    if not isinstance(events, list) or not events:
        return "events must have at least one entry"
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            return f"events[{i}] is not a mapping"
        details = event.get("details")
        if not isinstance(details, str) or not details.strip():
            return f"events[{i}].details must be a non-empty string"
        if details.lstrip().startswith(PLACEHOLDER_PREFIX):
            return (
                f"events[{i}].details is still the scaffolder's TODO placeholder — "
                "replace it with what actually happened"
            )
    return None


def cmd_validate(args: argparse.Namespace) -> int:
    target = Path(args.target)
    if not target.exists():
        # Fail like every other error path here rather than letting the read
        # blow up with a traceback further down (#27).
        print(f"error: '{target}' does not exist", file=sys.stderr)
        return 2

    schema = Path(args.schema)
    if not schema.is_file():
        print(
            f"error: history schema not found at '{schema}'. "
            "Pass --schema to a HistoryRecord schema or reinstall the package; "
            "the default is the packaged "
            "kg_microbe_governance/artifacts/schema/history.yaml.",
            file=sys.stderr,
        )
        return 2

    records = _iter_records(target)
    if not records:
        print(f"No history records found under {args.target}", file=sys.stderr)
        return 0

    # Structural pre-check first: it produces far clearer errors than linkml for
    # the mistakes people actually make (missing details, empty events).
    failures = 0
    for record_path in records:
        try:
            data = yaml.safe_load(record_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            print(f"FAIL {record_path}: unreadable: {exc}", file=sys.stderr)
            failures += 1
            continue
        problem = _structural_problem(data)
        if problem:
            print(f"FAIL {record_path}: {problem}", file=sys.stderr)
            failures += 1

    if failures:
        print(f"{failures} record(s) failed structural checks", file=sys.stderr)
        return 1

    if args.structural_only:
        print(
            f"OK (structural): {len(records)} record(s). NOTE: enum values and the "
            "timestamp format are NOT checked in this mode — run without "
            "--structural-only for the full schema gate.",
            file=sys.stderr,
        )
        return 0

    # Batch rather than passing every path at once: the argv ceiling is reachable
    # at a few tens of thousands of records, and the shell callers already chunk
    # via xargs, so batching keeps the module consistent with them (#28).
    batch_size = 500
    failed = False
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        cmd = [
            "linkml-validate",
            "--schema",
            str(schema),
            "--target-class",
            "HistoryRecord",
            *[str(p) for p in batch],
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
        except OSError as exc:  # e.g. errno 7, argument list too long
            print(f"error: could not invoke linkml-validate: {exc}", file=sys.stderr)
            return 2
        if proc.stdout.strip():
            print(proc.stdout.rstrip(), file=sys.stderr)
        if proc.returncode != 0:
            if proc.stderr.strip():
                print(proc.stderr.rstrip(), file=sys.stderr)
            failed = True
    if failed:
        return 1
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
    ap_val.add_argument("--schema", default=_default_schema_path())
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
