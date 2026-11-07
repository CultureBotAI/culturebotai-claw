#!/usr/bin/env python3
"""Commit staged changes in a Mech worktree and push its branch, holding that Mech's lock.

Purpose: the cross-repository checklist (AGENTS.md) requires a downstream write to
hold the Mech's LockManager lease, and its origin to be the manifest's
repository. This does exactly one commit-and-push of an existing worktree
branch under those two conditions, for review fixes on downstream PRs.
Inputs: --mech KEY, --worktree PATH (must be on a branch, with staged changes and
nothing unstaged), --message-file PATH.
Outputs: one commit on the worktree's branch, pushed to origin; prints the new
HEAD. Refuses on unstaged or untracked files, a detached HEAD, or an origin
that is not the manifest's repository.
Serves: downstream review fixes for the culturebotai-claw#729 related issues
(first use: TraitMech#2077 on TraitMech#2076). Written 2026-11-05.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import RepositoryTarget  # noqa: E402


def git(worktree: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(worktree), *args], text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mech", required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--message-file", type=Path, required=True)
    args = parser.parse_args()
    slug = load_fleet_manifest().mechs[args.mech].github
    worktree = args.worktree.resolve()
    branch = git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch == "HEAD":
        raise RuntimeError("detached HEAD")
    status = [line for line in git(worktree, "status", "--porcelain").split("\n") if line]
    if not status or any(line[1] != " " for line in status):
        raise RuntimeError(f"need staged changes and nothing unstaged or untracked: {status}")
    RepositoryTarget(name=args.mech, path=worktree, expected_repository=slug).open()
    with LockManager().lock(args.mech, "review-fix-push"):
        git(worktree, "commit", "-q", "-F", str(args.message_file))
        git(worktree, "push", "-q", "origin", branch)
    print(f"pushed {args.mech} {branch} {git(worktree, 'rev-parse', 'HEAD').strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
