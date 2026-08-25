"""
Lock Manager Plugin for Multi-Claude Coordination

Prevents conflicts between Orchestration Claude and downstream Claudes on one
machine by implementing a local file-based lock system.
"""

import fcntl
import logging
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

import yaml

from kg_microbe_fleet import UniqueKeySafeLoader

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_workspace_root() -> Path:
    """Resolve the shared runtime workspace, failing closed outside a checkout."""

    workspace = Path(os.getenv("OPENCLAW_WORKSPACE", "workspace")).expanduser()
    if workspace.is_absolute():
        if workspace.is_symlink():
            raise ValueError("OPENCLAW_WORKSPACE must not be a symlink")
        return workspace.resolve()

    orchestration_root = os.getenv("OPENCLAW_ORCHESTRATION_ROOT")
    if orchestration_root:
        base = Path(orchestration_root).expanduser()
    elif (PROJECT_ROOT / "pyproject.toml").is_file():
        base = PROJECT_ROOT
    else:
        raise ValueError(
            "OPENCLAW_ORCHESTRATION_ROOT must be set when OPENCLAW_WORKSPACE "
            "is relative and the orchestration checkout cannot be identified"
        )
    resolved_base = base.resolve()
    candidate = resolved_base / workspace
    if candidate.is_symlink():
        raise ValueError("OPENCLAW_WORKSPACE must not be a symlink")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_base)
    except ValueError as exc:
        raise ValueError(
            "relative OPENCLAW_WORKSPACE must stay within "
            "OPENCLAW_ORCHESTRATION_ROOT"
        ) from exc
    return resolved


class LockManager:
    """Local lock manager for multi-Claude coordination on one machine."""

    _RESOURCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    _MAX_LOCK_BYTES = 64 * 1024
    _GLOBAL_RESOURCE = "global"
    _HIERARCHY_GUARD_NAME = ".lock-hierarchy.guard"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize lock manager.

        Args:
            config: Configuration with locks_dir, my_id, default_timeout
        """
        self.config = config or {}
        configured_locks_dir = self.config.get("locks_dir")
        self.locks_dir = (
            Path(configured_locks_dir)
            if configured_locks_dir is not None
            else resolve_workspace_root() / "locks"
        )
        if self.locks_dir.is_symlink():
            raise ValueError(f"locks_dir must not be a symlink: {self.locks_dir}")
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        locks_stat = self.locks_dir.lstat()
        if stat.S_ISLNK(locks_stat.st_mode) or not stat.S_ISDIR(locks_stat.st_mode):
            raise ValueError(f"locks_dir must be a real directory: {self.locks_dir}")

        self.my_id = self.config.get("my_id", "orchestration_claude")
        self.default_timeout = self.config.get("default_timeout", 3600)  # 1 hour
        self.poll_interval = float(self.config.get("poll_interval", 0.1))
        self._leases: Dict[str, str] = {}
        self._leases_guard = RLock()

        logger.info(f"LockManager initialized: locks_dir={self.locks_dir}, my_id={self.my_id}")

    def acquire_lock(
        self,
        resource: str,
        operation: str,
        timeout: Optional[float] = None,
        wait: bool = False,
        max_wait: int = 300,
    ) -> bool:
        """
        Acquire a lock on a resource.

        Args:
            resource: Resource name (e.g., "culturemech", "mediaingredientmech")
            operation: Description of operation
            timeout: Lock expiration time in seconds (default: 1 hour)
            wait: If True, wait for lock to become available
            max_wait: Maximum wait time in seconds

        Returns:
            True if lock acquired, False otherwise
        """
        resource = self._validate_resource(resource)
        timeout = self.default_timeout if timeout is None else timeout
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if max_wait < 0:
            raise ValueError("max_wait cannot be negative")

        lock_file = self._lock_file(resource)
        start_time = time.monotonic()
        lease_token = uuid.uuid4().hex

        logger.info(f"Attempting to acquire lock: {resource} for operation: {operation}")

        while True:
            now = self._utc_now()
            lock_data = {
                'locked_by': self.my_id,
                'lease_token': lease_token,
                'locked_at': now.isoformat(),
                'operation': operation,
                'pid': os.getpid(),
                'expires_at': (now + timedelta(seconds=timeout)).isoformat(),
                'reason': operation,
            }

            try:
                with self._hierarchy_guard():
                    conflicting_resource = self._find_hierarchy_conflict(resource)
                    if conflicting_resource is None:
                        while True:
                            try:
                                self._create_lock_atomic(lock_file, lock_data)
                                break
                            except FileExistsError:
                                # The target may itself be an expired lease. Recheck
                                # and reclaim it while the hierarchy decision remains
                                # serialized, then retry the exclusive create.
                                if self.check_lock(resource) is not None:
                                    conflicting_resource = resource
                                    break

                    if conflicting_resource is not None:
                        logger.debug(
                            "Lock %s conflicts with active or unreadable lock %s",
                            resource,
                            conflicting_resource,
                        )
                    else:
                        with self._leases_guard:
                            self._leases[resource] = lease_token
                        logger.info(f"✓ Lock acquired: {resource} (expires in {timeout}s)")
                        return True
            except Exception as e:
                logger.error(f"Failed to write lock file {lock_file}: {e}")
                return False

            elapsed = time.monotonic() - start_time
            if not wait:
                logger.warning(
                    "Failed to acquire lock %s: conflicts with %s",
                    resource,
                    conflicting_resource,
                )
                return False
            if elapsed >= max_wait:
                logger.error(f"Timeout waiting for lock {resource} after {elapsed:.1f}s")
                return False

            logger.debug(f"Waiting for lock {resource} ({elapsed:.1f}s elapsed)")
            time.sleep(min(self.poll_interval, max_wait - elapsed))

    def release_lock(self, resource: str) -> bool:
        """
        Release a lock.

        Args:
            resource: Resource name

        Returns:
            True if lock released, False if lock didn't exist or not owned by us
        """
        resource = self._validate_resource(resource)
        with self._leases_guard:
            lease_token = self._leases.get(resource)
        if not lease_token:
            logger.error(f"Cannot release lock {resource}: no lease is owned by this manager")
            return False
        return self._release_owned_lock(resource, lease_token)

    def check_lock(self, resource: str) -> Optional[Dict[str, Any]]:
        """
        Check if resource is locked.

        Args:
            resource: Resource name

        Returns:
            Lock data if locked, None if available
        """
        resource = self._validate_resource(resource)
        lock_file = self._lock_file(resource)
        lock_data = self._read_lock(lock_file)
        if not lock_data:
            if self._path_exists_without_following(lock_file):
                # A malformed or partially written lock must still block work.
                return {
                    "locked_by": "unknown",
                    "invalid": True,
                    "reason": "lock file could not be read",
                }
            return None
        if not self._is_expired(lock_data):
            return lock_data

        self._reclaim_expired_lock(resource)
        # A contender may have acquired the resource immediately after reclamation.
        current_lock = self._read_lock(lock_file)
        if current_lock:
            # Even a newly observed expired lock remains held unless a later
            # guarded reclamation proves it can be removed. Never declare an
            # extant lease available on the strength of stale observations.
            return current_lock
        if self._path_exists_without_following(lock_file):
            # O_EXCL creation makes the path visible before the successful
            # acquirer finishes writing. That partial-file window must block.
            return {
                "locked_by": "unknown",
                "invalid": True,
                "reason": "lock file could not be read after reclamation",
            }
        return None

    def check_any_locks(self, resources: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Check multiple resources for locks.

        Args:
            resources: List of resource names

        Returns:
            Dictionary mapping resource to lock data (None if not locked)
        """
        return {resource: self.check_lock(resource) for resource in resources}

    def acquire_global_lock(
        self,
        operation: str,
        timeout: Optional[float] = None,
        wait: bool = False,
        max_wait: int = 300,
    ) -> bool:
        """
        Acquire global lock (blocks all downstream repos).

        Args:
            operation: Description of operation
            timeout: Lock expiration time
            wait: If True, wait for lock
            max_wait: Maximum wait time in seconds

        Returns:
            True if acquired
        """
        return self.acquire_lock(
            self._GLOBAL_RESOURCE,
            operation,
            timeout,
            wait,
            max_wait,
        )

    def release_global_lock(self) -> bool:
        """Release global lock."""
        return self.release_lock(self._GLOBAL_RESOURCE)

    def is_global_locked(self) -> bool:
        """Check if global lock is active."""
        return self.check_lock(self._GLOBAL_RESOURCE) is not None

    def get_all_locks(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all active locks.

        Returns:
            Dictionary mapping resource to lock data
        """
        all_locks = {}
        for lock_file in self.locks_dir.glob("*.lock"):
            resource = lock_file.stem
            lock_data = self.check_lock(resource)
            if lock_data:
                all_locks[resource] = lock_data
        return all_locks

    def force_release_all(self):
        """
        Force release all locks (EMERGENCY USE ONLY).

        This should only be used if locks are stuck due to crashes.
        """
        logger.warning("🚨 FORCE RELEASING ALL LOCKS - EMERGENCY MODE")
        for lock_file in self.locks_dir.glob("*.lock"):
            try:
                lock_file.unlink()
                logger.info(f"Force released: {lock_file.stem}")
            except Exception as e:
                logger.error(f"Failed to force release {lock_file.stem}: {e}")

    @contextmanager
    def lock(self, resource: str, operation: str, timeout: Optional[float] = None):
        """
        Context manager for automatic lock acquisition and release.

        Usage:
            with lock_manager.lock("culturemech", "export_ingredients"):
                # Do work
                pass

        Args:
            resource: Resource name
            operation: Operation description
            timeout: Lock timeout in seconds
        """
        acquired = self.acquire_lock(resource, operation, timeout, wait=False)
        if not acquired:
            raise RuntimeError(f"Failed to acquire lock on {resource}")

        resource = self._validate_resource(resource)
        with self._leases_guard:
            lease_token = self._leases[resource]

        try:
            yield
        finally:
            if not self._release_owned_lock(resource, lease_token):
                logger.warning(
                    f"Context manager did not release {resource}: its lease is no longer owned"
                )

    @staticmethod
    def _utc_now() -> datetime:
        """Return an aware UTC timestamp."""
        return datetime.now(timezone.utc)

    @classmethod
    def _validate_resource(cls, resource: str) -> str:
        """Validate a resource before using it as part of a lock filename."""
        if not isinstance(resource, str) or not cls._RESOURCE_PATTERN.fullmatch(resource):
            raise ValueError(
                "resource must be 1-128 characters and contain only letters, "
                "numbers, '.', '_', or '-'"
            )
        if resource in {".", ".."}:
            raise ValueError("resource cannot be '.' or '..'")
        return resource

    def _lock_file(self, resource: str) -> Path:
        return self.locks_dir / f"{resource}.lock"

    def _guard_file(self, resource: str) -> Path:
        return self.locks_dir / f".{resource}.lock.guard"

    def _find_hierarchy_conflict(self, resource: str) -> Optional[str]:
        """Find a conflicting lease while the hierarchy guard is held."""

        if resource != self._GLOBAL_RESOURCE:
            if self.check_lock(self._GLOBAL_RESOURCE) is not None:
                return self._GLOBAL_RESOURCE
            return None

        # Directory enumeration and every lease recheck happen under the same
        # hierarchy guard as the eventual global.lock creation. Consequently,
        # no compliant resource acquirer can appear between this scan and create.
        for lock_file in sorted(self.locks_dir.glob("*.lock")):
            repo_resource = lock_file.name.removesuffix(".lock")
            if repo_resource == self._GLOBAL_RESOURCE:
                continue
            try:
                repo_resource = self._validate_resource(repo_resource)
            except ValueError:
                # An extant lock-shaped entry that cannot be interpreted safely
                # must block a global lease rather than be silently skipped.
                return lock_file.name
            if self.check_lock(repo_resource) is not None:
                return repo_resource
        return None

    @staticmethod
    def _path_exists_without_following(path: Path) -> bool:
        """Return whether a directory entry exists, including broken symlinks."""

        try:
            path.lstat()
        except FileNotFoundError:
            return False
        except OSError:
            # An entry whose state cannot be inspected is unsafe, not absent.
            return True
        return True

    @contextmanager
    def _resource_guard(self, resource: str):
        """Serialize ownership checks and stale reclamation for one resource."""
        with self._file_guard(self._guard_file(resource)):
            yield

    @contextmanager
    def _hierarchy_guard(self):
        """Serialize global-versus-resource acquisition decisions."""
        with self._file_guard(self.locks_dir / self._HIERARCHY_GUARD_NAME):
            yield

    @contextmanager
    def _file_guard(self, guard_file: Path):
        """Take an exclusive flock on a nofollow regular guard file."""
        flags = os.O_CREAT | os.O_RDWR
        for optional_flag in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
            if hasattr(os, optional_flag):
                flags |= getattr(os, optional_flag)
        descriptor = os.open(guard_file, flags, 0o600)
        try:
            guard_stat = os.fstat(descriptor)
            if not stat.S_ISREG(guard_stat.st_mode):
                raise OSError(f"lock guard must be a regular file: {guard_file}")
            guard = os.fdopen(descriptor, "r+", encoding="utf-8")
            descriptor = -1
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        with guard:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(guard.fileno(), fcntl.LOCK_UN)

    def _create_lock_atomic(self, lock_file: Path, lock_data: Dict[str, Any]) -> None:
        """Create a complete lock file without replacing an existing lease."""
        serialized = yaml.safe_dump(lock_data, default_flow_style=False).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        descriptor = os.open(lock_file, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as lock:
                descriptor = -1
                lock.write(serialized)
                lock.flush()
                os.fsync(lock.fileno())
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            # This process created the file and incomplete locks fail closed, so
            # no other process can have legitimately replaced it here.
            lock_file.unlink(missing_ok=True)
            raise

    def _release_owned_lock(self, resource: str, lease_token: str) -> bool:
        """Release only when the on-disk lease still matches this acquisition."""
        lock_file = self._lock_file(resource)
        try:
            with self._resource_guard(resource):
                lock_data = self._read_lock(lock_file)
                if not lock_data:
                    logger.warning(f"Tried to release non-existent lock: {resource}")
                    released = False
                elif lock_data.get("lease_token") != lease_token:
                    logger.error(
                        f"Cannot release lock {resource}: lease is owned by another acquisition"
                    )
                    released = False
                else:
                    lock_file.unlink()
                    logger.info(f"✓ Lock released: {resource}")
                    released = True
        except Exception as e:
            logger.error(f"Failed to release lock {resource}: {e}")
            return False

        with self._leases_guard:
            if self._leases.get(resource) == lease_token:
                self._leases.pop(resource, None)
        return released

    def _reclaim_expired_lock(self, resource: str) -> bool:
        """Remove an expired lock after rechecking it under a process mutex."""
        lock_file = self._lock_file(resource)
        try:
            with self._resource_guard(resource):
                current_lock = self._read_lock(lock_file)
                if not current_lock or not self._is_expired(current_lock):
                    return False
                lock_file.unlink()
                return True
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.error(f"Failed to reclaim expired lock {resource}: {e}")
            return False

    def _is_expired(self, lock_data: Dict[str, Any]) -> bool:
        """Check expiration, accepting legacy naive timestamps as UTC."""
        try:
            expires_at = datetime.fromisoformat(lock_data["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return self._utc_now() > expires_at.astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Invalid lock expiration; treating lock as active: {e}")
            return False

    def _read_lock(self, lock_file: Path) -> Optional[Dict[str, Any]]:
        """Read one bounded regular lock file without following symlinks."""

        descriptor = -1
        try:
            path_stat = lock_file.lstat()
            if not stat.S_ISREG(path_stat.st_mode):
                logger.error(f"Unsafe lock file {lock_file}: expected a regular file")
                return None

            flags = os.O_RDONLY
            for optional_flag in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
                if hasattr(os, optional_flag):
                    flags |= getattr(os, optional_flag)
            descriptor = os.open(lock_file, flags)
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISREG(opened_stat.st_mode):
                logger.error(f"Unsafe lock file {lock_file}: expected a regular file")
                return None
            if (opened_stat.st_dev, opened_stat.st_ino) != (
                path_stat.st_dev,
                path_stat.st_ino,
            ):
                logger.error(f"Lock file changed while opening it: {lock_file}")
                return None
            if opened_stat.st_size > self._MAX_LOCK_BYTES:
                logger.error(f"Lock file is too large to trust: {lock_file}")
                return None

            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                descriptor = -1
                serialized = stream.read(self._MAX_LOCK_BYTES + 1)
            if len(serialized.encode("utf-8")) > self._MAX_LOCK_BYTES:
                logger.error(f"Lock file is too large to trust: {lock_file}")
                return None
            lock_data = yaml.load(serialized, Loader=UniqueKeySafeLoader)
            if not isinstance(lock_data, dict):
                logger.error(f"Invalid lock file {lock_file}: expected a mapping")
                return None
            return lock_data
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to read lock file {lock_file}: {e}")
            return None
        finally:
            if descriptor >= 0:
                os.close(descriptor)


class StatusManager:
    """Manage status files for inter-Claude communication."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize status manager.

        Args:
            config: Configuration with status_dir, my_id
        """
        self.config = config or {}
        configured_status_dir = self.config.get("status_dir")
        self.status_dir = (
            Path(configured_status_dir)
            if configured_status_dir is not None
            else resolve_workspace_root() / "status"
        )
        self.status_dir.mkdir(parents=True, exist_ok=True)

        self.my_id = self.config.get("my_id", "orchestration_claude")

        logger.info(f"StatusManager initialized: status_dir={self.status_dir}, my_id={self.my_id}")

    def update_status(
        self,
        status: str,
        current_operation: Optional[str] = None,
        last_completed: Optional[Dict[str, Any]] = None,
        next_available_at: Optional[str] = None,
    ):
        """
        Update status file.

        Args:
            status: Status (idle, busy, waiting, error)
            current_operation: Current operation description
            last_completed: Last completed operation details
            next_available_at: ISO timestamp when available
        """
        status_file = self.status_dir / f"{self.my_id}_status.yaml"

        status_data = {
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'status': status,
            'current_operation': current_operation,
            'last_completed_operation': last_completed,
            'next_available_at': next_available_at or datetime.now(timezone.utc).isoformat(),
        }

        try:
            with open(status_file, 'w') as f:
                yaml.dump(status_data, f, default_flow_style=False)
            logger.debug(f"Status updated: {status}")
        except Exception as e:
            logger.error(f"Failed to update status: {e}")

    def get_status(self, claude_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of another Claude instance.

        Args:
            claude_id: Claude instance ID

        Returns:
            Status data or None
        """
        status_file = self.status_dir / f"{claude_id}_status.yaml"
        if not status_file.exists():
            return None

        try:
            with open(status_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to read status for {claude_id}: {e}")
            return None

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all Claude instances."""
        all_status = {}
        for status_file in self.status_dir.glob("*_status.yaml"):
            claude_id = status_file.stem.replace("_status", "")
            status_data = self.get_status(claude_id)
            if status_data:
                all_status[claude_id] = status_data
        return all_status

    def is_any_busy(self, claude_ids: List[str]) -> bool:
        """Check if any of the specified Claudes are busy."""
        for claude_id in claude_ids:
            status = self.get_status(claude_id)
            if status and status.get('status') == 'busy':
                return True
        return False


# Plugin registration for OpenClaw
def register_plugin():
    """Register the LockManager plugin with OpenClaw."""
    return {
        "name": "lock_manager",
        "version": "1.0.0",
        "class": LockManager,
        "description": "Local lock system for multi-Claude coordination",
    }
