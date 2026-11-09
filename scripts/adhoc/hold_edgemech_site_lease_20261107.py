#!/usr/bin/env python3
"""Hold the verified companion-site edit lease for CLAW #766/#767, 2026-11-07.

Input: explicit site feature-worktree root. Output: a lease receipt on stdout.
Release by writing 'release' or closing stdin. No corpus, secrets or sends.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from kg_microbe_fleet.roots import resolve_culturebotai_site_root
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = resolve_culturebotai_site_root(
        claw_root=Path(__file__).resolve().parents[2],
        environ={"CULTUREBOTAI_SITE_ROOT": str(args.root)},
    )
    if root is None or root != args.root.resolve(strict=True):
        raise ValueError("Unexpected companion-site root")
    target = RepositoryTarget("culturebotai_site", root, "CultureBotAI/CultureBotAI.github.io")
    branch = "feat/edgemech-fleet-membership-20261107"
    if target.open().active_branch.name != branch:
        raise ValueError("Unexpected companion-site branch")
    with LockManager().lock("culturebotai_site", "edgemech-membership-766-767"):
        target.open()
        print(json.dumps({"status": "lease-held", "pid": os.getpid(), "root": str(root),
                          "branch": branch}), flush=True)
        for line in sys.stdin:
            if line.strip() == "release":
                break


if __name__ == "__main__":
    main()
