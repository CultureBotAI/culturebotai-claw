"""Retained PR1197 actual-main integration helper, 2026-11-15, issue1262.

Explicit worktree, expected head/main/common-Git and shared lock inputs. Preview
is read-only. Apply performs exact-object fetch then an ordinary no-FF merge in
short owned metadata leases. No push, GitHub write, cleanup or runtime action.
Checks, baseline validation and independent review occur outside the leases.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
from plugins.lock_manager import LockManager


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--common-git",type=Path,required=True)
    parser.add_argument("--locks",type=Path,required=True)
    parser.add_argument("--expected-head",required=True)
    parser.add_argument("--expected-main",required=True)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    for path in (args.root,args.common_git,args.locks):
        if not path.is_absolute() or path != path.resolve():
            raise ValueError("Canonical explicit paths required")
    env={k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0",GIT_NO_REPLACE_OBJECTS="1",GIT_NO_LAZY_FETCH="1",GIT_GRAFT_FILE=os.devnull)
    base=["git","-c","core.hooksPath="+os.devnull,"-c","core.fsmonitor=false","-c","commit.gpgsign=false","-c","gc.auto=0","-C",str(args.root)]
    def git(*words):
        return subprocess.check_output([*base,*words],env=env,stderr=subprocess.PIPE,timeout=30).decode().strip()
    def preflight():
        if git("rev-parse","HEAD") != args.expected_head:
            raise ValueError("Head changed")
        if git("status","--porcelain=v1","--untracked-files=all"):
            raise ValueError("Owned worktree must be clean")
        if Path(git("rev-parse","--git-common-dir")).resolve() != args.common_git:
            raise ValueError("Common Git mismatch")
        if git("branch","--show-current") != "repair/pr1197-baseline-20261115":
            raise ValueError("Wrong owned repair branch")
        if git("remote","get-url","origin") != "https://github.com/CultureBotAI/culturebotai-claw.git":
            raise ValueError("Wrong repository identity")
        gitdir=Path(git("rev-parse","--absolute-git-dir"))
        for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","REBASE_HEAD","rebase-merge","rebase-apply","sequencer","index.lock"):
            if (gitdir/name).exists():
                raise ValueError("Existing operation refused")
    def live_main():
        value=subprocess.check_output(["gh","api","repos/CultureBotAI/culturebotai-claw/commits/main","--jq",".sha"],env=env,timeout=30).decode().strip()
        if value != args.expected_main:
            raise ValueError("Published main changed")
    preflight()
    live_main()
    if not args.apply:
        print(json.dumps({"status":"preview","head":args.expected_head,"main":args.expected_main}))
        return
    manager=LockManager({"locks_dir":str(args.locks),"my_id":"stream-c-1197-refresh","default_timeout":60})
    with manager.lock("claw","fetch-pr1197-actual-main"):
        preflight()
        git("fetch","--no-tags","--no-write-fetch-head","origin",args.expected_main)
    live_main()
    with manager.lock("claw","merge-pr1197-actual-main"):
        preflight()
        git("merge","--no-ff",args.expected_main,"-m","Merge published main after port-pressure integration (#1262)")
    head=git("rev-parse","HEAD")
    if git("rev-list","--parents","-n","1",head).split() != [head,args.expected_head,args.expected_main]:
        raise ValueError("Unexpected merge parents")
    if git("status","--porcelain=v1","--untracked-files=all"):
        raise ValueError("Integration left unexpected worktree changes")
    print(json.dumps({"status":"integrated-local-only","head":head,"tree":git("rev-parse","HEAD^{tree}"),
                      "parents":[args.expected_head,args.expected_main],"push_performed":False,"runtime_actions":False},indent=2))

if __name__ == "__main__":
    main()
