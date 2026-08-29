"""Command line interface for provenance-bound governance inspection and sync."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import (
    Consumer,
    GovernanceError,
    load_governance_manifest,
    plan_sync,
    sync_repository,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kg-microbe-governance",
        description="Inspect or synchronize claw-governed Mech artifacts",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List canonical artifact mappings")
    list_parser.add_argument("--repository", help="Limit output to one Mech key or identity")
    list_parser.add_argument("--json", action="store_true", dest="as_json")

    fleet_parser = subparsers.add_parser(
        "fleet-audit",
        help=(
            "Audit every manifest-declared Mech's clean origin/main worktree "
            "against one claw pin"
        ),
    )
    fleet_parser.add_argument("--ref", required=True, help="Expected full claw commit SHA")
    fleet_parser.add_argument(
        "--target-root",
        action="append",
        required=True,
        metavar="MECH=PATH",
        help="One manifest key and exact worktree root; repeat for every Mech",
    )
    fleet_parser.add_argument("--json", action="store_true", dest="as_json")

    for command, help_text in (
        ("check", "Fail if a target differs from the packaged canonical bytes"),
        ("sync", "Plan or apply canonical artifacts and an immutable pin"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument(
            "--repository", required=True, help="Mech key or owner/repository identity"
        )
        command_parser.add_argument("--target-root", required=True, type=Path)
        command_parser.add_argument("--ref", required=True, help="Full claw commit SHA")
        command_parser.add_argument("--json", action="store_true", dest="as_json")
        if command == "sync":
            command_parser.add_argument(
                "--apply",
                action="store_true",
                help="Safely write the plan; omitted means dry-run",
            )
    return parser


def _list(args: argparse.Namespace) -> int:
    manifest = load_governance_manifest()
    consumers: tuple[Consumer, ...]
    if args.repository:
        consumers = (manifest.consumer_for(args.repository),)
    else:
        consumers = tuple(manifest.consumers.values())
    rows: list[dict[str, object]] = []
    for consumer in consumers:
        for artifact in manifest.artifacts_for(consumer):
            from .artifacts.scripts.check_vendored_sync import expand_target

            rows.append(
                {
                    "repository": consumer.github,
                    "artifact": artifact.artifact_id,
                    "source": artifact.source,
                    "target": expand_target(artifact, consumer),
                    "sha256": artifact.sha256,
                    "mode": f"{artifact.mode:04o}",
                }
            )
    if args.as_json:
        print(json.dumps(rows, sort_keys=True))
    else:
        for row in rows:
            print(
                "\t".join(
                    str(row[key])
                    for key in ("repository", "artifact", "source", "target", "sha256", "mode")
                )
            )
    return 0


def _changes(args: argparse.Namespace) -> int:
    if args.command == "sync":
        changes = sync_repository(
            args.repository,
            args.target_root,
            args.ref,
            apply=args.apply,
        )
    else:
        changes = plan_sync(args.repository, args.target_root, args.ref)
    rows = [
        {"artifact": change.artifact_id, "path": change.path, "reason": change.reason}
        for change in changes
    ]
    if args.as_json:
        print(json.dumps(rows, sort_keys=True))
    else:
        action = "WRITE" if args.command == "sync" and args.apply else "WOULD_WRITE"
        for change in changes:
            print(f"{action}\t{change.path}\t{change.reason}")
        if not changes:
            print("OK: governed artifacts and pin are current")
    if args.command == "check" and changes:
        return 1
    return 0


def _fleet_roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        key, separator, path = value.partition("=")
        if not separator or not key or not path:
            raise GovernanceError(
                "Each --target-root must have the form MECH=/exact/worktree/path"
            )
        if key in roots:
            raise GovernanceError(f"Duplicate --target-root key {key!r}")
        roots[key] = Path(path)
    return roots


def _fleet_audit(args: argparse.Namespace) -> int:
    from .fleet_audit import audit_fleet_pins

    result = audit_fleet_pins(_fleet_roots(args.target_root), args.ref)
    if args.as_json:
        document = {
            "ok": result.ok,
            "expected_ref": result.expected_ref,
            "fleet_issues": [issue.__dict__ for issue in result.fleet_issues],
            "repositories": [
                {
                    "key": repository.key,
                    "github": repository.github,
                    "root": str(repository.root),
                    "head": repository.head,
                    "origin_main": repository.origin_main,
                    "pin": repository.pin,
                    "expected_artifacts": repository.expected_artifacts,
                    "checked_artifacts": repository.checked_artifacts,
                    "issues": [issue.__dict__ for issue in repository.issues],
                }
                for repository in result.repositories
            ],
        }
        print(json.dumps(document, sort_keys=True))
    else:
        for issue in result.fleet_issues:
            print(f"FAIL\tfleet\t{issue.code}\t{issue.message}")
        for repository in result.repositories:
            if repository.ok:
                print(
                    f"OK\t{repository.key}\t{repository.checked_artifacts} artifacts\t"
                    f"{repository.pin}"
                )
            else:
                for issue in repository.issues:
                    print(
                        f"FAIL\t{repository.key}\t{issue.code}\t{issue.message}"
                    )
        if result.ok:
            print(
                f"OK: all {len(result.repositories)} Mechs match claw@{result.expected_ref}"
            )
    return 0 if result.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "list":
            return _list(args)
        if args.command == "fleet-audit":
            return _fleet_audit(args)
        return _changes(args)
    except GovernanceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
