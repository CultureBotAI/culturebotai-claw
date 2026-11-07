#!/usr/bin/env python3
"""After a PR merges, delete its branch remotely and locally and remove its worktree.

Purpose: the Git workflow ends each PR by deleting its branch, remote and local.
This does that for one merged PR, and only after checking that GitHub reports
the PR MERGED and that the local branch's head is the PR's reviewed head, so
nothing unmerged is deleted. For a Mech it holds that Mech's LockManager lease.
Inputs: --repo OWNER/NAME, --pr N, --checkout PATH (the clone the worktree
belongs to), --worktree PATH (optional), --mech KEY (optional; takes the lock).
Outputs: removes the worktree, deletes the local branch, and deletes the remote
branch if GitHub has not already. Prints what it did.
Serves: the culturebotai-claw#729 related-issue PRs. Written 2026-11-05.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plugins.lock_manager import LockManager  # noqa: E402


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(list(args), text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {completed.stderr.strip()}")
    return completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--mech")
    args = parser.parse_args()
    pr = json.loads(run("gh", "pr", "view", str(args.pr), "-R", args.repo,
                        "--json", "state,headRefName,headRefOid").stdout)
    if pr["state"] != "MERGED":
        raise RuntimeError(f"{args.repo}#{args.pr} is {pr['state']}, not MERGED")
    branch, head = pr["headRefName"], pr["headRefOid"]
    local = run("git", "-C", str(args.checkout), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                check=False).stdout.strip()
    if local and local != head:
        raise RuntimeError(f"local {branch} is {local[:10]}, not the merged head {head[:10]}")
    lock = LockManager().lock(args.mech, "cleanup-merged-branch") if args.mech else contextlib.nullcontext()
    with lock:
        if args.worktree and args.worktree.exists():
            if run("git", "-C", str(args.worktree), "status", "--porcelain").stdout.strip():
                raise RuntimeError(f"{args.worktree} has uncommitted changes")
            run("git", "-C", str(args.checkout), "worktree", "remove", str(args.worktree))
            print(f"removed worktree {args.worktree}")
        if local:
            run("git", "-C", str(args.checkout), "branch", "-D", branch)
            print(f"deleted local {branch} (was {head[:10]})")
        if run("git", "-C", str(args.checkout), "ls-remote", "--exit-code", "--heads", "origin", branch,
               check=False).returncode == 0:
            run("git", "-C", str(args.checkout), "push", "-q", "origin", "--delete", branch)
            print(f"deleted remote {branch}")
        else:
            print(f"remote {branch} already gone")
        run("git", "-C", str(args.checkout), "fetch", "-q", "--prune", "origin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
