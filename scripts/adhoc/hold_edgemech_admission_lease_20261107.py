#!/usr/bin/env python3
"""Hold the verified CLAW admission edit lease for issue #960, 2026-11-07.

Input: this existing feature worktree. Output: a lease receipt on stdout.
Release by writing 'release' or closing stdin; no downstream writes or sends.
"""

import json
import os
import sys
from pathlib import Path

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget


def main():
    root = Path(__file__).resolve().parents[2]
    target = RepositoryTarget("claw", root, "CultureBotAI/culturebotai-claw")
    branch = "feat/edgemech-milestones-766-767-20261107"
    if target.open().active_branch.name != branch:
        raise ValueError("Unexpected CLAW admission feature branch")
    with LockManager().lock("claw", "edgemech-post-cutoff-admission-960"):
        target.open()
        print(json.dumps({"status": "lease-held", "pid": os.getpid(), "root": str(root),
                          "branch": branch}), flush=True)
        for line in sys.stdin:
            if line.strip() == "release":
                break


if __name__ == "__main__":
    main()
