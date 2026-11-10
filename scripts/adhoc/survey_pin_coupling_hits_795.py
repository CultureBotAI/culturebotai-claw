#!/usr/bin/env python3
"""Survey what `pin-coupling` reports for a retired pin, grouped by path shape (#795).

Purpose: #795 says pin-coupling reports dated review/research records as
couplings. This runs find_pin_couplings for one old pin over every configured
Mech's local origin/main and prints each hit's Mech, path and kind, then a count
per (Mech, top-level directory), so the exemption can be designed from real data.
Inputs: --old-ref (full SHA); Mech roots exported from claw's .env (set -a; . ./.env).
Outputs: stdout only. Read-only: git grep / ls-tree on committed trees.
Serves: issue #795. Written 2026-11-05.
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from kg_microbe_governance import load_governance_manifest  # noqa: E402
from kg_microbe_governance.pin_coupling import find_pin_couplings  # noqa: E402
from plugins.repository_settings import RepositorySettings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-ref", required=True)
    parser.add_argument("--treeish", default="origin/main")
    args = parser.parse_args(argv)
    pin_path = load_governance_manifest().pin_path
    settings = RepositorySettings.from_environment()  # roots exported from claw's .env by the caller
    groups: collections.Counter = collections.Counter()
    for key in load_fleet_manifest().mechs:
        root = settings.paths.get(key)
        if root is None:  # unconfigured or invalid: report, keep going
            print(f"SKIP {key}: {settings.errors.get(key, 'not configured')}")
            continue
        for coupling in find_pin_couplings(root, args.old_ref, pin_path=pin_path,
                                           treeish=args.treeish):
            print(f"{key}\t{coupling.kind}\t{coupling.path}:{coupling.line}")
            top = coupling.path.split("/", 1)[0] if "/" in coupling.path else "(root)"
            groups[(key, top)] += 1
    print("--- per Mech and top-level directory")
    for (key, top), count in sorted(groups.items()):
        print(f"{count:5d}  {key}  {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
