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
import os
import yaml
from pathlib import Path
from datetime import datetime, timezone


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
    # Find workspace directory (same logic as lock_manager.py)
    workspace = os.getenv("OPENCLAW_WORKSPACE")
    if not workspace:
        # Try to find orchestration root and use its workspace
        orchestration_root = os.getenv("OPENCLAW_ORCHESTRATION_ROOT")
        if not orchestration_root:
            # Try to find it relative to this script
            script_dir = Path(__file__).parent
            orchestration_root = script_dir.parent
        workspace = str(Path(orchestration_root) / "workspace")

    locks_dir = Path(workspace) / "locks"
    lock_file = locks_dir / f"{resource_name}.lock"

    # Check global lock first
    global_lock = locks_dir / "global.lock"
    if global_lock.exists():
        try:
            with open(global_lock, 'r') as f:
                lock_data = yaml.safe_load(f)

            # Check if expired
            expires_at = datetime.fromisoformat(lock_data['expires_at'])
            if datetime.now(timezone.utc) <= expires_at:
                print(f"⚠️  GLOBAL LOCK ACTIVE")
                print(f"   Locked by: {lock_data['locked_by']}")
                print(f"   Operation: {lock_data['operation']}")
                print(f"   Since: {lock_data['locked_at']}")
                print(f"   Expires: {lock_data['expires_at']}")
                print()
                print(f"Cannot {operation} while global lock is active.")
                print("This usually means a cross-repo pipeline is running.")
                print()
                print("Options:")
                print("  1. Wait for operation to complete")
                print("  2. Ask orchestration Claude to cancel operation")
                print("  3. If stuck, remove lock file (EMERGENCY ONLY)")
                return 1
        except Exception as e:
            print(f"⚠️  Error reading global lock: {e}", file=sys.stderr)

    # Check resource-specific lock
    if not lock_file.exists():
        # No lock, proceed
        return 0

    try:
        with open(lock_file, 'r') as f:
            lock_data = yaml.safe_load(f)

        # Check if expired
        expires_at = datetime.fromisoformat(lock_data['expires_at'])
        if datetime.now(timezone.utc) > expires_at:
            # Expired, remove it
            lock_file.unlink()
            print(f"ℹ️  Removed expired lock on {resource_name}")
            return 0

        # Lock is active
        print(f"⚠️  {resource_name.upper()} IS LOCKED")
        print(f"   Locked by: {lock_data['locked_by']}")
        print(f"   Operation: {lock_data['operation']}")
        print(f"   Since: {lock_data['locked_at']}")
        print(f"   Reason: {lock_data.get('reason', 'N/A')}")
        print(f"   Expires: {lock_data['expires_at']}")
        print()
        print(f"Cannot {operation} while {resource_name} is locked.")
        print()
        print("What this means:")
        if lock_data['locked_by'] == 'orchestration_claude':
            print("  - The orchestration pipeline is working on this repo")
            print("  - Wait for the pipeline to complete")
            print("  - Check orchestration status with: openclaw-cli pipeline status")
        else:
            print(f"  - Another Claude instance ({lock_data['locked_by']}) is working")
            print("  - Wait for that operation to complete")
        print()
        print("Options:")
        print("  1. Wait for the lock to expire")
        print("  2. Check status: openclaw-cli pipeline status")
        print("  3. Ask the locking Claude to complete/cancel")
        print(f"  4. Emergency unlock: rm {lock_file} (USE WITH CAUTION)")

        return 1

    except Exception as e:
        print(f"❌ Error checking lock: {e}", file=sys.stderr)
        return 2


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
