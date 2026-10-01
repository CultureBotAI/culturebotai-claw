#!/usr/bin/env python3
"""Bounded metadata-only repository inventory. Never deletes or applies a plan.

No application file contents are opened. Git reads its own metadata and index;
unstaged content differences are deliberately not measured (status can execute filters).
Cache candidates require manual review, including content and reference checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

CACHE_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}
PROTECTED_PARTS = {
    "data", "raw", "research", "history", "evidence", "reference", "references",
    "references_cache", "cache", "datasets", "results", "outputs", "reports",
    "build", "dist", "site", "_site", "docs", "archive", "archives", "backups",
    "node_modules", ".venv", "venv", ".git", ".claude", ".codex", ".agents",
    "pins", "pinned", "artifacts", "curation", "curated", "provenance", "kb",
    "knowledge_base", "knowledgebase", "literature", "downloads", "reference_data",
}
OPERATIONS = (
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG",
    "rebase-merge", "rebase-apply", "sequencer", "index.lock",
)
PYTHON_CACHE = re.compile(r"[\w.]+\.cpython-\d+(?:\.opt-\d+)?\.pyc\Z")


class InventoryError(RuntimeError):
    """Missing, failed, or bounded evidence must not imply absence."""


def github_identity(value: str) -> str:
    """Accept GitHub SSH/HTTPS remotes without reporting embedded credentials."""
    if value.startswith("git@github.com:"):
        path = value[len("git@github.com:"):]
    else:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise InventoryError("origin has invalid URL syntax") from None
        if parsed.scheme not in {"https", "ssh"} or parsed.hostname != "github.com":
            raise InventoryError("origin must identify a github.com repository")
        if parsed.query or parsed.fragment or parsed.password:
            raise InventoryError("origin contains unsupported credential/query metadata")
        if port is not None or (
            parsed.scheme == "ssh" and parsed.username not in {None, "git"}
        ):
            raise InventoryError("origin has an unsupported port or SSH user")
        path = parsed.path.lstrip("/")
    path = path.removesuffix("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise InventoryError("origin has an invalid GitHub repository path")
    return path


class Git:
    def __init__(self, root: Path, *, timeout: float = 15, max_bytes: int = 16_000_000):
        self.root, self.timeout, self.max_bytes = root, timeout, max_bytes

    def run(self, *args: str, allowed: tuple[int, ...] = (0,)) -> bytes:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1", LC_ALL="C")
        # Trace2 reads global/system config before command-line -c settings.
        # Environment overrides disable all three destinations without hiding
        # legitimate repository configuration. Legacy GIT_TRACE* was stripped.
        env.update(GIT_TRACE2="0", GIT_TRACE2_EVENT="0", GIT_TRACE2_PERF="0")
        command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(self.root), *args]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        # Drain both streams with a shared hard cap; never emit Git's stderr,
        # which can contain configured URLs, credentials, or untrusted text.
        chunks: list[bytes] = []
        total = [0]
        overflow = threading.Event()
        diagnostic = threading.Event()
        mutex = threading.Lock()

        def drain(stream, collect: bool) -> None:
            try:
                while data := stream.read(65536):
                    if not collect:
                        diagnostic.set()
                    with mutex:
                        total[0] += len(data)
                        if total[0] > self.max_bytes:
                            overflow.set()
                            try:
                                proc.kill()
                            except ProcessLookupError:
                                pass
                            break
                        if collect:
                            chunks.append(data)
            finally:
                stream.close()

        readers = [threading.Thread(target=drain, args=(proc.stdout, True)),
                   threading.Thread(target=drain, args=(proc.stderr, False))]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
        finally:
            for reader in readers:
                reader.join()
        if overflow.is_set() or timed_out or proc.returncode not in allowed or diagnostic.is_set():
            reason = "output bound" if overflow.is_set() else "timeout" if timed_out else f"exit {proc.returncode}" if proc.returncode not in allowed else "diagnostic output"
            raise InventoryError(f"git {args[0]}: {reason}; evidence incomplete")
        return b"".join(chunks)

    def text(self, *args: str) -> str:
        return os.fsdecode(self.run(*args)).strip()


def nul_paths(raw: bytes) -> set[str]:
    if raw and not raw.endswith(b"\0"):
        raise InventoryError("Git path inventory is not NUL terminated")
    return {os.fsdecode(value) for value in raw.split(b"\0") if value}


def status_records(raw: bytes) -> list[dict]:
    if raw and not raw.endswith(b"\0"):
        raise InventoryError("Git status is not NUL terminated")
    fields = raw.split(b"\0")[:-1]
    rows = []
    if len(fields) % 2:
        raise InventoryError("Git staged status is incomplete")
    for index in range(0, len(fields), 2):
        if fields[index] not in {b"A", b"D", b"M", b"T", b"U", b"X", b"B"}:
            raise InventoryError("Git staged status record is malformed")
        rows.append({"index_status": fields[index].decode("ascii"), "path": os.fsdecode(fields[index + 1])})
    return rows


def fingerprint(info: os.stat_result) -> dict:
    return {
        "device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }


def protected_path(path: str) -> bool:
    parts = Path(path).parts
    return any(
        (part.lower() in PROTECTED_PARTS and not (
            part == "cache" and parts[max(0, index - 2):index] == (".pytest_cache", "v")
        ))
        or part.lower().startswith((".env", ".vendored", ".aws", ".ssh"))
        or re.search(r"(?:secret|credential|password|private[_-]?key|token)", part, re.I)
        or part.lower().endswith((".pem", ".key", ".p12", ".pfx"))
        for index, part in enumerate(parts)
    )


def cache_leaf_allowed(cache: str, relative: str, kind: str) -> bool:
    parts = Path(relative).parts
    if cache == "__pycache__":
        return kind == "file" and len(parts) == 1 and bool(PYTHON_CACHE.fullmatch(parts[0]))
    if cache == ".pytest_cache":
        if kind == "directory":
            return relative in {"v", "v/cache"}
        return relative in {".gitignore", "CACHEDIR.TAG", "README.md", "v/cache/nodeids", "v/cache/lastfailed", "v/cache/stepwise"}
    if kind == "directory":
        return len(parts) == 1 and bool(re.fullmatch(r"\d+\.\d+\.\d+", relative))
    return relative in {".gitignore", "CACHEDIR.TAG"} or (
        len(parts) == 2 and bool(re.fullmatch(r"\d+\.\d+\.\d+", parts[0]))
        and bool(re.fullmatch(r"[0-9a-f]+", parts[1]))
    )


def scan_tree(root: Path, tracked: set[str], ignored: set[str], untracked: set[str],
              *, max_entries: int, max_seconds: float) -> tuple[list[dict], list[str]]:
    """Use directory descriptors so a replaced directory cannot redirect scans."""
    entries, errors = [], []
    deadline = time.monotonic() + max_seconds
    root_device = root.stat().st_dev
    tracked_dirs = {str(parent) for path in tracked for parent in Path(path).parents}
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def walk(directory_fd: int, prefix: str, depth: int) -> None:
        before = fingerprint(os.fstat(directory_fd))
        with os.scandir(directory_fd) as listing:
            for item in listing:
                if len(entries) >= max_entries or time.monotonic() > deadline or depth > 100:
                    raise InventoryError("filesystem scan bound reached; unvisited paths remain unknown")
                relative = prefix + item.name
                try:
                    info = item.stat(follow_symlinks=False)
                    kind = "symlink" if stat.S_ISLNK(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "special"
                    reason = None
                    child_fd = None
                    if item.name == ".git":
                        reason = "git_metadata" if not prefix else "nested_git_metadata"
                    elif kind == "symlink":
                        reason = "symlink_not_followed"
                    elif info.st_dev != root_device or (kind == "directory" and os.path.ismount(root / relative)):
                        reason = "mount_not_traversed"
                    elif kind == "special":
                        reason = "special_file_not_opened"
                    elif kind == "directory" and protected_path(relative):
                        reason = "retained_protected_subtree"
                    elif kind == "directory":
                        child_fd = os.open(item.name, flags, dir_fd=directory_fd)
                        if fingerprint(os.fstat(child_fd)) != fingerprint(info):
                            os.close(child_fd)
                            raise InventoryError(f"directory changed while opening {relative!r}")
                        try:
                            os.stat(".git", dir_fd=child_fd, follow_symlinks=False)
                            reason = "nested_repository_not_traversed"
                        except FileNotFoundError:
                            pass
                        except OSError:
                            os.close(child_fd)
                            raise
                    try:
                        tracked_here = relative in tracked or relative in tracked_dirs
                        row = {"path": relative, "kind": kind, "metadata": fingerprint(info),
                               "tracked": relative in tracked, "tracked_descendants": relative in tracked_dirs,
                               "ignored": relative in ignored, "untracked": relative in untracked,
                               "disposition": "protected" if reason or tracked_here or protected_path(relative) else "review",
                               "reason": reason or ("tracked_or_tracked_descendants" if tracked_here else "protected_name" if protected_path(relative) else "unknown_material")}
                        if kind == "directory" and reason:
                            row.update(descendants_not_inspected=True, subtree_size_unmeasured=True)
                        entries.append(row)
                        if child_fd is not None and reason is None:
                            walk(child_fd, relative + "/", depth + 1)
                    finally:
                        if child_fd is not None:
                            os.close(child_fd)
                except OSError:
                    errors.append(f"cannot inspect metadata for {relative!r}")
        if fingerprint(os.fstat(directory_fd)) != before:
            errors.append(f"directory changed during scan: {prefix!r}")

    try:
        root_fd = os.open(root, flags)
        try:
            walk(root_fd, "", 0)
        finally:
            os.close(root_fd)
    except (OSError, InventoryError) as exc:
        errors.append(str(exc))
    entries.sort(key=lambda row: row["path"])
    return entries, errors


def cache_candidates(entries: list[dict], *, complete: bool, operations: list[str]) -> list[dict]:
    if not complete or operations:
        for row in entries:
            if Path(row["path"]).name in CACHE_NAMES:
                row.update(disposition="protected", candidate_exclusion="incomplete_evidence_or_git_operation")
        return []
    candidates = []
    for row in entries:
        if row["kind"] != "directory" or Path(row["path"]).name not in CACHE_NAMES:
            continue
        name, prefix = Path(row["path"]).name, row["path"] + "/"
        members = [entry for entry in entries if entry["path"].startswith(prefix)]
        reason = None
        if row["disposition"] == "protected":
            continue
        if not members:
            reason = "empty_cache_requires_review"
        elif any(entry["disposition"] == "protected" or entry["kind"] not in {"file", "directory"}
                 or not cache_leaf_allowed(name, entry["path"][len(prefix):], entry["kind"])
                 for entry in members):
            reason = "protected_or_unrecognized_cache_descendant"
        elif any(entry["metadata"]["size"] > 2_000_000 for entry in members) or sum(
            entry["metadata"]["size"] for entry in members if entry["kind"] == "file"
        ) > 16_000_000:
            reason = "cache_size_requires_review"
        if reason:
            row.update(disposition="protected", reason=reason)
            continue
        row.update(disposition="review_candidate", reason="recognized_tool_cache_metadata_only")
        candidates.append({"path": row["path"], "kind": name, "file_count": sum(entry["kind"] == "file" for entry in members),
                           "bytes": sum(entry["metadata"]["size"] for entry in members if entry["kind"] == "file"),
                           "requires_manual_review": True})
    return candidates


def git_metadata(git: Git, git_dir: Path) -> dict:
    branches = []
    raw = git.run("for-each-ref", "--format=%(refname)%00%(objectname)%00%(upstream)%00", "refs/heads", "refs/remotes")
    for line in raw.splitlines():
        fields = line.split(b"\0")
        if len(fields) != 4 or fields[-1]:
            raise InventoryError("Git branch inventory is malformed")
        branches.append(dict(zip(("ref", "oid", "upstream"), map(os.fsdecode, fields[:3]))))
    worktrees, current = [], {}
    raw = git.run("worktree", "list", "--porcelain", "-z")
    if raw and not raw.endswith(b"\0\0"):
        raise InventoryError("Git worktree inventory is incomplete")
    for field in raw.split(b"\0"):
        if not field:
            if current:
                worktrees.append(current)
                current = {}
        else:
            key, _, value = os.fsdecode(field).partition(" ")
            if key in current:
                raise InventoryError("Git worktree inventory repeats a metadata field")
            if key in {"worktree", "HEAD", "branch"} and value:
                current[key] = value
            elif key in {"locked", "prunable", "bare", "detached"}:
                # Lock/prune reasons can contain private notes. Preserve only
                # presence, never arbitrary free text from Git metadata files.
                current[key] = True
            else:
                raise InventoryError("Git worktree inventory has an unsupported metadata field")
    stash_ref = git.run("rev-parse", "--verify", "--quiet", "refs/stash", allowed=(0, 1))
    stash = git.run("reflog", "show", "--format=%H%x00%ct%x00", "refs/stash") if stash_ref else b""
    if stash_ref and not stash:
        raise InventoryError("stash ref exists without a readable reflog")
    stashes = []
    for line in stash.splitlines():
        fields = line.split(b"\0")
        if len(fields) != 3 or fields[-1]:
            raise InventoryError("Git stash inventory is malformed")
        stashes.append({"oid": fields[0].decode("ascii"), "commit_timestamp": fields[1].decode("ascii")})
    operations = [name for name in OPERATIONS if os.path.lexists(git_dir / name)]
    return {"branches": branches, "worktrees": worktrees, "stashes": stashes, "operations": operations,
            "diagnostic_refs": ["REBASE_HEAD"] if os.path.lexists(git_dir / "REBASE_HEAD") else []}


def inventory(repo: Path, expected_origin: str, *, max_entries: int = 50_000,
              max_seconds: float = 30, git_max_bytes: int = 16_000_000) -> dict:
    report = {
        "schema_version": 1, "mode": "read_only", "apply_supported": False,
        "generated_at": datetime.now(timezone.utc).isoformat(), "complete": False,
        "scope": "candidate scan outside retained protected subtrees; Git pathname metadata",
        "unstaged_content_state": "unmeasured; no worktree content comparisons or clean/process filters",
        "limitations": ["Metadata fingerprints are not content hashes, deletion authorization, or content drift proof.",
                        "Candidates require manual content, reference, provenance and user-intent review before any action.",
                        "No file-content or reference-absence claims; no worktree, branch or stash deletion recommendations.",
                        "Concurrent changes may invalidate this observation; revalidate exact paths before any action.",
                        "Known data/build/history/tool-environment roots are retained without inspecting descendants or measuring subtree sizes; ordinary source/scripts/tests trees are inspected within bounds.",
                        "Git metadata, nested repositories, symlinks and detected mounts are reported but never traversed; complete means the defined candidate scan completed, not that excluded subtrees were inspected."],
        "errors": [], "entries": [], "candidates": [],
    }
    try:
        if max_entries < 1 or max_seconds <= 0 or git_max_bytes < 1:
            raise InventoryError("inventory bounds must be positive")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_origin):
            raise InventoryError("expected origin must be owner/repository")
        root = repo.resolve(strict=True)
        if not root.is_dir():
            raise InventoryError("repository root is not a directory")
        git = Git(root, max_bytes=git_max_bytes)
        if git.text("rev-parse", "--is-bare-repository") != "false":
            raise InventoryError("a working repository is required")
        if Path(git.text("rev-parse", "--show-toplevel")).resolve() != root:
            raise InventoryError("--repo must be the exact Git working-tree root")
        origins = git.text("config", "--get-all", "remote.origin.url").splitlines()
        if len(origins) != 1 or github_identity(origins[0]).casefold() != expected_origin.casefold():
            raise InventoryError("origin identity does not match the expected repository")
        head = git.text("rev-parse", "--verify", "HEAD")
        git_dir = Path(git.text("rev-parse", "--absolute-git-dir"))
        common = git.text("rev-parse", "--path-format=absolute", "--git-common-dir")
        report["provenance"] = {"root": str(root), "git_dir": str(git_dir), "git_common_dir": common,
                                "head": head, "origin": expected_origin, "origin_url": f"https://github.com/{expected_origin}.git"}
        tracked = nul_paths(git.run("ls-files", "--cached", "-z"))
        ignored = nul_paths(git.run("ls-files", "--others", "--ignored", "--exclude-standard", "-z"))
        untracked = nul_paths(git.run("ls-files", "--others", "--exclude-standard", "-z"))
        report["staged_status"] = status_records(git.run("diff-index", "--cached", "--name-status", "-z", "--no-ext-diff", "--no-textconv", "--no-renames", "HEAD", "--"))
        report.update(git_metadata(git, git_dir))
        report["entries"], errors = scan_tree(root, tracked, ignored, untracked, max_entries=max_entries, max_seconds=max_seconds)
        report["errors"].extend(errors)
        if git.text("rev-parse", "--verify", "HEAD") != head:
            report["errors"].append("HEAD changed during inventory")
        if git.text("config", "--get-all", "remote.origin.url").splitlines() != origins:
            report["errors"].append("origin configuration changed during inventory")
        report["complete"] = not report["errors"]
        report["candidates"] = cache_candidates(report["entries"], complete=report["complete"], operations=report["operations"])
        report["retained_subtrees"] = [entry["path"] for entry in report["entries"] if entry.get("descendants_not_inspected")]
        report["git_path_counts"] = {"tracked": len(tracked), "ignored": len(ignored), "untracked": len(untracked)}
        encoded = json.dumps([(entry["path"], entry["metadata"]) for entry in report["entries"]], sort_keys=True).encode()
        report["metadata_fingerprint_sha256"] = hashlib.sha256(encoded).hexdigest()
    except (InventoryError, OSError, ValueError, UnicodeError) as exc:
        # OSError text can include a filename, but never opened file contents.
        report["errors"].append(str(exc))
        report["complete"] = False
        report["candidates"] = []
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--expected-origin", required=True, metavar="OWNER/REPO")
    parser.add_argument("--json", action="store_true", help="write the full JSON report to stdout")
    parser.add_argument("--max-entries", type=int, default=50_000)
    parser.add_argument("--max-seconds", type=float, default=30)
    parser.add_argument("--git-max-bytes", type=int, default=16_000_000)
    args = parser.parse_args(argv)
    report = inventory(args.repo, args.expected_origin, max_entries=args.max_entries, max_seconds=args.max_seconds, git_max_bytes=args.git_max_bytes)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"Read-only inventory: complete={report['complete']}, entries={len(report['entries'])}, review_candidates={len(report['candidates'])}")
        for error in report["errors"]:
            print(f"Incomplete: {error}")
        print("No apply support. Candidates and metadata fingerprints do not authorize deletion.")
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
