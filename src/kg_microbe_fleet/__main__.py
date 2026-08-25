"""Dependency-light queries over the canonical Mech fleet manifest.

Shell scripts, GitHub workflows, skills, and declarative agents use this CLI
instead of embedding their own repository lists. All commands are local and
offline; they only read and validate the packaged manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from . import FleetManifest, FleetManifestError, MechDefinition, load_fleet_manifest


def _capability_names(manifest: FleetManifest) -> frozenset[str]:
    declared = getattr(manifest, "capability_names", None)
    if declared is not None:
        return frozenset(declared)
    return frozenset(
        name
        for mech in manifest.mechs.values()
        for name in mech.capabilities
    )


def _select(
    manifest: FleetManifest, capability: str | None
) -> tuple[MechDefinition, ...]:
    if capability is None:
        return tuple(manifest.mechs.values())
    if capability not in _capability_names(manifest):
        known = ", ".join(sorted(_capability_names(manifest)))
        raise FleetManifestError(
            f"Unknown fleet capability '{capability}'; known capabilities: {known}"
        )
    return tuple(
        mech for mech in manifest.mechs.values() if mech.supports(capability)
    )


def _tsv_value(value: object, label: str) -> str:
    rendered = str(value)
    if "\t" in rendered or "\n" in rendered or "\r" in rendered:
        raise FleetManifestError(f"{label} is not safe for TSV output")
    return rendered


def _identity(mech: MechDefinition) -> dict[str, Any]:
    return {
        "key": mech.key,
        "display_name": mech.display_name,
        "github": mech.github,
        "environment_variable": mech.environment_variable,
        "package_path": mech.package_path,
        "schema_paths": list(mech.schema_paths),
        "record_globs": list(mech.record_globs),
    }


def _list_command(args: argparse.Namespace, manifest: FleetManifest) -> None:
    mechs = _select(manifest, args.capability)
    if args.format == "json":
        print(json.dumps([_identity(mech) for mech in mechs], sort_keys=True))
        return
    if args.format == "tsv":
        fields = ["key", "display_name", "github", "environment_variable"]
        if args.include_package_path:
            fields.append("package_path")
        for mech in mechs:
            row = _identity(mech)
            print(
                "\t".join(
                    _tsv_value(row[field], f"{mech.key}.{field}")
                    for field in fields
                )
            )
        return
    for mech in mechs:
        print(getattr(mech, args.field))


def _capability_settings(mech: MechDefinition, capability: str) -> Mapping[str, Any]:
    declaration = mech.capability(capability)
    if declaration is None:
        raise FleetManifestError(f"{mech.key} does not declare {capability}")
    settings = getattr(declaration, "settings", {})
    if not isinstance(settings, Mapping):
        raise FleetManifestError(f"{mech.key}.{capability}.settings must be a mapping")
    return settings


def _matrix_command(args: argparse.Namespace, manifest: FleetManifest) -> None:
    rows: list[dict[str, Any]] = []
    for mech in _select(manifest, args.capability):
        repository_name = mech.github.rsplit("/", 1)[-1]
        row: dict[str, Any] = {
            "mech": mech.display_name,
            "repository": mech.github,
            "checkout_path": repository_name,
            "workdir": repository_name,
        }
        settings = _capability_settings(mech, args.capability)
        for name in args.setting:
            if name not in settings:
                raise FleetManifestError(
                    f"{mech.key}.{args.capability}.settings is missing '{name}'"
                )
            row[name] = settings[name]
        rows.append(row)
    if not rows:
        raise FleetManifestError(
            f"Capability '{args.capability}' has no enabled Mechs"
        )
    print(json.dumps({"include": rows}, separators=(",", ":"), sort_keys=True))


def _show_command(args: argparse.Namespace, manifest: FleetManifest) -> None:
    if args.field == "vendored_hub":
        print(manifest.vendored_hub)
        return
    raise FleetManifestError(f"Unsupported manifest field: {args.field}")


def _scope_command(args: argparse.Namespace, manifest: FleetManifest) -> None:
    """Emit a fixed-column capability snapshot for shell consumers.

    Columns are, in order: key, display name, GitHub identity, environment
    variable, package path, and vendored role.  Unlike composing separate
    ``list`` and ``show`` calls, one scope query cannot observe two different
    manifest snapshots.  Consumers that need a vendored authority can also
    require that the declared hub is a member of the selected capability.
    """

    mechs = _select(manifest, args.capability)
    if not mechs:
        raise FleetManifestError(
            f"Capability '{args.capability}' has no enabled Mechs"
        )
    if args.require_vendored_hub and not any(
        mech.key == manifest.vendored_hub and mech.vendored_role == "hub"
        for mech in mechs
    ):
        raise FleetManifestError(
            f"vendored hub '{manifest.vendored_hub}' is not in capability "
            f"scope '{args.capability}'"
        )

    for mech in mechs:
        print(
            "\t".join(
                _tsv_value(value, f"{mech.key}.{label}")
                for label, value in (
                    ("key", mech.key),
                    ("display_name", mech.display_name),
                    ("github", mech.github),
                    ("environment_variable", mech.environment_variable),
                    ("package_path", mech.package_path),
                    ("vendored_role", mech.vendored_role),
                )
            )
        )


def _targets_command(args: argparse.Namespace, manifest: FleetManifest) -> None:
    """Emit exact, identity-validated checkout roots for local mutations.

    Unconfigured roots remain visible as an empty final field. A configured
    but untrustworthy root fails the whole query before any row is printed, so
    shell consumers cannot act on a partial fleet.
    """

    # Imported lazily: pure manifest queries remain dependency-light and the
    # repository-settings layer continues to own Git identity validation.
    from plugins.repository_settings import (
        RepositoryConfigurationError,
        RepositorySettings,
        merged_repository_environment,
    )

    mechs = _select(manifest, args.capability)
    environ: Mapping[str, str] | None = None
    if args.dotenv is not None:
        try:
            environ = merged_repository_environment(args.dotenv)
        except RepositoryConfigurationError as exc:
            raise FleetManifestError(str(exc)) from exc
    settings = RepositorySettings.from_environment(
        manifest=manifest,
        environ=environ,
    )
    invalid = {
        mech.key: settings.invalid[mech.key]
        for mech in mechs
        if mech.key in settings.invalid
    }
    if invalid:
        details = "; ".join(f"{key}: {message}" for key, message in invalid.items())
        raise FleetManifestError(f"configured fleet target is untrustworthy: {details}")

    rows: list[str] = []
    for mech in mechs:
        path = (
            ""
            if mech.key in settings.unconfigured
            else str(settings.get_target(mech.key).path)
        )
        rows.append(
            "\t".join(
                _tsv_value(value, f"{mech.key}.{label}")
                for label, value in (
                    ("key", mech.key),
                    ("display_name", mech.display_name),
                    ("github", mech.github),
                    ("environment_variable", mech.environment_variable),
                    ("path", path),
                )
            )
        )
    print("\n".join(rows))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kg-microbe-fleet")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list applicable Mechs")
    list_parser.add_argument("--capability")
    list_parser.add_argument(
        "--format", choices=("lines", "json", "tsv"), default="lines"
    )
    list_parser.add_argument(
        "--field",
        choices=(
            "key",
            "display_name",
            "github",
            "environment_variable",
            "package_path",
        ),
        default="key",
        help="field emitted by the lines format",
    )
    list_parser.add_argument(
        "--include-package-path",
        action="store_true",
        help="append package_path to each TSV row",
    )

    matrix_parser = subparsers.add_parser(
        "matrix", help="render a GitHub Actions include matrix"
    )
    matrix_parser.add_argument("--capability", required=True)
    matrix_parser.add_argument("--setting", action="append", default=[])

    show_parser = subparsers.add_parser("show", help="show one manifest value")
    show_parser.add_argument("--field", choices=("vendored_hub",), required=True)

    scope_parser = subparsers.add_parser(
        "scope",
        help="emit a stable TSV capability snapshot for shell consumers",
    )
    scope_parser.add_argument("--capability", required=True)
    scope_parser.add_argument(
        "--require-vendored-hub",
        action="store_true",
        help="fail unless the declared vendored hub is in the selected scope",
    )

    targets_parser = subparsers.add_parser(
        "targets", help="list local checkout roots after exact Git identity validation"
    )
    targets_parser.add_argument("--capability", required=True)
    targets_parser.add_argument(
        "--dotenv",
        type=Path,
        help="explicit dotenv file for checkout roots; exported values take precedence",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        manifest = load_fleet_manifest()
        if args.command == "list":
            _list_command(args, manifest)
        elif args.command == "matrix":
            _matrix_command(args, manifest)
        elif args.command == "show":
            _show_command(args, manifest)
        elif args.command == "scope":
            _scope_command(args, manifest)
        else:
            _targets_command(args, manifest)
    except FleetManifestError as exc:
        print(f"fleet manifest error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
