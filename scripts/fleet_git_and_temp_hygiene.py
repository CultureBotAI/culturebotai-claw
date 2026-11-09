#!/usr/bin/env python3
"""Read-only fleet Git worktree, branch, stash, lock, and temp-file hygiene audit.

Inspects:
1. System temp roots (`/tmp`, `/private/tmp`, `$TMPDIR`), deduplicated by realpath:
   - Flags helper scripts (`.py`, `.sh`, `.R`, `.jq`, `.sql`) as
     `PROVENANCE_PROMOTE_REQUIRED` (promote to `scripts/adhoc/` before cleanup).
   - Identifies temporary Git clones/worktrees, tool caches/browser profiles, and
     intermediate scratch data/logs, including byte sizes and macOS 4-day `/tmp`
     reaper risk (`age_days >= 3.0`).
2. `claw/workspace/` runtime state:
   - Distinguishes registered git worktrees, orphan worktrees, runtime state
     directories, and lock files.
   - Performs strictly read-only inspection of `workspace/locks/*.lock` and
     `*.lock.guard` (never unlinking expired locks or mutating directories).
3. Local Git state across `claw`, all 14 manifest-declared Mechs,
   `CultureBotAI.github.io`, and `kg-microbe`:
   - Current branch, dirty/untracked counts, local branch count, worktrees
     (including `prunable`, `locked`, and `missing_on_disk`), stash count,
     active Git operations (`MERGE_HEAD`, `rebase-merge`, `index.lock`, etc.),
     and shadowed sibling checkouts (`sibling_default` vs `.env` root).

Strictly read-only: never deletes files, prunes worktrees, drops stashes, or
releases locks.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from kg_microbe_fleet.roots import (  # noqa: E402
    MechRootError,
    dotenv_value,
    resolve_culturebotai_site_root,
    resolve_mech_root,
    sibling_default,
)
from kg_microbe_fleet.roots import (  # noqa: E402
    claw_root as default_claw_root,
)
from plugins.lock_manager import UniqueKeySafeLoader  # noqa: E402

PROVENANCE_SCRIPT_SUFFIXES = {".py", ".sh", ".r", ".jq", ".sql"}
SCRATCH_DATA_SUFFIXES = {
    ".json",
    ".jsonl",
    ".tsv",
    ".csv",
    ".txt",
    ".log",
    ".md",
    ".html",
    ".pdf",
    ".png",
    ".svg",
    ".yaml",
    ".yml",
    ".bak",
}
CACHE_OR_PROFILE_PATTERNS = (
    "pip-audit-cache",
    "puppeteer",
    "claude-",
    "codex-",
    "agy-",
    "pytest-of-",
    "uv-",
    "mypy-",
    "ruff-",
)
FLEET_TEMP_KEYWORDS = (
    "mech",
    "claw",
    "kg-microbe",
    "kgm",
    "culturebot",
    "sssom",
    "metpo",
    "feba",
    "mim",
    "pip-audit",
    "gh_",
    "pr_",
    "issue",
    "audit",
    "figure",
    "plate",
    "proposal",
)
GIT_OPERATIONS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
    "rebase-merge",
    "rebase-apply",
    "sequencer",
    "index.lock",
)
REAPER_WARN_DAYS = 3.0


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        LC_ALL="C",
    )
    return env


def _run_git(root: Path, *args: str, timeout: float = 15.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.excludesFile={os.devnull}",
            "-C",
            str(root),
            *args,
        ],
        capture_output=True,
        env=_git_env(),
        timeout=timeout,
        check=False,
    )


def _bounded_tree_size(path: Path, max_entries: int = 2500) -> tuple[int, int, bool]:
    """Return (bytes, file_count, truncated) using bounded os.scandir without reading files."""
    try:
        st = path.lstat()
    except OSError:
        return 0, 0, False
    if not path.is_dir() or path.is_symlink():
        return int(st.st_size), 1, False

    total_bytes = 0
    file_count = 0
    seen = 0
    truncated = False
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    seen += 1
                    if seen > max_entries:
                        truncated = True
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    else:
                        total_bytes += int(info.st_size)
                        file_count += 1
        except OSError:
            continue
        if truncated:
            break
    return total_bytes, file_count, truncated


def classify_temp_entry(name: str, path: Path, is_dir: bool) -> str | None:
    """Classify a top-level temp entry if relevant to development/fleet hygiene."""
    lower = name.lower()
    suffix = Path(name).suffix.lower()

    if not is_dir and suffix in PROVENANCE_SCRIPT_SUFFIXES:
        return "PROVENANCE_PROMOTE_REQUIRED"

    if is_dir:
        try:
            if (path / ".git").exists():
                return "TEMP_GIT_CHECKOUT"
        except OSError:
            pass
        # Check if directory contains any provenance helper scripts at depth 1
        try:
            with os.scandir(path) as it:
                for sub in it:
                    if sub.is_file(follow_symlinks=False) and Path(sub.name).suffix.lower() in PROVENANCE_SCRIPT_SUFFIXES:
                        return "PROVENANCE_PROMOTE_REQUIRED"
        except OSError:
            pass

    if any(pat in lower for pat in CACHE_OR_PROFILE_PATTERNS):
        return "TOOL_CACHE_OR_PROFILE"

    if any(kw in lower for kw in FLEET_TEMP_KEYWORDS) or suffix in SCRATCH_DATA_SUFFIXES:
        return "SCRATCH_DATA_OR_LOG"

    return None


def scan_temp_roots(
    tmp_roots: list[Path] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scan system temp roots (deduplicated by realpath) in read-only mode."""
    current_time = now or datetime.now(timezone.utc)
    if tmp_roots is None:
        candidates = [Path("/tmp"), Path("/private/tmp")]
        tmpdir_env = os.environ.get("TMPDIR")
        if tmpdir_env:
            candidates.append(Path(tmpdir_env))
    else:
        candidates = list(tmp_roots)

    deduped_roots: list[Path] = []
    seen_realpaths: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen_realpaths or not resolved.is_dir():
            continue
        seen_realpaths.add(resolved)
        deduped_roots.append(resolved)

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for root in deduped_roots:
        try:
            with os.scandir(root) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            errors.append(f"{root}: {exc}")
            continue

        for entry in entries:
            entry_path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            category = classify_temp_entry(entry.name, entry_path, is_dir)
            if category is None:
                continue

            size_bytes, file_count, size_truncated = _bounded_tree_size(entry_path)
            mtime = datetime.fromtimestamp(info.st_mtime, tz=timezone.utc)
            age_days = round(max(0.0, (current_time - mtime).total_seconds() / 86400.0), 2)
            items.append(
                {
                    "path": str(entry_path),
                    "name": entry.name,
                    "kind": "directory" if is_dir else "file",
                    "category": category,
                    "size_bytes": size_bytes,
                    "file_count": file_count,
                    "size_truncated": size_truncated,
                    "modified_at": mtime.isoformat(),
                    "age_days": age_days,
                    "reaper_risk": age_days >= REAPER_WARN_DAYS,
                }
            )

    by_category: dict[str, int] = {}
    for item in items:
        cat = item["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "scanned_roots": [str(r) for r in deduped_roots],
        "total_items": len(items),
        "total_bytes": sum(item["size_bytes"] for item in items),
        "by_category": by_category,
        "provenance_scripts": [
            item["path"] for item in items if item["category"] == "PROVENANCE_PROMOTE_REQUIRED"
        ],
        "items": items,
        "errors": errors,
    }


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def inspect_locks_readonly(
    lock_dir: Path,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Inspect workspace/locks without instantiating LockManager or mutating files."""
    current_time = now or datetime.now(timezone.utc)
    if not lock_dir.is_dir():
        return []

    records: list[dict[str, Any]] = []
    try:
        entries = sorted(os.scandir(lock_dir), key=lambda e: e.name)
    except OSError:
        return []

    lock_names = {e.name for e in entries if e.name.endswith(".lock")}
    local_host = socket.gethostname()

    for entry in entries:
        path = Path(entry.path)
        if entry.name.endswith(".lock.guard"):
            corresponding = entry.name[: -len(".guard")].lstrip(".")
            if corresponding not in lock_names:
                records.append(
                    {
                        "file": entry.name,
                        "path": str(path),
                        "status": "ORPHAN_GUARD",
                        "repository": corresponding.removesuffix(".lock"),
                        "detail": "guard file has no matching .lock file",
                    }
                )
            continue
        if not entry.name.endswith(".lock"):
            continue

        try:
            raw = path.read_text(encoding="utf-8")
            data = yaml.load(raw, Loader=UniqueKeySafeLoader)
            if not isinstance(data, dict):
                raise ValueError("lock payload is not a mapping")
            expires_raw = str(data["expires_at"])
            expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            pid = int(data.get("pid", -1))
            host = str(data.get("hostname", ""))
            expired = current_time > expires_at
            same_host = host == local_host
            pid_alive = _pid_is_alive(pid) if same_host else None
            if expired:
                status = "EXPIRED"
            elif same_host and pid_alive is False:
                status = "DEAD_PID"
            else:
                status = "ACTIVE"
            records.append(
                {
                    "file": entry.name,
                    "path": str(path),
                    "status": status,
                    "repository": str(data.get("repository", entry.name.removesuffix(".lock"))),
                    "operation": str(data.get("operation", "")),
                    "owner": str(data.get("owner", "")),
                    "hostname": host,
                    "pid": pid,
                    "pid_alive": pid_alive,
                    "acquired_at": str(data.get("acquired_at", "")),
                    "expires_at": expires_at.isoformat(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            records.append(
                {
                    "file": entry.name,
                    "path": str(path),
                    "status": "MALFORMED",
                    "repository": entry.name.removesuffix(".lock"),
                    "detail": str(exc),
                }
            )
    return records


def scan_workspace(
    claw_root: Path,
    registered_worktrees: set[Path],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect claw/workspace/ subdirectories, worktrees, and locks read-only."""
    workspace_dir = claw_root / "workspace"
    if not workspace_dir.is_dir():
        return {
            "path": str(workspace_dir),
            "exists": False,
            "entries": [],
            "locks": [],
        }

    entries: list[dict[str, Any]] = []
    try:
        scanned = sorted(os.scandir(workspace_dir), key=lambda e: e.name)
    except OSError:
        scanned = []

    for item in scanned:
        item_path = Path(item.path)
        try:
            resolved = item_path.resolve()
            is_dir = item.is_dir(follow_symlinks=False)
        except OSError:
            continue

        if item.name == "locks" and is_dir:
            kind = "LOCK_DIRECTORY"
        elif resolved in registered_worktrees:
            kind = "REGISTERED_WORKTREE"
        elif is_dir and (item_path / ".git").exists():
            kind = "ORPHAN_WORKTREE"
        else:
            kind = "RUNTIME_STATE"

        size_bytes, file_count, truncated = _bounded_tree_size(item_path)
        entries.append(
            {
                "name": item.name,
                "path": str(item_path),
                "kind": kind,
                "size_bytes": size_bytes,
                "file_count": file_count,
                "size_truncated": truncated,
            }
        )

    locks = inspect_locks_readonly(workspace_dir / "locks", now=now)
    return {
        "path": str(workspace_dir),
        "exists": True,
        "entries": entries,
        "locks": locks,
    }


def _parse_worktree_porcelain(raw: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for token in raw.split(b"\0"):
        text = os.fsdecode(token)
        if not text:
            if current:
                wt_path = Path(current["worktree"])
                current["missing_on_disk"] = not wt_path.exists()
                records.append(current)
                current = {}
            continue
        key, _, value = text.partition(" ")
        if key == "worktree":
            current = {
                "worktree": value,
                "head": None,
                "branch": None,
                "bare": False,
                "detached": False,
                "locked": False,
                "prunable": False,
            }
        elif key in {"HEAD", "branch"}:
            current[key.lower()] = value
        elif key in {"bare", "detached", "locked", "prunable"}:
            current[key] = True
    if current:
        wt_path = Path(current["worktree"])
        current["missing_on_disk"] = not wt_path.exists()
        records.append(current)
    return records


def inspect_repo_git_hygiene(
    key: str,
    repo_name: str,
    root: Path | None,
    *,
    sibling_path: Path | None = None,
    config_error: str | None = None,
) -> dict[str, Any]:
    """Inspect one repository's local branches, worktrees, stashes, and operations."""
    row: dict[str, Any] = {
        "key": key,
        "repo": repo_name,
        "configured": root is not None,
        "root": str(root) if root is not None else None,
        "branch": None,
        "dirty_tracked_count": 0,
        "untracked_count": 0,
        "local_branch_count": 0,
        "stash_count": 0,
        "worktrees": [],
        "prunable_worktrees": 0,
        "locked_worktrees": 0,
        "operations": [],
        "sibling_shadow": None,
        "error": config_error,
    }
    if sibling_path is not None and sibling_path.exists():
        try:
            sib_real = sibling_path.resolve()
            if root is None:
                row["sibling_shadow"] = {
                    "sibling_path": str(sib_real),
                    "detail": "sibling checkout exists on disk while .env root is unconfigured",
                }
            elif sib_real != root.resolve():
                row["sibling_shadow"] = {
                    "sibling_path": str(sib_real),
                    "configured_root": str(root.resolve()),
                    "detail": "sibling_default checkout differs from .env-configured root",
                }
        except OSError:
            pass

    if root is None:
        return row
    if not root.is_dir():
        row["error"] = f"directory does not exist: {root}"
        return row

    head_proc = _run_git(root, "symbolic-ref", "-q", "--short", "HEAD")
    if head_proc.returncode == 0:
        row["branch"] = os.fsdecode(head_proc.stdout).strip()
    else:
        rev_proc = _run_git(root, "rev-parse", "--short", "HEAD")
        if rev_proc.returncode != 0:
            row["error"] = "not a readable Git repository"
            return row
        row["branch"] = "DETACHED"

    status_proc = _run_git(root, "status", "--porcelain=v1", "-z")
    if status_proc.returncode == 0:
        tokens = status_proc.stdout.split(b"\0")
        idx = 0
        dirty = 0
        untracked = 0
        while idx < len(tokens):
            tok = tokens[idx]
            idx += 1
            if not tok:
                continue
            code = os.fsdecode(tok[:2])
            if code == "??":
                untracked += 1
            else:
                dirty += 1
                if code[0] in {"R", "C"} and idx < len(tokens):
                    idx += 1
        row["dirty_tracked_count"] = dirty
        row["untracked_count"] = untracked

    refs_proc = _run_git(root, "for-each-ref", "--format=%(refname)", "refs/heads")
    if refs_proc.returncode == 0:
        row["local_branch_count"] = len(
            [line for line in refs_proc.stdout.splitlines() if line.strip()]
        )

    stash_proc = _run_git(root, "stash", "list")
    if stash_proc.returncode == 0:
        row["stash_count"] = len(
            [line for line in stash_proc.stdout.splitlines() if line.strip()]
        )

    wt_proc = _run_git(root, "worktree", "list", "--porcelain", "-z")
    if wt_proc.returncode == 0:
        worktrees = _parse_worktree_porcelain(wt_proc.stdout)
        row["worktrees"] = worktrees
        row["prunable_worktrees"] = sum(
            1 for wt in worktrees if wt.get("prunable") or wt.get("missing_on_disk")
        )
        row["locked_worktrees"] = sum(1 for wt in worktrees if wt.get("locked"))

    git_dir_proc = _run_git(root, "rev-parse", "--path-format=absolute", "--git-dir")
    if git_dir_proc.returncode == 0:
        git_dir = Path(os.fsdecode(git_dir_proc.stdout).strip())
        ops: list[str] = []
        for op_name in GIT_OPERATIONS:
            if (git_dir / op_name).exists():
                ops.append(op_name)
        row["operations"] = ops

    return row


def collect_hygiene_report(
    *,
    claw_root: Path | None = None,
    tmp_roots: list[Path] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect the complete read-only Git, worktree, lock, and temp hygiene report."""
    current_time = now or datetime.now(timezone.utc)
    resolved_claw = claw_root.resolve() if claw_root is not None else default_claw_root()
    manifest = load_fleet_manifest()

    repos: list[dict[str, Any]] = []
    claw_row = inspect_repo_git_hygiene("claw", "culturebotai-claw", resolved_claw)
    repos.append(claw_row)

    registered_claw_worktrees: set[Path] = set()
    for wt in claw_row.get("worktrees", []):
        try:
            registered_claw_worktrees.add(Path(wt["worktree"]).resolve())
        except OSError:
            pass

    for key in sorted(manifest.mechs):
        mech = manifest.mechs[key]
        repo_name = mech.github.split("/")[-1]
        sibling_path = sibling_default(mech.display_name, resolved_claw)
        try:
            mech_root: Path | None = resolve_mech_root(key, claw_root=resolved_claw)
            err = None
        except MechRootError as exc:
            mech_root = None
            err = str(exc)
        repos.append(
            inspect_repo_git_hygiene(
                key,
                repo_name,
                mech_root,
                sibling_path=sibling_path,
                config_error=err,
            )
        )

    # Companion X-Mech Suite site repository
    try:
        site_root: Path | None = resolve_culturebotai_site_root(claw_root=resolved_claw)
        site_err = None
    except MechRootError as exc:
        site_root = None
        site_err = str(exc)
    repos.append(
        inspect_repo_git_hygiene(
            "culturebotai_site",
            "CultureBotAI.github.io",
            site_root,
            sibling_path=resolved_claw.parent / "CultureBotAI.github.io",
            config_error=site_err,
        )
    )

    # Optional kg-microbe checkout
    kgm_raw = os.environ.get("KGM_ROOT") or dotenv_value(resolved_claw, "KGM_ROOT")
    kgm_sibling = resolved_claw.parent / "kg-microbe"
    kgm_root = Path(kgm_raw).resolve() if kgm_raw else (kgm_sibling.resolve() if kgm_sibling.is_dir() else None)
    if kgm_root is not None:
        repos.append(
            inspect_repo_git_hygiene(
                "kg_microbe",
                "kg-microbe",
                kgm_root,
                sibling_path=kgm_sibling,
            )
        )

    temp_summary = scan_temp_roots(tmp_roots, now=current_time)
    workspace_summary = scan_workspace(
        resolved_claw,
        registered_claw_worktrees,
        now=current_time,
    )

    findings: list[str] = []
    for script_path in temp_summary["provenance_scripts"]:
        findings.append(
            f"PROVENANCE_PROMOTE_REQUIRED: helper script in temp root must be saved to scripts/adhoc/: {script_path}"
        )
    for lock in workspace_summary["locks"]:
        if lock["status"] != "ACTIVE":
            findings.append(
                f"LOCK_{lock['status']}: {lock['file']} ({lock.get('repository', '')})"
            )
    for entry in workspace_summary["entries"]:
        if entry["kind"] == "ORPHAN_WORKTREE":
            findings.append(f"ORPHAN_WORKTREE in workspace/: {entry['path']}")
    for repo in repos:
        if repo["prunable_worktrees"] > 0:
            findings.append(
                f"PRUNABLE_WORKTREE: {repo['repo']} has {repo['prunable_worktrees']} prunable/missing worktree(s)"
            )
        if repo["operations"]:
            findings.append(
                f"ACTIVE_GIT_OPERATION: {repo['repo']} has {', '.join(repo['operations'])}"
            )
        if repo["sibling_shadow"] is not None:
            findings.append(
                f"SIBLING_SHADOW: {repo['repo']} ({repo['sibling_shadow']['detail']})"
            )

    return {
        "generated_at": current_time.isoformat(),
        "claw_root": str(resolved_claw),
        "temp": temp_summary,
        "workspace": workspace_summary,
        "repositories": repos,
        "findings": findings,
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "Fleet Git, Worktree, Lock, and Temp Hygiene Audit",
        f"Generated: {report['generated_at']}",
        "",
        "1. Repository Git & Worktree State",
        f"{'REPO':<24} {'BRANCH':<28} {'DIRTY':<6} {'UNTRK':<6} {'BRS':<5} {'WTS':<5} {'STASH':<6} {'OPS/NOTES'}",
    ]
    for repo in report["repositories"]:
        if not repo["configured"]:
            note = "unconfigured"
            if repo.get("sibling_shadow"):
                note += " (SHADOW SIBLING EXISTS)"
            lines.append(
                f"{repo['repo']:<24} {'-':<28} {'-':<6} {'-':<6} {'-':<5} {'-':<5} {'-':<6} {note}"
            )
            continue
        branch = (repo["branch"] or "-")[:27]
        wt_count = len(repo["worktrees"])
        notes: list[str] = []
        if repo["prunable_worktrees"]:
            notes.append(f"prunable_wt={repo['prunable_worktrees']}")
        if repo["locked_worktrees"]:
            notes.append(f"locked_wt={repo['locked_worktrees']}")
        if repo["operations"]:
            notes.append(f"ops={','.join(repo['operations'])}")
        if repo["sibling_shadow"]:
            notes.append("shadow_sibling")
        if repo["error"]:
            notes.append(f"err={repo['error']}")
        note_str = "; ".join(notes) if notes else "clean"
        lines.append(
            f"{repo['repo']:<24} {branch:<28} {repo['dirty_tracked_count']:<6} "
            f"{repo['untracked_count']:<6} {repo['local_branch_count']:<5} "
            f"{wt_count:<5} {repo['stash_count']:<6} {note_str}"
        )

    ws = report["workspace"]
    lines.extend(
        [
            "",
            f"2. CLAW Workspace ({ws['path']})",
        ]
    )
    if not ws["exists"]:
        lines.append("  workspace directory does not exist")
    else:
        for entry in ws["entries"]:
            lines.append(
                f"  {entry['name']:<34} {entry['kind']:<22} files={entry['file_count']:<6} bytes={entry['size_bytes']}"
            )
        if ws["locks"]:
            lines.append("  Locks:")
            for lock in ws["locks"]:
                lines.append(
                    f"    {lock['file']:<28} status={lock['status']:<12} repo={lock.get('repository', '-')}"
                )
        else:
            lines.append("  Locks: none")

    temp = report["temp"]
    lines.extend(
        [
            "",
            f"3. System Temp Roots ({', '.join(temp['scanned_roots'])})",
            f"  fleet/dev temp items={temp['total_items']}; total_bytes={temp['total_bytes']}; categories={temp['by_category']}",
        ]
    )
    for item in temp["items"][:25]:
        risk = " [REAPER_RISK]" if item["reaper_risk"] else ""
        lines.append(
            f"  {item['category']:<28} {item['age_days']:>5.1f}d {item['size_bytes']:>10}B  {item['path']}{risk}"
        )
    if len(temp["items"]) > 25:
        lines.append(f"  ... and {len(temp['items']) - 25} more temp item(s)")

    if report["findings"]:
        lines.extend(["", "Findings"])
        for finding in report["findings"]:
            lines.append(f"  - {finding}")
    else:
        lines.extend(["", "Findings: none"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claw-root",
        type=Path,
        default=None,
        help="Path to the culturebotai-claw repository root",
    )
    parser.add_argument(
        "--tmp-root",
        type=Path,
        action="append",
        dest="tmp_roots",
        default=None,
        help="Override temp root(s) to scan (may be passed multiple times)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_hygiene_report(
        claw_root=args.claw_root,
        tmp_roots=args.tmp_roots,
    )
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
