"""Offline capture controls and exact-path restore model; 2026-11-15.

Runs only in a new explicit synthetic directory; never accepts a live worktree.
Inputs: reviewed capture helper and new durable fixture directory. Outputs:
public-safe receipts. No GitHub, production restoration or cleanup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-helper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.output.is_absolute() and args.output == args.output.resolve() and not os.path.lexists(args.output), "New canonical fixture output required")
    args.output.mkdir(mode=0o700)
    root = args.output/"synthetic-repo"
    root.mkdir()
    env = {k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL=os.devnull,GIT_OPTIONAL_LOCKS="0",
               GIT_NO_LAZY_FETCH="1",GIT_LITERAL_PATHSPECS="1",GIT_NO_REPLACE_OBJECTS="1",GIT_GRAFT_FILE=os.devnull)
    def git(*words):
        return subprocess.check_output(["git","-c","core.hooksPath="+os.devnull,"-c","core.fsmonitor=false","-c","core.autocrlf=false","-C",str(root),*words],env=env,stderr=subprocess.PIPE)
    git("init","-q")
    git("remote","add","origin","https://github.com/CultureBotAI/culturebotai-claw.git")
    (root/".gitignore").write_text("cache/\n")
    (root/"staged.bin").write_bytes(b"initial\x00content")
    (root/"unstaged.txt").write_text("initial\n")
    git("add","--all")
    git("-c","user.name=Offline fixture","-c","user.email=offline-fixture.invalid","commit","-qm","fixture")
    head = git("rev-parse","HEAD").decode().strip()
    git("checkout","--detach","-q",head)
    (root/"staged.bin").write_bytes(b"changed\x00content")
    (root/"staged-link").symlink_to("staged.bin")
    git("add","staged.bin","staged-link")
    (root/"unstaged.txt").write_text("unstaged data\n")
    (root/"extra.txt").write_text("preserve me\n")
    (root/"cache").mkdir()
    (root/"cache"/"value").write_text("preserve ignored\n")
    index_raw = (root/".git"/"index").read_bytes()
    copy = args.output/"private.index"
    copy.write_bytes(index_raw)
    def run(name, expected, index):
        destination = args.output/name
        process = subprocess.run([sys.executable,str(args.capture_helper),"--root",str(root),"--output",str(destination),"--expected-head",expected,"--repository","CultureBotAI/culturebotai-claw","--index-copy",str(index)],capture_output=True,env=env,timeout=60)
        return process,destination
    process,destination=run("capture",head,copy)
    require(process.returncode == 0,"Positive capture failed: "+process.stderr.decode())
    capture=json.loads((destination/"capture.json").read_bytes())
    require(capture["staged_paths"] == ["staged-link","staged.bin"] and capture["unstaged_paths"] == ["unstaged.txt"],"Exact lists differ")
    require(capture["untracked_paths"] == ["extra.txt"] and capture["ignored_roots_retained_unmeasured"] == ["cache/"],"Extra inventory differs")
    for name,digest in capture["payload_sha256"].items():
        require(sha((destination/name).read_bytes()) == digest,"Payload readback differs")
    require((root/".git"/"index").read_bytes() == index_raw,"Source index changed")
    wrong_head,dest=run("wrong-head","0"*40,copy)
    require(wrong_head.returncode != 0 and not dest.exists(),"Wrong head accepted")
    mismatch=args.output/"mismatch.index"
    mismatch.write_bytes(index_raw+b"drift")
    wrong_copy,dest=run("wrong-copy",head,mismatch)
    require(wrong_copy.returncode != 0 and not dest.exists(),"Mismatched private index accepted")
    # This restore exercises only our synthetic repository. It uses the exact
    # source/list/NUL/explicit-stage pattern in the reviewed preparation plan.
    git("restore","--source="+head,"--staged","--worktree","--pathspec-from-file="+str(destination/"staged-paths.z"),"--pathspec-file-nul")
    require(not os.path.lexists(root/"staged-link") and (root/"staged.bin").read_bytes() == b"initial\x00content","Staged restoration differs")
    require((root/"unstaged.txt").read_text() == "unstaged data\n","Unselected tracked change lost")
    git("restore","--source="+head,"--worktree","--pathspec-from-file="+str(destination/"unstaged-paths.z"),"--pathspec-file-nul")
    require((root/"unstaged.txt").read_text() == "initial\n","Unstaged restoration differs")
    require((root/"extra.txt").read_text() == "preserve me\n" and (root/"cache"/"value").read_text() == "preserve ignored\n","Extra lost")
    result={"capture_helper_sha256":sha(args.capture_helper.read_bytes()),"review_helper_sha256":sha(Path(__file__).read_bytes()),
            "positive_capture":True,"source_index_preserved":True,"binary_and_symlink_payloads_preserved":True,
            "wrong_head_refused_before_output":True,"wrong_index_refused_before_output":True,
            "synthetic_exact_path_restore":True,"unselected_tracked_change_preserved":True,
            "untracked_and_ignored_preserved":True,"production_writes":False}
    with (args.output/"controls.json").open("x") as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print(json.dumps(result,indent=2))

if __name__ == "__main__":
    main()
