#!/usr/bin/env python3
"""Preview or fast-forward the current origin-tracking branch in claw and each Mech.

Default execution is offline and read-only. --apply fetches under a repository
lock and uses a fast-forward-only merge, with no branch switching or stashing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
import importlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

if not os.access(Path.home() / ".gitconfig", os.R_OK):
    os.environ.setdefault("GIT_CONFIG_GLOBAL", "/dev/null")
    os.environ.setdefault("GIT_CONFIG_NOSYSTEM", "1")

from kg_microbe_fleet import (
    FleetManifestError,
    UniqueKeySafeLoader,
    default_fleet_pull_schema_path,
    load_fleet_manifest,
)
from plugins.lock_manager import LockManager
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositoryTarget,
    RepositorySettings,
    merged_repository_environment,
)

CLAW_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_KEY = "claw"
CONTROL_PLANE_REPOSITORY = "CultureBotAI/culturebotai-claw"
SUCCESS = {"would_update", "updated", "up_to_date", "ahead"}
# REBASE_HEAD is a commit pointer that can survive a finished rebase. The
# rebase state directories identify an active operation, including paused ones.
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
               "rebase-merge", "rebase-apply", "sequencer", "BISECT_START", "index.lock")
PR_NUMBER_RE = re.compile(
    r"(?:Merge pull request #(\d+)|\(#(\d+)\)|\bPR\s+#(\d+))",
    re.IGNORECASE,
)


class GitError(RuntimeError):
    pass


class Git:
    """Give Git work, including fetch subprocesses, one shared deadline."""

    def __init__(self, root: Path, timeout: float):
        self.root = root
        self.deadline = time.monotonic() + timeout

    def run(self, *args: str, allowed=(0,)) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GitError("repository operation timed out")
        env = dict(os.environ)
        # A caller's alternate index/worktree must never redirect this command.
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                     "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            env.pop(name, None)
        env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                   "-c", "submodule.recurse=false", *args]
        with subprocess.Popen(
            command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        ) as process:
            try:
                stdout, _stderr = process.communicate(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise GitError(f"git {args[0]} timed out") from None
            except KeyboardInterrupt:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise
            if process.returncode not in allowed:
                # Remote stderr can contain authenticated URLs. Preserve the
                # failing operation and code without exposing credential text.
                raise GitError(f"git {args[0]} failed (exit {process.returncode})")
            return stdout.rstrip("\n")


class FleetPullSettings:
    """RepositorySettings plus the explicit claw control-plane checkout."""

    def __init__(self, settings, claw_root: Path = CLAW_ROOT) -> None:
        self._settings = settings
        self._claw = RepositoryTarget(
            CONTROL_PLANE_KEY,
            claw_root,
            CONTROL_PLANE_REPOSITORY,
        )

    @property
    def unconfigured(self) -> tuple[str, ...]:
        return self._settings.unconfigured

    def get_target(self, key: str) -> RepositoryTarget:
        if key == CONTROL_PLANE_KEY:
            self._claw.open()
            return self._claw
        return self._settings.get_target(key)


def inspect(git: Git) -> dict:
    state: dict = {"status": "eligible", "detail": "", "branch": None,
                   "upstream": None, "before": None, "after": None,
                   "ahead": None, "behind": None, "commits": [], "prs": []}
    branch_ref = git.run("symbolic-ref", "--quiet", "HEAD", allowed=(0, 1))
    state["before"] = git.run("rev-parse", "--verify", "HEAD^{commit}")
    state["after"] = state["before"]
    if not branch_ref:
        return {**state, "status": "skipped_detached", "detail": "HEAD is detached"}
    state["branch"] = branch_ref.removeprefix("refs/heads/")
    for marker in IN_PROGRESS:
        path = Path(git.run("rev-parse", "--git-path", marker))
        if (git.root / path).exists():
            return {**state, "status": "skipped_in_progress", "detail": marker}
    if git.run("status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"):
        return {**state, "status": "skipped_dirty",
                "detail": "staged, unstaged, untracked, or submodule changes"}
    tracking = git.run("for-each-ref", "--format=%(upstream)%00%(upstream:remotename)"
                       "%00%(upstream:remoteref)", branch_ref).split("\0")
    if len(tracking) != 3 or not tracking[0]:
        return {**state, "status": "skipped_no_upstream", "detail": "no tracking branch"}
    upstream, remote, remote_ref = tracking
    state["upstream"] = upstream
    state["remote_ref"] = remote_ref
    if remote != "origin" or not upstream.startswith("refs/remotes/origin/") or not remote_ref.startswith("refs/heads/"):
        return {**state, "status": "skipped_non_origin",
                "detail": "requires an origin branch with an origin tracking ref"}
    if git.run("symbolic-ref", "--quiet", upstream, allowed=(0, 1)):
        return {**state, "status": "skipped_symbolic_upstream",
                "detail": "symbolic tracking ref could redirect fetch into a local branch"}
    return state


def extract_commits_and_prs(
    git: Git, before: str, target: str
) -> tuple[list[dict[str, str]], list[str]]:
    log_output = git.run("log", "--format=%h%x09%s", f"{before}..{target}")
    commits: list[dict[str, str]] = []
    prs: list[str] = []
    seen_prs: set[str] = set()
    for line in log_output.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        subject = subject.strip()
        commits.append({"sha": sha.strip(), "subject": subject})
        for match in PR_NUMBER_RE.finditer(subject):
            number = next(group for group in match.groups() if group is not None)
            pr_ref = f"#{number}"
            if pr_ref not in seen_prs:
                seen_prs.add(pr_ref)
                prs.append(pr_ref)
    return commits, prs


def compare(git: Git, state: dict) -> dict:
    target = git.run("rev-parse", "--verify", state["upstream"] + "^{commit}")
    ahead, behind = map(int, git.run("rev-list", "--left-right", "--count",
                                    state["before"] + "..." + target).split())
    status = ("skipped_diverged" if ahead and behind else "ahead" if ahead
              else "would_update" if behind else "up_to_date")
    commits, prs = (
        extract_commits_and_prs(git, state["before"], target)
        if status == "would_update"
        else ([], [])
    )
    return {**state, "status": status, "ahead": ahead, "behind": behind,
            "target": target, "commits": commits, "prs": prs,
            "detail": "local and upstream histories diverged" if ahead and behind else ""}


def update_one(settings, key: str, root: Path, *, timeout: float) -> dict:
    git = Git(root, timeout)
    state: dict = {}
    try:
        # Revalidate after acquiring the lock, not just at fleet discovery time.
        if settings.get_target(key).path != root:
            raise GitError("repository path changed during preflight")
        before = inspect(git)
        state = before.copy()
        if before["status"] != "eligible":
            return state
        # Keep the inspected branch/HEAD even if a mutation fails. Its final
        # HEAD is unknown until another successful observation, including when
        # a command changes the checkout before failing or exhausting its deadline.
        state["after"] = None
        git.run("fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                "--no-auto-maintenance", "--no-prune", "--refmap=", "origin",
                "+" + before["remote_ref"] + ":" + before["upstream"])
        # A non-cooperating process could edit files, change branch, or reconfigure
        # tracking during fetch. Recheck before touching the working tree.
        if settings.get_target(key).path != root:
            raise GitError("repository path changed during fetch")
        current = inspect(git)
        state["after"] = current["before"]
        if current["status"] != "eligible":
            return current
        if any(current.get(name) != before.get(name)
               for name in ("before", "branch", "upstream", "remote_ref")):
            raise GitError("HEAD, branch, or tracking changed during fetch; rerun")
        state = compare(git, current)
        if state["status"] != "would_update":
            return state
        state["after"] = None
        git.run("merge", "--ff-only", "--no-squash", "--no-autostash",
                "--no-overwrite-ignore", "--no-edit", "--no-stat", state["target"])
        state["after"] = git.run("rev-parse", "--verify", "HEAD^{commit}")
        if state["after"] != state["target"]:
            raise GitError("HEAD differs from the fetched commit after fast-forward; inspect checkout")
        return {**state, "status": "updated"}
    except (RepositoryConfigurationError, GitError, OSError, ValueError) as exc:
        return {**state, "status": "error", "detail": str(exc)}


def run_fleet(settings, keys, *, apply=False, locks=None, timeout=60) -> list[dict]:
    results = []
    for key in keys:
        result = {"key": key, "status": "error", "detail": "", "path": None,
                  "commits": [], "prs": []}
        try:
            if key in getattr(settings, "unconfigured", ()):
                result.update(status="not_configured", detail="repository root is not configured")
                results.append(result)
                continue
            root = settings.get_target(key).path
            result["path"] = str(root)
            if apply:
                manager = locks if locks is not None else LockManager()
                entered = False
                try:
                    with manager.lock(key, "fleet-pull", timeout=timeout + 30):
                        entered = True
                        result.update(update_one(settings, key, root, timeout=timeout))
                except RuntimeError:
                    if entered:
                        raise
                    result.update(status="skipped_locked", detail="repository lock unavailable")
            else:
                git = Git(root, timeout)
                state = inspect(git)
                result.update(state)
                if state["status"] == "eligible":
                    result.update(compare(git, state))
        except (RepositoryConfigurationError, GitError, OSError, ValueError) as exc:
            result.update(status="error", detail=str(exc))
        results.append(result)
    return results


def _timeout(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 300:
        raise argparse.ArgumentTypeError("timeout must be 1–300 seconds")
    return parsed


def selected_keys(requested: list[str] | None, manifest) -> list[str]:
    keys = list(dict.fromkeys(requested or [CONTROL_PLANE_KEY, *manifest.mechs]))
    known = {CONTROL_PLANE_KEY, *manifest.mechs}
    unknown = set(keys) - known
    if unknown:
        names = ", ".join(sorted(unknown))
        raise argparse.ArgumentTypeError(f"unknown repository key(s): {names}")
    return keys


def _format_commits(row: dict) -> str:
    commits = row.get("commits")
    if commits:
        return str(len(commits))
    behind = row.get("behind")
    if isinstance(behind, int) and behind > 0:
        return str(behind)
    return "—"


def _format_prs(prs: list) -> str:
    if not prs:
        return "—"
    return ", ".join(str(pr).strip() for pr in prs if str(pr).strip()) or "—"


def render_table(results: list[dict]) -> str:
    """Show updates first, followed by every repository that was not updated."""
    lines = ["| Repository | Branch | Result | Merged Commits | Merged PRs | Details |",
             "|---|---|---|---|---|---|"]
    for row in sorted(results, key=lambda item: item["status"] != "updated"):
        detail = row.get("detail", "")
        if row["status"] == "updated":
            detail = f"{row['before'][:12]} → {row['after'][:12]}"
            if row.get("behind") is not None:
                detail += f" ({row['behind']} commits)"
        elif row["status"] == "up_to_date":
            detail = "Already up to date with the compared upstream"
        elif row["status"] == "ahead":
            detail = f"Local branch is {row['ahead']} commits ahead"
        elif row["status"] == "would_update":
            detail = f"Preview: cached upstream is {row['behind']} commits ahead"
        show_changes = row["status"] in {"updated", "would_update"}
        commits_cell = _format_commits(row) if show_changes else "—"
        prs_cell = _format_prs(row.get("prs") or []) if show_changes else "—"
        cells = (
            row["key"],
            row.get("branch") or "—",
            row["status"],
            commits_cell,
            prs_cell,
            detail,
        )
        lines.append("| " + " | ".join(
            " ".join(str(cell).split()).replace("|", "\\|") for cell in cells
        ) + " |")
    updated = sum(row["status"] == "updated" for row in results)
    lines.append(f"\nUpdated: {updated}. Not updated: {len(results) - updated}.")
    return "\n".join(lines)


class _PureLinkMLYamlLoader(UniqueKeySafeLoader):
    """Pure-Python YAML loader isolating LinkML from C-loader import-order state."""

    yaml_path_resolvers: dict[Any, Any] = {}


@contextmanager
def _pure_linkml_loader():
    linkml_yaml_loader = importlib.import_module("linkml_runtime.loaders.yaml_loader")
    lock = vars(linkml_yaml_loader).setdefault(
        "_claw_linkml_loader_lock", threading.RLock()
    )
    with lock:
        original = linkml_yaml_loader.DupCheckYamlLoader
        linkml_yaml_loader.DupCheckYamlLoader = _PureLinkMLYamlLoader
        try:
            yield
        finally:
            linkml_yaml_loader.DupCheckYamlLoader = original


@lru_cache(maxsize=4)
def _report_validator(schema_path: Path):
    from linkml.validator import Validator
    from linkml.validator.plugins import JsonschemaValidationPlugin

    schema_doc = yaml.load(
        schema_path.read_text(encoding="utf-8"), Loader=UniqueKeySafeLoader
    )
    if not isinstance(schema_doc, dict):
        raise ValueError("fleet_pull schema must be a YAML mapping")
    with _pure_linkml_loader():
        return Validator(
            schema_doc,
            validation_plugins=[JsonschemaValidationPlugin(closed=True)],
            strict=True,
        )


def validate_report(
    report: Mapping[str, Any], schema_path: Path | None = None
) -> None:
    """Validate a fleet-pull JSON report dict against the LinkML schema."""
    resolved_schema = schema_path or default_fleet_pull_schema_path()
    validation = _report_validator(resolved_schema).validate(
        dict(report), target_class="FleetPullReport"
    )
    if validation.results:
        messages = "; ".join(result.message for result in validation.results)
        raise ValueError(f"Invalid FleetPullReport payload: {messages}")


def build_report(
    keys: Sequence[str],
    results: Sequence[Mapping[str, Any]],
    *,
    apply: bool,
    incomplete: bool,
    snapshot_utc: str | None = None,
) -> dict[str, Any]:
    """Build the top-level FleetPullReport JSON dictionary."""
    return {
        "snapshot_utc": snapshot_utc or dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry_run",
        "comparison": "fetch_eligible_only" if apply else "cached_refs",
        "selected": list(keys),
        "complete": not incomplete,
        "results": [dict(row) for row in results],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="fetch and fast-forward eligible checkouts")
    mode.add_argument("--dry-run", action="store_true", help="offline preview (the default)")
    parser.add_argument(
        "--mech",
        action="append",
        help="select a repository key, including claw; repeat to select several",
    )
    parser.add_argument("--dotenv", type=Path, help="repository configuration (default: CLAW .env if present)")
    parser.add_argument("--timeout", type=_timeout, default=60, help="seconds per repository (default: 60)")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)
    try:
        manifest = load_fleet_manifest()
        try:
            keys = selected_keys(args.mech, manifest)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        dotenv = args.dotenv
        if dotenv is None and (CLAW_ROOT / ".env").exists():
            dotenv = CLAW_ROOT / ".env"
        settings = FleetPullSettings(
            RepositorySettings.from_environment(
                manifest=manifest, environ=merged_repository_environment(dotenv),
            )
        )
        results = run_fleet(settings, keys, apply=args.apply, timeout=args.timeout)
    except (FleetManifestError, RepositoryConfigurationError, OSError, ValueError) as exc:
        print(f"fleet-pull: {exc}", file=sys.stderr)
        return 2
    incomplete = any(row["status"] not in SUCCESS for row in results)
    if args.json:
        report = build_report(
            keys, results, apply=args.apply, incomplete=incomplete
        )
        print(json.dumps(report, indent=2))
    else:
        print("Fleet pull: " + ("apply" if args.apply else "offline preview; upstream refs may be stale"))
        print("\n" + render_table(results))
        print(f"Coverage: {len(results)}/{len(keys)} selected repositories reported; "
              + ("some skipped or failed" if incomplete else "complete"))
    return 1 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
