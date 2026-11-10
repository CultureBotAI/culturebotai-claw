"""Observed-revision goal boundaries, separate from immutable workflow evidence.

This is the narrow counterpart of fleet_pull: only a verified default checkout
may fast-forward, and an ahead checkout is a hold. It shares RepositoryTarget
identity validation and LockManager leases with the fleet updater. Receipts are
observations, never perpetual claims that HEAD is the latest remote revision.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget, _repository_identity

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
OPERATIONS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge",
              "rebase-apply", "sequencer", "BISECT_START", "index.lock")
OwnerCheck = Callable[[], Mapping[int, str]]


class FreshnessError(ValueError):
    """A fail-closed, credential-free diagnostic."""


def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


class Git:
    """Bounded Git with hooks, ambient redirection and ancestry replacement off."""

    def __init__(self, root: Path, timeout: float = 90):
        self.root = root
        self.deadline = time.monotonic() + timeout

    def run(self, *args: str, allowed: Sequence[int] = (0,)) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise FreshnessError("git_timeout")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
                   GIT_NO_REPLACE_OBJECTS="1", GIT_GRAFT_FILE=os.devnull,
                   GIT_NO_LAZY_FETCH="1")
        try:
            result = subprocess.run(
                ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                 "-c", "submodule.recurse=false", "-c", "gc.auto=0",
                 "-c", "maintenance.auto=false", "-C", str(self.root), *args],
                env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=remaining, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FreshnessError(f"git_{args[0]}_unavailable") from exc
        if result.returncode not in allowed:
            # URLs and Git stderr can contain credentials. Neither belongs in evidence.
            raise FreshnessError(f"git_{args[0]}_failed")
        if len(result.stdout) > 4_000_000:
            raise FreshnessError("git_output_bound")
        return result.stdout.rstrip("\n")


def identity(git: Git, target: RepositoryTarget) -> None:
    """Revalidate exact root and every effective fetch/push URL under safe env."""
    if target.path.is_symlink() or target.path.resolve() != target.path:
        raise FreshnessError("checkout_path_not_canonical")
    root = git.run("rev-parse", "--show-toplevel")
    if Path(root).resolve() != target.path:
        raise FreshnessError("checkout_root_mismatch")
    for prefix in (("remote", "get-url", "--all", "origin"),
                   ("remote", "get-url", "--push", "--all", "origin")):
        urls = git.run(*prefix).splitlines()
        if not urls or any((_repository_identity(url) or "").casefold()
                           != target.expected_repository.casefold() for url in urls):
            raise FreshnessError("wrong_canonical_remote")
    if git.run("rev-parse", "--is-shallow-repository") != "false":
        raise FreshnessError("shallow_history_requires_owned_full_base")
    if git.run("config", "--get", "extensions.partialClone", allowed=(0, 1)):
        raise FreshnessError("partial_clone_requires_owned_full_base")


def state(git: Git) -> dict[str, str]:
    branch = git.run("symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1))
    head = git.run("rev-parse", "--verify", "HEAD^{commit}")
    if not SHA.fullmatch(head):
        raise FreshnessError("invalid_head")
    for marker in OPERATIONS:
        path = Path(git.run("rev-parse", "--path-format=absolute", "--git-path", marker))
        if os.path.lexists(path):
            raise FreshnessError("active_git_operation:" + marker)
    for flag in ("-v", "-f"):
        entries = git.run("ls-files", flag, "-z").split("\0")
        if any(entry and (entry[0].islower() or entry[0] == "S") for entry in entries):
            raise FreshnessError("hidden_index_flags:preserve_owner_flags_and_use_owned_base")
    for option in ("core.sparseCheckout", "index.sparse"):
        if git.run("config", "--bool", "--get", option, allowed=(0, 1)) == "true":
            raise FreshnessError("sparse_checkout_requires_owned_full_base")
    tracked = git.run("status", "--porcelain=v1", "-z", "--untracked-files=all",
                      "--ignore-submodules=none")
    return {"branch": branch, "head": head, "tracked_status": tracked}


def advertised(git: Git) -> tuple[str, str]:
    lines = git.run("ls-remote", "--symref", "origin", "HEAD").splitlines()
    refs, heads = [], []
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 2 or fields[1] != "HEAD":
            raise FreshnessError("malformed_default_branch_observation")
        if fields[0].startswith("ref: refs/heads/"):
            refs.append(fields[0].removeprefix("ref: refs/heads/"))
        elif SHA.fullmatch(fields[0]):
            heads.append(fields[0])
        else:
            raise FreshnessError("malformed_default_branch_observation")
    if len(refs) != 1 or len(heads) != 1:
        raise FreshnessError("missing_or_ambiguous_remote_default")
    git.run("check-ref-format", "refs/heads/" + refs[0])
    return refs[0], heads[0]


def _processes() -> dict[int, dict[str, Any]]:
    try:
        value = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,tty=,lstart=,comm="],
                               capture_output=True, text=True, check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise FreshnessError("owner_process_inventory_unavailable") from exc
    result = {}
    for line in value.splitlines():
        parts = line.split(None, 8)
        if len(parts) != 9 or not parts[0].isdigit() or not parts[1].isdigit():
            raise FreshnessError("owner_process_inventory_malformed")
        result[int(parts[0])] = {"ppid": int(parts[1]),
                                "identity": " ".join([parts[0], *parts[2:]])}
    return result


def owner_snapshot(roots: Sequence[Path], allowed: Mapping[int, str]) -> dict[str, Any]:
    """Reject unknown same-user cwd owners, including shared Git worktrees.

    Caller-supplied exceptions must come from a fresh native idle/binding proof;
    the standalone CLI supplies none. PID identity is rechecked independently.
    This is an explicit host observation, not ownership inferred from a name.
    """
    processes = _processes()
    own = set()
    pid = os.getpid()
    while pid in processes and pid > 1 and pid not in own:
        own.add(pid)
        pid = processes[pid]["ppid"]
    for pid, expected in allowed.items():
        if type(pid) is not int or not isinstance(expected, str):
            raise FreshnessError("invalid_allowed_owner")
        if pid not in processes or processes[pid]["identity"] != expected:
            raise FreshnessError("owner_identity_changed")
    cwds: dict[int, Path] = {}
    if sys.platform == "darwin":
        try:
            proc = subprocess.Popen(["lsof", "-nP", "-a", "-u", str(os.getuid()),
                                     "-d", "cwd", "-Fpn"], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            out, diagnostic = proc.communicate(timeout=15)
            own.add(proc.pid)
            if proc.returncode != 0 or diagnostic.strip() or len(out) > 4_000_000:
                raise FreshnessError("owner_cwd_inventory_unavailable")
        except (OSError, subprocess.SubprocessError) as exc:
            raise FreshnessError("owner_cwd_inventory_unavailable") from exc
        current = None
        for line in out.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                current = int(line[1:])
            elif line.startswith("n") and current is not None:
                cwds[current] = Path(line[1:]).resolve()
    elif sys.platform.startswith("linux"):
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid != os.getuid():
                    continue
                cwds[int(entry.name)] = (entry / "cwd").resolve(strict=True)
            except FileNotFoundError:
                continue  # A completed process no longer owns a checkout.
            except OSError as exc:
                raise FreshnessError("owner_cwd_inventory_unavailable") from exc
    else:
        raise FreshnessError("owner_inventory_unsupported_host")
    after = _processes()
    holders = {}
    for pid, expected in allowed.items():
        if after.get(pid, {}).get("identity") != expected:
            raise FreshnessError("owner_identity_changed_during_cwd_probe")
    for pid, cwd in cwds.items():
        if any(cwd == root or cwd.is_relative_to(root) for root in roots):
            if pid not in own and processes.get(pid) != after.get(pid):
                raise FreshnessError("owner_identity_changed_during_cwd_probe")
            if pid not in own and pid not in allowed:
                raise FreshnessError("other_live_owner:" + str(pid))
            holders[str(pid)] = processes.get(pid, {}).get("identity", "own_query")
    return {"checked_at": utc(), "allowed": {str(k): v for k, v in allowed.items()},
            "cwd_holders": holders}


def worktree_roots(git: Git) -> list[Path]:
    roots = []
    for line in git.run("worktree", "list", "--porcelain", "-z").split("\0"):
        if line.startswith("worktree "):
            root = Path(line.removeprefix("worktree "))
            if not root.is_absolute():
                raise FreshnessError("worktree_inventory_malformed")
            roots.append(root.resolve())
    if not roots or git.root not in roots:
        raise FreshnessError("worktree_inventory_incomplete")
    return roots


def collisions(git: Git, before: str, fetched: str) -> list[str]:
    """Test only incoming paths; noncolliding ignored evidence is not traversed."""
    incoming = git.run("diff", "--name-only", "-z", "--diff-filter=ACRT", before, fetched, "--")
    tracked = set(git.run("ls-files", "-z").split("\0"))
    found = []
    for name in filter(None, incoming.split("\0")):
        path = git.root / name
        if name not in tracked and os.path.lexists(path):
            found.append(name)
        for parent in path.parents:
            if parent == git.root:
                break
            relative = str(parent.relative_to(git.root))
            if os.path.lexists(parent) and (parent.is_symlink() or not parent.is_dir()):
                if relative not in tracked:
                    found.append(relative)
    return sorted(set(found))


def frozen_workflow_paths(git: Git, before: str, fetched: str,
                          frozen_paths: Mapping[str, str] | None = None) -> dict[str, str]:
    """Code freshness cannot perform an implicit workflow-profile adoption."""
    def tree(revision: str) -> dict[str, str]:
        result = {}
        for entry in filter(None, git.run("ls-tree", "-r", "-z", revision, "--", "workflow").split("\0")):
            metadata, path = entry.split("\t", 1)
            if path == "workflow/mech-workflow.yaml" or path.startswith("workflow/parent/"):
                result[path] = metadata
        return result
    old, new = tree(before), tree(fetched)
    if old != new:
        raise FreshnessError("workflow_pin_change_requires_adoption")
    for relative, expected in (frozen_paths or {}).items():
        path = Path(relative)
        if (path.is_absolute() or any(part in {"", ".", ".."} for part in relative.split("/"))
                or not DIGEST.fullmatch(expected)):
            raise FreshnessError("invalid_frozen_workflow_path")
        actual = git.root / path
        if actual.is_symlink() or hashlib.sha256(actual.read_bytes()).hexdigest() != expected:
            raise FreshnessError("frozen_workflow_bytes_changed")
        before_entry = git.run("ls-tree", before, "--", relative)
        after_entry = git.run("ls-tree", fetched, "--", relative)
        if not before_entry or before_entry != after_entry:
            raise FreshnessError("workflow_pin_change_requires_adoption")
    return old


def save_receipt(directory: Path, report: Mapping[str, Any]) -> dict[str, str]:
    """Publish complete immutable bytes; identical receipts are idempotent."""
    directory = directory.absolute()
    if directory.is_symlink() or directory.resolve() != directory:
        raise FreshnessError("receipt_directory_not_canonical")
    directory.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    sha = hashlib.sha256(raw).hexdigest()
    destination = directory / (sha + ".json")
    temporary = directory / (".new-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes() != raw:
                raise FreshnessError("receipt_collision") from None
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(destination), "sha256": sha}


def ensure_freshness(
    target: RepositoryTarget, *, phase: str, boundary_id: str, policy_sha256: str,
    locks: LockManager, receipt_dir: Path, protected_roots: Sequence[Path],
    owner_check: OwnerCheck | None = None, merge_commits: Sequence[str] = (),
    frozen_paths: Mapping[str, str] | None = None,
    apply: bool = False, attempts: int = 2, timeout: float = 90,
) -> dict[str, Any]:
    """Measure/fetch/inspect/FF/re-observe under the fleet repository lease.

    A preview never fetches or writes a receipt. A successful apply holds only
    for the observed boundary; consumers must verify persisted HEAD again before
    inventory/dispatch. An unsuccessful apply can have safely fast-forwarded;
    its receipt reports that fact and never authorizes inventory or closure.
    """
    if phase not in {"pre_goal", "post_merge"} or not boundary_id or len(boundary_id) > 256:
        raise FreshnessError("invalid_boundary")
    if not DIGEST.fullmatch(policy_sha256):
        raise FreshnessError("invalid_policy_digest")
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise FreshnessError("invalid_attempt_bound")
    if phase == "post_merge" and not merge_commits:
        raise FreshnessError("post_merge_requires_verified_merge_commits")
    if any(not isinstance(sha, str) or not SHA.fullmatch(sha) for sha in merge_commits):
        raise FreshnessError("invalid_merge_commit")
    if phase == "pre_goal" and merge_commits:
        raise FreshnessError("pre_goal_cannot_claim_merge")
    report: dict[str, Any] = {
        "schema_version": "1.0.0", "repository_key": target.name,
        "repository": target.expected_repository, "checkout": str(target.path),
        "remote": "origin", "phase": phase, "boundary_id": boundary_id,
        "policy_sha256": policy_sha256, "started_at": utc(), "status": "hold",
        "before": None, "fetched": None, "after": None, "default_branch": None,
        "merge_commits": list(merge_commits), "observations": [], "apply": apply,
    }
    git = Git(target.path, timeout)
    refs: list[tuple[str, str | None]] = []
    try:
        with locks.lock(target.name, "goal-freshness", timeout + 30):
            try:
                identity(git, target)
                roots = worktree_roots(git)
                protected = [p.resolve() for p in protected_roots]
                if any(root == protected_root for root in roots for protected_root in protected):
                    raise FreshnessError("deploy_required:live_control_checkout_or_shared_git")
                if target.name == "claw" and not protected:
                    raise FreshnessError("deploy_required:claw_protected_roots_unregistered")
                first = state(git)
                report.update(before=first["head"], after=first["head"])
                if not first["branch"]:
                    raise FreshnessError("detached_checkout:use_owned_default_base")
                if first["tracked_status"]:
                    raise FreshnessError("dirty_or_staged_checkout:preserve_owner_work")
                if not apply:
                    report.update(status="preview", reason="not_fetched:no_execution_authority")
                else:
                    for attempt in range(1, attempts + 1):
                        identity(git, target)
                        report["ownership"] = owner_snapshot(roots, (owner_check or dict)())
                        branch, remote_head = advertised(git)
                        report["default_branch"] = branch
                        if first["branch"] != branch:
                            raise FreshnessError("feature_checkout:use_owned_default_base")
                        ref = "refs/goal-freshness/" + uuid.uuid4().hex
                        refs.append((ref, None))
                        git.run("fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                                "--no-auto-maintenance", "--no-prune", "--refmap=", "origin",
                                "refs/heads/" + branch + ":" + ref)
                        fetched = git.run("rev-parse", "--verify", ref + "^{commit}")
                        refs[-1] = (ref, fetched)
                        report["fetched"] = fetched
                        observation = {"attempt": attempt, "at": utc(), "advertised": remote_head,
                                       "fetched": fetched, "branch": branch}
                        report["observations"].append(observation)
                        identity(git, target)
                        now = state(git)
                        if now != first:
                            raise FreshnessError("checkout_changed_during_fetch")
                        if advertised(git) != (branch, fetched) or remote_head != fetched:
                            observation["outcome"] = "remote_ref_race"
                            continue
                        counts = git.run("rev-list", "--left-right", "--count", first["head"] + "..." + fetched).split()
                        if len(counts) != 2:
                            raise FreshnessError("invalid_divergence_observation")
                        ahead, behind = map(int, counts)
                        report.update(ahead=ahead, behind=behind)
                        if ahead:
                            raise FreshnessError("diverged_checkout" if behind else "local_ahead_checkout")
                        report["workflow_files"] = frozen_workflow_paths(git, first["head"], fetched, frozen_paths)
                        unsafe = collisions(git, first["head"], fetched)
                        if unsafe:
                            report["overwrite_collisions"] = unsafe
                            raise FreshnessError("untracked_or_ignored_overwrite_collision")
                        for merge in merge_commits:
                            git.run("merge-base", "--is-ancestor", merge, fetched)
                        # A scan after fetch is not permission to mutate later: prove
                        # native ownership, identity, status and advertised ref again.
                        report["ownership"] = owner_snapshot(worktree_roots(git), (owner_check or dict)())
                        identity(git, target)
                        if state(git) != first:
                            raise FreshnessError("checkout_changed_before_fast_forward")
                        if advertised(git) != (branch, fetched):
                            observation["outcome"] = "remote_ref_race"
                            continue
                        if behind:
                            report["after"] = None  # Mutation outcome is unknown until read back.
                            git.run("merge", "--ff-only", "--no-squash", "--no-autostash",
                                    "--no-overwrite-ignore", "--no-edit", "--no-stat", fetched)
                        after = state(git)
                        report["after"] = after["head"]
                        if after["head"] != fetched or after["branch"] != branch or after["tracked_status"]:
                            raise FreshnessError("fast_forward_readback_failed")
                        identity(git, target)
                        if advertised(git) != (branch, fetched):
                            observation["outcome"] = "remote_ref_race_after_fast_forward"
                            first = after
                            continue
                        report.update(status="verified", reason="observed_revision_verified",
                                      verified_at=utc(), outcome="fast_forwarded" if report["before"] != after["head"] else "already_current")
                        observation["outcome"] = "verified"
                        break
                    else:
                        raise FreshnessError("remote_ref_race:retry_bound_exhausted")
            finally:
                for ref, sha in refs:
                    if sha is not None:
                        try:
                            git.run("update-ref", "-d", ref, sha)
                        except FreshnessError:
                            report.update(status="hold", reason="owned_fetch_ref_cleanup_failed")
                if apply and report["status"] != "verified":
                    report["after"] = None
                    try:
                        recovery = Git(target.path, 10)
                        identity(recovery, target)
                        actual = recovery.run("rev-parse", "--verify", "HEAD^{commit}")
                        if SHA.fullmatch(actual):
                            report["after"] = actual
                            report["after_observed_at"] = utc()
                    except FreshnessError:
                        report["after_readback"] = "unavailable:do_not_infer_unchanged"
    except (FreshnessError, RuntimeError, OSError, ValueError) as exc:
        report.update(status="hold", reason=str(exc) if isinstance(exc, FreshnessError)
                      else "repository_lease_or_observation_failed")
    finally:
        report["completed_at"] = utc()
    if apply:
        report["receipt"] = save_receipt(receipt_dir, report)
    return report


def verify_saved_receipt(receipt: Mapping[str, Any]) -> None:
    """Authenticate the immutable observation without changing active evidence."""
    reference = receipt.get("receipt")
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise FreshnessError("freshness_receipt_reference_missing")
    path = Path(reference["path"])
    if (not path.is_absolute() or path.resolve() != path or not path.is_file()
            or path.stat().st_size > 1_000_000):
        raise FreshnessError("freshness_receipt_reference_unsafe")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise FreshnessError("freshness_receipt_digest_changed")
    saved = json.loads(raw)
    expected = {key: value for key, value in receipt.items() if key != "receipt"}
    if saved != expected or saved.get("apply") is not True or not saved.get("verified_at"):
        raise FreshnessError("freshness_receipt_bytes_differ")


def verify_inventory_head(target: RepositoryTarget, receipt: Mapping[str, Any], *,
                          boundary_id: str, policy_sha256: str) -> str:
    """Re-observe the remote and persisted HEAD before the inventory handoff."""
    if (receipt.get("status") != "verified" or receipt.get("phase") != "pre_goal"
            or receipt.get("boundary_id") != boundary_id or receipt.get("policy_sha256") != policy_sha256
            or receipt.get("repository_key") != target.name
            or receipt.get("repository") != target.expected_repository
            or receipt.get("checkout") != str(target.path)):
        raise FreshnessError("freshness_receipt_context_mismatch")
    verify_saved_receipt(receipt)
    git = Git(target.path, 20)
    identity(git, target)
    current = state(git)
    if (current["head"] != receipt.get("fetched") or current["head"] != receipt.get("after")
            or current["branch"] != receipt.get("default_branch") or current["tracked_status"]):
        raise FreshnessError("inventory_head_changed_since_freshness")
    if advertised(git) != (current["branch"], current["head"]):
        raise FreshnessError("remote_moved_since_inventory_freshness")
    return current["head"]
