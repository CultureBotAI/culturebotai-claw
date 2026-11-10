"""`kg-microbe-kgx check` -- judge one Mech's exported KGX graph."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, claw_root, resolve_mech_root
from kg_microbe_kgx.contract import (
    KgxProfile,
    check_graph,
    check_release_bundle,
    fetch_release_bundle,
    summarise,
)

CLAW_ROOT = claw_root()


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-kgx",
        description=(
            "Check an exported KGX graph for the things that make a TSV mean "
            "different things to different readers: a bare carriage return, a "
            "literal newline inside a field, a duplicated column name, rows that "
            "the csv module and a line-splitter count differently. Also the "
            "usual structure -- required columns, CURIE identifiers, no repeated "
            "node id, no edge naming a node the nodes file does not define."
        ),
    )
    parser.add_argument("command", choices=["check", "export"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument("--nodes", type=Path)
    parser.add_argument("--edges", type=Path)
    parser.add_argument(
        "--release-dir",
        type=Path,
        help="check: directory containing nodes.tsv.gz, edges.tsv.gz and manifest.json (#540)",
    )
    parser.add_argument(
        "--release-tag",
        type=str,
        help="check: GitHub release tag (or 'latest') to download and check (#540)",
    )
    parser.add_argument(
        "--out", type=Path,
        help="export: directory for nodes.tsv, edges.tsv, .tsv.gz assets and manifest.json",
    )
    parser.add_argument(
        "--sample", type=int,
        help="export: only the first N records, for a quick look (marked sampled)",
    )
    args = parser.parse_args(argv)

    if args.command == "export":
        return _export(manifest, args)

    declaration = manifest.mechs[args.mech]
    capability = declaration.capabilities.get("kgx_export")
    settings = capability.settings if capability is not None else {}
    explicit_target = (
        args.release_dir is not None
        or args.release_tag is not None
        or (args.nodes is not None and args.edges is not None)
    )
    if not explicit_target and (capability is None or not capability.is_enabled):
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        status = getattr(capability, "status", "undeclared")
        print(f"{args.mech}: kgx_export is {status}, so there is nothing to check: {reason}")
        return 0

    profile = KgxProfile(
        extra_prefixes=tuple(settings.get("extra_prefixes", ()))
    )

    if args.release_dir is not None:
        findings = check_release_bundle(args.release_dir, profile)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(f"{args.mech}: {summarise(findings) or 'clean'}")
        return 1 if findings else 0

    release_tag = args.release_tag
    if (
        release_tag is None
        and args.nodes is None
        and args.edges is None
        and (
            settings.get("release_asset")
            or settings.get("source") == "release"
            or ("release_tag" in settings and "nodes_path" not in settings)
        )
    ):
        release_tag = str(settings.get("release_tag") or "latest")

    if release_tag is not None:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                bundle_dir = fetch_release_bundle(
                    declaration.github, Path(tmp), tag=release_tag
                )
            except RuntimeError as exc:
                print(f"{args.mech}: {exc}", file=sys.stderr)
                return 2
            findings = check_release_bundle(bundle_dir, profile)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(f"{args.mech}: {summarise(findings) or 'clean'}")
        return 1 if findings else 0

    nodes, edges = args.nodes, args.edges
    if nodes is None or edges is None:
        try:
            root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        nodes = nodes or root / settings["nodes_path"]
        edges = edges or root / settings["edges_path"]

    for path in (nodes, edges):
        if not path.is_file():
            print(f"{args.mech}: no KGX file at {path}", file=sys.stderr)
            return 2

    findings = check_graph(nodes, edges, profile)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    print(f"{args.mech}: {summarise(findings) or 'clean'}")
    return 1 if findings else 0


def _export(manifest, args) -> int:
    """Write and check one Mech's KGX graph, read through its declared shape.

    Unlike `check`, this does not need `kgx_export` enabled: producing the
    graph is how a Mech gets to enable it.
    """
    import subprocess

    from kg_microbe_kgx.export import ExportError, ExportSettings, write_export

    if args.out is None:
        print("export needs --out", file=sys.stderr)
        return 2
    declaration = manifest.mechs[args.mech]
    try:
        settings = ExportSettings.from_manifest(args.mech, declaration)
        root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
    except (ExportError, MechRootError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
        check=False,
    ).stdout.strip()
    try:
        document, findings = write_export(
            root, declaration.record_globs, settings, args.out, sample=args.sample,
            provenance={"source_commit": commit or None},
        )
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    stats = document["statistics"]
    print(
        f"{args.mech}: {stats['nodes']} nodes, {stats['edges']} edges "
        f"({stats['predicates_mapped_fraction']} of predicates mapped, "
        f"{stats['minted_nodes']} nodes minted) -> {args.out}"
    )
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    if findings:
        print(f"{args.mech}: the export fails the KGX contract: {summarise(findings)}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
