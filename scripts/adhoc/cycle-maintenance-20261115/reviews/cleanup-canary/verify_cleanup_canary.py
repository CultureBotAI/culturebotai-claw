"""Read-only independent cleanup-canary verification, 2026-11-15.

Inputs: explicit quarantine, operator proof/receipts, plan, common Git directory,
retirement helper and public GitHub PR. Output: one JSON document on stdout.
No file, ref, registration, branch or GitHub mutation is performed. Regular file
bytes are hashed without symlink traversal. Use --private for full local detail;
the default result omits local paths and symlink targets. Related issue #1269.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def regular(path):
    require(not path.is_symlink(), "Symlink supplied for evidence file")
    with path.open("rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "Evidence must be regular")
        return stream.read()


def git(common, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_NO_LAZY_FETCH="1", GIT_GRAFT_FILE=os.devnull)
    result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                             "-c", "gc.auto=0", "-c", "core.fsmonitor=false",
                             "--git-dir=" + str(common), *args],
                            env=env, check=True, capture_output=True, timeout=30)
    return result.stdout


def registrations(common):
    rows = []
    for block in git(common, "worktree", "list", "--porcelain", "-z").split(b"\0\0"):
        row = {}
        for field in block.split(b"\0"):
            if field:
                key, _, value = field.decode().partition(" ")
                row[key] = value
        if row:
            rows.append(row)
    return rows


def walk(root):
    result = {}
    device = root.stat().st_dev
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted([*dirs, *files]):
            path = Path(directory) / name
            before = path.lstat()
            require(before.st_dev == device, "Unexpected filesystem boundary")
            entry = {"mode": stat.S_IMODE(before.st_mode)}
            if stat.S_ISLNK(before.st_mode):
                entry.update(kind="symlink", target=os.readlink(path))
            elif stat.S_ISDIR(before.st_mode):
                entry["kind"] = "directory"
            elif stat.S_ISREG(before.st_mode):
                digest = hashlib.sha256()
                blob = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
                    for part in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(part)
                        blob.update(part)
                entry.update(kind="file", bytes=before.st_size, sha256=digest.hexdigest(), git_blob=blob.hexdigest())
            else:
                raise ValueError("Special preserved node")
            after = path.lstat()
            require((before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                    "Preserved entry changed during readback")
            result[path.relative_to(root).as_posix()] = entry
    return result


def api(path):
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True, timeout=60)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("quarantine", "proof", "dry-run", "apply", "plan", "common-git", "retirement-helper"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-helper-sha256", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    for path in (args.quarantine, args.proof, args.dry_run, args.apply, args.plan,
                 args.common_git, args.retirement_helper):
        require(path.is_absolute() and path == path.resolve(), "Canonical absolute input required")
    paths = {name: args.quarantine / name for name in ("before.json", "preserved.json", "completed.json", "recovery.json")}
    paths.update(proof=args.proof, dry_run=args.dry_run, apply=args.apply, plan=args.plan)
    raw = {name: regular(path) for name, path in paths.items()}
    data = {name: json.loads(value) for name, value in raw.items()}
    before, expected = data["before.json"], data["preserved.json"]
    completed, recovery, proof = data["completed.json"], data["recovery.json"], data["proof"]
    require(sha(regular(args.retirement_helper)) == args.expected_helper_sha256, "Retirement helper changed")
    require(sha(raw["proof"]) == before["proof_sha256"] and proof == before["proof"], "Operator proof differs")
    require(sha(raw["plan"]) == before["plan_sha256"] == proof["plan_sha256"], "Plan differs")
    require(proof["repository"] == args.repository and proof["merged_pr"]["number"] == args.pr, "Wrong repository or PR")
    require(proof["common_git"] == str(args.common_git) and proof["quarantine"] == str(args.quarantine), "Wrong local identity")
    require(proof["owner_complete"] is True and proof["readers_clear"] is True, "Missing completion attestations")
    worktree = Path(proof["worktree"])
    current = registrations(args.common_git)
    old_rows = {row["worktree"]: row for row in before["registrations"]}
    new_rows = {row["worktree"]: row for row in current}
    require(set(old_rows) - set(new_rows) == {str(worktree)}, "Removal set differs")
    require(not (set(new_rows) - set(old_rows)), "Unexpected registration added")
    require(all(old_rows[key] == new_rows[key] for key in new_rows), "Another registration changed")
    require(not os.path.lexists(worktree), "Worktree still present")
    require(not os.path.lexists(before["gitdir"]), "Target Git registration directory remains")
    require(completed["mode"] == "applied" and completed["branch_deleted"] is None, "Unexpected action mode/ref deletion")
    require(data["dry_run"]["actions_performed"] == 0 and data["apply"]["mode"] == "applied", "Dry/apply mismatch")
    require({k: v for k, v in completed.items() if k != "worktree"} == {k: v for k, v in data["apply"].items() if k != "worktree"}, "Completion/apply differ")
    require(completed["head"] == proof["expected_head"] == recovery["head"], "Source HEAD differs")
    require(completed["recovery_ref"] == recovery["ref"], "Recovery ref differs")
    require(git(args.common_git, "rev-parse", recovery["ref"]).decode().strip() == completed["head"], "Recovery ref missing/wrong")
    require(git(args.common_git, "cat-file", "-t", completed["head"]).strip() == b"commit", "Source commit missing")
    baseline = {path: {key: value for key, value in entry.items() if key != "fingerprint"}
                for path, entry in before["preserved"].items()}
    require(baseline == expected, "Before/preserved manifests differ")
    observed = walk(args.quarantine / "preserved")
    roots = completed["preservation_roots"]
    # Parent directories created only to house leaf preservation roots are not preserved entries.
    parents = {str(parent) for root in roots for parent in Path(root).parents if str(parent) != "."}
    for parent in parents - set(expected):
        require(observed[parent]["kind"] == "directory", "Unexpected preservation container")
        del observed[parent]
    require(observed == expected, "Preserved entry bytes/modes/targets or complete inventory differ")
    require(len(observed) == completed["preservation_entries"] == data["dry_run"]["preservation_entries"], "Preservation count differs")
    require(sha(raw["preserved.json"]) == completed["manifest_sha256"] == data["dry_run"]["manifest_sha256"], "Preservation digest differs")
    tree = {}
    for row in git(args.common_git, "ls-tree", "-r", "-z", completed["head"]).split(b"\0"):
        if row:
            meta, name = row.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            tree[name.decode()] = {"mode": mode, "kind": kind, "oid": oid}
    require(set(before["tracked"]) == set(tree), "Tracked-source inventory differs")
    for name, entry in tree.items():
        prior = before["entries"][name]
        if prior["kind"] == "symlink":
            body = prior["target"].encode()
            blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            require(entry["mode"] == "120000", "Source link mode differs")
        else:
            blob = prior["git_blob"]
            require(bool(prior["mode"] & 0o111) == (entry["mode"] == "100755"), "Source executable mode differs")
        require(blob == entry["oid"], "Source blob differs from recorded worktree")
    live = api(f"repos/{args.repository}/pulls/{args.pr}")
    require(live["merged"] is True and live["state"] == "closed" and live["base"]["ref"] == "main", "PR not merged into main")
    require(live["head"]["sha"] == completed["head"] and live["merge_commit_sha"] == proof["merged_pr"]["merge_commit"], "Published exact source or merge differs")
    require(live["base"]["repo"]["full_name"].lower() == args.repository.lower(), "Wrong public repository")
    refs = api(f"repos/{args.repository}/git/matching-refs/heads/{live['head']['ref']}")
    remote_present = any(row["ref"] == "refs/heads/" + live["head"]["ref"] for row in refs)
    public = {"reviewed_at": datetime.now(timezone.utc).isoformat(), "repository": args.repository,
              "pr": args.pr, "verdict": "PASS", "source_head": completed["head"],
              "merge_sha": live["merge_commit_sha"], "preserved_entries": len(observed),
              "preservation_roots": len(roots), "tracked_source_paths": len(tree),
              "all_preserved_bytes_modes_symlink_targets_verified": True,
              "only_target_registration_removed": True, "other_registrations_unchanged": True,
              "source_recovery_ref_verified": True, "remote_pr_branch_present": remote_present,
              "branch_deletion_actor_verified": False, "environment_preserved": ".venv" in roots,
              "retained_original_review_helpers": sum(name.startswith("scripts/adhoc/") for name in roots),
              "retirement_helper_sha256": args.expected_helper_sha256,
              "verifier_sha256": sha(regular(Path(__file__).resolve())),
              "evidence_sha256": {name: sha(value) for name, value in raw.items()},
              "no_cleanup_by_reviewer": True}
    if args.private:
        public["private_detail"] = {"worktree": str(worktree), "common_git": str(args.common_git),
                                    "quarantine": str(args.quarantine), "recovery": recovery,
                                    "registrations_before": before["registrations"], "registrations_after": current,
                                    "preservation_roots": roots, "remote_branch": live["head"]["ref"]}
    print(json.dumps(public, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
