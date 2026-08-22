#!/usr/bin/env python3
"""
Lock Checker for Claude Code Hooks

This script checks if a resource is locked before allowing Claude to proceed.
Used in pre-edit, pre-commit, and other hooks to prevent conflicts.

Exit codes:
  0 - No lock, proceed
  1 - Locked, block operation
  2 - Error
"""

import sys

from plugins.lock_manager import LockManager, resolve_workspace_root


def check_lock(resource_name: str, operation: str = "operation") -> int:
    """
    Check if a resource is currently locked.

    Args:
        resource_name: Name of resource (culturemech, mediaingredientmech, communitymech, global)
        operation: Description of operation being attempted

    Returns:
        0 if not locked (proceed)
        1 if locked (block)
        2 if error
    """
    try:
        locks_dir = resolve_workspace_root() / "locks"
        manager = LockManager({"locks_dir": str(locks_dir), "my_id": "hook-checker"})
        global_lock = manager.check_lock("global")
        if global_lock is not None:
            _print_lock("GLOBAL", global_lock, operation)
            return 1

        lock_data = manager.check_lock(resource_name)
        if lock_data is None:
            return 0

        _print_lock(resource_name.upper(), lock_data, operation)
        return 1
    except (OSError, ValueError) as e:
        print(f"❌ Error checking lock: {e}", file=sys.stderr)
        return 2


def _print_lock(resource: str, lock_data: dict, operation: str) -> None:
    """Print lock state without assuming a malformed lock has every field."""
    print(f"⚠️  {resource} IS LOCKED")
    print(f"   Locked by: {lock_data.get('locked_by', 'unknown')}")
    print(f"   Operation: {lock_data.get('operation', 'unknown')}")
    print(f"   Since: {lock_data.get('locked_at', 'unknown')}")
    print(f"   Reason: {lock_data.get('reason', 'N/A')}")
    print(f"   Expires: {lock_data.get('expires_at', 'unknown')}")
    print()
    print(f"Cannot {operation} while the coordination lock is active or unreadable.")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: check_lock.py <resource_name> [operation]", file=sys.stderr)
        print("Example: check_lock.py culturemech 'edit files'", file=sys.stderr)
        sys.exit(2)

    resource_name = sys.argv[1]
    operation = sys.argv[2] if len(sys.argv) > 2 else "operation"

    exit_code = check_lock(resource_name, operation)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
