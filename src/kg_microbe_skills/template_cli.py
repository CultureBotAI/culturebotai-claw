"""Offline baseline and consumer planning; writes require ``--apply``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_skills.catalogue import CatalogueError
from kg_microbe_skills.template import (
    TemplateError,
    apply_plan,
    check_baseline,
    encode,
    plan_repository,
    refresh_baseline,
)
from kg_microbe_write import WriteError
from plugins.repository_settings import RepositoryConfigurationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("refresh", "check-baseline", "plan", "apply", "check"):
        command = sub.add_parser(name)
        command.add_argument("--source-root", type=Path, required=name == "refresh")
        if name == "refresh":
            command.add_argument("--version", default="1.0.0")
            command.add_argument("--apply", action="store_true")
        if name in {"plan", "apply", "check"}:
            command.add_argument("--target-root", type=Path, required=True)
            command.add_argument("--config", type=Path)
        if name == "apply":
            command.add_argument("--apply", action="store_true", help="write the validated candidate (default: dry run)")
    args = parser.parse_args(argv)
    try:
        if args.command == "refresh":
            result = refresh_baseline(args.source_root, version=args.version, apply=args.apply)
        elif args.command == "check-baseline":
            result = check_baseline(args.source_root)
        else:
            plan = plan_repository(args.target_root, config_path=args.config, source_root=args.source_root)
            result = apply_plan(plan, apply=args.apply) if args.command == "apply" else plan.report
        print(encode(result), end="")
        return int(args.command == "check" and result["status"] != "current")
    except (TemplateError, CatalogueError, RepositoryConfigurationError, WriteError, OSError, ValueError, RuntimeError) as exc:
        print(encode({"status": "error", "error": str(exc)}), file=sys.stderr, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
