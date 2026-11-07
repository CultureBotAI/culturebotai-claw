#!/usr/bin/env python3
"""After a PR merges, delete its branch remotely and locally and remove its worktree.

Purpose: the Git workflow ends each PR by deleting its branch, remote and local.
This does that for one merged PR, and deletes nothing it cannot show is the
merged work. It checks everything first, and deletes only if every check passes:
- GitHub reports the PR MERGED, from a branch of the same repository (not a fork);
- --checkout's fetch and push origin is --repo (RepositoryTarget);
- the worktree, if given, is a linked, unlocked worktree of --checkout, at the
  merged head, with nothing modified or untracked, no ignored file other than
  a regenerable cache, and no index entry hidden from `git status`
  (skip-worktree or assume-unchanged);
- the local branch, if present, is at the merged head and checked out nowhere
  else; it is removed with a compare-and-delete, and its config section after it;
- the remote-tracking ref, if present, is at the merged head; it is removed
  with a compare-and-delete;
- the remote branch, if present, is exactly refs/heads/<branch> at the merged
  head; it is removed with a lease on that head, so a later push survives.
All of this runs under the repository's LockManager lease: the manifest key for
a Mech, `claw` for this repository. Paths are resolved once, against the
current directory, before anything is checked.
Without --apply it is a dry run: every check runs, under the lock, and it prints
what --apply would delete. A dry run therefore refuses wherever --apply would.
Requires: claw's .env exported first (set -a; . ./.env). It refuses to run
unless OPENCLAW_WORKSPACE is set to an absolute path, as that .env sets it; it
cannot tell whether the path is claw's, so exporting the .env stays the
caller's job.
Inputs: --repo OWNER/NAME (claw or a manifest Mech), --pr N, --checkout PATH
(the clone the worktree belongs to), --worktree PATH (optional), --apply.
Outputs: prints each planned or completed step. Exits 1 on a refusal or on a
failure before the first deletion (both say nothing was deleted), and on a
failure after one, which prints every step that completed and the commands
that recreate exactly what was removed.
Serves: the culturebotai-claw#729 related-issue PRs. Written 2026-11-05. The
first version (commit 1396fe0534 in culturebotai-claw PR 851) cleaned up
CellStructureMech PR 3068. Rewritten 2026-11-06 for culturebotai-claw#854,
#855, #856 and #858, for #867-#870 and #872 from the second review round, and
for #873-#875 and #880 from the third, and for #893-#895 from the fourth, before
its reuse on further merged PRs.
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
REGENERABLE_FILES = {".coverage", ".DS_Store"}
REGENERABLE_SUFFIXES = (".egg-info",)
# Explicit, so no status.showUntrackedFiles setting can hide untracked or ignored files.
STATUS = ("status", "--porcelain", "--ignored=traditional", "--untracked-files=normal")


class Refused(RuntimeError):
    """A check failed; nothing has been deleted."""


class PartialFailure(RuntimeError):
    """A deletion failed after an earlier one succeeded; `done` lists what had completed."""

    def __init__(self, done: list[str], error: Exception, recovery: str):
        super().__init__(str(error))
        self.done, self.error, self.recovery = done, error, recovery


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
    RepositoryTarget(name=key, path=path, expected_repository=repo).open()


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
            or path.name in REGENERABLE_FILES)


def hidden_entries(path: Path) -> list[str]:
    """Index entries `git status` cannot report changes to: skip-worktree (S) or assume-unchanged (h)."""
    return [line for line in git(path, "ls-files", "-v").stdout.split("\n") if line and not line.startswith("H ")]


def worktree_problems(worktree: Path, head: str) -> list[str]:
    problems = []
    actual = git(worktree, "rev-parse", "HEAD").stdout.strip()
    if actual != head:
        problems.append(f"{worktree} is at {actual[:10]}, not the merged head {head[:10]}")
    for line in git(worktree, *STATUS).stdout.split("\n"):
        if line and not (line.startswith("!! ") and _regenerable(line)):
            problems.append(f"{worktree}: {line}")
    hidden = hidden_entries(worktree)
    if hidden:
        problems.append(f"{worktree}: {len(hidden)} index entries are skip-worktree or assume-unchanged, "
                        f"so status cannot see their changes: {', '.join(hidden[:3])}")
    return problems


def worktree_entries(checkout: Path) -> list[dict]:
    """Every worktree of the checkout: resolved path, checked-out branch ref, locked, and whether it is the main one."""
    entries: list[dict] = []
    for line in git(checkout, "worktree", "list", "--porcelain").stdout.split("\n"):
        if line.startswith("worktree "):
            entries.append({"path": Path(line[len("worktree "):]).resolve(), "branch": None, "locked": False,
                            "main": not entries})
        elif entries and line.startswith("branch "):
            entries[-1]["branch"] = line[len("branch "):]
        elif entries and (line == "locked" or line.startswith("locked ")):
            entries[-1]["locked"] = True
    return entries


def remote_branch_sha(checkout: Path, branch: str) -> str | None:
    ref = f"refs/heads/{branch}"
    listed = git(checkout, "ls-remote", "origin", ref).stdout.split("\n")
    shas = [line.split("\t")[0] for line in listed if line.endswith(f"\t{ref}")]
    return shas[0] if shas else None


def tracking_sha(checkout: Path, branch: str) -> str:
    return git(checkout, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", check=False).stdout.strip()


def recovery_for(done: list[str], checkout: Path, worktree: Path | None, branch: str, head: str) -> str:
    steps = [f"everything removed was at {head}"]
    if any(step.startswith("deleted local ") for step in done):
        steps.append(f"recreate the branch with `git -C {checkout} branch {branch} {head}`")
    if any(step.startswith("removed worktree ") for step in done):
        if any(step.startswith("deleted local ") for step in done):
            steps.append(f"the worktree with `git -C {checkout} worktree add {worktree} {branch}`")
        else:  # the worktree was detached; there is no branch to put it on
            steps.append(f"the worktree with `git -C {checkout} worktree add --detach {worktree} {head}`")
    if any(step.startswith("deleted remote ") for step in done):
        steps.append(f"the remote branch with `git -C {checkout} push origin {head}:refs/heads/{branch}`")
    return "; ".join(steps)


def cleanup(repo: str, number: int, checkout: Path, worktree: Path | None, *, apply: bool = False,
            pr_view: Callable[[str, int], dict] | None = None,
            verify_origin: Callable[[str, Path, str], None] | None = None) -> list[str]:
    pr_view = pr_view or gh_pr_view
    verify_origin = verify_origin or open_target
    checkout = checkout.resolve()
    worktree = worktree.resolve() if worktree is not None else None
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
    tracking = f"refs/remotes/origin/{branch}"
    with LockManager().lock(key, "cleanup-merged-branch"):
        verify_origin(key, checkout, repo)
        problems = []
        entries = worktree_entries(checkout)
        removing = worktree is not None and worktree.exists()
        skipped: list[str] = []
        if worktree is not None and not removing:
            if any(e["path"] == worktree for e in entries):
                problems.append(f"{worktree} is registered but missing on disk; run `git -C {checkout} worktree prune` first")
            else:
                skipped.append(f"worktree {worktree} is not present, skipped")
        if removing:
            entry = next((e for e in entries if e["path"] == worktree), None)
            if entry is None:
                problems.append(f"{worktree} is not a worktree of {checkout}")
            elif entry["main"]:
                problems.append(f"{worktree} is the main worktree of {checkout}")
            elif entry["locked"]:
                problems.append(f"{worktree} is locked; `git worktree unlock` it first if it should go")
            else:
                problems += worktree_problems(worktree, head)
        local = git(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                    check=False).stdout.strip()
        if local and local != head:
            problems.append(f"local {branch} is {local[:10]}, not the merged head {head[:10]}")
        others = [e["path"] for e in entries
                  if e["branch"] == f"refs/heads/{branch}" and not (removing and e["path"] == worktree)]
        if local and others:
            problems.append(f"{branch} is also checked out in {', '.join(map(str, others))}")
        tracked = tracking_sha(checkout, branch)
        if tracked and tracked != head:
            problems.append(f"{tracking} is {tracked[:10]}, not the merged head {head[:10]}")
        remote = remote_branch_sha(checkout, branch)
        if remote and remote != head:
            problems.append(f"origin {branch} is {remote[:10]}, not the merged head {head[:10]}")
        if problems:
            raise Refused("; ".join(problems))
        if not apply:
            return (skipped + [f"would remove worktree {worktree}"] * removing
                    + [f"would delete local {branch} (at {head[:10]})"] * bool(local)
                    + [f"would delete remote {branch} (at {head[:10]})" if remote else f"remote {branch} already gone"]
                    + [f"would delete {tracking} (at {head[:10]})"] * bool(tracked))
        done: list[str] = list(skipped)
        try:
            if removing:
                git(checkout, "worktree", "remove", str(worktree))
                done.append(f"removed worktree {worktree}")
            if local:
                git(checkout, "update-ref", "-d", f"refs/heads/{branch}", head)
                done.append(f"deleted local {branch} (was {head[:10]})")
                # update-ref leaves the branch's upstream config; `branch -D` would have removed it.
                removed = git(checkout, "config", "--remove-section", f"branch.{branch}", check=False).returncode == 0
                leftover = [name for name in ("remote", "merge")
                            if git(checkout, "config", "--get", f"branch.{branch}.{name}", check=False).returncode == 0]
                if leftover:
                    raise RuntimeError(f"branch.{branch}.{leftover[0]} is still set")
                done.append(f"removed branch.{branch} config" if removed else f"no branch.{branch} config to remove")
            if remote:
                git(checkout, "push", "-q", f"--force-with-lease=refs/heads/{branch}:{head}",
                    "origin", "--delete", f"refs/heads/{branch}")
                done.append(f"deleted remote {branch} (was {head[:10]})")
            else:
                done.append(f"remote {branch} already gone")
            if tracked and not tracking_sha(checkout, branch):
                done.append(f"{tracking} went with the remote branch (was {head[:10]})")  # push --delete drops it
            elif tracked:
                git(checkout, "update-ref", "-d", tracking, head)
                done.append(f"deleted {tracking} (was {head[:10]})")
        except Exception as exc:
            if not any(step.startswith(("removed ", "deleted ")) for step in done):
                raise
            raise PartialFailure(done, exc, recovery_for(done, checkout, worktree, branch, head)) from exc
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--apply", action="store_true", help="delete; without it, check and print the plan")
    args = parser.parse_args()
    try:
        done = cleanup(args.repo, args.pr, args.checkout, args.worktree, apply=args.apply)
    except Refused as exc:
        print(f"refused, nothing deleted: {exc}", file=sys.stderr)
        return 1
    except PartialFailure as exc:
        for step in exc.done:
            print(step)
        print(f"failed after the steps above: {exc.error}", file=sys.stderr)
        print(f"recovery: {exc.recovery}", file=sys.stderr)
        return 1
    except Exception as exc:  # raised before the first deletion
        print(f"failed, nothing deleted: {exc}", file=sys.stderr)
        return 1
    print("\n".join(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
