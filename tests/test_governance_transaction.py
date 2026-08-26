"""Exception-safety contracts for multi-file governance synchronization."""

from __future__ import annotations

import subprocess
from importlib.resources import files
from pathlib import Path

import pytest

import kg_microbe_governance as governance
from kg_microbe_governance import GovernanceError, SyncChange, sync_repository
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
)

REF = "a" * 40


def _asset_bytes(source: str) -> bytes:
    prefix = "src/kg_microbe_governance/"
    resource = files("kg_microbe_governance")
    for part in source.removeprefix(prefix).split("/"):
        resource = resource.joinpath(part)
    return resource.read_bytes()


def _fetch(url: str) -> bytes:
    marker = f"/{REF}/"
    assert marker in url
    source = url.split(marker, 1)[1]
    if source == CANONICAL_MANIFEST_PATH:
        return files("kg_microbe_governance").joinpath(
            "vendored_artifacts.json"
        ).read_bytes()
    return _asset_bytes(source)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(governance, "fetch_url", _fetch)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _repository(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(
        root,
        "remote",
        "add",
        "origin",
        "https://github.com/CultureBotAI/CultureMech.git",
    )
    return root


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.name=Transaction Test",
        "-c",
        "user.email=transaction@example.invalid",
        "commit",
        "-qm",
        message,
    )


def _assert_empty_and_clean(root: Path) -> None:
    assert sorted(path.name for path in root.iterdir()) == [".git"]
    assert _git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
    internal = list(root.rglob("*.kgmg.tmp")) + list(root.rglob("*.kgmg.bak"))
    assert internal == []


@pytest.mark.parametrize("failure_position", [1, 7, 15])
def test_promotion_failure_rolls_back_every_file_and_created_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_position: int,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    original = governance._promote_entry
    calls = 0

    def fail_after_promotion(entry) -> None:
        nonlocal calls
        calls += 1
        original(entry)
        if calls == failure_position:
            raise OSError("injected promotion failure")

    monkeypatch.setattr(governance, "_promote_entry", fail_after_promotion)
    with pytest.raises(GovernanceError, match="transaction failed"):
        sync_repository("culturemech", root, REF, apply=True)

    assert calls == failure_position
    _assert_empty_and_clean(root)


def test_staging_failure_rolls_back_prepared_files_and_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    original = governance._write_staged_file
    calls = 0

    def fail_during_staging(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls == 6:
            raise OSError("injected staging failure")
        original(*args, **kwargs)

    monkeypatch.setattr(governance, "_write_staged_file", fail_during_staging)
    with pytest.raises(GovernanceError, match="transaction failed"):
        sync_repository("culturemech", root, REF, apply=True)

    assert calls == 6
    _assert_empty_and_clean(root)


def test_token_generation_failure_closes_new_parent_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    original_open_parent = governance._open_parent
    prepared_fds: list[int] = []

    def recording_open_parent(*args, **kwargs):
        descriptor, filename = original_open_parent(*args, **kwargs)
        if kwargs.get("created_directories") is not None:
            prepared_fds.append(descriptor)
        return descriptor, filename

    def entropy_failure(_length: int) -> str:
        raise OSError("injected entropy failure")

    monkeypatch.setattr(governance, "_open_parent", recording_open_parent)
    monkeypatch.setattr(governance.secrets, "token_hex", entropy_failure)

    with pytest.raises(GovernanceError, match="transaction failed"):
        sync_repository("culturemech", root, REF, apply=True)

    assert prepared_fds
    for descriptor in prepared_fds:
        with pytest.raises(OSError):
            governance.os.fstat(descriptor)
    _assert_empty_and_clean(root)


def test_keyboard_interrupt_rolls_back_then_is_reraised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    original = governance._promote_entry
    calls = 0

    def interrupt_after_promotion(entry) -> None:
        nonlocal calls
        calls += 1
        original(entry)
        if calls == 4:
            raise KeyboardInterrupt

    monkeypatch.setattr(governance, "_promote_entry", interrupt_after_promotion)
    with pytest.raises(KeyboardInterrupt):
        sync_repository("culturemech", root, REF, apply=True)

    _assert_empty_and_clean(root)


def test_post_write_verification_failure_restores_tracked_and_absent_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    _commit(root, "install governed files")

    existing = root / "scripts/chem_formula.py"
    existing.write_text("committed drift\n")
    absent = root / "tests/test_provider_triage_contract.py"
    absent.unlink()
    _commit(root, "commit drift and deletion")
    before_inode = existing.stat().st_ino

    original_plan = governance._plan_sync
    calls = 0

    def fail_post_write(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original_plan(*args, **kwargs)
        if calls >= 1 and not result:
            return (SyncChange("injected", "scripts/chem_formula.py", "drift"),)
        return result

    monkeypatch.setattr(governance, "_plan_sync", fail_post_write)
    with pytest.raises(GovernanceError, match="verification failed"):
        sync_repository("culturemech", root, REF, apply=True)

    assert existing.read_text() == "committed drift\n"
    assert existing.stat().st_ino == before_inode
    assert not absent.exists()
    assert _git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert list(root.rglob("*.kgmg.tmp")) == []
    assert list(root.rglob("*.kgmg.bak")) == []


def test_observed_pre_promotion_edit_is_preserved_with_recovery_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    _commit(root, "install governed files")
    target = root / "scripts/chem_formula.py"
    target.write_text("committed drift\n")
    _commit(root, "commit deliberate drift")

    original_prepare = governance._prepare_transaction

    def race_after_staging(*args, **kwargs) -> None:
        original_prepare(*args, **kwargs)
        target.write_text("concurrent user bytes\n")

    monkeypatch.setattr(governance, "_prepare_transaction", race_after_staging)
    with pytest.raises(GovernanceError, match="recovery was incomplete"):
        sync_repository("culturemech", root, REF, apply=True)

    assert target.read_text() == "concurrent user bytes\n"
    assert list(target.parent.glob(".chem_formula.py.*.kgmg.bak"))


def test_target_created_after_locked_snapshot_is_never_adopted_or_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    target = root / "scripts/check_vendored_sync.py"
    original_prepare = governance._prepare_transaction

    def race_before_preparation(*args, **kwargs) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("concurrent user bytes\n")
        original_prepare(*args, **kwargs)

    monkeypatch.setattr(governance, "_prepare_transaction", race_before_preparation)

    with pytest.raises(GovernanceError, match="changed after locked snapshot"):
        sync_repository("culturemech", root, REF, apply=True)

    assert target.read_text() == "concurrent user bytes\n"
    assert list(target.parent.glob("*.kgmg.tmp")) == []
    assert list(target.parent.glob("*.kgmg.bak")) == []


@pytest.mark.parametrize("interrupt_timing", ["before", "after"])
def test_cleanup_interrupt_around_anchor_unlink_never_attempts_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_timing: str,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    _commit(root, "install governed files")
    target = root / "scripts/chem_formula.py"
    target.write_text("committed drift\n")
    _commit(root, "commit deliberate drift")
    canonical = _asset_bytes(
        "src/kg_microbe_governance/artifacts/scripts/chem_formula.py"
    )

    original_unlink = governance._unlink_if_present
    injected = False

    def interrupt_after_unlink(parent_fd: int, name: str | None) -> None:
        nonlocal injected
        if (
            not injected
            and str(name).endswith(".kgmg.bak")
            and interrupt_timing == "before"
        ):
            injected = True
            raise KeyboardInterrupt
        original_unlink(parent_fd, name)
        if (
            not injected
            and str(name).endswith(".kgmg.bak")
            and interrupt_timing == "after"
        ):
            injected = True
            raise KeyboardInterrupt

    monkeypatch.setattr(governance, "_unlink_if_present", interrupt_after_unlink)

    with pytest.raises(GovernanceError, match="committed, but cleanup was incomplete"):
        sync_repository("culturemech", root, REF, apply=True)

    assert injected
    assert target.read_bytes() == canonical
    assert governance.plan_sync("culturemech", root, REF) == ()
    assert list(root.rglob("*.kgmg.tmp")) == []
    assert list(root.rglob("*.kgmg.bak")) == []


def test_cleanup_close_interrupt_is_retried_without_descriptor_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    _commit(root, "install governed files")
    target = root / "scripts/chem_formula.py"
    target.write_text("committed drift\n")
    _commit(root, "commit deliberate drift")

    cleanup_started = False
    interrupted_fd: int | None = None
    original_verify = governance._verify_transaction
    original_close = governance.os.close

    def mark_commit_point(entries) -> None:
        nonlocal cleanup_started
        original_verify(entries)
        cleanup_started = True

    def interrupt_before_close(descriptor: int) -> None:
        nonlocal interrupted_fd
        if cleanup_started and interrupted_fd is None:
            interrupted_fd = descriptor
            raise KeyboardInterrupt
        original_close(descriptor)

    monkeypatch.setattr(governance, "_verify_transaction", mark_commit_point)
    monkeypatch.setattr(governance.os, "close", interrupt_before_close)

    with pytest.raises(GovernanceError, match="committed, but cleanup was incomplete"):
        sync_repository("culturemech", root, REF, apply=True)

    assert interrupted_fd is not None
    with pytest.raises(OSError):
        governance.os.fstat(interrupted_fd)
    assert governance.plan_sync("culturemech", root, REF) == ()


def test_rollback_close_interrupt_cannot_skip_remaining_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    original_prepare = governance._prepare_transaction
    original_promote = governance._promote_entry
    original_rollback = governance._rollback_transaction
    original_close = governance.os.close
    parent_fds: set[int] = set()
    rollback_started = False
    injected = False

    def record_entries(*args, **kwargs) -> None:
        original_prepare(*args, **kwargs)
        entries = args[-1]
        parent_fds.update(entry.parent_fd for entry in entries)

    def fail_after_first_promotion(entry) -> None:
        original_promote(entry)
        raise OSError("injected primary promotion failure")

    def mark_rollback(*args, **kwargs):
        nonlocal rollback_started
        rollback_started = True
        return original_rollback(*args, **kwargs)

    def interrupt_parent_close(descriptor: int) -> None:
        nonlocal injected
        if rollback_started and descriptor in parent_fds and not injected:
            injected = True
            raise KeyboardInterrupt
        original_close(descriptor)

    monkeypatch.setattr(governance, "_prepare_transaction", record_entries)
    monkeypatch.setattr(governance, "_promote_entry", fail_after_first_promotion)
    monkeypatch.setattr(governance, "_rollback_transaction", mark_rollback)
    monkeypatch.setattr(governance.os, "close", interrupt_parent_close)

    with pytest.raises(GovernanceError, match="recovery was incomplete"):
        sync_repository("culturemech", root, REF, apply=True)

    assert injected
    for descriptor in parent_fds:
        with pytest.raises(OSError):
            governance.os.fstat(descriptor)
    _assert_empty_and_clean(root)


def test_final_snapshot_detects_drift_in_an_unchanged_governed_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    _commit(root, "install governed files")
    changed = root / "scripts/chem_formula.py"
    changed.write_text("committed drift\n")
    _commit(root, "commit deliberate drift")
    unchanged = root / "tests/test_skill_frontmatter.py"
    original_plan = governance._plan_sync
    injected = False

    def drift_after_path_plan(*args, **kwargs):
        nonlocal injected
        result = original_plan(*args, **kwargs)
        if not injected and not result:
            unchanged.write_text("concurrent unchanged-target drift\n")
            injected = True
        return result

    monkeypatch.setattr(governance, "_plan_sync", drift_after_path_plan)

    with pytest.raises(GovernanceError, match="verification failed"):
        sync_repository("culturemech", root, REF, apply=True)

    assert injected
    assert changed.read_text() == "committed drift\n"
    assert unchanged.read_text() == "concurrent unchanged-target drift\n"


def test_symlink_lock_is_rejected_before_target_mutation(tmp_path: Path) -> None:
    root = _repository(tmp_path / "CultureMech")
    outside = tmp_path / "outside-lock"
    outside.write_text("preserve\n")
    (root / ".git/kg-microbe-governance.lock").symlink_to(outside)

    with pytest.raises(GovernanceError, match="open.*lock safely"):
        sync_repository("culturemech", root, REF, apply=True)

    assert outside.read_text() == "preserve\n"
    assert not (root / "scripts").exists()


def test_stable_lock_inode_rejects_a_concurrent_synchronizer(tmp_path: Path) -> None:
    root = _repository(tmp_path / "CultureMech")
    lock_path = root / ".git/kg-microbe-governance.lock"

    with governance._repository_sync_lock(root):
        inode = lock_path.stat().st_ino
        with pytest.raises(GovernanceError, match="Another governance synchronization"):
            sync_repository("culturemech", root, REF, apply=True)

    with governance._repository_sync_lock(root):
        assert lock_path.stat().st_ino == inode


def test_lock_unlock_interrupt_still_closes_and_releases_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech")
    assert governance.fcntl is not None
    original_flock = governance.fcntl.flock
    interrupted_fd: int | None = None

    def interrupt_unlock(descriptor: int, operation: int) -> None:
        nonlocal interrupted_fd
        if operation == governance.fcntl.LOCK_UN and interrupted_fd is None:
            interrupted_fd = descriptor
            raise KeyboardInterrupt
        original_flock(descriptor, operation)

    monkeypatch.setattr(governance.fcntl, "flock", interrupt_unlock)

    with pytest.raises(KeyboardInterrupt):
        with governance._repository_sync_lock(root):
            pass

    assert interrupted_fd is not None
    with pytest.raises(OSError):
        governance.os.fstat(interrupted_fd)
    with governance._repository_sync_lock(root):
        pass
