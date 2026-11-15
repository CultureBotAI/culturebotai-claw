"""Independent read-only snapshot review; 2026-11-15.

Inputs: explicit private restoration plan, public source package, new output dir.
Reads original snapshots without index-aware Git commands. Reconstructs saved
patches only in fresh synthetic Git fixtures under the new output directory.
Outputs: public-safe hash/count receipts. Never restores or cleans a live tree.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def git(root, *args, input=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1",
               GIT_GRAFT_FILE=os.devnull, GIT_LITERAL_PATHSPECS="1")
    proc = subprocess.run(["git", "-c", "core.hooksPath="+os.devnull, "-c", "core.fsmonitor=false",
                           "-c", "core.autocrlf=false", "-C", str(root), *args], input=input,
                          capture_output=True, env=env, timeout=60)
    require(proc.returncode == 0, "Synthetic/read-only Git operation failed: "+repr(args)+":"+proc.stderr.decode())
    return proc.stdout


def node(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return os.readlink(path).encode(), stat.S_IMODE(info.st_mode), "120000"
    require(stat.S_ISREG(info.st_mode), "Unexpected node kind")
    return path.read_bytes(), stat.S_IMODE(info.st_mode), "100755" if info.st_mode & 0o111 else "100644"


def install(root, name, raw, mode):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "120000":
        path.symlink_to(raw.decode())
    else:
        path.write_bytes(raw)
        path.chmod(0o755 if mode == "100755" else 0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.output.is_absolute() and args.output == args.output.resolve(), "Canonical output required")
    require(not os.path.lexists(args.output), "Output must be new")
    plan_raw = args.plan.read_bytes()
    plan = json.loads(plan_raw)
    provenance = json.loads((args.source_package / "PROVENANCE.json").read_bytes())
    require(sha(plan_raw) == provenance["private_plan_sha256"], "Plan hash mismatch")
    source_hashes = {}
    for name, digest in provenance["helpers"].items():
        require(sha((args.source_package/name).read_bytes()) == digest, "Helper hash mismatch")
        source_hashes[name] = digest
    for row in plan["snapshots"]:
        source = Path(row["source_root"])
        require(source not in args.output.parents and args.output not in source.parents, "Output/source overlap")
    args.output.mkdir(mode=0o700)
    rows = []
    for row in plan["snapshots"]:
        capture_path = Path(row["capture"])
        captured_raw = capture_path.read_bytes()
        require(sha(captured_raw) == row["capture_sha256"], "Capture hash mismatch")
        captured = json.loads(captured_raw)
        bundle, source = capture_path.parent, Path(row["source_root"])
        require(captured["root"] == str(source) and captured["head"] == row["source_head"], "Identity mismatch")
        for name, digest in captured["payload_sha256"].items():
            require(sha((bundle/name).read_bytes()) == digest, "Payload hash mismatch")
        require((Path(captured["gitdir"])/"index").read_bytes() == (bundle/"original.index").read_bytes(), "Live index drift")
        require(git(source, "rev-parse", "HEAD").decode().strip() == captured["head"], "Live head drift")
        for name, expected in captured["worktree_entries"].items():
            if expected["kind"] == "absent":
                require(not os.path.lexists(source/name), "Absent source appeared")
            else:
                raw, mode, gitmode = node(source/name)
                require(sha(raw) == expected["sha256"] and mode == expected["mode"] and gitmode == expected["git_mode"], "Live source drift")
        require(captured["staged_paths"] == row["exact_staged_paths"], "Staged path mismatch")
        require(captured["unstaged_paths"] == row["exact_unstaged_paths"], "Unstaged path mismatch")
        require(captured["untracked_paths"] == row["retained_untracked_paths"], "Untracked path mismatch")
        selected = row["exact_staged_paths"] or row["exact_unstaged_paths"]
        path_raw = Path(row["restore_pathspec"]).read_bytes()
        require(sha(path_raw) == row["restore_pathspec_sha256"], "Path-list digest mismatch")
        require(path_raw == b"\0".join(name.encode() for name in selected)+b"\0", "Path-list mismatch")
        restore = row["git_arguments_after_validated_prefix"]
        require(restore[:2] == ["restore", "--source="+captured["head"]], "Restore source mismatch")
        require("--worktree" in restore and ("--staged" in restore) == bool(row["exact_staged_paths"]), "Restore mode mismatch")
        require("--pathspec-file-nul" in restore, "Nonliteral list")
        fixture = args.output / row["label"]
        fixture.mkdir()
        git(fixture, "init", "-q")
        for name, entry in captured["head_entries"].items():
            if entry is not None:
                raw = (bundle/"head"/name).read_bytes()
                require(git(source,"cat-file","blob",entry["oid"]) == raw, "HEAD object mismatch")
                install(fixture,name,raw,entry["mode"])
        git(fixture,"add","--all")
        patch = (bundle/"staged.patch").read_bytes()
        if patch:
            git(fixture,"apply","--index","--binary","--whitespace=nowarn","-", input=patch)
        for name, entry in captured["index_entries"].items():
            if entry is not None:
                raw = (bundle/"index"/name).read_bytes()
                require(git(source,"cat-file","blob",entry["oid"]) == raw, "Index object mismatch")
                require(git(fixture,"show",":"+name) == raw, "Reconstructed index mismatch")
            else:
                require(not os.path.lexists(fixture/name), "Unexpected reconstructed index path")
        patch = (bundle/"unstaged.patch").read_bytes()
        if patch:
            git(fixture,"apply","--binary","--whitespace=nowarn","-", input=patch)
        changed = set(captured["staged_paths"]) | set(captured["unstaged_paths"])
        for name in changed:
            expected = captured["worktree_entries"].get(name)
            if expected is None or expected["kind"] == "absent":
                require(not os.path.lexists(fixture/name), "Unexpected reconstructed path")
            else:
                raw, _, mode = node(fixture/name)
                require(sha(raw) == expected["sha256"] and mode == expected["git_mode"], "Reconstructed worktree mismatch")
        for name in captured["untracked_paths"]:
            expected = captured["worktree_entries"][name]
            require(sha((bundle/"untracked"/name).read_bytes()) == expected["sha256"], "Untracked copy mismatch")
        rows.append({"label":row["label"], "capture_sha256":sha(captured_raw), "head":captured["head"],
                     "payload_count":len(captured["payload_sha256"]), "staged_count":len(captured["staged_paths"]),
                     "unstaged_count":len(captured["unstaged_paths"]), "untracked_count":len(captured["untracked_paths"]),
                     "all_payloads_exact":True, "live_selected_state_unchanged":True,
                     "patch_roundtrip_exact":True, "restoration_performed":False})
    result={"plan_sha256":sha(plan_raw), "helper_sha256":sha(Path(__file__).read_bytes()),
            "reviewed_sources":source_hashes,"snapshots":rows,"live_writes":False}
    with (args.output/"verification.json").open("x") as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print(json.dumps(result,indent=2))

if __name__ == "__main__":
    main()
