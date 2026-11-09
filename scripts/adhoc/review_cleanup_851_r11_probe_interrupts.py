#!/usr/bin/env python3
# Historical review evidence: a Claude reviewer's probe for PR 851, the eleventh round (560faf2499); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Probe cleanup_merged_pr_branch.py's BaseException handlers (review of PR 851 round 11, 2026-11-08).

Inputs: --script PATH (the cleanup script under review), --raise CLASS
(RuntimeError|KeyboardInterrupt|SystemExit|GeneratorExit), --at remote|tracking|push,
--via main|cleanup, --message TEXT (default: none, as a real Ctrl-C has none),
--keep-local (leave the local branch so a deletion precedes the push).
Outputs: what escaped or was returned, the cause chain, origin's branch state,
whether the lock was released, and (--run-recovery) whether the printed recovery
restores origin's branch. Scratch only; writes nothing in any repository.
"""
from __future__ import annotations

import argparse
import builtins
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=True).stdout.strip()


def ref(path: Path, name: str) -> str | None:
    done = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "--quiet", name],
                          text=True, capture_output=True, check=False)
    return done.stdout.strip() or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--raise", dest="raise_", default="KeyboardInterrupt")
    ap.add_argument("--at", choices=["remote", "tracking", "push"], default="remote")
    ap.add_argument("--via", choices=["main", "cleanup"], default="main")
    ap.add_argument("--message", default=None)
    ap.add_argument("--keep-local", action="store_true")
    ap.add_argument("--run-recovery", action="store_true")
    ap.add_argument("--scratch", type=Path, required=True)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="probe-", dir=args.scratch))
    config = tmp / "gitconfig"
    config.write_text("[user]\n\tname = test\n\temail = test\n[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    os.environ["GIT_CONFIG_GLOBAL"] = str(config)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["OPENCLAW_WORKSPACE"] = str(tmp / "workspace")
    os.environ["OPENCLAW_ORCHESTRATION_ROOT"] = str(tmp)

    source = tmp / "source"
    source.mkdir()
    git(source, "init", "-q")
    (source / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    git(source, "add", ".gitignore")
    git(source, "commit", "-q", "-m", "initial")
    origin = tmp / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(origin)], check=True)
    checkout = tmp / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    worktree = tmp / "wt"
    git(checkout, "worktree", "add", "-q", "-b", "feature", str(worktree), "origin/main")
    (worktree / "change").write_text("change\n", encoding="utf-8")
    git(worktree, "add", "change")
    git(worktree, "commit", "-q", "-m", "change")
    head = git(worktree, "rev-parse", "HEAD")
    git(worktree, "push", "-q", "origin", "HEAD:refs/heads/feature")
    git(checkout, "fetch", "-q", "origin")
    git(checkout, "worktree", "remove", str(worktree))
    if not args.keep_local:
        git(checkout, "branch", "-q", "-D", "feature")

    spec = importlib.util.spec_from_file_location("cleanup_merged_pr_branch", args.script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from kg_microbe_fleet import load_fleet_manifest  # noqa: E402  (resolved through the script's sys.path insert)
    from plugins.lock_manager import LockManager  # noqa: E402

    repo = load_fleet_manifest().mechs["traitmech"].github
    pr = {"state": "MERGED", "headRefName": "feature", "headRefOid": head, "isCrossRepository": False}
    mod.gh_pr_view = lambda r, n: pr
    mod.open_target = lambda key, path, r: None

    exc_class = getattr(builtins, args.raise_)
    exc_args = (args.message,) if args.message is not None else ()
    calls: list[str] = []

    if args.at == "remote":
        real = mod.remote_branch_sha

        def stub(checkout_, branch):
            calls.append(branch)
            if len(calls) == 2:
                raise exc_class(*exc_args)
            return real(checkout_, branch)
        mod.remote_branch_sha = stub
    elif args.at == "tracking":
        real = mod.tracking_sha

        def stub(checkout_, branch):
            calls.append(branch)
            if len(calls) == 2:
                raise exc_class(*exc_args)
            return real(checkout_, branch)
        mod.tracking_sha = stub
    else:  # the signal lands after git applied the push server-side but before subprocess.run returned
        real_git = mod.git

        def stub(path, *gargs, check=True):
            completed = real_git(path, *gargs, check=check)
            if gargs and gargs[0] == "push":
                raise exc_class(*exc_args)
            return completed
        mod.git = stub

    out, err = io.StringIO(), io.StringIO()
    outcome: str
    recovery = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            if args.via == "main":
                sys.argv = ["cleanup_merged_pr_branch.py", "--repo", repo, "--pr", "1", "--checkout", str(checkout), "--apply"]
                rc = mod.main()
                outcome = f"main() returned {rc}"
            else:
                done = mod.cleanup(repo, 1, checkout, None, apply=True, pr_view=lambda r, n: pr,
                                   verify_origin=lambda k, p, r: None)
                outcome = f"cleanup() returned {done}"
    except BaseException as exc:  # noqa: BLE001  (the probe's whole point)
        chain = []
        e: BaseException | None = exc
        while e is not None:
            chain.append(f"{type(e).__name__}({str(e)!r})")
            e = e.__cause__
        outcome = f"escaped: {' <- '.join(chain)}"
        if isinstance(exc, mod.PartialFailure):
            outcome += f"\n  .done={exc.done}\n  .error={type(exc.error).__name__}({str(exc.error)!r})\n  .recovery={exc.recovery}"
            recovery = exc.recovery
    print(outcome)
    print(f"stdout: {out.getvalue()!r}")
    print(f"stderr: {err.getvalue()!r}")
    if recovery is None:
        for line in err.getvalue().splitlines():
            if line.startswith("recovery: "):
                recovery = line[len("recovery: "):]
    print(f"origin feature: {ref(origin, 'refs/heads/feature')}  (head {head[:10]})")
    print(f"local feature: {ref(checkout, 'refs/heads/feature')}  tracking: {ref(checkout, 'refs/remotes/origin/feature')}")
    try:
        with LockManager().lock("traitmech", "probe-after"):
            print("lock: released (re-acquired after the run)")
    except RuntimeError as exc:
        print(f"lock: STILL HELD ({exc})")
    if args.run_recovery and recovery:
        texts = [part.split("`")[1] for part in recovery.split("; ") if "`" in part]
        for text in texts:
            subprocess.run(["bash", "-c", text], check=True, capture_output=True)
        print(f"ran {len(texts)} recovery command(s); origin feature now: {ref(origin, 'refs/heads/feature')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
