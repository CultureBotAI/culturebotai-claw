"""Offline commands for release accounting; no provider or scientific auto-approval."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .contract import load_bundle, validate_bundle
from .identity import CurationError
from .ledger import apply_bundle, audit, coverage, ingest_export, lookup


def main(argv: list[str] | None = None) -> int:
    """Create, inspect or update a local ledger using explicit immutable inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser(
        "init", help="Verify an occurrence export and create a new ledger"
    )
    initialize.add_argument("--export", dest="export_directory", type=Path, required=True)
    initialize.add_argument("--database", type=Path, required=True)
    status = commands.add_parser("status", help="Report complete versus selected coverage")
    status.add_argument("--database", type=Path, required=True)
    reconcile = commands.add_parser(
        "audit", help="Scan membership and reconcile transactional counters"
    )
    reconcile.add_argument("--database", type=Path, required=True)
    show = commands.add_parser("show", help="Retrieve one occurrence and current decision")
    show.add_argument("--database", type=Path, required=True)
    show.add_argument("--occurrence", required=True)
    apply = commands.add_parser("apply", help="Apply a validated, input-bound review bundle")
    apply.add_argument("--database", type=Path, required=True)
    apply.add_argument("--bundle", type=Path, required=True)
    apply.add_argument("--expected-revision", required=True)
    validate = commands.add_parser(
        "validate-bundle", help="Check a bounded bundle without changing a ledger"
    )
    validate.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = ingest_export(args.export_directory, args.database)
        elif args.command == "status":
            result = coverage(args.database)
        elif args.command == "audit":
            result = audit(args.database)
        elif args.command == "show":
            result = lookup(args.database, args.occurrence)
        elif args.command == "apply":
            result = apply_bundle(
                args.database, load_bundle(args.bundle), expected_revision=args.expected_revision
            )
        else:
            validate_bundle(load_bundle(args.bundle))
            result = {"valid": True, "scientific_approval": False}
    except (CurationError, OSError, sqlite3.Error) as exc:
        print(f"curation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
