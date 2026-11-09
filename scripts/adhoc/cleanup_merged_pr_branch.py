#!/usr/bin/env python3
"""After a PR merges, delete its branch remotely and locally and remove its worktree.

Purpose: the Git workflow ends each PR by deleting its branch, remote and local.
This does that for one merged PR, and deletes nothing it cannot show is the
merged work. It checks everything first, and deletes only if every check passes:
- GitHub reports the PR MERGED, from a branch of the same repository (not a fork);
- --checkout's fetch and push origin is --repo (RepositoryTarget);
- the worktree, if given, is a linked, unlocked worktree of --checkout and not
  --checkout itself, at the merged head, with nothing modified or untracked,
  no ignored file other than a regenerable cache, and no index entry hidden
  from `git status` (skip-worktree or assume-unchanged); it is checked again
  immediately before it is removed;
- the local branch, if present, is a plain ref (not symbolic) at the merged
  head and checked out nowhere else; it is removed with a compare-and-delete
  that does not follow symbolic refs, and its config section after it;
- the remote-tracking ref, if present, is a plain ref at the merged head; after
  the remote delete it is removed with the same compare-and-delete if git left
  it, and recorded as gone with the remote branch if git removed it on the
  push (git 2.56 does, 2.50 does not, even for a push to the remote's URL);
- origin's fetch refspecs map refs/heads/<branch> nowhere but its tracking
  ref, since a push updates whatever local refs they map, on some git versions
  whether it goes to the remote's name or its URL;
- the remote branch, if present, is exactly refs/heads/<branch> at the merged
  head; it is removed with a lease on that head, pushed to the remote's URL
  rather than its name, which on the gits that distinguish touches no local
  ref; a url.<base>.pushInsteadOf that would redirect that URL is refused,
  since git applies it to a bare URL and not to an explicit pushurl, and after
  the push origin is asked again, so a delete that went elsewhere is a failure.
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
failure after one, which prints every step that completed and the shell-quoted
commands that recreate exactly what was removed: the branch at the head, the
worktree on it or detached as it was, every entry of its config section, the
remote branch.
Serves: the culturebotai-claw#729 related-issue PRs. Written 2026-11-05. The
first version (commit 1396fe0534 in culturebotai-claw PR 851) cleaned up
CellStructureMech PR 3068. Rewritten 2026-11-06 for culturebotai-claw#854,
#855, #856 and #858, for #867-#870 and #872 from the second review round,
for #873-#875 and #880 from the third, for #893-#895 from the fourth, for
#920 and #921 from the fifth, and on 2026-11-07 for #931-#936 from the Codex
review, #950 from CI's git 2.56, #974-#977 from the review of that round, and
#1010-#1014 from the review of that one, and #1037-#1039 from the review of that,
before its reuse on further merged PRs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
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


def fetch_mappings(checkout: Path, ref: str) -> list[tuple[str, str]]:
    """Where origin's fetch refspecs map `ref` locally: (refspec, destination) for each that matches it.

    A push updates these refs as a side effect; on git 2.56 even a push to the remote's URL does.
    A negative refspec (^src, which git allows no destination) and a destination-less one map nothing.
    """
    mappings = []
    for spec in filter(None, git(checkout, "config", "--get-all", "remote.origin.fetch", check=False).stdout.split("\n")):
        body = spec[1:] if spec.startswith("+") else spec
        if ":" not in body:
            continue
        src, dst = body.split(":", 1)
        if not dst:  # `refs/heads/x:` fetches into FETCH_HEAD only and stores nothing
            continue
        if "*" in src:
            prefix, suffix = src.split("*", 1)
            if ref.startswith(prefix) and ref.endswith(suffix) and len(ref) >= len(prefix) + len(suffix):
                mappings.append((spec, dst.replace("*", ref[len(prefix):len(ref) - len(suffix)], 1)))
        elif src == ref:
            mappings.append((spec, dst))
    return mappings


def symbolic_target(checkout: Path, ref: str) -> str:
    """What a symbolic ref points at, or '' for a plain ref (or no ref)."""
    return git(checkout, "symbolic-ref", "--quiet", ref, check=False).stdout.strip()


def branch_config(checkout: Path, branch: str) -> list[tuple[str, str | None]]:
    """Every (key, value) of the branch's config section, in file order; None for a key set without a value.

    NUL-separated, so a value holding a newline (`git branch --edit-description`) is one entry, not several.
    """
    listed = git(checkout, "config", "-z", "--get-regexp", f"^branch\\.{re.escape(branch)}\\.", check=False)
    if listed.returncode != 0:
        return []
    entries: list[tuple[str, str | None]] = []
    for entry in listed.stdout.split("\0"):
        if entry:
            key, newline, value = entry.partition("\n")
            entries.append((key, value if newline else None))
    return entries


def recovery_for(done: list[str], checkout: Path, worktree: Path | None, branch: str, head: str, *,
                 worktree_on_branch: bool, config_entries: list[tuple[str, str | None]]) -> str:
    """The shell-quoted commands that put back exactly what `done` says went, in the order they must run."""
    c = str(checkout)
    steps = [f"everything removed was at {head}"]
    if any(step.startswith("deleted local ") for step in done):
        steps.append("recreate the branch with `" + shlex.join(["git", "-C", c, "branch", branch, head]) + "`")
    if any(step.startswith("removed worktree ") for step in done):
        if worktree_on_branch:
            steps.append("the worktree with `" + shlex.join(["git", "-C", c, "worktree", "add", str(worktree), branch]) + "`")
        else:  # the worktree was detached; there is no branch to put it on
            steps.append("the worktree with `"
                         + shlex.join(["git", "-C", c, "worktree", "add", "--detach", str(worktree), head]) + "`")
    if any(step.startswith("removed branch.") for step in done):
        for key, value in config_entries:
            if value is None:  # set without a value, which git reads as true and `git config` cannot write back as such
                steps.append("its config with `" + shlex.join(["git", "-C", c, "config", "--add", key, "true"])
                             + "` (it was set without a value)")
            else:
                steps.append("its config with `" + shlex.join(["git", "-C", c, "config", "--add", key, value]) + "`")
    if any(step.startswith("deleted remote ") for step in done):
        steps.append("the remote branch with `"
                     + shlex.join(["git", "-C", c, "push", "origin", f"{head}:refs/heads/{branch}"]) + "`")
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
    local_ref, tracking = f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"
    with LockManager().lock(key, "cleanup-merged-branch"):
        verify_origin(key, checkout, repo)
        problems = []
        entries = worktree_entries(checkout)
        removing = worktree is not None and worktree.exists()
        worktree_on_branch = False
        skipped: list[str] = []
        if worktree is not None and not removing:
            if any(e["path"] == worktree for e in entries):
                problems.append(f"{worktree} is registered but missing on disk; run `"
                                + shlex.join(["git", "-C", str(checkout), "worktree", "prune"]) + "` first")
            else:
                skipped.append(f"worktree {worktree} is not present, skipped")
        if removing:
            entry = next((e for e in entries if e["path"] == worktree), None)
            if entry is None:
                problems.append(f"{worktree} is not a worktree of {checkout}")
            elif entry["main"]:
                problems.append(f"{worktree} is the main worktree of {checkout}")
            elif entry["path"] == checkout:
                problems.append(f"{worktree} is --checkout itself; name the clone it belongs to")
            elif entry["locked"]:
                problems.append(f"{worktree} is locked; `git worktree unlock` it first if it should go")
            else:
                problems += worktree_problems(worktree, head)
                worktree_on_branch = entry["branch"] == local_ref
        for ref in (local_ref, tracking):
            target = symbolic_target(checkout, ref)
            if target:
                problems.append(f"{ref} is a symbolic ref to {target}; this tool deletes only plain refs")
        local = git(checkout, "rev-parse", "--verify", "--quiet", local_ref, check=False).stdout.strip()
        if local and local != head:
            problems.append(f"local {branch} is {local[:10]}, not the merged head {head[:10]}")
        others = [e["path"] for e in entries if e["branch"] == local_ref and not (removing and e["path"] == worktree)]
        if local and others:
            problems.append(f"{branch} is also checked out in {', '.join(map(str, others))}")
        tracked = tracking_sha(checkout, branch)
        if tracked and tracked != head:
            problems.append(f"{tracking} is {tracked[:10]}, not the merged head {head[:10]}")
        remote = remote_branch_sha(checkout, branch)
        if remote and remote != head:
            problems.append(f"origin {branch} is {remote[:10]}, not the merged head {head[:10]}")
        for spec, destination in fetch_mappings(checkout, local_ref):
            if destination != tracking:
                problems.append(f"remote.origin.fetch {spec} maps {local_ref} onto {destination}, which a push can "
                                f"update; this tool touches only {tracking}")
        push_url = git(checkout, "remote", "get-url", "--push", "origin").stdout.strip()
        # git applies url.<base>.pushInsteadOf to a bare URL on the command line and not to a remote with an
        # explicit pushurl, so the configured URL this tool pushes to could be sent elsewhere.
        rewrites = git(checkout, "config", "-z", "--get-regexp", r"^url\..*\.pushinsteadof$", check=False).stdout
        for entry in filter(None, rewrites.split("\0")):
            key, _, prefix = entry.partition("\n")
            if prefix and push_url.startswith(prefix):
                problems.append(f"{key} {prefix} would send a push to {push_url} elsewhere; unset it first")
        if problems:
            raise Refused("; ".join(problems))
        if not apply:
            return (skipped + [f"would remove worktree {worktree}"] * removing
                    + [f"would delete local {branch} (at {head[:10]})"] * bool(local)
                    + [f"would delete remote {branch} (at {head[:10]})" if remote else f"remote {branch} already gone"]
                    + [f"would delete {tracking} (at {head[:10]})"] * bool(tracked))
        config_entries = branch_config(checkout, branch)
        done: list[str] = list(skipped)
        try:
            if removing:
                again = worktree_problems(worktree, head)
                if again:
                    raise RuntimeError(f"{worktree} changed after the check: " + "; ".join(again))
                git(checkout, "worktree", "remove", str(worktree))
                done.append(f"removed worktree {worktree}")
            if local:
                git(checkout, "update-ref", "--no-deref", "-d", local_ref, head)
                done.append(f"deleted local {branch} (was {head[:10]})")
                # update-ref leaves the branch's config section; `branch -D` would have removed it.
                if config_entries:
                    git(checkout, "config", "--remove-section", f"branch.{branch}", check=False)
                    leftover = branch_config(checkout, branch)
                    if leftover:
                        raise RuntimeError(f"branch.{branch} config is still set: " + ", ".join(k for k, _ in leftover))
                    done.append(f"removed branch.{branch} config ({len(config_entries)} entries)")
                else:
                    done.append(f"no branch.{branch} config to remove")
            if remote:
                # To the URL, not the remote name: on the gits that distinguish, that updates no local
                # ref. On git 2.56 it still updates what the fetch refspecs map, which the checks above
                # confined to the tracking ref; its disappearance is read back below.
                git(checkout, "push", "-q", f"--force-with-lease={local_ref}:{head}", push_url, "--delete", local_ref)
                try:
                    still = remote_branch_sha(checkout, branch)
                except BaseException as exc:  # an interrupt here must leave the record too
                    # The delete was accepted; the recovery must still name the push that puts the branch back.
                    done.append(f"deleted remote {branch} (was {head[:10]}; accepted, not confirmed)")
                    raise RuntimeError(f"origin accepted the delete but could not be asked again: {exc}") from exc
                if still:
                    raise RuntimeError(f"origin still has {branch} at {still[:10]} after the delete was accepted; "
                                       "the push went elsewhere")
                done.append(f"deleted remote {branch} (was {head[:10]})")
            else:
                done.append(f"remote {branch} already gone")
            if tracked:
                now = tracking_sha(checkout, branch)
                if not now:
                    done.append(f"{tracking} went with the remote branch (was {head[:10]})")
                elif now != head:
                    raise RuntimeError(f"{tracking} is {now[:10]} after the push, not the merged head {head[:10]}; "
                                       "left in place")
                else:
                    git(checkout, "update-ref", "--no-deref", "-d", tracking, head)
                    done.append(f"deleted {tracking} (was {head[:10]})")
        except BaseException as exc:  # a KeyboardInterrupt after a deletion still gets the record and the recovery
            if not any(step.startswith(("removed ", "deleted ")) for step in done):
                raise
            raise PartialFailure(done, exc, recovery_for(done, checkout, worktree, branch, head,
                                                         worktree_on_branch=worktree_on_branch,
                                                         config_entries=config_entries)) from exc
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
