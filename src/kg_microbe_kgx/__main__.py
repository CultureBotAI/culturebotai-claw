"""`kg-microbe-kgx check` -- judge one Mech's exported KGX graph."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_kgx.contract import KgxProfile, check_graph, summarise

CLAW_ROOT = Path(__file__).resolve().parents[2]


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
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument("--nodes", type=Path)
    parser.add_argument("--edges", type=Path)
    args = parser.parse_args(argv)

    capability = manifest.mechs[args.mech].capabilities.get("kgx_export")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} exports no KGX: {reason}")
        return 0

    nodes, edges = args.nodes, args.edges
    if nodes is None or edges is None:
        try:
            root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        nodes = nodes or root / capability.settings["nodes_path"]
        edges = edges or root / capability.settings["edges_path"]

    for path in (nodes, edges):
        if not path.is_file():
            print(f"{args.mech}: no KGX file at {path}", file=sys.stderr)
            return 2

    profile = KgxProfile(
        extra_prefixes=tuple(capability.settings.get("extra_prefixes", ()))
    )
    findings = check_graph(nodes, edges, profile)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    print(f"{args.mech}: {summarise(findings) or 'clean'}")
    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
