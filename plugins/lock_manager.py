"""
Lock Manager Plugin for Multi-Claude Coordination

Prevents conflicts between Orchestration Claude and downstream Claudes
by implementing a distributed file-based lock system.
"""

import os
import time
import yaml
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class LockManager:
    """Distributed lock manager for multi-Claude coordination."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize lock manager.

        Args:
            config: Configuration with locks_dir, my_id, default_timeout
        """
        self.config = config or {}
        self.locks_dir = Path(self.config.get("locks_dir",
                                               os.getenv("OPENCLAW_WORKSPACE", ".") + "/locks"))
        self.locks_dir.mkdir(parents=True, exist_ok=True)

        self.my_id = self.config.get("my_id", "orchestration_claude")
        self.default_timeout = self.config.get("default_timeout", 3600)  # 1 hour

        logger.info(f"LockManager initialized: locks_dir={self.locks_dir}, my_id={self.my_id}")

    def acquire_lock(
        self,
        resource: str,
        operation: str,
        timeout: Optional[int] = None,
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
        timeout = timeout or self.default_timeout
        lock_file = self.locks_dir / f"{resource}.lock"
        start_time = time.time()

        logger.info(f"Attempting to acquire lock: {resource} for operation: {operation}")

        while True:
            # Check existing lock
            existing_lock = self._read_lock(lock_file)
            if existing_lock:
                # Check if expired
                expires_at = datetime.fromisoformat(existing_lock['expires_at'])
                if datetime.utcnow() > expires_at:
                    # Expired, remove it
                    logger.info(f"Lock {resource} expired, removing")
                    lock_file.unlink()
                else:
                    # Still valid
                    logger.debug(f"Lock {resource} held by {existing_lock['locked_by']}")

                    if not wait:
                        logger.warning(f"Failed to acquire lock {resource}: already locked")
                        return False

                    # Wait and retry
                    elapsed = time.time() - start_time
                    if elapsed > max_wait:
                        logger.error(f"Timeout waiting for lock {resource} after {elapsed:.1f}s")
                        return False

                    logger.debug(f"Waiting for lock {resource} ({elapsed:.1f}s elapsed)")
                    time.sleep(5)
                    continue

            # Create lock
            lock_data = {
                'locked_by': self.my_id,
                'locked_at': datetime.utcnow().isoformat(),
                'operation': operation,
                'pid': os.getpid(),
                'expires_at': (datetime.utcnow() + timedelta(seconds=timeout)).isoformat(),
                'reason': operation,
            }

            try:
                with open(lock_file, 'w') as f:
                    yaml.dump(lock_data, f, default_flow_style=False)

                logger.info(f"✓ Lock acquired: {resource} (expires in {timeout}s)")
                return True

            except Exception as e:
                logger.error(f"Failed to write lock file {lock_file}: {e}")
                return False

    def release_lock(self, resource: str) -> bool:
        """
        Release a lock.

        Args:
            resource: Resource name

        Returns:
            True if lock released, False if lock didn't exist or not owned by us
        """
        lock_file = self.locks_dir / f"{resource}.lock"

        if not lock_file.exists():
            logger.warning(f"Tried to release non-existent lock: {resource}")
            return False

        # Check if we own the lock
        lock_data = self._read_lock(lock_file)
        if lock_data and lock_data.get('locked_by') != self.my_id:
            logger.error(f"Cannot release lock {resource}: owned by {lock_data['locked_by']}")
            return False

        try:
            lock_file.unlink()
            logger.info(f"✓ Lock released: {resource}")
            return True
        except Exception as e:
            logger.error(f"Failed to release lock {resource}: {e}")
            return False

    def check_lock(self, resource: str) -> Optional[Dict[str, Any]]:
        """
        Check if resource is locked.

        Args:
            resource: Resource name

        Returns:
            Lock data if locked, None if available
        """
        lock_file = self.locks_dir / f"{resource}.lock"
        if not lock_file.exists():
            return None

        lock_data = self._read_lock(lock_file)
        if not lock_data:
            return None

        # Check expiration
        expires_at = datetime.fromisoformat(lock_data['expires_at'])
        if datetime.utcnow() > expires_at:
            logger.info(f"Lock {resource} expired, removing")
            lock_file.unlink()
            return None

        return lock_data

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
        timeout: Optional[int] = None,
        wait: bool = False,
    ) -> bool:
        """
        Acquire global lock (blocks all downstream repos).

        Args:
            operation: Description of operation
            timeout: Lock expiration time
            wait: If True, wait for lock

        Returns:
            True if acquired
        """
        return self.acquire_lock("global", operation, timeout, wait)

    def release_global_lock(self) -> bool:
        """Release global lock."""
        return self.release_lock("global")

    def is_global_locked(self) -> bool:
        """Check if global lock is active."""
        return self.check_lock("global") is not None

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
    def lock(self, resource: str, operation: str, timeout: Optional[int] = None):
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

        try:
            yield
        finally:
            self.release_lock(resource)

    def _read_lock(self, lock_file: Path) -> Optional[Dict[str, Any]]:
        """Read lock file safely."""
        if not lock_file.exists():
            return None

        try:
            with open(lock_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to read lock file {lock_file}: {e}")
            return None


class StatusManager:
    """Manage status files for inter-Claude communication."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize status manager.

        Args:
            config: Configuration with status_dir, my_id
        """
        self.config = config or {}
        self.status_dir = Path(self.config.get("status_dir",
                                                os.getenv("OPENCLAW_WORKSPACE", ".") + "/status"))
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
            'last_updated': datetime.utcnow().isoformat(),
            'status': status,
            'current_operation': current_operation,
            'last_completed_operation': last_completed,
            'next_available_at': next_available_at or datetime.utcnow().isoformat(),
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
        "description": "Distributed lock system for multi-Claude coordination",
    }
