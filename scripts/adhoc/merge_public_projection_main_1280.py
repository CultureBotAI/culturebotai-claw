"""Prepare ordinary current-main integration for PR1280, 2026-11-16.

Inputs: canonical CLAW root, exact topic head and current-main commit.
Output: dry-run plan or an uncommitted ordinary merge on this topic worktree.
The short metadata lease excludes commit hooks/push, which the caller runs later.
This refreshes stale workflow event provenance without changing audit policy.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "CultureBotAI/culturebotai-claw"
BRANCH = "feat/public-fleet-projection-1254-20261115"


def run(*command: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True, timeout=90).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claw-root", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-main", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha)
               for sha in (args.expected_head, args.expected_main)):
        raise ValueError("Both expected revisions must be immutable full commits")
    claw = args.claw_root.resolve(strict=True)
    RepositoryTarget("claw", claw, REPOSITORY).open()
    if not (claw / ".git").is_dir():
        raise ValueError("Shared lock root must be the canonical standalone CLAW checkout")
    if run("git", "rev-parse", "--path-format=absolute", "--git-common-dir") != run(
        "git", "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=claw,
    ):
        raise ValueError("Topic worktree and canonical CLAW must share Git metadata")

    def verify() -> None:
        RepositoryTarget("claw-topic", ROOT, REPOSITORY).open()
        if (run("git", "branch", "--show-current") != BRANCH
                or run("git", "rev-parse", "HEAD") != args.expected_head
                or run("git", "status", "--porcelain", "--untracked-files=all")):
            raise ValueError("Expected clean topic branch/head changed")

    verify()
    observed_main = run("gh", "api", f"repos/{REPOSITORY}/git/ref/heads/main", "--jq", ".object.sha")
    if observed_main != args.expected_main:
        raise ValueError("Current main changed; inspect and explicitly select the new base")
    print(json.dumps({"worktree": str(ROOT), "head": args.expected_head,
                      "main": observed_main, "apply": args.apply}), flush=True)
    if not args.apply:
        return
    # Fetch only the selected object, leaving shared origin/main and FETCH_HEAD alone.
    run("git", "fetch", "--no-tags", "--no-prune", "--no-write-fetch-head", "origin", observed_main)
    locks = LockManager({"locks_dir": str(claw / "workspace/locks")})
    with locks.lock("claw", "prepare-pr1280-current-main", timeout=300):
        verify()
        run("git", "-c", "core.hooksPath=/dev/null", "merge", "--no-commit", "--no-ff", observed_main)
        if run("git", "rev-parse", "MERGE_HEAD") != observed_main:
            raise RuntimeError("Merge preparation did not retain the expected base")
    print("Ordinary merge prepared; validate and commit/push after this lease has released.")


if __name__ == "__main__":
    main()
