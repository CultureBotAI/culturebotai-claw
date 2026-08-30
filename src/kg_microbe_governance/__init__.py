"""Canonical governance manifest and provenance-bound Mech artifact synchronizer."""

from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable, Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by capability checks off Unix
    fcntl = None  # type: ignore[assignment]

from .artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    MAX_DOWNLOAD_BYTES,
    Artifact,
    CanonicalFetchError,
    Consumer,
    GovernanceError,
    GovernanceManifest,
    _git_environment,
    _safe_local_file,
    _validate_git_repository,
    expand_target,
    fetch_url,
    parse_manifest,
    raw_url,
)

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

    from kg_microbe_fleet import FleetManifest

__all__ = [
    "Artifact",
    "CanonicalFetchError",
    "Consumer",
    "GovernanceError",
    "GovernanceManifest",
    "SyncChange",
    "load_governance_manifest",
    "plan_sync",
    "sync_repository",
    "verify_canonical_ref",
]

PACKAGE_NAME = "kg_microbe_governance"
MANIFEST_FILENAME = "vendored_artifacts.json"
_ARTIFACT_PREFIX = f"src/{PACKAGE_NAME}/artifacts/"


@dataclass(frozen=True)
class SyncChange:
    """One file that a check or synchronization would change."""

    artifact_id: str
    path: str
    reason: str


@dataclass(frozen=True)
class _FileState:
    exists: bool
    content: bytes = b""
    mode: int = 0
    device: int = 0
    inode: int = 0


@dataclass
class _TransactionEntry:
    relative: str
    content: bytes
    mode: int
    parent_fd: int
    filename: str
    temporary: str
    anchor: Optional[str]
    original: _FileState


def _manifest_resource() -> "Traversable":
    return files(PACKAGE_NAME).joinpath(MANIFEST_FILENAME)


def _artifact_resource(source: str) -> "Traversable":
    if not source.startswith(_ARTIFACT_PREFIX):
        raise GovernanceError(f"Canonical source is outside artifact root: {source}")
    relative = source.removeprefix(f"src/{PACKAGE_NAME}/")
    resource: Traversable = files(PACKAGE_NAME)
    for part in relative.split("/"):
        resource = resource.joinpath(part)
    if not resource.is_file():
        raise GovernanceError(f"Canonical artifact is missing from package: {source}")
    return resource


def _validate_fleet_alignment(
    manifest: GovernanceManifest, fleet_manifest: "FleetManifest"
) -> None:
    expected_keys = set(fleet_manifest.keys)
    actual_keys = set(manifest.consumers)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise GovernanceError(
            "Governance consumers differ from the canonical fleet "
            f"(missing={missing}, unknown={unknown})"
        )
    for key, consumer in manifest.consumers.items():
        mech = fleet_manifest.get(key)
        if consumer.github != mech.github or consumer.package_path != mech.package_path:
            raise GovernanceError(
                f"Governance identity/path drift for {key}: "
                f"{consumer.github}, {consumer.package_path}"
            )
    governance = fleet_manifest.vendored_governance
    if manifest.canonical_repository != governance.canonical_repository:
        raise GovernanceError("Governance authority differs from fleet.yaml")
    if manifest.pin_path != governance.pin_path:
        raise GovernanceError("Governance pin path differs from fleet.yaml")
    if governance.manifest_path != CANONICAL_MANIFEST_PATH:
        raise GovernanceError(
            "Fleet governance manifest path differs from the standalone checker"
        )
    edison_scope = {
        key
        for key, mech in fleet_manifest.mechs.items()
        if mech.supports("edison_key_discovery")
    }
    edison = next(
        (
            artifact
            for artifact in manifest.artifacts
            if artifact.artifact_id == "edison_capture"
        ),
        None,
    )
    if edison is None or set(edison.consumers) != edison_scope:
        raise GovernanceError(
            "Edison artifact applicability differs from the fleet capability scope"
        )
    # The provider-triage contract test imports scripts/deep_research_provider.py
    # from the consumer, so it applies exactly where deep_research is enabled.
    # It shipped as `consumers: all` until a Mech without a research provider
    # joined and the vendored test failed at import (#252). Derived and checked
    # here, like Edison above, so the list cannot drift from the capability.
    triage_scope = {
        key
        for key, mech in fleet_manifest.mechs.items()
        if mech.supports("deep_research")
    }
    triage = next(
        (
            artifact
            for artifact in manifest.artifacts
            if artifact.artifact_id == "provider_triage_contract"
        ),
        None,
    )
    if triage is None or set(triage.consumers) != triage_scope:
        raise GovernanceError(
            "Provider-triage artifact applicability differs from the fleet capability scope"
        )


def load_governance_manifest(
    path: Optional[Path] = None,
    *,
    fleet_manifest: Optional["FleetManifest"] = None,
) -> GovernanceManifest:
    """Load the strict manifest and prove its bytes and fleet mappings."""

    try:
        data = path.read_bytes() if path is not None else _manifest_resource().read_bytes()
    except OSError as exc:
        raise GovernanceError(f"Unable to read governance manifest: {exc}") from exc
    manifest = parse_manifest(data)
    if fleet_manifest is None:
        from kg_microbe_fleet import load_fleet_manifest

        fleet_manifest = load_fleet_manifest()
    _validate_fleet_alignment(manifest, fleet_manifest)
    for artifact in manifest.artifacts:
        content = _artifact_resource(artifact.source).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact.sha256:
            raise GovernanceError(
                f"Canonical artifact checksum drift: {artifact.source} "
                f"is {digest}, manifest says {artifact.sha256}"
            )
    return manifest


def _validate_ref(ref: str) -> str:
    from .artifacts.scripts.check_vendored_sync import _SHA_PATTERN

    if not _SHA_PATTERN.fullmatch(ref):
        raise GovernanceError("Canonical ref must be exactly 40 lowercase hex digits")
    return ref


def _verify_canonical_ref(
    canonical_ref: str,
    manifest: GovernanceManifest,
    *,
    fetch: Optional[Callable[[str], bytes]] = None,
) -> None:
    fetcher = fetch or fetch_url
    packaged_manifest = _manifest_resource().read_bytes()
    remote_manifest = fetcher(raw_url(canonical_ref, CANONICAL_MANIFEST_PATH))
    # Parse first so a malformed canonical document never becomes an opaque
    # byte-mismatch diagnosis. Exact bytes are then required because this
    # installed package is the source of the pending writes.
    parse_manifest(remote_manifest)
    if remote_manifest != packaged_manifest:
        raise GovernanceError(
            "Pinned claw manifest does not match the installed governance package"
        )
    for artifact in manifest.artifacts:
        remote = fetcher(raw_url(canonical_ref, artifact.source))
        digest = hashlib.sha256(remote).hexdigest()
        if digest != artifact.sha256:
            raise GovernanceError(
                f"Pinned claw artifact checksum drift: {artifact.source} "
                f"is {digest}, manifest says {artifact.sha256}"
            )
        packaged = _artifact_resource(artifact.source).read_bytes()
        if remote != packaged:
            raise GovernanceError(
                f"Pinned claw artifact differs from installed package: {artifact.source}"
            )


def verify_canonical_ref(canonical_ref: str) -> GovernanceManifest:
    """Bind an immutable claw ref to the exact installed manifest and payloads."""

    canonical_ref = _validate_ref(canonical_ref)
    manifest = load_governance_manifest()
    _verify_canonical_ref(canonical_ref, manifest)
    return manifest


def _desired_files(
    manifest: GovernanceManifest,
    consumer: Consumer,
    canonical_ref: str,
) -> tuple[tuple[str, str, bytes, int], ...]:
    desired: list[tuple[str, str, bytes, int]] = []
    for artifact in manifest.artifacts_for(consumer):
        content = _artifact_resource(artifact.source).read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise GovernanceError(
                f"Canonical artifact checksum drift: {artifact.source}"
            )
        desired.append(
            (
                artifact.artifact_id,
                expand_target(artifact, consumer),
                content,
                artifact.mode,
            )
        )
    desired.append(
        ("canonical_pin", manifest.pin_path, (canonical_ref + "\n").encode("ascii"), 0o644)
    )
    return tuple(desired)


def _change_reason(
    path: Path, content: bytes, mode: int, *, executable_mask: int = stat.S_IXUSR
) -> Optional[str]:
    if not path.exists():
        return "missing"
    if not path.is_file():
        raise GovernanceError(f"Governed target is not a regular file: {path}")
    try:
        metadata = path.stat()
        with path.open("rb") as stream:
            current = stream.read(MAX_DOWNLOAD_BYTES + 1)
        current_mode = metadata.st_mode
    except OSError as exc:
        raise GovernanceError(f"Unable to inspect governed target {path}: {exc}") from exc
    return _state_change_reason(
        _FileState(True, current, stat.S_IMODE(current_mode)),
        content,
        mode,
        executable_mask=executable_mask,
    )


def _state_change_reason(
    state: _FileState,
    content: bytes,
    mode: int,
    *,
    executable_mask: int = stat.S_IXUSR,
) -> Optional[str]:
    """Describe governed drift from one stable file snapshot."""

    if not state.exists:
        return "missing"
    reasons: list[str] = []
    if state.content != content:
        reasons.append("content drift")
    if bool(state.mode & executable_mask) != bool(mode & executable_mask):
        reasons.append("mode drift")
    writable_mask = stat.S_IWGRP | stat.S_IWOTH
    if (state.mode & writable_mask) != (mode & writable_mask):
        reasons.append("unsafe writable mode")
    return ", ".join(reasons) if reasons else None


def _validate_target_repository(root: Path, consumer: Consumer) -> Path:
    """Require an exact Git root whose origin matches the selected consumer."""

    resolved, identity = _validate_git_repository(root)
    if identity.lower() != consumer.github.lower():
        raise GovernanceError(
            f"Target origin is {identity!r}; expected {consumer.github!r}"
        )
    return resolved


def _require_clean_worktree(root: Path) -> None:
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=_git_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GovernanceError(f"Unable to inspect target worktree: {root}") from exc
    if result.stdout:
        raise GovernanceError(
            "Refusing --apply in a dirty target worktree; commit or move existing "
            "changes before synchronizing"
        )


def _git_path_result(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                *arguments,
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=_git_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GovernanceError(f"Unable to inspect governed Git paths at {root}") from exc


def _require_trackable_targets(
    root: Path, desired: tuple[tuple[str, str, bytes, int], ...]
) -> None:
    """Refuse paths Git would hide and pre-existing untracked targets."""

    for _artifact_id, relative, _content, _mode in desired:
        target = _safe_local_file(root, relative)
        tracked = _git_path_result(
            root, ["ls-files", "--error-unmatch", "--", relative]
        )
        if tracked.returncode == 0:
            continue
        if tracked.returncode not in {1}:
            raise GovernanceError(
                f"Unable to determine whether governed target is tracked: {relative}"
            )
        ignored = _git_path_result(
            root, ["check-ignore", "--quiet", "--no-index", "--", relative]
        )
        if ignored.returncode == 0:
            raise GovernanceError(
                f"Governed target is ignored by Git and cannot be safely applied: {relative}"
            )
        if ignored.returncode not in {1}:
            raise GovernanceError(
                f"Unable to determine whether governed target is ignored: {relative}"
            )
        if target.exists():
            raise GovernanceError(
                f"Refusing to overwrite pre-existing untracked target: {relative}"
            )


def _plan_sync(
    manifest: GovernanceManifest,
    consumer: Consumer,
    root: Path,
    canonical_ref: str,
) -> tuple[SyncChange, ...]:
    changes: list[SyncChange] = []
    for artifact_id, relative, content, mode in _desired_files(
        manifest, consumer, canonical_ref
    ):
        target = _safe_local_file(root, relative)
        mode_mask = 0o111 if artifact_id == "canonical_pin" else stat.S_IXUSR
        reason = _change_reason(target, content, mode, executable_mask=mode_mask)
        if reason is not None:
            changes.append(SyncChange(artifact_id, relative, reason))
    return tuple(changes)


def _changes_from_snapshots(
    desired: tuple[tuple[str, str, bytes, int], ...],
    snapshots: dict[str, _FileState],
) -> tuple[SyncChange, ...]:
    """Build the apply plan from the states bound to this transaction."""

    changes: list[SyncChange] = []
    for artifact_id, relative, content, mode in desired:
        mode_mask = 0o111 if artifact_id == "canonical_pin" else stat.S_IXUSR
        reason = _state_change_reason(
            snapshots[relative], content, mode, executable_mask=mode_mask
        )
        if reason is not None:
            changes.append(SyncChange(artifact_id, relative, reason))
    return tuple(changes)


def plan_sync(
    repository: str,
    root: Path,
    canonical_ref: str,
) -> tuple[SyncChange, ...]:
    """Return a provenance-verified plan; never mutate the target repository."""

    canonical_ref = _validate_ref(canonical_ref)
    manifest = load_governance_manifest()
    _verify_canonical_ref(canonical_ref, manifest)
    consumer = manifest.consumer_for(repository)
    root = _validate_target_repository(root, consumer)
    return _plan_sync(manifest, consumer, root, canonical_ref)


def _close_descriptor_safely(
    descriptor: int,
    label: str,
) -> tuple[bool, list[str]]:
    """Close an owned fd with one interrupt-aware retry and EBADF proof."""

    errors: list[str] = []
    for _attempt in range(2):
        try:
            os.close(descriptor)
            return True, errors
        except BaseException as exc:
            errors.append(f"{label}: close: {type(exc).__name__}: {exc}")
            try:
                os.fstat(descriptor)
            except OSError as probe:
                if probe.errno == errno.EBADF:
                    return True, errors
                errors.append(f"{label}: close probe: {probe}")
    return False, errors


@contextmanager
def _owned_descriptor(descriptor: int, label: str) -> Iterator[int]:
    """Guarantee best-effort closure without masking a clean close."""

    try:
        yield descriptor
    except BaseException as primary:
        _closed, errors = _close_descriptor_safely(descriptor, label)
        if errors:
            raise GovernanceError(
                "Descriptor cleanup failed after an operation error: "
                + "; ".join(errors)
            ) from primary
        raise
    else:
        _closed, errors = _close_descriptor_safely(descriptor, label)
        if errors:
            raise GovernanceError("Descriptor cleanup failed: " + "; ".join(errors))


def _open_parent(
    root: Path,
    relative: str,
    *,
    created_directories: Optional[list[str]] = None,
    create: bool = True,
) -> tuple[int, str]:
    """Open/create a target parent by dirfd without following symlinks."""

    parts = PurePosixPath(relative).parts
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root, flags)
    traversed: list[str] = []
    try:
        for part in parts[:-1]:
            traversed.append(part)
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
                    if created_directories is not None:
                        created_directories.append("/".join(traversed))
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=descriptor)
            closed, close_errors = _close_descriptor_safely(
                descriptor,
                f"parent traversal for {relative}",
            )
            if closed:
                descriptor = child
            else:
                _child_closed, child_errors = _close_descriptor_safely(
                    child,
                    f"unadopted child descriptor for {relative}",
                )
                close_errors.extend(child_errors)
            if close_errors:
                raise GovernanceError(
                    "Unable to close a traversed parent descriptor: "
                    + "; ".join(close_errors)
                )
        return descriptor, parts[-1]
    except BaseException as primary:
        _closed, close_errors = _close_descriptor_safely(
            descriptor,
            f"parent traversal recovery for {relative}",
        )
        if close_errors:
            raise GovernanceError(
                "Unable to close a parent descriptor during recovery: "
                + "; ".join(close_errors)
            ) from primary
        raise


def _require_safe_dirfd_support() -> None:
    missing_flags = [
        name
        for name in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
        if not hasattr(os, name)
    ]
    required_dirfd = (
        os.open,
        os.mkdir,
        os.stat,
        os.link,
        os.rename,
        os.unlink,
        os.rmdir,
    )
    missing_dirfd = [
        function.__name__
        for function in required_dirfd
        if function not in os.supports_dir_fd
    ]
    missing_follow = [
        function.__name__
        for function in (os.link,)
        if function not in os.supports_follow_symlinks
    ]
    missing_lock: list[str] = ["fcntl.flock"] if fcntl is None else []
    if missing_flags or missing_dirfd or missing_follow or missing_lock:
        details = ", ".join(
            missing_flags + missing_dirfd + missing_follow + missing_lock
        )
        raise GovernanceError(
            "Safe symlink-resistant apply is unavailable on this platform: " + details
        )


@contextmanager
def _repository_sync_lock(root: Path) -> Iterator[None]:
    """Serialize cooperating synchronizers on one stable Git-metadata inode."""

    if fcntl is None:  # pragma: no cover - guarded by _require_safe_dirfd_support
        raise GovernanceError("Repository locking is unavailable on this platform")
    from .artifacts.scripts.check_vendored_sync import _run_git

    raw_path = _run_git(
        root, ("rev-parse", "--git-path", "kg-microbe-governance.lock")
    ).strip()
    lock_path = Path(raw_path)
    if not lock_path.is_absolute():
        lock_path = root / lock_path
    descriptor = -1
    body_failed = False
    try:
        try:
            descriptor = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as exc:
            raise GovernanceError(
                "Unable to open the repository governance lock safely"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            visible = lock_path.lstat()
        except OSError as exc:
            raise GovernanceError(
                "Unable to verify the repository governance lock inode"
            ) from exc
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (visible.st_dev, visible.st_ino):
            raise GovernanceError("Repository governance lock must be a stable regular file")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GovernanceError(
                "Another governance synchronization is active for this worktree"
            ) from exc
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        if descriptor >= 0:
            unlock_failure: Optional[BaseException] = None
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            except BaseException as exc:
                unlock_failure = exc
            closed, close_errors = _close_descriptor_safely(
                descriptor,
                "repository governance lock",
            )
            if closed:
                descriptor = -1
            if not body_failed:
                if unlock_failure is not None:
                    raise unlock_failure
                if close_errors:
                    raise GovernanceError(
                        "Repository governance lock cleanup failed: "
                        + "; ".join(close_errors)
                    )


def _capture_file_state(parent_fd: int, filename: str) -> _FileState:
    descriptor = -1
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return _FileState(False)
    except OSError as exc:
        raise GovernanceError(f"Unable to inspect governed target {filename}: {exc}") from exc
    with _owned_descriptor(descriptor, f"governed target {filename}"):
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise GovernanceError(f"Governed target is not a regular file: {filename}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise GovernanceError(
                    f"Governed target exceeds {MAX_DOWNLOAD_BYTES} bytes: {filename}"
                )
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise GovernanceError(f"Governed target changed while inspecting: {filename}")
        return _FileState(
            True,
            b"".join(chunks),
            stat.S_IMODE(after.st_mode),
            after.st_dev,
            after.st_ino,
        )


def _snapshot_target_states(
    root: Path,
    desired: tuple[tuple[str, str, bytes, int], ...],
) -> dict[str, _FileState]:
    """Capture every target without creating parents or following symlinks."""

    snapshots: dict[str, _FileState] = {}
    for _artifact_id, relative, _content, _mode in desired:
        try:
            parent_fd, filename = _open_parent(root, relative, create=False)
        except FileNotFoundError:
            snapshots[relative] = _FileState(False)
            continue
        except OSError as exc:
            raise GovernanceError(
                f"Unable to snapshot governed target {relative}: {exc}"
            ) from exc
        with _owned_descriptor(parent_fd, f"snapshot parent for {relative}"):
            snapshots[relative] = _capture_file_state(parent_fd, filename)
    return snapshots


def _same_file_state(left: _FileState, right: _FileState) -> bool:
    return (
        left.exists == right.exists
        and (
            not left.exists
            or (
                left.content,
                left.mode,
                left.device,
                left.inode,
            )
            == (
                right.content,
                right.mode,
                right.device,
                right.inode,
            )
        )
    )


def _matches_desired(state: _FileState, content: bytes, mode: int) -> bool:
    return state.exists and state.content == content and state.mode == mode


def _write_staged_file(parent_fd: int, name: str, content: bytes, mode: int) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        mode,
        dir_fd=parent_fd,
    )
    with _owned_descriptor(descriptor, f"staged artifact {name}"):
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while staging governed artifact")
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)


def _prepare_transaction(
    root: Path,
    desired: tuple[tuple[str, str, bytes, int], ...],
    change_paths: set[str],
    expected_states: dict[str, _FileState],
    created_directories: list[str],
    entries: list[_TransactionEntry],
) -> None:
    for _artifact_id, relative, content, mode in desired:
        if relative not in change_paths:
            continue
        parent_fd, filename = _open_parent(
            root,
            relative,
            created_directories=created_directories,
        )
        temporary: Optional[str] = None
        anchor: Optional[str] = None
        try:
            token = secrets.token_hex(12)
            temporary = f".{filename}.{token}.kgmg.tmp"
            original = _capture_file_state(parent_fd, filename)
            if not _same_file_state(original, expected_states[relative]):
                raise GovernanceError(
                    f"Governed target changed after locked snapshot: {relative}"
                )
            _write_staged_file(parent_fd, temporary, content, mode)
            if original.exists:
                anchor = f".{filename}.{token}.kgmg.bak"
                os.link(
                    filename,
                    anchor,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                anchored = _capture_file_state(parent_fd, anchor)
                if not _same_file_state(original, anchored):
                    raise GovernanceError(
                        f"Rollback anchor verification failed for {relative}"
                    )
            os.fsync(parent_fd)
            entries.append(
                _TransactionEntry(
                    relative,
                    content,
                    mode,
                    parent_fd,
                    filename,
                    temporary,
                    anchor,
                    original,
                )
            )
        except BaseException as primary:
            cleanup_errors: list[str] = []
            pending = [internal for internal in (temporary, anchor) if internal]
            for _attempt in range(2):
                retry: list[str] = []
                for internal in pending:
                    try:
                        _unlink_if_present(parent_fd, internal)
                    except BaseException as exc:
                        cleanup_errors.append(
                            f"{relative}: preparation cleanup {internal}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        retry.append(internal)
                pending = retry
                if not pending:
                    break
            _closed, close_errors = _close_descriptor_safely(
                parent_fd,
                f"{relative}: preparation cleanup",
            )
            cleanup_errors.extend(close_errors)
            if cleanup_errors:
                raise GovernanceError(
                    "Transaction preparation failed and cleanup encountered errors: "
                    + "; ".join(cleanup_errors)
                ) from primary
            raise


def _promote_entry(entry: _TransactionEntry) -> None:
    """Promote one staged file; retained as a failure-injection seam."""

    current = _capture_file_state(entry.parent_fd, entry.filename)
    if not _same_file_state(current, entry.original):
        raise GovernanceError(
            f"Governed target changed before promotion: {entry.relative}"
        )
    if entry.original.exists:
        os.rename(
            entry.temporary,
            entry.filename,
            src_dir_fd=entry.parent_fd,
            dst_dir_fd=entry.parent_fd,
        )
    else:
        os.link(
            entry.temporary,
            entry.filename,
            src_dir_fd=entry.parent_fd,
            dst_dir_fd=entry.parent_fd,
            follow_symlinks=False,
        )
        os.unlink(entry.temporary, dir_fd=entry.parent_fd)
    os.fsync(entry.parent_fd)


def _unlink_if_present(parent_fd: int, name: Optional[str]) -> None:
    if name is None:
        return
    try:
        os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        pass


def _remove_created_directories(root: Path, created: list[str]) -> list[str]:
    errors: list[str] = []
    for relative in reversed(created):
        parent_fd = -1
        try:
            parent_fd, name = _open_parent(root, relative, create=False)
        except BaseException as exc:
            errors.append(
                f"{relative}: directory cleanup open: {type(exc).__name__}: {exc}"
            )
            continue
        try:
            os.rmdir(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except BaseException as exc:
            errors.append(
                f"{relative}: directory cleanup: {type(exc).__name__}: {exc}"
            )
        finally:
            closed, close_errors = _close_descriptor_safely(
                parent_fd,
                f"{relative}: directory cleanup",
            )
            if closed:
                parent_fd = -1
            errors.extend(close_errors)
    return errors


def _rollback_transaction(
    root: Path,
    entries: list[_TransactionEntry],
    created_directories: list[str],
) -> list[str]:
    errors: list[str] = []
    for entry in reversed(entries):
        try:
            current = _capture_file_state(entry.parent_fd, entry.filename)
            if entry.original.exists:
                if _same_file_state(current, entry.original):
                    pass
                elif _matches_desired(current, entry.content, entry.mode):
                    if entry.anchor is None:
                        raise GovernanceError("rollback anchor is missing")
                    os.rename(
                        entry.anchor,
                        entry.filename,
                        src_dir_fd=entry.parent_fd,
                        dst_dir_fd=entry.parent_fd,
                    )
                    entry.anchor = None
                    restored = _capture_file_state(entry.parent_fd, entry.filename)
                    if not _same_file_state(restored, entry.original):
                        raise GovernanceError("restored target differs from snapshot")
                else:
                    raise GovernanceError(
                        "target contains third-party bytes; rollback anchor retained"
                    )
            elif not current.exists:
                pass
            elif _matches_desired(current, entry.content, entry.mode):
                os.unlink(entry.filename, dir_fd=entry.parent_fd)
            else:
                raise GovernanceError(
                    "new target contains third-party bytes and was preserved"
                )
            _unlink_if_present(entry.parent_fd, entry.temporary)
            _unlink_if_present(entry.parent_fd, entry.anchor)
            entry.anchor = None
            os.fsync(entry.parent_fd)
        except BaseException as exc:
            errors.append(f"{entry.relative}: {exc}")
    for entry in entries:
        if entry.parent_fd < 0:
            continue
        closed, close_errors = _close_descriptor_safely(
            entry.parent_fd,
            f"{entry.relative}: rollback cleanup",
        )
        errors.extend(close_errors)
        if closed:
            entry.parent_fd = -1
    errors.extend(_remove_created_directories(root, created_directories))
    return errors


def _verify_transaction(entries: list[_TransactionEntry]) -> None:
    """Establish the commit point only after every promoted target is exact."""

    for entry in entries:
        state = _capture_file_state(entry.parent_fd, entry.filename)
        if not _matches_desired(state, entry.content, entry.mode):
            raise GovernanceError(
                f"Synchronization verification failed: {entry.relative}"
            )


def _cleanup_committed_transaction(entries: list[_TransactionEntry]) -> list[str]:
    """Best-effort cleanup after commit; never make rollback appear possible."""

    errors: list[str] = []
    for entry in entries:
        if entry.parent_fd < 0:
            continue
        pending = [
            ("temporary", entry.temporary),
            ("anchor", entry.anchor),
        ]
        # A signal may be delivered immediately before or after an unlink.
        # Retry once using the still-open directory descriptor; FileNotFound is
        # success and proves cleanup completed in the after-unlink case.
        for _attempt in range(2):
            retry: list[tuple[str, Optional[str]]] = []
            for kind, internal in pending:
                if internal is None:
                    continue
                try:
                    _unlink_if_present(entry.parent_fd, internal)
                    if kind == "anchor":
                        entry.anchor = None
                except BaseException as exc:
                    errors.append(
                        f"{entry.relative}: cleanup {internal}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    retry.append((kind, internal))
            pending = retry
            if not pending:
                break
        for _attempt in range(2):
            try:
                os.fsync(entry.parent_fd)
                break
            except BaseException as exc:
                errors.append(
                    f"{entry.relative}: cleanup fsync: {type(exc).__name__}: {exc}"
                )
    for entry in entries:
        if entry.parent_fd < 0:
            continue
        closed, close_errors = _close_descriptor_safely(
            entry.parent_fd,
            f"{entry.relative}: committed cleanup",
        )
        errors.extend(close_errors)
        if closed:
            entry.parent_fd = -1
    return errors


def sync_repository(
    repository: str,
    root: Path,
    canonical_ref: str,
    *,
    apply: bool = False,
) -> tuple[SyncChange, ...]:
    """Plan or safely apply provenance-bound bytes; dry-run is the default."""

    canonical_ref = _validate_ref(canonical_ref)
    manifest = load_governance_manifest()
    _verify_canonical_ref(canonical_ref, manifest)
    consumer = manifest.consumer_for(repository)
    root = _validate_target_repository(root, consumer)
    if not apply:
        return _plan_sync(manifest, consumer, root, canonical_ref)
    _require_safe_dirfd_support()
    desired = _desired_files(manifest, consumer, canonical_ref)
    with _repository_sync_lock(root):
        # All target state is revalidated and replanned while cooperating
        # writers are serialized. Remote verification intentionally happened
        # before the lock so a slow network cannot block another local run.
        root = _validate_target_repository(root, consumer)
        _require_trackable_targets(root, desired)
        _require_clean_worktree(root)
        snapshots = _snapshot_target_states(root, desired)
        # Close the windows on either side of the stable dirfd snapshot. The
        # snapshot itself is then compared again inside transaction preparation.
        _require_clean_worktree(root)
        _require_trackable_targets(root, desired)
        changes = _changes_from_snapshots(desired, snapshots)
        if not changes:
            return ()

        entries: list[_TransactionEntry] = []
        created_directories: list[str] = []
        committed = False
        try:
            _prepare_transaction(
                root,
                desired,
                {change.path for change in changes},
                snapshots,
                created_directories,
                entries,
            )
            # Staging and rollback-anchor creation must not alter the original
            # target states. Catch observed editor races before the first
            # promotion.
            for entry in entries:
                current = _capture_file_state(entry.parent_fd, entry.filename)
                if not _same_file_state(current, entry.original):
                    raise GovernanceError(
                        f"Governed target changed during staging: {entry.relative}"
                    )
            for entry in entries:
                _promote_entry(entry)
            remaining = _plan_sync(manifest, consumer, root, canonical_ref)
            final_states = _snapshot_target_states(root, desired)
            snapshot_remaining = _changes_from_snapshots(desired, final_states)
            if remaining or snapshot_remaining:
                paths = ", ".join(
                    dict.fromkeys(
                        change.path
                        for change in (*remaining, *snapshot_remaining)
                    )
                )
                raise GovernanceError(f"Synchronization verification failed: {paths}")
            _verify_transaction(entries)
            # This is the commit point. From here onward rollback anchors may
            # be removed, so cleanup failures must never trigger impossible
            # restoration attempts.
            committed = True
            cleanup_errors = _cleanup_committed_transaction(entries)
            if cleanup_errors:
                raise GovernanceError(
                    "Synchronization committed, but cleanup was incomplete: "
                    + "; ".join(cleanup_errors)
                )
            return changes
        except BaseException as primary:
            if committed:
                _cleanup_committed_transaction(entries)
                raise
            recovery_errors = _rollback_transaction(
                root, entries, created_directories
            )
            if recovery_errors:
                details = "; ".join(recovery_errors)
                raise GovernanceError(
                    "Synchronization failed and recovery was incomplete: " + details
                ) from primary
            if isinstance(primary, (GovernanceError, KeyboardInterrupt, SystemExit)):
                raise
            raise GovernanceError(
                f"Synchronization transaction failed: {primary}"
            ) from primary
