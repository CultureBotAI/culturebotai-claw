"""Concurrency and ownership tests for the file-based lock manager."""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
import yaml

import plugins.lock_manager as lock_manager_module
from plugins.lock_manager import LockManager, StatusManager, resolve_workspace_root
from scripts.check_lock import check_lock


class _SlowCreateLockManager(LockManager):
    """Widen an unguarded check/create race without changing production code."""

    def _create_lock_atomic(self, lock_file: Path, lock_data: dict[str, Any]) -> None:
        time.sleep(0.1)
        super()._create_lock_atomic(lock_file, lock_data)


def _contend_for_lock(
    locks_dir: str,
    contender: int,
    start_event,
    release_event,
    ready_queue,
    result_queue,
) -> None:
    """Process target that holds a successful acquisition until parent release."""
    manager = LockManager(
        {
            "locks_dir": locks_dir,
            "my_id": f"contender-{contender}",
            "poll_interval": 0.01,
        }
    )
    ready_queue.put(contender)
    if not start_event.wait(10):
        result_queue.put((contender, False, "start timeout"))
        return

    acquired = manager.acquire_lock("shared-resource", "contention test", timeout=30)
    lock_data = manager.check_lock("shared-resource") if acquired else None
    result_queue.put(
        (
            contender,
            acquired,
            lock_data.get("lease_token") if lock_data else None,
        )
    )
    if acquired:
        if not release_event.wait(10):
            result_queue.put((contender, False, "release timeout"))
            return
        result_queue.put((contender, manager.release_lock("shared-resource"), "released"))


def _run_contenders(locks_dir: Path, count: int = 8):
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    release_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_contend_for_lock,
            args=(
                str(locks_dir),
                contender,
                start_event,
                release_event,
                ready_queue,
                result_queue,
            ),
        )
        for contender in range(count)
    ]

    try:
        for process in processes:
            process.start()
        ready = {ready_queue.get(timeout=15) for _ in processes}
        assert ready == set(range(count))

        start_event.set()
        results = [result_queue.get(timeout=15) for _ in processes]
        winners = [result for result in results if result[1]]
        assert len(winners) == 1
        assert winners[0][2]

        release_event.set()
        released = result_queue.get(timeout=15)
        assert released[0] == winners[0][0]
        assert released[1:] == (True, "released")
    finally:
        start_event.set()
        release_event.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert all(process.exitcode == 0 for process in processes)


def _contend_for_hierarchy_lock(
    locks_dir: str,
    resource: str,
    start_barrier,
    release_event,
    result_queue,
) -> None:
    """Race a global lease against a repo lease in a spawned process."""
    manager = _SlowCreateLockManager(
        {
            "locks_dir": locks_dir,
            "my_id": f"hierarchy-{resource}",
            "poll_interval": 0.01,
        }
    )
    start_barrier.wait(timeout=10)
    acquired = manager.acquire_lock(resource, "hierarchy contention", timeout=30)
    result_queue.put((resource, acquired))
    if acquired:
        if not release_event.wait(10):
            result_queue.put((resource, False, "release timeout"))
            return
        result_queue.put((resource, manager.release_lock(resource), "released"))


def _acquire_hierarchy_test_lock(
    manager: LockManager,
    resource: str,
    *,
    wait: bool = False,
    max_wait: int = 300,
) -> bool:
    """Acquire either side through its public API for hierarchy tests."""
    if resource == "global":
        return manager.acquire_global_lock(
            "hierarchy test",
            wait=wait,
            max_wait=max_wait,
        )
    return manager.acquire_lock(
        resource,
        "hierarchy test",
        wait=wait,
        max_wait=max_wait,
    )


def _release_hierarchy_test_lock(manager: LockManager, resource: str) -> bool:
    """Release either side through its public API for hierarchy tests."""
    if resource == "global":
        return manager.release_global_lock()
    return manager.release_lock(resource)


def test_only_one_process_acquires_a_free_lock(tmp_path: Path) -> None:
    _run_contenders(tmp_path / "locks")


def test_only_one_process_reclaims_an_expired_lock(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    (locks_dir / "shared-resource.lock").write_text(
        yaml.safe_dump(
            {
                "locked_by": "dead-process",
                "lease_token": "expired-lease",
                "locked_at": (expired - timedelta(minutes=1)).isoformat(),
                "expires_at": expired.isoformat(),
                "operation": "abandoned work",
                "pid": 999999,
            }
        ),
        encoding="utf-8",
    )

    _run_contenders(locks_dir)


def test_global_and_repo_locks_conflict_in_both_acquisition_orders(
    tmp_path: Path,
) -> None:
    locks_dir = tmp_path / "locks"
    global_owner = LockManager({"locks_dir": locks_dir, "my_id": "global-owner"})
    repo_owner = LockManager({"locks_dir": locks_dir, "my_id": "repo-owner"})

    assert global_owner.acquire_global_lock("global first")
    assert not repo_owner.acquire_lock("culturemech", "blocked by global")
    assert global_owner.release_global_lock()

    assert repo_owner.acquire_lock("culturemech", "repo first")
    # Direct callers of acquire_lock("global") must get the same hierarchy
    # semantics as callers using acquire_global_lock().
    assert not global_owner.acquire_lock("global", "blocked by repo")
    assert repo_owner.release_lock("culturemech")


@pytest.mark.parametrize(
    ("held_resource", "requested_resource"),
    [("global", "culturemech"), ("culturemech", "global")],
)
def test_hierarchy_wait_retries_after_conflicting_lease_is_released(
    tmp_path: Path,
    held_resource: str,
    requested_resource: str,
) -> None:
    locks_dir = tmp_path / "locks"
    owner = LockManager({"locks_dir": locks_dir, "my_id": "owner"})
    waiter = LockManager(
        {
            "locks_dir": locks_dir,
            "my_id": "waiter",
            "poll_interval": 0.005,
        }
    )
    assert _acquire_hierarchy_test_lock(owner, held_resource)
    # Exercise max_wait on both APIs before checking a successful retry.
    assert not _acquire_hierarchy_test_lock(
        waiter,
        requested_resource,
        wait=True,
        max_wait=0,
    )

    release_results: list[bool] = []

    def release_owner() -> None:
        time.sleep(0.05)
        release_results.append(_release_hierarchy_test_lock(owner, held_resource))

    release_thread = Thread(target=release_owner)
    release_thread.start()
    assert _acquire_hierarchy_test_lock(
        waiter,
        requested_resource,
        wait=True,
        max_wait=2,
    )
    release_thread.join(timeout=2)

    assert not release_thread.is_alive()
    assert release_results == [True]
    assert _release_hierarchy_test_lock(waiter, requested_resource)


@pytest.mark.parametrize(
    ("expired_resource", "requested_resource"),
    [("global", "culturemech"), ("culturemech", "global")],
)
def test_hierarchy_acquisition_reclaims_expired_conflicts(
    tmp_path: Path,
    expired_resource: str,
    requested_resource: str,
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    expired_file = locks_dir / f"{expired_resource}.lock"
    expired_file.write_text(
        yaml.safe_dump(
            {
                "locked_by": "expired-owner",
                "lease_token": "expired-lease",
                "expires_at": expired.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    manager = LockManager({"locks_dir": locks_dir})

    assert _acquire_hierarchy_test_lock(manager, requested_resource)
    assert not expired_file.exists()
    assert _release_hierarchy_test_lock(manager, requested_resource)


@pytest.mark.parametrize(
    ("blocking_resource", "requested_resource"),
    [("global", "culturemech"), ("culturemech", "global")],
)
@pytest.mark.parametrize("unsafe_kind", ["malformed", "broken_symlink"])
def test_hierarchy_conflicts_fail_closed_on_unreadable_lock_entries(
    tmp_path: Path,
    blocking_resource: str,
    requested_resource: str,
    unsafe_kind: str,
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    blocking_file = locks_dir / f"{blocking_resource}.lock"
    if unsafe_kind == "malformed":
        blocking_file.write_text("not: [valid", encoding="utf-8")
    else:
        blocking_file.symlink_to(tmp_path / "missing-lock")
    manager = LockManager({"locks_dir": locks_dir})

    assert not _acquire_hierarchy_test_lock(manager, requested_resource)
    assert blocking_file.lstat()


def test_invalid_lock_shaped_entry_blocks_global_acquisition(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    invalid_lock = locks_dir / "not a resource.lock"
    invalid_lock.write_text("untrusted\n", encoding="utf-8")
    manager = LockManager({"locks_dir": locks_dir})

    assert not manager.acquire_global_lock("must fail closed")
    assert invalid_lock.exists()


@pytest.mark.parametrize("guard_kind", ["symlink", "fifo"])
def test_unsafe_hierarchy_guard_fails_closed_without_hanging(
    tmp_path: Path,
    guard_kind: str,
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    hierarchy_guard = locks_dir / ".lock-hierarchy.guard"
    if guard_kind == "symlink":
        outside = tmp_path / "outside-hierarchy-guard"
        outside.write_text("must remain unchanged\n", encoding="utf-8")
        hierarchy_guard.symlink_to(outside)
    else:
        os.mkfifo(hierarchy_guard)
    manager = LockManager({"locks_dir": locks_dir})

    started = time.monotonic()
    assert not manager.acquire_lock("culturemech", "must fail closed")
    assert time.monotonic() - started < 2
    assert not (locks_dir / "culturemech.lock").exists()


def test_global_and_repo_acquisition_are_atomic_across_processes(
    tmp_path: Path,
) -> None:
    locks_dir = tmp_path / "locks"
    context = multiprocessing.get_context("spawn")
    start_barrier = context.Barrier(2)
    release_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_contend_for_hierarchy_lock,
            args=(
                str(locks_dir),
                resource,
                start_barrier,
                release_event,
                result_queue,
            ),
        )
        for resource in ("global", "culturemech")
    ]

    try:
        for process in processes:
            process.start()
        results = [result_queue.get(timeout=15) for _ in processes]
        winners = [resource for resource, acquired in results if acquired]

        assert len(winners) == 1
        assert winners[0] in {"global", "culturemech"}

        release_event.set()
        released = result_queue.get(timeout=15)
        assert released == (winners[0], True, "released")
    finally:
        release_event.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert all(process.exitcode == 0 for process in processes)


@pytest.mark.parametrize(
    ("wait", "max_wait"),
    [(False, 300), (True, 0)],
)
def test_failed_expired_lock_reclaim_respects_wait_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wait: bool,
    max_wait: int,
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    (locks_dir / "culturemech.lock").write_text(
        yaml.safe_dump(
            {
                "locked_by": "dead-process",
                "lease_token": "expired-lease",
                "locked_at": (expired - timedelta(minutes=1)).isoformat(),
                "expires_at": expired.isoformat(),
                "operation": "abandoned work",
                "pid": 999999,
            }
        ),
        encoding="utf-8",
    )
    manager = LockManager({"locks_dir": locks_dir})
    reclaim_attempts = 0

    def fail_reclaim(resource: str) -> bool:
        nonlocal reclaim_attempts
        reclaim_attempts += 1
        return False

    monkeypatch.setattr(manager, "_reclaim_expired_lock", fail_reclaim)

    assert not manager.acquire_lock(
        "culturemech",
        "bounded reclaim",
        wait=wait,
        max_wait=max_wait,
    )
    assert reclaim_attempts == 1


def test_release_requires_the_exact_local_lease(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    owner = LockManager({"locks_dir": locks_dir, "my_id": "same-identity"})
    impostor = LockManager({"locks_dir": locks_dir, "my_id": "same-identity"})

    assert owner.acquire_lock("culturemech", "owner operation")
    original = owner.check_lock("culturemech")
    assert original is not None

    assert not impostor.release_lock("culturemech")
    assert owner.check_lock("culturemech") == original
    assert owner.release_lock("culturemech")


def test_expired_context_cannot_release_its_successor(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    first = LockManager({"locks_dir": locks_dir, "my_id": "first"})
    successor = LockManager({"locks_dir": locks_dir, "my_id": "successor"})

    with first.lock("culturemech", "short operation", timeout=0.02):
        time.sleep(0.05)
        assert successor.acquire_lock("culturemech", "successor operation", timeout=30)
        successor_lock = successor.check_lock("culturemech")
        assert successor_lock is not None
        successor_token = successor_lock["lease_token"]

    current = successor.check_lock("culturemech")
    assert current is not None
    assert current["lease_token"] == successor_token
    assert successor.release_lock("culturemech")


@pytest.mark.parametrize(
    "resource",
    ["", ".", "..", "../outside", "nested/resource", "back\\slash", "white space"],
)
def test_resource_names_cannot_escape_the_lock_directory(
    tmp_path: Path, resource: str
) -> None:
    manager = LockManager({"locks_dir": tmp_path / "locks"})

    with pytest.raises(ValueError, match="resource"):
        manager.acquire_lock(resource, "invalid")


def test_lock_metadata_uses_unique_lease_and_aware_utc_timestamps(tmp_path: Path) -> None:
    manager = LockManager({"locks_dir": tmp_path / "locks"})

    assert manager.acquire_lock("culturemech", "metadata")
    lock_data = manager.check_lock("culturemech")
    assert lock_data is not None
    assert len(lock_data["lease_token"]) == 32
    assert lock_data["lease_token"] != manager.my_id
    for field in ("locked_at", "expires_at"):
        timestamp = datetime.fromisoformat(lock_data[field])
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() == timedelta(0)
    assert manager.release_lock("culturemech")


def test_corrupt_lock_fails_closed(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    lock_file = locks_dir / "culturemech.lock"
    lock_file.write_text("not: [valid", encoding="utf-8")
    manager = LockManager({"locks_dir": locks_dir})

    assert not manager.acquire_lock("culturemech", "must not overwrite")
    lock_status = manager.check_lock("culturemech")
    assert lock_status is not None
    assert lock_status["invalid"] is True
    assert lock_file.read_text(encoding="utf-8") == "not: [valid"


def test_duplicate_lock_keys_fail_closed_without_reclamation(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    lock_file = locks_dir / "culturemech.lock"
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    serialized = (
        "locked_by: existing-owner\n"
        f"expires_at: {future.isoformat()}\n"
        f"expires_at: {past.isoformat()}\n"
    )
    lock_file.write_text(serialized, encoding="utf-8")
    manager = LockManager({"locks_dir": locks_dir})

    lock_status = manager.check_lock("culturemech")

    assert lock_status is not None
    assert lock_status["invalid"] is True
    assert lock_file.read_text(encoding="utf-8") == serialized
    assert not manager.acquire_lock("culturemech", "must not overwrite")
    assert lock_file.read_text(encoding="utf-8") == serialized


@pytest.mark.parametrize("unsafe_kind", ["broken_symlink", "symlink", "directory", "fifo"])
def test_nonregular_lock_entries_fail_closed_without_hanging(
    tmp_path: Path, unsafe_kind: str
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    lock_file = locks_dir / "culturemech.lock"
    if unsafe_kind == "broken_symlink":
        lock_file.symlink_to(tmp_path / "missing-lock.yaml")
    elif unsafe_kind == "symlink":
        outside = tmp_path / "outside-lock.yaml"
        outside.write_text(
            yaml.safe_dump(
                {
                    "locked_by": "untrusted-target",
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(hours=1)
                    ).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        lock_file.symlink_to(outside)
    elif unsafe_kind == "directory":
        lock_file.mkdir()
    else:
        os.mkfifo(lock_file)

    manager = LockManager({"locks_dir": locks_dir})
    status = manager.check_lock("culturemech")

    assert status is not None
    assert status["invalid"] is True
    assert not manager.acquire_lock("culturemech", "must not overwrite")


def test_hook_checker_never_unlocks_a_broken_symlink_lock(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    locks_dir = workspace / "locks"
    locks_dir.mkdir(parents=True)
    (locks_dir / "culturemech.lock").symlink_to(tmp_path / "missing.yaml")
    environment = os.environ.copy()
    environment["OPENCLAW_WORKSPACE"] = str(workspace)
    checker = Path(__file__).parents[1] / "scripts" / "check_lock.py"

    result = subprocess.run(
        [sys.executable, str(checker), "culturemech", "edit files"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=5,
    )

    assert result.returncode == 1
    assert "active or unreadable" in result.stdout


def test_lock_manager_rejects_a_direct_symlinked_locks_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-locks"
    outside.mkdir()
    linked = tmp_path / "linked-locks"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="locks_dir must not be a symlink"):
        LockManager({"locks_dir": linked})


@pytest.mark.parametrize("guard_kind", ["symlink", "fifo"])
def test_unsafe_guard_cannot_hang_or_reclaim_an_expired_lock(
    tmp_path: Path, guard_kind: str
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    lock_file = locks_dir / "culturemech.lock"
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    lock_file.write_text(
        yaml.safe_dump(
            {
                "locked_by": "expired-owner",
                "lease_token": "expired-lease",
                "expires_at": expired.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    guard = locks_dir / ".culturemech.lock.guard"
    if guard_kind == "symlink":
        outside = tmp_path / "outside-guard"
        outside.write_text("must remain unchanged\n", encoding="utf-8")
        guard.symlink_to(outside)
    else:
        os.mkfifo(guard)

    manager = LockManager({"locks_dir": locks_dir})
    status = manager.check_lock("culturemech")

    assert status is not None
    assert status["locked_by"] == "expired-owner"
    assert lock_file.exists()


def test_relative_workspace_cannot_escape_trusted_orchestration_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "orchestration"
    root.mkdir()
    monkeypatch.setenv("OPENCLAW_ORCHESTRATION_ROOT", str(root))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", "../outside")

    with pytest.raises(ValueError, match="must stay within"):
        resolve_workspace_root()


def test_direct_symlinked_workspace_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace-link"
    workspace.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(workspace))

    with pytest.raises(ValueError, match="must not be a symlink"):
        resolve_workspace_root()


def test_post_reclamation_partial_successor_lock_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    lock_file = locks_dir / "culturemech.lock"
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    lock_file.write_text(
        yaml.safe_dump(
            {
                "locked_by": "expired-owner",
                "expires_at": expired.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    manager = LockManager({"locks_dir": locks_dir})

    def expose_partial_successor(resource: str) -> bool:
        assert resource == "culturemech"
        lock_file.write_text("", encoding="utf-8")
        return True

    monkeypatch.setattr(manager, "_reclaim_expired_lock", expose_partial_successor)

    status = manager.check_lock("culturemech")

    assert status is not None
    assert status["invalid"] is True
    assert "after reclamation" in status["reason"]


def test_atomic_lock_file_is_private_to_the_owner(tmp_path: Path) -> None:
    manager = LockManager({"locks_dir": tmp_path / "locks"})
    assert manager.acquire_lock("culturemech", "permissions")

    mode = os.stat(tmp_path / "locks" / "culturemech.lock").st_mode & 0o777
    assert mode == 0o600
    assert manager.release_lock("culturemech")


def test_hook_checker_blocks_on_corrupt_lock(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    locks_dir = workspace / "locks"
    locks_dir.mkdir(parents=True)
    (locks_dir / "culturemech.lock").write_text("not: [valid", encoding="utf-8")
    environment = os.environ.copy()
    environment["OPENCLAW_WORKSPACE"] = str(workspace)
    checker = Path(__file__).parents[1] / "scripts" / "check_lock.py"

    result = subprocess.run(
        [sys.executable, str(checker), "culturemech", "edit files"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 1
    assert "active or unreadable" in result.stdout


def test_relative_workspace_uses_configured_orchestration_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENCLAW_ORCHESTRATION_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", "runtime")

    lock_manager = LockManager()
    status_manager = StatusManager()

    assert lock_manager.locks_dir == tmp_path / "runtime" / "locks"
    assert status_manager.status_dir == tmp_path / "runtime" / "status"


def test_default_workspace_is_independent_of_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENCLAW_ORCHESTRATION_ROOT", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)

    assert resolve_workspace_root() == Path(__file__).parents[1] / "workspace"


def test_manager_and_hook_checker_share_workspace_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestration_root = tmp_path / "orchestration"
    orchestration_root.mkdir()
    (orchestration_root / "pyproject.toml").touch()
    monkeypatch.setattr(lock_manager_module, "PROJECT_ROOT", orchestration_root)
    monkeypatch.delenv("OPENCLAW_ORCHESTRATION_ROOT", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    manager = LockManager()
    assert manager.acquire_lock("culturemech", "shared resolution")
    assert check_lock("culturemech", "test shared resolution") == 1
    assert manager.release_lock("culturemech")


def test_relative_workspace_fails_closed_outside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed_root = tmp_path / "site-packages"
    installed_root.mkdir()
    monkeypatch.setattr(lock_manager_module, "PROJECT_ROOT", installed_root)
    monkeypatch.delenv("OPENCLAW_ORCHESTRATION_ROOT", raising=False)
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)

    with pytest.raises(ValueError, match="OPENCLAW_ORCHESTRATION_ROOT"):
        resolve_workspace_root()

    assert not (installed_root / "workspace").exists()

    explicit_locks = tmp_path / "explicit-locks"
    explicit_status = tmp_path / "explicit-status"
    assert LockManager({"locks_dir": explicit_locks}).locks_dir == explicit_locks
    assert StatusManager({"status_dir": explicit_status}).status_dir == explicit_status
