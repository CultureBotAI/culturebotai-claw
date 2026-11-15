"""Retire one proved-owned clean worktree, preserving every extra byte (2026-11-15).

Dry-run is the default. This helper consumes trusted, fresh operator attestations;
it does not manufacture merge authority or query GitHub. Issue #1269 binds parsed proof/plan to the same captured bytes. Dirty tracked/index,
sparse, nested-repository and active-reader cases require separate review.
Private manifests include explicit local paths: never publish actual run receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = "CultureBotAI/culturebotai-claw"
LEASE_DEADLINE: ContextVar[float | None] = ContextVar("retirement_lease_deadline", default=None)
MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_LOG", "index.lock", "locked")


class Refusal(ValueError):
    """No authority or incomplete preservation proof; stop without guessing."""


def require(ok: Any, message: str) -> None:
    if not ok:
        raise Refusal(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def unique(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def read_bytes(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), "proof/plan must be regular files")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "proof/plan must be regular files")
        return stream.read()


def decode_json(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(value, dict), "proof/plan must be JSON objects")
    return value


def exact_path(path: Path, *, present: bool = True) -> Path:
    require(path.is_absolute(), "all paths must be explicit absolute paths")
    require(path == Path(os.path.abspath(path)), "path must be normalized")
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "symlink path ancestor refused")
    if present:
        require(path.exists(), "required path absent")
    require(not any(path == base or path.is_relative_to(base) for base in (Path('/tmp'), Path('/private/tmp'))), "session paths must be durable")
    temporary = os.environ.get("TMPDIR")
    if temporary:
        require(not path.is_relative_to(Path(temporary).resolve()), "session paths must not use TMPDIR")
    return path


def budget() -> float:
    deadline = LEASE_DEADLINE.get()
    remaining = 20.0 if deadline is None else deadline - time.monotonic()
    require(remaining > 0, "short metadata lease operation budget exhausted")
    return min(20.0, remaining)


@contextmanager
def metadata_lease(config: dict, operation: str):
    from plugins.lock_manager import LockManager
    with LockManager(config).lock("claw", operation, timeout=60):
        token = LEASE_DEADLINE.set(time.monotonic() + 45)
        try:
            yield
        finally:
            LEASE_DEADLINE.reset(token)


def git(common: Path, *args: str, cwd: Path | None = None) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_GRAFT_FILE=os.devnull,
               GIT_OPTIONAL_LOCKS="0")
    command = ["git", "-c", "advice.graftFileDeprecated=false", "-c", "gc.auto=0",
               "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false"]
    command += ["-C", str(cwd)] if cwd else [f"--git-dir={common}"]
    result = subprocess.run([*command, *args], env=env, capture_output=True, timeout=budget())
    require(result.returncode == 0, f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def registrations(common: Path) -> list[dict]:
    blocks = git(common, "worktree", "list", "--porcelain", "-z").split(b"\0\0")
    rows = []
    for block in blocks:
        row = {}
        for field in block.split(b"\0"):
            if field:
                key, _, value = field.decode().partition(" ")
                row[key] = value
        if row:
            rows.append(row)
    return rows


def fingerprint(path: Path) -> list[int]:
    s = path.lstat()
    return [s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def node(path: Path, device: int) -> dict:
    before = fingerprint(path)
    require(before[0] == device, "cross-filesystem preservation refused")
    mode = before[2]
    if stat.S_ISLNK(mode):
        value = {"kind": "symlink", "target": os.readlink(path), "mode": stat.S_IMODE(mode)}
    elif stat.S_ISREG(mode):
        hasher = hashlib.sha256()
        blob = hashlib.sha1(b"blob " + str(before[3]).encode() + b"\0")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            require(fingerprint(path) == before, "file changed before hashing")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
                blob.update(chunk)
        value = {"kind": "file", "bytes": before[3], "sha256": hasher.hexdigest(), "git_blob": blob.hexdigest(), "mode": stat.S_IMODE(mode)}
    elif stat.S_ISDIR(mode):
        value = {"kind": "directory", "mode": stat.S_IMODE(mode)}
    else:
        raise Refusal("special file cannot be preserved safely")
    require(fingerprint(path) == before, "file changed during hashing")
    return {**value, "fingerprint": before}


def walk(root: Path) -> dict[str, dict]:
    device = root.stat().st_dev
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in sorted([*dirs, *files]):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if relative == ".git":
                require(path.is_file() and not path.is_symlink(), "only linked worktrees are supported")
                continue
            require(name != ".git", "nested Git boundary requires separate preservation review")
            result[relative] = node(path, device)
    return result


def content(entries: dict[str, dict]) -> dict:
    return {path: {key: value for key, value in row.items() if key != "fingerprint"}
            for path, row in entries.items()}


def readers_clear(root: Path) -> None:
    result = subprocess.run(["lsof", "-nP", "-Fpn", "+D", str(root)], capture_output=True, timeout=45)
    require(result.returncode == 1 and not result.stdout and not result.stderr,
            "active readers or incomplete lsof observation; owner must resolve without killing processes")


def validate_proof(args: argparse.Namespace, proof: dict, plan: dict, *, plan_sha256: str) -> dict:
    require(type(proof.get("schema_version")) is int and proof["schema_version"] == 1 and proof.get("repository") == REPOSITORY, "proof identity/version mismatch")
    for name in ("task_scope", "worktree", "common_git", "quarantine"):
        require(proof.get(name) == str(getattr(args, name)), f"proof {name} mismatch")
    require(proof.get("expected_head") == args.expected_head and SHA.fullmatch(args.expected_head), "proof expected head mismatch")
    require(proof.get("disposition") == "retire_clean" and proof.get("owner_complete") is True
            and proof.get("readers_clear") is True, "completed owner/readers/disposition attestation required")
    require(isinstance(proof.get("owner_evidence"), str) and proof["owner_evidence"].strip(), "owner completion evidence required")
    observed = datetime.fromisoformat(proof["observed_at"].replace("Z", "+00:00"))
    require(observed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 900,
            "proof must be timezone-aware and no older than 15 minutes")
    require(proof.get("plan_sha256") == plan_sha256, "action plan bytes changed")
    matches = [row for row in plan.get("items", []) if row.get("root") == str(args.worktree)]
    require(len(matches) == 1 and matches[0].get("common_git_directory") == str(args.common_git), "worktree absent from exact scoped plan")
    planned = matches[0]
    if planned.get("head") != args.expected_head or str(planned.get("decision", "")).startswith("HOLD"):
        require(isinstance(proof.get("plan_override_reason"), str) and proof["plan_override_reason"].strip(),
                "fresh evidence must explain superseded plan hold/head")
    pr = proof.get("merged_pr", {})
    require(type(pr.get("number")) is int and pr["number"] > 0 and pr.get("state") == "MERGED"
            and pr.get("base_ref") == "main" and pr.get("repository") == REPOSITORY,
            "exact merged PR/main proof required")
    for field in ("head", "merge_commit", "published_main"):
        require(isinstance(pr.get(field), str) and SHA.fullmatch(pr[field]), "immutable merged PR SHA required")
    require(pr.get("url") == f"https://github.com/{REPOSITORY}/pull/{pr['number']}", "PR URL mismatch")
    require(pr.get("observed_at") == proof["observed_at"], "PR and owner evidence must share fresh observation")
    git(args.common_git, "merge-base", "--is-ancestor", args.expected_head, pr["head"])
    git(args.common_git, "merge-base", "--is-ancestor", pr["merge_commit"], pr["published_main"])
    if pr.get("merge_method") == "squash":
        require(proof.get("exact_squash_head_verified") is True, "squash requires exact API-head verification attestation")
    else:
        require(pr.get("merge_method") == "merge", "only proved merge or exact squash is supported")
        git(args.common_git, "merge-base", "--is-ancestor", pr["head"], pr["merge_commit"])
    return planned


def inspect(args: argparse.Namespace, *, probe=readers_clear) -> dict:
    for name in ("task_scope", "worktree", "common_git", "proof", "action_plan", "locks_dir"):
        exact_path(getattr(args, name))
    exact_path(args.quarantine, present=False)
    require(args.worktree != args.task_scope and args.worktree.is_relative_to(args.task_scope), "worktree must be strictly inside task scope")
    require(args.quarantine.is_relative_to(args.task_scope) and not args.quarantine.exists(), "new quarantine must be inside task scope")
    require(not args.common_git.is_relative_to(args.worktree), "primary clone is held until linked worktrees retire")
    proof_raw, plan_raw = read_bytes(args.proof), read_bytes(args.action_plan)
    proof, plan = decode_json(proof_raw), decode_json(plan_raw)
    validate_proof(args, proof, plan, plan_sha256=digest(plan_raw))
    rows = registrations(args.common_git)
    selected = [row for row in rows if row.get("worktree") == str(args.worktree)]
    require(len(selected) == 1 and selected[0].get("HEAD") == args.expected_head, "registered exact worktree/head mismatch")
    require(not any(key in selected[0] for key in ("locked", "prunable", "bare")), "locked/prunable/bare worktree refused")
    branch = selected[0].get("branch")
    require("expected_branch" in proof and proof["expected_branch"] == branch, "exact owned branch attestation required")
    require(branch not in {"refs/heads/main", "refs/heads/master"}, "default branch retirement refused")
    for row in rows:
        registered = Path(row["worktree"])
        for outside in (args.quarantine, args.proof, args.action_plan, args.locks_dir):
            require(not outside.is_relative_to(registered), "proof/quarantine/locks must be outside every registered checkout")
    require(git(args.common_git, "rev-parse", "--show-toplevel", cwd=args.worktree).decode().strip() == str(args.worktree), "wrong top-level")
    common = Path(git(args.common_git, "rev-parse", "--git-common-dir", cwd=args.worktree).decode().strip())
    require((args.worktree / common).resolve() == args.common_git, "common Git mismatch")
    gitdir = Path(git(args.common_git, "rev-parse", "--absolute-git-dir", cwd=args.worktree).decode().strip())
    require(gitdir.is_relative_to(args.common_git / "worktrees"), "linked Git metadata escaped common directory")
    for marker in MARKERS:
        require(not (gitdir / marker).exists(), "operation or worktree lock marker present")
    origins = git(args.common_git, "remote", "get-url", "--all", "origin", cwd=args.worktree).decode().splitlines()
    pushes = git(args.common_git, "remote", "get-url", "--push", "--all", "origin", cwd=args.worktree).decode().splitlines()
    valid = {f"https://github.com/{REPOSITORY}", f"https://github.com/{REPOSITORY}.git", f"git@github.com:{REPOSITORY}.git"}
    require(origins and pushes and set(origins + pushes) <= valid, "origin URL mismatch")
    index = git(args.common_git, "ls-files", "--stage", "-z", cwd=args.worktree)
    expected = {}
    for item in git(args.common_git, "ls-tree", "-rz", args.expected_head).split(b"\0"):
        if item:
            metadata, path = item.split(b"\t", 1)
            mode, kind, oid = metadata.decode().split()
            require(kind == "blob" and mode in {"100644", "100755", "120000"}, "submodule/non-file Git entry refused")
            expected[path.decode()] = (mode, oid)
    actual = {}
    for item in index.split(b"\0"):
        if item:
            metadata, path = item.split(b"\t", 1)
            mode, oid, stage = metadata.decode().split()
            require(stage == "0", "unmerged index refused")
            actual[path.decode()] = (mode, oid)
    require(actual == expected, "dirty staged/index state: preserve exact bytes/patch/index separately before restoration")
    flags = git(args.common_git, "ls-files", "-v", "-z", cwd=args.worktree)
    require(all(not row or row[:1] == b"H" for row in flags.split(b"\0")), "sparse/assume-unchanged index refused")
    entries = walk(args.worktree)
    for path, (mode, oid) in expected.items():
        row = entries.get(path, {})
        if mode == "120000":
            target = os.fsencode(row.get("target", ""))
            actual_oid = hashlib.sha1(b"blob " + str(len(target)).encode() + b"\0" + target).hexdigest()
            require(row.get("kind") == "symlink" and actual_oid == oid, "dirty tracked symlink refused")
        else:
            require(row.get("kind") == "file" and row.get("git_blob") == oid
                    and bool(row["mode"] & stat.S_IXUSR) == (mode == "100755"),
                    "dirty tracked bytes/mode: preserve exact bytes/patch/index separately before restoration")
    tracked_dirs = {str(parent) for path in expected for parent in Path(path).parents if str(parent) != "."}
    extras = set(entries) - set(expected) - tracked_dirs
    roots = []
    for path in sorted(extras, key=lambda value: (len(Path(value).parts), value)):
        if not any(path == parent or path.startswith(parent + "/") for parent in roots):
            roots.append(path)
    preserved = {path: row for path, row in entries.items() if any(path == top or path.startswith(top + "/") for top in roots)}
    probe(args.worktree)
    require(read_bytes(args.proof) == proof_raw and read_bytes(args.action_plan) == plan_raw,
            "proof or plan changed during inventory")
    return {"proof": proof, "proof_sha256": digest(proof_raw), "plan_sha256": digest(plan_raw),
            "registration": selected[0], "registrations": rows, "gitdir": str(gitdir),
            "index_sha256": digest((gitdir / "index").read_bytes()), "tracked": sorted(expected),
            "entries": entries, "preservation_roots": roots, "preserved": preserved}


def preserved_view(root: Path, before: dict) -> dict:
    observed = walk(root)
    parents = {str(parent) for path in before["preservation_roots"]
               for parent in Path(path).parents if str(parent) != "."}
    require(set(observed) == set(before["preserved"]) | parents, "unexpected quarantine entry")
    require(all(observed[path]["kind"] == "directory" for path in parents), "quarantine ancestor is not a directory")
    return {path: observed[path] for path in before["preserved"]}


def save_new(path: Path, value: Any) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())


def fast_recheck(args: argparse.Namespace, before: dict, *, moved: bool) -> None:
    proof_raw, plan_raw = read_bytes(args.proof), read_bytes(args.action_plan)
    require(digest(proof_raw) == before["proof_sha256"], "proof changed")
    require(digest(plan_raw) == before["plan_sha256"], "plan changed")
    validate_proof(args, decode_json(proof_raw), decode_json(plan_raw), plan_sha256=digest(plan_raw))
    require(registrations(args.common_git) == before["registrations"], "worktree registration drift")
    gitdir = Path(before["gitdir"])
    require(digest((gitdir / "index").read_bytes()) == before["index_sha256"], "index changed")
    require(not any((gitdir / marker).exists() for marker in MARKERS), "operation marker appeared")
    names = before["tracked"] if moved else before["entries"]
    for name in names:
        budget()
        require(fingerprint(args.worktree / name) == before["entries"][name]["fingerprint"], "file changed after inventory")
    actual_names = set()
    for directory, dirs, files in os.walk(args.worktree, followlinks=False):
        budget()
        actual_names.update((Path(directory) / name).relative_to(args.worktree).as_posix() for name in [*dirs, *files])
    expected_names = set(before["entries"]) - (set(before["preserved"]) if moved else set())
    require(actual_names - {".git"} == expected_names, "new/missing filesystem entry after inventory")


def retire(args: argparse.Namespace, *, probe=readers_clear) -> dict:
    before = inspect(args, probe=probe)
    summary = {"mode": "dry_run", "worktree": str(args.worktree), "head": args.expected_head,
               "preservation_roots": before["preservation_roots"], "preservation_entries": len(before["preserved"]),
               "manifest_sha256": digest(encode(content(before["preserved"]))), "actions_performed": 0}
    if not args.apply:
        return summary
    require(args.quarantine.parent.is_dir() and args.quarantine.parent.stat().st_dev == args.worktree.stat().st_dev,
            "pre-existing quarantine parent must share filesystem")
    args.quarantine.mkdir(mode=0o700)
    save_new(args.quarantine / "before.json", before)
    preserved_root = args.quarantine / "preserved"
    preserved_root.mkdir(mode=0o700)
    recovery = f"refs/cleanup-recovery/{uuid.uuid4().hex}"
    git(args.common_git, "check-ref-format", recovery)
    config = {"locks_dir": str(args.locks_dir), "my_id": args.owner, "default_timeout": 60}
    try:
        with metadata_lease(config, "preserve-owned-clean-worktree"):
            fast_recheck(args, before, moved=False)
            git(args.common_git, "update-ref", recovery, args.expected_head, "0" * 40)
            save_new(args.quarantine / "recovery.json", {"ref": recovery, "head": args.expected_head})
            for name in before["preservation_roots"]:
                budget()
                source, destination = args.worktree / name, preserved_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                require(not destination.exists() and not destination.is_symlink(), "quarantine collision")
                os.rename(source, destination)
        after_move = preserved_view(preserved_root, before)
        require(content(after_move) == content(before["preserved"]), "quarantine content verification failed; retain recovery paths")
        save_new(args.quarantine / "preserved.json", content(after_move))
        probe(args.worktree)
        with metadata_lease(config, "retire-owned-clean-worktree"):
            fast_recheck(args, before, moved=True)
            for name, row in after_move.items():
                budget()
                require(fingerprint(preserved_root / name) == row["fingerprint"], "preserved content changed before retirement")
            git(args.common_git, "worktree", "remove", "--", str(args.worktree))
            remaining = registrations(args.common_git)
            require(remaining == [row for row in before["registrations"] if row != before["registration"]], "unexpected registration change")
            require(not args.worktree.exists(), "worktree still exists")
            branch = before["registration"].get("branch")
            if branch:
                require(not any(row.get("branch") == branch for row in remaining), "branch still used")
                git(args.common_git, "update-ref", "-d", branch, args.expected_head)
            require(git(args.common_git, "rev-parse", recovery).decode().strip() == args.expected_head, "recovery ref mismatch")
        require(content(preserved_view(preserved_root, before)) == content(before["preserved"]), "final preservation verification failed")
        result = {**summary, "mode": "applied", "actions_performed": len(before["preservation_roots"]) + 2,
                  "recovery_ref": recovery, "branch_deleted": branch, "preserved_manifest": "preserved.json"}
        save_new(args.quarantine / "completed.json", result)
        return result
    except Exception as exc:
        save_new(args.quarantine / "failure.json", {"error": str(exc), "recovery_ref": recovery,
                 "instruction": "Retain quarantine and worktree state. Review exact moves before any recovery; no automatic rollback."})
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("task-scope", "worktree", "common-git", "quarantine", "proof", "action-plan", "locks-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--owner", required=True, help="Owned metadata-lease identity; not a session control")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(retire(args), indent=2))
    except (Refusal, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
