#!/usr/bin/env python3
"""Commit staged changes in a Mech worktree and push its branch, holding that Mech's lock.

Purpose: the cross-repository checklist (AGENTS.md) requires a downstream write to
hold the Mech's LockManager lease, and its origin to be the manifest's
repository. This does exactly one commit-and-push of an existing worktree
feature branch under those two conditions, for review fixes on downstream PRs.
Every check runs inside the lock, so none can go stale before the commit.
Requires: claw's .env exported first (set -a; . ./.env). It refuses to run
unless OPENCLAW_WORKSPACE is set to an absolute path, as that .env sets it; it
cannot tell whether the path is claw's, so exporting the .env stays the
caller's job.
Inputs: --mech KEY, --worktree PATH (must be on a feature branch, with staged
changes and nothing unstaged, untracked or hidden from status), --message-file
PATH. Paths are resolved against the current directory.
Outputs: one commit on the worktree's branch, pushed to origin with an explicit
refspec; prints the new HEAD. Refuses on unstaged or untracked files, a
skip-worktree or assume-unchanged index entry, a detached HEAD, the default
branch (main, or whatever origin/HEAD names), or an origin that is not the
manifest's repository. The branch is read from the symbolic ref, so a tag
with the branch's name cannot disguise it.
Serves: downstream review fixes for the culturebotai-claw#729 related issues
(first use: TraitMech#2077 on TraitMech#2076). Written 2026-11-05; checks moved
under the lock and the default branch refused 2026-11-06 for
culturebotai-claw#857 and #858; paths resolved at entry for #868; the symbolic
ref, explicit untracked listing and hidden-entry check for #876 and #877.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import RepositoryTarget  # noqa: E402


def git(worktree: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(["git", "-C", str(worktree), *args], text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed


def default_branches(worktree: Path) -> set[str]:
    names = {"main"}
    origin_head = git(worktree, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False)
    if origin_head.returncode == 0:
        names.add(origin_head.stdout.strip().removeprefix("origin/"))
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mech", required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--message-file", type=Path, required=True)
    args = parser.parse_args()
    if not Path(os.environ.get("OPENCLAW_WORKSPACE", "")).is_absolute():
        raise RuntimeError("OPENCLAW_WORKSPACE is not an absolute path; export claw's .env first")
    slug = load_fleet_manifest().mechs[args.mech].github
    # Resolved here, against the current directory: `git -C <worktree>` would read a relative path from the worktree.
    worktree, message_file = args.worktree.resolve(), args.message_file.resolve()
    with LockManager().lock(args.mech, "review-fix-push"):
        RepositoryTarget(name=args.mech, path=worktree, expected_repository=slug).open()
        symbolic = git(worktree, "symbolic-ref", "--quiet", "HEAD", check=False)
        if symbolic.returncode != 0:
            raise RuntimeError("detached HEAD")
        branch = symbolic.stdout.strip().removeprefix("refs/heads/")
        if branch in default_branches(worktree):
            raise RuntimeError(f"{branch} is the default branch; commit review fixes on the PR's branch")
        status = [line for line in git(worktree, "status", "--porcelain", "--untracked-files=normal").stdout.split("\n")
                  if line]
        if not status or any(line[1] != " " for line in status):
            raise RuntimeError(f"need staged changes and nothing unstaged or untracked: {status}")
        hidden = [line for line in git(worktree, "ls-files", "-v").stdout.split("\n") if line and not line.startswith("H ")]
        if hidden:
            raise RuntimeError(f"{len(hidden)} index entries are skip-worktree or assume-unchanged, so status "
                               f"cannot see their changes: {', '.join(hidden[:3])}")
        git(worktree, "commit", "-q", "-F", str(message_file))
        git(worktree, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    print(f"pushed {args.mech} {branch} {git(worktree, 'rev-parse', 'HEAD').stdout.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
