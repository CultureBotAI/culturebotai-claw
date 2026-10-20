"""Offline validation of pinned workflow profiles and immutable goal evidence."""
import argparse
import json
import sys
from pathlib import Path

from . import (
    PARENT_PATH,
    SCHEMA_PATH,
    WorkflowError,
    load_document,
    load_effective_workflow,
    read_goal_evidence,
    validate_parent,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate and resolve a local profile")
    validate.add_argument("--profile", type=Path, required=True)
    validate.add_argument("--parent", type=Path, default=PARENT_PATH)
    validate.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    validate.add_argument("--repository-key")
    validate.add_argument("--json", action="store_true")
    parent = commands.add_parser("validate-parent")
    parent.add_argument("path", type=Path, nargs="?", default=PARENT_PATH)
    parent.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    evidence = commands.add_parser("validate-evidence")
    evidence.add_argument("path", type=Path)
    evidence.add_argument("--root", type=Path, required=True)
    evidence.add_argument("--previous", type=Path)
    evidence.add_argument("--required-output", action="append", default=[],
                          help="additional output kind required by the pinned effective stage; repeatable")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = load_effective_workflow(args.parent, args.profile, args.repository_key,
                                             schema_path=args.schema)
            print(json.dumps(result, indent=2) if args.json else "Workflow profile valid")
        elif args.command == "validate-parent":
            validate_parent(load_document(args.path.read_bytes()), args.schema)
            print("Workflow parent valid")
        else:
            previous = load_document(args.previous.read_bytes()) if args.previous else None
            read_goal_evidence(args.path, repository_root=args.root, previous=previous,
                               required_outputs=args.required_output)
            print("Base contract and supplied output requirements valid; remote closure, full active policy, "
                  "and committed bytes remain caller checks")
        return 0
    except (WorkflowError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
