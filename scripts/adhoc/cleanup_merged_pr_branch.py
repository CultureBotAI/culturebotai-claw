#!/usr/bin/env python3
"""After a PR merges, delete its branch remotely and locally and remove its worktree.

Purpose: the Git workflow ends each PR by deleting its branch, remote and local.
This does that for one merged PR, and deletes nothing it cannot show is the
merged work. It checks everything first and deletes only if every check passes:
- GitHub reports the PR MERGED, from a branch of the same repository (not a fork);
- --checkout's fetch and push origin is --repo (RepositoryTarget);
- the worktree, if given, is at the merged head, with nothing modified or
  untracked, and no ignored file other than a regenerable cache;
- the local branch, if present, is at the merged head and checked out nowhere
  else; it is removed with a compare-and-delete;
- the remote branch, if present, is exactly refs/heads/<branch> at the merged
  head; it is removed with a lease on that head, so a later push survives.
All of this runs under the repository's LockManager lease: the manifest key for
a Mech, `claw` for this repository.
Requires: claw's .env exported first (set -a; . ./.env). It refuses to run
unless OPENCLAW_WORKSPACE is an absolute path, so the lock is the shared one
rather than a private workspace/ under whichever checkout holds this script.
Inputs: --repo OWNER/NAME (claw or a manifest Mech), --pr N, --checkout PATH
(the clone the worktree belongs to), --worktree PATH (optional).
Outputs: removes the worktree, deletes the local and remote branch and the
remote-tracking ref, and prints what it did. Exits nonzero, deleting nothing,
on any failed check.
Serves: the culturebotai-claw#729 related-issue PRs. Written 2026-11-05. The
first version (commit 1396fe0534 in culturebotai-claw PR 851) cleaned up
CellStructureMech PR 3068. Rewritten 2026-11-06 for culturebotai-claw#854,
#855, #856 and #858, before its reuse on further merged PRs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import RepositoryTarget  # noqa: E402

CLAW_KEY = "claw"
# Ignored paths a worktree regenerates on its own; any other ignored file blocks removal.
REGENERABLE_DIRECTORIES = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov"}
REGENERABLE_FILES = (".coverage", ".DS_Store")
REGENERABLE_SUFFIXES = (".egg-info",)


class Refused(RuntimeError):
    """A check failed; nothing has been deleted."""


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(list(args), text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {completed.stderr.strip()}")
    return completed


def git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run("git", "-C", str(path), *args, check=check)


def gh_pr_view(repo: str, number: int) -> dict:
    return json.loads(run("gh", "pr", "view", str(number), "-R", repo, "--json",
                          "state,headRefName,headRefOid,isCrossRepository").stdout)


def open_target(key: str, path: Path, repo: str) -> None:
    RepositoryTarget(name=key, path=path.resolve(), expected_repository=repo).open()


def lock_key(repo: str) -> str:
    manifest = load_fleet_manifest()
    if repo.lower() == manifest.vendored_governance.canonical_repository.lower():
        return CLAW_KEY
    keys = [key for key, mech in manifest.mechs.items() if mech.github.lower() == repo.lower()]
    if len(keys) != 1:
        raise Refused(f"{repo} is neither claw nor a manifest Mech")
    return keys[0]


def _regenerable(line: str) -> bool:
    path = PurePosixPath(line[3:].rstrip("/"))
    return (any(part in REGENERABLE_DIRECTORIES or part.endswith(REGENERABLE_SUFFIXES) for part in path.parts)
            or path.name.startswith(REGENERABLE_FILES))


def worktree_problems(worktree: Path, head: str) -> list[str]:
    problems = []
    actual = git(worktree, "rev-parse", "HEAD").stdout.strip()
    if actual != head:
        problems.append(f"{worktree} is at {actual[:10]}, not the merged head {head[:10]}")
    for line in git(worktree, "status", "--porcelain", "--ignored").stdout.split("\n"):
        if line and not (line.startswith("!! ") and _regenerable(line)):
            problems.append(f"{worktree}: {line}")
    return problems


def remote_branch_sha(checkout: Path, branch: str) -> str | None:
    ref = f"refs/heads/{branch}"
    listed = git(checkout, "ls-remote", "origin", ref).stdout.split("\n")
    shas = [line.split("\t")[0] for line in listed if line.endswith(f"\t{ref}")]
    return shas[0] if shas else None


def worktrees_on(checkout: Path, branch: str) -> list[Path]:
    """Every worktree of the checkout, itself included, that has the branch checked out."""
    found, path = [], None
    for line in git(checkout, "worktree", "list", "--porcelain").stdout.split("\n"):
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):]).resolve()
        elif line == f"branch refs/heads/{branch}" and path is not None:
            found.append(path)
    return found


def cleanup(repo: str, number: int, checkout: Path, worktree: Path | None, *,
            pr_view: Callable[[str, int], dict] = gh_pr_view,
            verify_origin: Callable[[str, Path, str], None] = open_target) -> list[str]:
    workspace = os.environ.get("OPENCLAW_WORKSPACE", "")
    if not Path(workspace).is_absolute():
        raise Refused("OPENCLAW_WORKSPACE is not an absolute path; export claw's .env first")
    key = lock_key(repo)
    pr = pr_view(repo, number)
    if pr["state"] != "MERGED":
        raise Refused(f"{repo}#{number} is {pr['state']}, not MERGED")
    if pr["isCrossRepository"]:
        raise Refused(f"{repo}#{number} is from a fork; its branch is not in {repo}")
    branch, head = pr["headRefName"], pr["headRefOid"]
    done = []
    with LockManager().lock(key, "cleanup-merged-branch"):
        verify_origin(key, checkout, repo)
        problems = []
        removing = worktree is not None and worktree.exists()
        if removing:
            problems += worktree_problems(worktree, head)
        local = git(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                    check=False).stdout.strip()
        if local and local != head:
            problems.append(f"local {branch} is {local[:10]}, not the merged head {head[:10]}")
        others = [path for path in worktrees_on(checkout, branch)
                  if not (removing and path == worktree.resolve())]
        if local and others:
            problems.append(f"{branch} is also checked out in {', '.join(map(str, others))}")
        remote = remote_branch_sha(checkout, branch)
        if remote and remote != head:
            problems.append(f"origin {branch} is {remote[:10]}, not the merged head {head[:10]}")
        if problems:
            raise Refused("; ".join(problems))
        if removing:
            git(checkout, "worktree", "remove", str(worktree))
            done.append(f"removed worktree {worktree}")
        if local:
            git(checkout, "update-ref", "-d", f"refs/heads/{branch}", head)
            done.append(f"deleted local {branch} (was {head[:10]})")
        if remote:
            git(checkout, "push", "-q", f"--force-with-lease=refs/heads/{branch}:{head}",
                "origin", "--delete", f"refs/heads/{branch}")
            done.append(f"deleted remote {branch} (was {head[:10]})")
        else:
            done.append(f"remote {branch} already gone")
        tracking = f"refs/remotes/origin/{branch}"
        if git(checkout, "rev-parse", "--verify", "--quiet", tracking, check=False).returncode == 0:
            git(checkout, "update-ref", "-d", tracking)
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--worktree", type=Path)
    args = parser.parse_args()
    try:
        done = cleanup(args.repo, args.pr, args.checkout, args.worktree)
    except Refused as exc:
        print(f"refused, nothing deleted: {exc}", file=sys.stderr)
        return 1
    print("\n".join(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
