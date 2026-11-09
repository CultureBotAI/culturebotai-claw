"""Inspect fleet rollout, validate embedding registries, and build local maps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .registry import EmbeddingError, load_registry
from .rollout import load_rollout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kg-microbe-embeddings")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rollout", help="validate/report the complete fleet adoption plan")
    check = commands.add_parser("check", help="validate a multi-set registry without inference")
    check.add_argument("registry", type=Path)
    check.add_argument(
        "--artifacts", action="store_true", help="also validate IDs and vector bytes"
    )
    build_parser = commands.add_parser("build", help="project ready sets into a new local release")
    build_parser.add_argument("registry", type=Path)
    build_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "rollout":
            result = load_rollout()
        elif args.command == "check":
            if args.artifacts:
                from .project import check_inputs

                result = check_inputs(args.registry)
            else:
                result = load_registry(args.registry)
        else:
            from .project import build

            result = build(args.registry, args.output)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (EmbeddingError, OSError, ValueError, ImportError) as exc:
        print(f"embedding operation refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
