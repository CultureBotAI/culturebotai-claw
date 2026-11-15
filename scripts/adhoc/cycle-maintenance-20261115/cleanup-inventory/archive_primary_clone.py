"""Archive one completed shallow no-checkout review clone; 2026-11-15, issue1269.

Dry-run by default. Inputs: explicit owned paths, immutable reviewed helper,
fresh operator proof and reviewed plan/checklist. Outputs: PRIVATE manifests,
reader/ref receipts and relocation map. Retains the whole clone by one exclusive
atomic directory rename. No checkout, index creation, hook, fetch, prune or delete.
The operator attests the bounded known-borrower review; this is not global proof.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

SHARED_SHA256 = "5513d8c984104fe0c0d6da1c8aaa37549e6e3307baa541498a862a185bac1af9"
REQUIRED_RETIREMENTS = (
    "reviews/1138/rereview/worktree",
    "reviews/1138/final-integration/worktree",
    "reviews/permanent-cycle/remote-independent/worktree",
    "reviews/remote-verifier/worktree",
)
REPOSITORY = "CultureBotAI/culturebotai-claw"
PLAN_SHA256 = "e4ad06b3beb263f37510d702b7ac6af706de98703d43e578e62741744f3dcc0d"
REVIEW_SHA256 = "d31a188d3a01e7bab16ee8a384fbe4dffe6e648554d694dbec0862f403d0fcca"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_shared(path):
    raw = path.read_bytes()
    require(sha(raw) == SHARED_SHA256, "Reviewed shared helper bytes changed")
    module = types.ModuleType("reviewed_retirement_primitives")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def save(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    require(path.read_bytes() == raw, "Evidence readback mismatch")
    return sha(raw)


def acl(path):
    # The bounded operator supports Darwin only; Linux ACLs are not silently omitted.
    require(sys.platform == "darwin", "This reviewed archival operator requires Darwin")
    lib = ctypes.CDLL(None, use_errno=True)
    lib.acl_get_link_np.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.acl_get_link_np.restype = ctypes.c_void_p
    lib.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
    lib.acl_to_text.restype = ctypes.c_void_p
    lib.acl_free.argtypes = [ctypes.c_void_p]
    ctypes.set_errno(0)
    handle = lib.acl_get_link_np(os.fsencode(path), 0x00000100)  # ACL_TYPE_EXTENDED
    if not handle:
        # Darwin returns ENOENT for the absent extended ACL on this filesystem.
        # Independently confirm a successful existing-node listing with no ACL
        # entries; do not collapse permission/unsupported errors into absence.
        require(ctypes.get_errno() == errno.ENOENT, "ACL read failed")
        check = subprocess.run(["/bin/ls", "-lde", str(path)], capture_output=True, timeout=10)
        require(
            check.returncode == 0 and not check.stderr and len(check.stdout.splitlines()) == 1,
            "ACL absence could not be independently established",
        )
        return {"absent": True}
    text = None
    try:
        length = ctypes.c_ssize_t()
        text = lib.acl_to_text(handle, ctypes.byref(length))
        require(bool(text), "ACL serialization failed")
        return base64.b64encode(ctypes.string_at(text, length.value)).decode()
    finally:
        if text:
            lib.acl_free(text)
        lib.acl_free(handle)


def xattrs(path):
    lib = ctypes.CDLL(None, use_errno=True)
    lib.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    lib.listxattr.restype = ctypes.c_ssize_t
    lib.getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    lib.getxattr.restype = ctypes.c_ssize_t
    raw_path = os.fsencode(path)
    size = lib.listxattr(raw_path, None, 0, 1)  # XATTR_NOFOLLOW
    require(size >= 0, "Extended-attribute inventory failed")
    buffer = ctypes.create_string_buffer(size)
    require(lib.listxattr(raw_path, buffer, size, 1) == size, "Extended-attribute names changed")
    result = {}
    for name in sorted(value for value in buffer.raw.split(b"\0") if value):
        count = lib.getxattr(raw_path, name, None, 0, 0, 1)
        require(count >= 0, "Extended-attribute read failed")
        value = ctypes.create_string_buffer(count)
        require(
            lib.getxattr(raw_path, name, value, count, 0, 1) == count, "Extended-attribute changed"
        )
        result[base64.b64encode(name).decode()] = base64.b64encode(value.raw).decode()
    return result


def fingerprint(path):
    s = path.lstat()
    return [
        s.st_dev,
        s.st_ino,
        s.st_mode,
        s.st_size,
        s.st_mtime_ns,
        s.st_ctime_ns,
        s.st_uid,
        s.st_gid,
        s.st_nlink,
        s.st_flags,
    ]


def paths(root):
    def failed_enumeration(error):
        raise error

    yield ".", root
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed_enumeration):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            yield path.relative_to(root).as_posix(), path


def quick(root, shared):
    result = {}
    for name, path in paths(root):
        shared.budget()
        result[name] = fingerprint(path)
    return result


def relocation_stable_target(root, path, target):
    """Resolve each relative link component without ever crossing the clone root."""
    require(not Path(target).is_absolute(), "Absolute symlink is not relocation-stable (#1272)")
    stack = list(path.parent.relative_to(root).parts)
    pending = list(Path(target).parts)
    hops = 0
    while pending:
        part = pending.pop(0)
        if part == ".":
            continue
        if part == "..":
            require(stack, "Symlink traversal leaves the preserved root (#1272)")
            stack.pop()
            continue
        stack.append(part)
        candidate = root.joinpath(*stack)
        if candidate.is_symlink():
            hops += 1
            require(hops <= 40, "Unresolved symlink loop (#1272)")
            nested = Path(os.readlink(candidate))
            require(
                not nested.is_absolute(),
                "Absolute chained symlink is not relocation-stable (#1272)",
            )
            stack.pop()
            pending = list(nested.parts) + pending
    return root.joinpath(*stack)


def inventory(root):
    device = root.stat().st_dev
    result = {}
    for name, path in paths(root):
        before = fingerprint(path)
        require(before[0] == device, "Mount/cross-device descendant refused")
        kind = before[2]
        row = {
            "fingerprint": before,
            "mode": stat.S_IMODE(kind),
            "uid": before[6],
            "gid": before[7],
            "flags": before[9],
            "acl": acl(path),
            "xattrs": xattrs(path),
        }
        if stat.S_ISDIR(kind):
            row["kind"] = "directory"
        elif stat.S_ISREG(kind):
            require(before[8] == 1, "Hardlinked file needs separate dependency review")
            hasher = hashlib.sha256()
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
                require(fingerprint(path) == before, "File changed before hashing")
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(block)
            row.update(kind="file", bytes=before[3], sha256=hasher.hexdigest())
        elif stat.S_ISLNK(kind):
            target = os.readlink(path)
            relocation_stable_target(root, path, target)
            row.update(kind="symlink", target=target)
        else:
            raise ValueError("Special descendant refused")
        require(fingerprint(path) == before, "Node changed during inventory")
        result[name] = row
    return result


def preserved(entries):
    # Directory rename may change only the root ctime. Descendant identities,
    # timestamps and metadata stay bound as well as bytes/ACLs/xattrs.
    result = {}
    for name, row in entries.items():
        value = dict(row)
        stable = list(value["fingerprint"])
        if name == ".":
            stable[5] = None
        value["fingerprint"] = stable
        result[name] = value
    return result


def readers(root):
    process = subprocess.run(
        ["lsof", "-nP", "-Fpn", "+D", str(root)], capture_output=True, timeout=45
    )
    require(
        process.returncode == 1 and not process.stdout and not process.stderr,
        "Active reader or incomplete reader observation",
    )
    return {
        "exit": process.returncode,
        "stdout_base64": base64.b64encode(process.stdout).decode(),
        "stderr_base64": base64.b64encode(process.stderr).decode(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def snapshot(root, expected_head, shared, *, full):
    common = root / ".git"
    require(
        root.is_dir() and set(p.name for p in root.iterdir()) == {".git"},
        "Expected no-checkout primary only",
    )
    require(common.is_dir() and not common.is_symlink(), "Primary Git directory changed")
    require(not os.path.lexists(common / "index"), "Absent index must stay absent")
    require(
        (common / "shallow").is_file() and not (common / "shallow").is_symlink(),
        "Shallow boundary required",
    )
    for name in (
        "commondir",
        "gitdir",
        "objects/info/alternates",
        "objects/info/http-alternates",
        "config.worktree",
        *shared.MARKERS,
    ):
        require(
            not os.path.lexists(common / name), "Operation/external Git dependency refused: " + name
        )
    linked = common / "worktrees"
    require(
        not linked.exists() or (linked.is_dir() and not any(linked.iterdir())),
        "Linked Git metadata remains",
    )
    for name, _ in paths(common):
        shared.budget()
        require(not name.endswith(".lock"), "Git lock marker remains")

    def git(*args):
        return shared.git(common, *args, cwd=root)

    require(
        Path(git("rev-parse", "--absolute-git-dir").decode().strip()) == common, "Gitdir mismatch"
    )
    require(
        Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
        == common,
        "Common Git mismatch",
    )
    require(git("rev-parse", "HEAD").decode().strip() == expected_head, "Unexpected HEAD")
    require(
        git("rev-parse", "--is-shallow-repository").strip() == b"true",
        "Expected shallow repository",
    )
    require(git("rev-parse", "--show-object-format").strip() == b"sha1", "Unreviewed object format")
    origin = git("remote", "get-url", "origin").decode().strip()
    require(
        origin in (f"https://github.com/{REPOSITORY}.git", f"git@github.com:{REPOSITORY}.git"),
        "Origin mismatch",
    )
    config = git("config", "--local", "--no-includes", "--null", "--list")
    for entry in config.split(b"\0"):
        key, _, value = entry.decode().partition("\n")
        key = key.lower()
        require(
            not (
                key.startswith(("include.", "includeif."))
                or key in ("core.worktree", "extensions.partialclone", "extensions.worktreeconfig")
                or key.endswith(".promisor")
            ),
            "Unsupported configuration dependency",
        )
        require(not (key == "core.bare" and value.lower() == "true"), "Bare repository refused")
    registrations = shared.registrations(common)
    require(
        len(registrations) == 1
        and registrations[0] == {"worktree": str(root), "HEAD": expected_head, "detached": ""},
        "Single detached primary registration required",
    )
    refs = git("for-each-ref", "--format=%(refname)%09%(objectname)%09%(symref)")
    recovery = git("for-each-ref", "refs/cleanup-recovery/", "--format=%(refname)%09%(objectname)")
    result = {
        "head": expected_head,
        "refs_base64": base64.b64encode(refs).decode(),
        "recovery_refs_base64": base64.b64encode(recovery).decode(),
        "config_sha256": sha(config),
        "shallow_sha256": sha(shared.read_bytes(common / "shallow")),
        "index_absent": True,
    }
    if full:
        result["connectivity_output_base64"] = base64.b64encode(
            git("fsck", "--connectivity-only", "--no-dangling")
        ).decode()
        recovery_trees = {}
        for line in recovery.decode().splitlines():
            ref, oid = line.split("\t")
            require(shared.SHA.fullmatch(oid), "Malformed recovery ref")
            git("cat-file", "-e", oid + "^{commit}")
            git("cat-file", "-e", oid + "^{tree}")
            recovery_trees[ref] = {
                "oid": oid,
                "ls_tree_base64": base64.b64encode(git("ls-tree", "-r", "-z", oid)).decode(),
            }
        result["recovery_trees"] = recovery_trees
    return result


def exclusive_rename(source, destination, parent_ids, source_id):
    require(sys.platform == "darwin", "Exclusive Darwin rename unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    srcfd = os.open(source.parent, flags)
    dstfd = os.open(destination.parent, flags)
    try:
        for fd, expected in ((srcfd, parent_ids[0]), (dstfd, parent_ids[1])):
            s = os.fstat(fd)
            require([s.st_dev, s.st_ino] == expected, "Parent descriptor identity changed")
        entry = os.stat(source.name, dir_fd=srcfd, follow_symlinks=False)
        require(
            [entry.st_dev, entry.st_ino] == source_id and stat.S_ISDIR(entry.st_mode),
            "Source identity changed",
        )
        lib = ctypes.CDLL(None, use_errno=True)
        rename = lib.renameatx_np
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(
            srcfd, os.fsencode(source.name), dstfd, os.fsencode(destination.name), 0x00000004
        ):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(srcfd)
        os.close(dstfd)


def archive(args, *, probe=readers):
    shared = load_shared(args.shared_helper)
    for name in ("task_scope", "source", "proof", "plan", "review", "locks_dir", "shared_helper"):
        shared.exact_path(getattr(args, name))
    for name in ("archive_parent", "evidence"):
        path = shared.exact_path(getattr(args, name), present=False)
        require(not os.path.lexists(path) and path.parent.is_dir(), "Exclusive new output required")
        require(
            path.is_relative_to(args.task_scope)
            and args.source not in path.parents
            and path not in args.source.parents,
            "Output outside owned scope or aliases source",
        )
    require(args.source == args.task_scope / "reviews/1236/repo", "Wrong scoped primary clone")
    destination = args.archive_parent / "repo"
    require(
        args.evidence != args.archive_parent
        and args.evidence not in args.archive_parent.parents
        and args.archive_parent not in args.evidence.parents,
        "Evidence/archive overlap",
    )
    require(
        args.source.stat().st_dev == args.archive_parent.parent.stat().st_dev,
        "Archive must stay on same filesystem",
    )
    proof_raw, plan_raw, review_raw = (
        shared.read_bytes(getattr(args, name)) for name in ("proof", "plan", "review")
    )
    proof = shared.decode_json(proof_raw)
    bound = {args.proof: proof_raw, args.plan: plan_raw, args.review: review_raw}
    require(
        proof.get("schema_version") == 1 and proof.get("repository") == REPOSITORY,
        "Proof identity mismatch",
    )
    for key, value in (
        ("task_scope", args.task_scope),
        ("source", args.source),
        ("destination", destination),
    ):
        require(proof.get(key) == str(value), "Proof path mismatch")
    require(
        proof.get("expected_head") == args.expected_head
        and shared.SHA.fullmatch(args.expected_head),
        "Proof HEAD mismatch",
    )
    require(
        proof.get("plan_sha256") == sha(plan_raw) == PLAN_SHA256
        and proof.get("review_sha256") == sha(review_raw) == REVIEW_SHA256,
        "Reviewed input digest mismatch",
    )
    require(
        proof.get("owner_complete") is True
        and proof.get("dependencies_reviewed") is True
        and proof.get("unknown_dependencies") == [],
        "Owner/dependency hold remains",
    )
    require(
        isinstance(proof.get("owner_evidence"), str) and proof["owner_evidence"].strip(),
        "Owner evidence required",
    )
    require(
        isinstance(proof.get("borrower_review"), dict)
        and proof["borrower_review"].get("bounded_scope")
        and proof["borrower_review"].get("known_borrowers") == [],
        "Known borrowers must be cleared by bounded review",
    )
    observed = datetime.fromisoformat(proof["observed_at"].replace("Z", "+00:00"))
    require(
        observed.tzinfo is not None
        and 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 900,
        "Fresh operator proof required",
    )
    dependencies = proof.get("retirements", [])
    require(
        {d.get("relative_root") for d in dependencies} == set(REQUIRED_RETIREMENTS)
        and len(dependencies) == 4,
        "All four exact retirement receipts required",
    )
    for row in dependencies:
        require(
            not os.path.lexists(args.task_scope / row["relative_root"]), "Retired source remains"
        )
        receipt = shared.exact_path(Path(row["receipt"]))
        raw = shared.read_bytes(receipt)
        require(sha(raw) == row["sha256"], "Retirement receipt hash mismatch")
        doc = shared.decode_json(raw)
        require(
            doc.get("mode") == "applied"
            and doc.get("worktree") == str(args.task_scope / row["relative_root"])
            and doc.get("recovery_ref", "").startswith("refs/cleanup-recovery/"),
            "Unfinished retirement proof",
        )
        bound[receipt] = raw
    before = snapshot(args.source, args.expected_head, shared, full=True)
    require(
        proof.get("refs_sha256") == sha(base64.b64decode(before["refs_base64"])),
        "Frozen refs mismatch",
    )
    for row in dependencies:
        doc = shared.decode_json(bound[Path(row["receipt"])])
        require(doc["recovery_ref"] in before["recovery_trees"], "Retirement recovery ref missing")
    first_reader = probe(args.source)
    manifest = inventory(args.source)
    require(
        quick(args.source, shared) == {k: v["fingerprint"] for k, v in manifest.items()},
        "Inventory drift",
    )
    for path, raw in bound.items():
        require(shared.read_bytes(path) == raw, "Bound proof/plan/receipt changed")
    args.evidence.mkdir(mode=0o700)
    manifest_hash = save(args.evidence / "manifest.json", manifest)
    save(args.evidence / "git-before.json", before)
    save(args.evidence / "readers-before.json", first_reader)
    intent = {
        "source": str(args.source),
        "destination": str(destination),
        "source_identity": manifest["."]["fingerprint"][:2],
        "manifest_sha256": manifest_hash,
        "proof_sha256": sha(proof_raw),
        "plan_sha256": sha(plan_raw),
        "review_sha256": sha(review_raw),
        "helper_sha256": sha(Path(__file__).read_bytes()),
        "shared_helper_sha256": SHARED_SHA256,
        "single_relocation": True,
        "index_absent": True,
    }
    save(args.evidence / "intent.json", intent)
    if not args.apply:
        return {
            "mode": "dry-run",
            "manifest_sha256": manifest_hash,
            "entries": len(manifest),
            "source_moved": False,
        }
    last_reader = probe(args.source)
    save(args.evidence / "readers-final.json", last_reader)
    for path, raw in bound.items():
        require(shared.read_bytes(path) == raw, "Bound proof/plan/receipt changed")
    args.archive_parent.mkdir(mode=0o700)
    parent_ids = [fingerprint(args.source.parent)[:2], fingerprint(args.archive_parent)[:2]]
    config = {
        "locks_dir": str(args.locks_dir),
        "my_id": "owned-primary-clone-archive",
        "default_timeout": 60,
    }
    with shared.metadata_lease(config, "archive-completed-owned-primary-clone"):
        require(
            0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 900,
            "Operator proof expired before transition",
        )
        for path, raw in bound.items():
            require(shared.read_bytes(path) == raw, "Bound proof/plan/receipt changed inside lease")
        for path in (args.source, args.source.parent, args.archive_parent, args.evidence):
            shared.exact_path(path)
        require(not os.path.lexists(destination), "Archive collision")
        require(
            quick(args.source, shared) == {k: v["fingerprint"] for k, v in manifest.items()},
            "Source fingerprint drift",
        )
        quick_git = snapshot(args.source, args.expected_head, shared, full=False)
        require(all(before[key] == value for key, value in quick_git.items()), "Git state changed")
        require(
            quick(args.source, shared) == {k: v["fingerprint"] for k, v in manifest.items()},
            "Late source fingerprint drift",
        )
        shared.budget()
        exclusive_rename(args.source, destination, parent_ids, intent["source_identity"])
    require(
        not os.path.lexists(args.source)
        and fingerprint(destination)[:2] == intent["source_identity"],
        "Relocation identity mismatch",
    )
    after_manifest = inventory(destination)
    require(
        preserved(after_manifest) == preserved(manifest),
        "Preserved bytes/metadata mismatch; retain partial state",
    )
    after = snapshot(destination, args.expected_head, shared, full=True)
    require(after == before, "Relocated Git state mismatch; retain partial state")
    result = {
        "mode": "applied",
        **intent,
        "entries": len(manifest),
        "source_moved": True,
        "all_bytes_metadata_refs_shallow_preserved": True,
        "no_index_created": True,
        "old_receipts_unchanged": True,
        "disk_space_reclaimed": False,
    }
    save(args.evidence / "git-after.json", after)
    save(args.evidence / "relocation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "task-scope",
        "source",
        "archive-parent",
        "evidence",
        "proof",
        "plan",
        "review",
        "locks-dir",
        "shared-helper",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(archive(args), indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
