"""Bounded, read-only observations of explicitly owned session state (#938).

Callers resolve every repository through RepositorySettings and validate its
origin before calling. This module neither fetches nor establishes ownership
from a directory name. Remote evidence is the local remote-tracking refs, not a
claim that those refs are fresh on the server. The separate closure gate must
obtain authoritative origin evidence.

The file-age pass reads directory entries/stat metadata, never file contents.
Git object reads follow that pass. Operating-system atime effects of ordinary
reads are not a backup or a retention policy; no timestamp is explicitly set.
"""
from __future__ import annotations

import math
import os
import re
import selectors
import stat
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_DAY = 86400


@dataclass(frozen=True)
class Limits:
    """Hard per-Mech bounds; exhaustion is an unknown observation, not zero."""

    max_entries: int = 100_000
    max_depth: int = 64
    max_roots: int = 64
    max_refs: int = 10_000
    max_commits: int = 10_000
    max_output_bytes: int = 4_000_000
    max_samples: int = 20
    timeout_seconds: float = 15.0
    git_timeout_seconds: float = 3.0
    retention_seconds: float = 4 * _DAY
    warning_seconds: float = _DAY

    def __post_init__(self) -> None:
        for name in ("max_entries", "max_depth", "max_roots", "max_refs", "max_commits",
                     "max_output_bytes", "max_samples"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("timeout_seconds", "git_timeout_seconds", "retention_seconds", "warning_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.warning_seconds >= self.retention_seconds:
            raise ValueError("warning_seconds must be less than retention_seconds")


class ObservationError(RuntimeError):
    """A coded observation failure; never retain Git stderr or credentials."""


@dataclass
class _Budget:
    limits: Limits
    deadline: float = field(init=False)

    def __post_init__(self) -> None:
        self.deadline = time.monotonic() + self.limits.timeout_seconds

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise ObservationError("time_limit")

    def git_timeout(self) -> float:
        self.check()
        return min(self.limits.git_timeout_seconds, self.deadline - time.monotonic())


def run_git(root: Path, args: Sequence[str], *, input_bytes: bytes = b"",
            timeout: float, output_limit: int) -> bytes:
    """Run only the caller's read-only Git query, with bounded pipes and time.

    Ambient Git path/config injection and lazy partial-clone fetching are
    disabled. On exhaustion only this function's own Git child is terminated.
    """
    query = tuple(args)
    fixed = {
        ("rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir", "--is-shallow-repository"),
        ("worktree", "list", "--porcelain", "-z"),
        ("cat-file", "--batch-check=%(objectname) %(objecttype)"),
    }
    refs = (len(query) == 5 and query[0] == "for-each-ref"
            and re.fullmatch(r"--count=[1-9][0-9]*", query[1])
            and query[2:] == ("--format=%(refname)%00%(objectname)", "refs/heads", "refs/remotes"))
    commits = (len(query) == 5 and query[0] == "rev-list"
               and re.fullmatch(r"--max-count=[1-9][0-9]*", query[1])
               and query[2:] in {("--branches", "--not", "--remotes"),
                                 ("--stdin", "--not", "--remotes")})
    if query not in fixed and not refs and not commits:
        raise ObservationError("disallowed_git_query")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1",
               GIT_NO_REPLACE_OBJECTS="1", GIT_GRAFT_FILE=os.devnull,
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "gc.auto=0",
               "-c", "maintenance.auto=false", "-C", str(root), *args]
    deadline = time.monotonic() + timeout
    output = bytearray()
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env)
    except OSError as exc:
        raise ObservationError("git_unavailable") from exc
    assert process.stdin is not None and process.stdout is not None
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            if input_bytes:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()
            sent = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ObservationError("git_timeout")
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.data == "stdin":
                        try:
                            sent += os.write(key.fd, input_bytes[sent:sent + 65536])
                        except BrokenPipeError:
                            sent = len(input_bytes)
                        if sent == len(input_bytes):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                    else:
                        chunk = os.read(key.fd, min(65536, output_limit + 1 - len(output)))
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            output.extend(chunk)
                            if len(output) > output_limit:
                                raise ObservationError("git_output_limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ObservationError("git_timeout")
            try:
                result = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise ObservationError("git_timeout") from exc
            if result:
                raise ObservationError("git_failed")
            return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stdin.close()


def _git(root: Path, args: Sequence[str], budget: _Budget, input_bytes: bytes = b"") -> bytes:
    return run_git(root, args, input_bytes=input_bytes, timeout=budget.git_timeout(),
                   output_limit=budget.limits.max_output_bytes)


def _absolute(path: Path) -> Path:
    if not path.is_absolute() or "\x00" in str(path):
        raise ObservationError("invalid_owned_path")
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ObservationError("missing_or_unresolvable_path") from exc


def _refs(root: Path, budget: _Budget) -> tuple[bytes, int, int]:
    raw = _git(root, ["for-each-ref", f"--count={budget.limits.max_refs + 1}",
                      "--format=%(refname)%00%(objectname)", "refs/heads", "refs/remotes"], budget)
    lines = raw.splitlines()
    if len(lines) > budget.limits.max_refs:
        raise ObservationError("ref_limit")
    local = remote = 0
    for line in lines:
        fields = line.split(b"\0")
        if len(fields) != 2 or not _SHA.fullmatch(fields[1].decode("ascii", errors="replace")):
            raise ObservationError("invalid_ref_observation")
        if fields[0].startswith(b"refs/heads/"):
            local += 1
        elif fields[0].startswith(b"refs/remotes/"):
            remote += 1
        else:
            raise ObservationError("invalid_ref_observation")
    return raw, local, remote


@dataclass
class _Repository:
    root: Path
    common: Path
    refs: bytes
    local_refs: int
    remote_refs: int
    worktrees: list[Path]
    shallow: bool
    worktree_snapshot: bytes


def _repository(path: Path, budget: _Budget) -> _Repository:
    root = _absolute(path)
    metadata = _git(root, ["rev-parse", "--path-format=absolute", "--show-toplevel",
                           "--git-common-dir", "--is-shallow-repository"], budget).decode().splitlines()
    if (len(metadata) != 3 or _absolute(Path(metadata[0])) != root
            or metadata[2] not in {"true", "false"}):
        raise ObservationError("not_exact_repository_root")
    common = _absolute(Path(metadata[1]))
    raw = _git(root, ["worktree", "list", "--porcelain", "-z"], budget)
    worktrees = [Path(item[9:].decode()) for item in raw.split(b"\0") if item.startswith(b"worktree ")]
    if not worktrees or len(worktrees) > budget.limits.max_roots:
        raise ObservationError("worktree_limit_or_missing")
    refs, local, remote = _refs(root, budget)
    return _Repository(root, common, refs, local, remote, worktrees, metadata[2] == "true", raw)


def _commits(root: Path, args: Sequence[str], budget: _Budget, data: bytes = b"") -> set[str]:
    raw = _git(root, ["rev-list", f"--max-count={budget.limits.max_commits + 1}", *args], budget, data)
    rows = raw.decode("ascii").splitlines()
    if len(rows) > budget.limits.max_commits:
        raise ObservationError("commit_limit")
    if any(not _SHA.fullmatch(row) for row in rows):
        raise ObservationError("invalid_commit_observation")
    return set(rows)


def _unpublished(repositories: list[_Repository], budget: _Budget) -> set[str]:
    candidates: set[str] = set()
    for repo in repositories:
        candidates.update(_commits(repo.root, ["--branches", "--not", "--remotes"], budget))
        if len(candidates) > budget.limits.max_commits:
            raise ObservationError("commit_limit")
    # A fresher clone can know a remote contains a candidate that another clone
    # still considers local. Query available objects in one batch; never fetch.
    for repo in repositories:
        if not candidates or not repo.remote_refs:
            continue
        data = ("\n".join(sorted(candidates)) + "\n").encode("ascii")
        observed = _git(repo.root, ["cat-file", "--batch-check=%(objectname) %(objecttype)"], budget, data)
        rows = observed.decode("ascii").splitlines()
        if len(rows) != len(candidates):
            raise ObservationError("invalid_object_observation")
        available: set[str] = set()
        for expected, row in zip(sorted(candidates), rows, strict=True):
            if row == f"{expected} commit":
                available.add(expected)
            elif row != f"{expected} missing":
                raise ObservationError("invalid_object_observation")
        if available:
            uncovered = _commits(repo.root, ["--stdin", "--not", "--remotes"], budget,
                                  ("\n".join(sorted(available)) + "\n").encode("ascii"))
            candidates.difference_update(available - uncovered)
    for repo in repositories:
        if _refs(repo.root, budget)[0] != repo.refs:
            raise ObservationError("refs_changed_during_observation")
        if _git(repo.root, ["worktree", "list", "--porcelain", "-z"], budget) != repo.worktree_snapshot:
            raise ObservationError("worktrees_changed_during_observation")
    return candidates


def _temporary_bases(tmpdir: Path | None) -> tuple[Path, ...]:
    paths = [Path("/tmp"), Path("/private/tmp")]
    supplied = tmpdir if tmpdir is not None else (Path(os.environ["TMPDIR"]) if os.environ.get("TMPDIR") else None)
    if supplied is not None:
        if not supplied.is_absolute() or supplied == Path("/"):
            raise ObservationError("invalid_tmpdir")
        paths.append(supplied)
    try:
        return tuple(dict.fromkeys(path.resolve(strict=False) for path in paths))
    except (RuntimeError, OSError) as exc:
        raise ObservationError("invalid_tmpdir") from exc


def _open_directory(path: Path, budget: _Budget) -> int:
    """Anchor every canonical ancestor; O_NOFOLLOW on only the leaf is unsafe."""
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise ObservationError("unsupported_directory_safety")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            budget.check()
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _scan_paths(paths: Sequence[Path], explicit: set[Path], known_roots: set[Path],
                common_dirs: set[Path], bases: tuple[Path, ...], now: float, budget: _Budget) -> dict[str, Any]:
    result: dict[str, Any] = {"complete": True, "at_risk_files": 0, "overdue_files": 0,
                              "scanned_entries": 0, "regular_files": 0, "temporary_paths": 0,
                              "symlinks_skipped": 0, "samples": [], "errors": []}
    limits = budget.limits

    def error(code: str, path: Path) -> None:
        result["complete"] = False
        if len(result["errors"]) < limits.max_samples:
            result["errors"].append({"code": code, "path": str(path)})

    resolved: set[Path] = set()
    explicit_resolved: set[Path] = set()
    for path in paths:
        try:
            budget.check()
            root = _absolute(path)
            if root in {Path("/"), Path.home().resolve(), *bases}:
                raise ObservationError("unbounded_owned_path")
            if path in explicit:
                explicit_resolved.add(root)
            if root in explicit_resolved or any(root.is_relative_to(base) for base in bases):
                resolved.add(root)
        except ObservationError as exc:
            error(str(exc), path)
    # A declared campaign can contain a registered clone; scan its files once.
    roots: list[Path] = []
    for root in sorted(resolved, key=lambda item: (len(item.parts), str(item))):
        if not any(root.is_relative_to(parent) for parent in roots):
            roots.append(root)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

    def file_info(path: Path, info: os.stat_result, temporary: bool) -> None:
        result["regular_files"] += 1
        if not temporary:
            return
        times = (info.st_atime, info.st_mtime, info.st_ctime)
        if any(not math.isfinite(value) for value in times) or max(times) > now + 60:
            raise ObservationError("invalid_or_future_file_time")
        age = now - max(times)
        if age >= limits.retention_seconds - limits.warning_seconds:
            result["at_risk_files"] += 1
            result["overdue_files"] += int(age >= limits.retention_seconds)
            if len(result["samples"]) < limits.max_samples:
                result["samples"].append({"path": str(path), "age_seconds": age,
                                           "seconds_to_cutoff": limits.retention_seconds - age})

    def walk(fd: int, path: Path, depth: int, device: int, temporary: bool) -> None:
        budget.check()
        names = set()
        with os.scandir(fd) as entries:
            for entry in entries:
                budget.check()
                if result["scanned_entries"] >= limits.max_entries:
                    raise ObservationError("entry_limit")
                result["scanned_entries"] += 1
                names.add(entry.name)
                child = path / entry.name
                if entry.name == ".git" and path not in known_roots and path not in common_dirs:
                    error("unregistered_repository", path)
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        result["symlinks_skipped"] += 1
                    elif info.st_dev != device:
                        error("cross_device_path", child)
                    elif stat.S_ISREG(info.st_mode):
                        file_info(child, info, temporary)
                    elif stat.S_ISDIR(info.st_mode):
                        if depth >= limits.max_depth:
                            error("depth_limit", child)
                            continue
                        child_fd = os.open(entry.name, flags, dir_fd=fd)
                        try:
                            opened = os.fstat(child_fd)
                            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                                raise ObservationError("directory_changed_during_observation")
                            walk(child_fd, child, depth + 1, device, temporary)
                        finally:
                            os.close(child_fd)
                except OSError:
                    error("unreadable_or_changed_path", child)
        if {"HEAD", "objects", "refs"} <= names and path not in common_dirs:
            error("unregistered_repository", path)

    for root in roots[:limits.max_roots]:
        temporary = any(root.is_relative_to(base) for base in bases)
        result["temporary_paths"] += int(temporary)
        try:
            budget.check()
            parent_fd = _open_directory(root.parent, budget)
            try:
                info = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    if result["scanned_entries"] >= limits.max_entries:
                        raise ObservationError("entry_limit")
                    result["scanned_entries"] += 1
                    file_info(root, info, temporary)
                elif stat.S_ISDIR(info.st_mode):
                    fd = os.open(root.name, flags, dir_fd=parent_fd)
                    try:
                        opened = os.fstat(fd)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise ObservationError("directory_changed_during_observation")
                        walk(fd, root, 0, info.st_dev, temporary)
                    finally:
                        os.close(fd)
                else:
                    raise ObservationError("not_regular_owned_path")
            finally:
                os.close(parent_fd)
        except (OSError, ObservationError) as exc:
            error(str(exc) if isinstance(exc, ObservationError) else "unreadable_owned_path", root)
            if str(exc) in {"time_limit", "entry_limit"}:
                break
    if len(roots) > limits.max_roots:
        error("root_limit", roots[limits.max_roots])
    return result


def observe_mech(repository_roots: Sequence[Path], *, session_state_paths: Sequence[Path] | None,
                 tmpdir: Path | None = None, now: datetime | None = None,
                 limits: Limits = Limits()) -> dict[str, Any]:
    """Observe an explicit same-Mech ownership inventory without changing it.

    ``None`` state paths means the inventory has not been declared; an empty
    sequence is an explicit declaration that only repository/worktree roots
    need observation. Unregistered Git markers in declared state paths make
    the inventory incomplete. No global temporary-directory scan is performed.
    """
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    budget = _Budget(limits)
    errors: list[dict[str, str]] = []
    repositories: dict[Path, _Repository] = {}
    paths = [Path(item) for item in (session_state_paths or ())[:limits.max_roots]]
    explicit = set(paths)
    known_roots: set[Path] = set()
    for value in repository_roots[:limits.max_roots]:
        path = Path(value)
        paths.append(path)
        try:
            repo = _repository(path, budget)
            repositories.setdefault(repo.common, repo)
            paths.extend(repo.worktrees)
            known_roots.update(tree.resolve(strict=False) for tree in repo.worktrees)
            if repo.shallow:
                errors.append({"code": "shallow_history", "path": str(repo.root)})
            if not repo.remote_refs:
                errors.append({"code": "no_remote_tracking_refs", "path": str(repo.root)})
        except (ObservationError, UnicodeError, OSError) as exc:
            errors.append({"code": str(exc) if isinstance(exc, ObservationError) else "invalid_git_observation",
                           "path": str(path)})
    if not repository_roots:
        errors.append({"code": "repository_inventory_missing"})
    if len(repository_roots) > limits.max_roots:
        errors.append({"code": "root_limit"})
    if session_state_paths is not None and len(session_state_paths) > limits.max_roots:
        errors.append({"code": "state_root_limit"})
    if session_state_paths is None:
        errors.append({"code": "state_inventory_missing"})
    try:
        bases = _temporary_bases(tmpdir)
        temporary = _scan_paths(paths, explicit, known_roots, set(repositories), bases,
                                observed.timestamp(), budget)
    except ObservationError as exc:
        temporary = {"complete": False, "at_risk_files": 0, "overdue_files": 0,
                     "errors": [{"code": str(exc)}], "samples": [], "temporary_paths": 0}
    count: int | None = None
    commit_samples: list[str] = []
    try:
        commits = _unpublished(list(repositories.values()), budget)
        count = len(commits)
        commit_samples = sorted(commits)[:limits.max_samples]
        if any(item["code"] not in {"no_remote_tracking_refs", "state_inventory_missing"} for item in errors):
            count = None
    except (ObservationError, UnicodeError, OSError) as exc:
        errors.append({"code": str(exc) if isinstance(exc, ObservationError) else "invalid_git_observation"})
    errors.extend(temporary["errors"])
    observed_count = count
    if any(item["code"] == "unregistered_repository" for item in temporary["errors"]):
        count = None
    inventory_complete = session_state_paths is not None and len(session_state_paths) <= limits.max_roots
    if not inventory_complete:
        count = None
    complete = not errors and temporary["complete"]
    risk = bool(count or temporary["at_risk_files"] or commit_samples)
    status = "alert" if risk else ("healthy" if complete else "unknown")
    return {"schema_version": "1.0.0", "observed_at": observed.astimezone(timezone.utc).isoformat(),
            "status": status, "alert": status != "healthy", "complete": complete,
            "repository_count": len(repositories), "unpushed_commits": count,
            "at_risk_files": temporary["at_risk_files"] if temporary["complete"] and inventory_complete else None,
            "overdue_files": temporary["overdue_files"] if temporary["complete"] and inventory_complete else None,
            "observed_unpushed_commits": observed_count,
            "observed_at_risk_files": temporary["at_risk_files"],
            "observed_overdue_files": temporary["overdue_files"],
            "commit_samples": commit_samples, "temporary": temporary,
            "errors": errors[:limits.max_samples],
            "error_count": len(errors),
            "remote_evidence": "local_remote_tracking_refs_only_no_fetch",
            "retention_seconds": limits.retention_seconds, "warning_seconds": limits.warning_seconds,
            "repositories": [{"root": str(repo.root), "common_dir": str(repo.common),
                               "local_branch_count": repo.local_refs,
                               "remote_tracking_ref_count": repo.remote_refs,
                               "worktrees": [str(path) for path in repo.worktrees]}
                              for repo in repositories.values()]}


def observe_repository(root: Path, *, session_state_paths: Sequence[Path] | None = None,
                       tmpdir: Path | None = None, now: datetime | None = None,
                       limits: Limits = Limits()) -> dict[str, Any]:
    """Convenience wrapper for one already identity-validated repository root."""
    return observe_mech([root], session_state_paths=session_state_paths, tmpdir=tmpdir,
                         now=now, limits=limits)


def public_summary(observation: dict[str, Any]) -> dict[str, Any]:
    """Project fixed counts/status only; exclude private paths, refs and text."""
    fields = {"schema_version", "observed_at", "status", "alert", "complete", "repository_count",
              "unpushed_commits", "at_risk_files", "overdue_files"}
    private = {"observed_unpushed_commits", "observed_at_risk_files", "observed_overdue_files",
               "commit_samples", "temporary", "errors", "error_count", "remote_evidence",
               "retention_seconds", "warning_seconds", "repositories"}
    if not isinstance(observation, dict) or not fields <= observation.keys() or observation.keys() - fields - private:
        raise ValueError("invalid durability observation fields")
    if (observation["schema_version"] != "1.0.0" or not isinstance(observation["status"], str)
            or observation["status"] not in {"healthy", "alert", "unknown"}):
        raise ValueError("invalid durability observation version/status")
    for key in ("alert", "complete"):
        if type(observation[key]) is not bool:
            raise ValueError("invalid durability flag")
    for key in ("repository_count", "unpushed_commits", "at_risk_files", "overdue_files"):
        value = observation[key]
        if (value is None and key != "repository_count"):
            continue
        if type(value) is not int or value < 0:
            raise ValueError("invalid durability count")
    try:
        timestamp = datetime.fromisoformat(observation["observed_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid durability timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("invalid durability timestamp")
    if observation["alert"] != (observation["status"] != "healthy"):
        raise ValueError("inconsistent durability alert")
    if observation["status"] == "unknown" and observation["complete"]:
        raise ValueError("inconsistent unknown durability observation")
    if observation["complete"] and any(observation[key] is None for key in (
            "unpushed_commits", "at_risk_files", "overdue_files")):
        raise ValueError("incomplete durability counts")
    if (observation["at_risk_files"] is not None and observation["overdue_files"] is not None
            and observation["overdue_files"] > observation["at_risk_files"]):
        raise ValueError("inconsistent durability file counts")
    if observation["status"] == "healthy" and (not observation["complete"] or not observation["repository_count"] or any(
            observation[key] != 0 for key in ("unpushed_commits", "at_risk_files", "overdue_files"))):
        raise ValueError("inconsistent healthy durability observation")
    return {key: observation[key] for key in sorted(fields)}
