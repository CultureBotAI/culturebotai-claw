#!/usr/bin/env python3
"""Preserve evidence worktrees while retiring merged edge-curation branches.

Purpose: user-authorized PR #762 / KG #1718 merge cleanup, 2026-11-04.
Inputs: explicit checkout, shared CLAW coordination root, operation and reviewed SHA.
Output: refreshed default ref or detached HEAD / removed local feature ref.
Default is a read-only plan. No file removal, checkout, merge, push or remote deletion.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

TARGETS = {
    "kg-microbe": (
        "Knowledge-Graph-Hub/kg-microbe", "master", "feat/edge-curation-snapshot-20261103", 1718
    ),
    "claw": (
        "CultureBotAI/culturebotai-claw", "main", "feat/edge-curation-ledger-20261103", 762
    ),
}


def run(command: list[str], *, allow: tuple[int, ...] = (0,), timeout: int = 20) -> str:
    """Bound every child and retain non-success as an error."""
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode not in allow:
        raise RuntimeError(f"Command failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def verify_root(git: str, root: Path, repository: str) -> None:
    """Only act at an explicitly selected checkout with the expected Git identity."""
    actual = Path(run([git, "-C", str(root), "rev-parse", "--show-toplevel"])).resolve()
    origin = run([git, "-C", str(root), "remote", "get-url", "origin"])
    if actual != root or origin.removesuffix(".git") != f"https://github.com/{repository}":
        raise ValueError("Unexpected checkout root or repository origin")


def command_for(args: argparse.Namespace, git: str) -> list[str]:
    """Check merged PR identity and exact local state before constructing a mutation."""
    repository, base, branch, number = TARGETS[args.target]
    prefix = [git, "-C", str(args.repository)]
    if args.operation == "fetch":
        return [*prefix, "fetch", "--no-tags", "origin", f"refs/heads/{base}:refs/remotes/origin/{base}"]
    if not args.head or not re.fullmatch(r"[a-f0-9]{40}", args.head):
        raise ValueError("Cleanup requires the complete reviewed head SHA")
    gh = shutil.which("gh")
    if gh is None:
        raise ValueError("gh is required for merged-PR verification")
    pr = json.loads(run([
        gh, "pr", "view", str(number), "--repo", repository, "--json",
        "state,baseRefName,headRefName,headRefOid,headRepository,mergeCommit",
    ]))
    if (
        pr["state"] != "MERGED" or pr["baseRefName"] != base
        or pr["headRefName"] != branch or pr["headRefOid"] != args.head
        or pr["headRepository"]["nameWithOwner"] != repository
    ):
        raise ValueError("PR is not the expected merged candidate")
    run([*prefix, "merge-base", "--is-ancestor", pr["mergeCommit"]["oid"], f"origin/{base}"])
    if run([*prefix, "rev-parse", "HEAD"]) != args.head:
        raise ValueError("Worktree HEAD differs from the reviewed candidate")
    if run([*prefix, "rev-parse", f"refs/heads/{branch}"]) != args.head:
        raise ValueError("Feature branch moved after review")
    run([*prefix, "diff", "--quiet"])
    run([*prefix, "diff", "--cached", "--quiet"])
    symbolic = run([*prefix, "symbolic-ref", "-q", "HEAD"], allow=(0, 1))
    if args.operation == "detach":
        if symbolic != f"refs/heads/{branch}":
            raise ValueError("Worktree is not on the approved feature branch")
        # Rewrite only HEAD at the same object: tracked, ignored and untracked
        # files are untouched, unlike switching this evidence worktree to main.
        return [*prefix, "update-ref", "--no-deref", "HEAD", args.head, args.head]
    if symbolic:
        raise ValueError("Detach the evidence worktree before deleting its branch")
    if f"branch refs/heads/{branch}" in run([*prefix, "worktree", "list", "--porcelain"]).splitlines():
        raise ValueError("Feature branch is still checked out in a worktree")
    return [*prefix, "update-ref", "-d", f"refs/heads/{branch}", args.head]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--claw-root", type=Path, required=True)
    parser.add_argument("--operation", choices=("fetch", "detach", "delete"), required=True)
    parser.add_argument("--head")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    args.repository = args.repository.resolve(strict=True)
    args.claw_root = args.claw_root.resolve(strict=True)
    git = shutil.which("git")
    if git is None:
        parser.error("git is required")
    verify_root(git, args.repository, TARGETS[args.target][0])
    verify_root(git, args.claw_root, TARGETS["claw"][0])
    command = command_for(args, git)
    if not args.apply:
        print(json.dumps({"mode": "plan", "command": command}))
        return
    code_root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(code_root), str(code_root / "src")]
    os.environ["OPENCLAW_ORCHESTRATION_ROOT"] = str(args.claw_root)
    from plugins.lock_manager import LockManager

    def interrupted(signum: int, _frame: object) -> None:
        # subprocess.run's context closes/waits for its child on BaseException
        # before the outer lock context releases the owned lease.
        raise SystemExit(128 + signum)

    for handled in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(handled, interrupted)
    manager = LockManager({"my_id": f"edge-curation-cleanup-{os.getpid()}"})
    with manager.lock(args.target, "edge-curation-metadata", timeout=600):
        verify_root(git, args.repository, TARGETS[args.target][0])
        if command_for(args, git) != command:
            raise ValueError("Metadata plan changed before execution")
        run(command, timeout=240)
    print(json.dumps({"mode": "applied", "command": command}))


if __name__ == "__main__":
    main()
