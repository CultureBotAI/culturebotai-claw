#!/usr/bin/env python3
"""
Test Multi-Claude Coordination System

Tests the lock manager and status manager to ensure proper coordination
between multiple Claude instances.
"""

import os
import sys
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Add plugins to path
sys.path.insert(0, str(Path(__file__).parent / "plugins"))


def test_lock_acquisition():
    """Test basic lock acquisition and release."""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Lock Acquisition and Release")
    logger.info("="*60)

    try:
        from lock_manager import LockManager

        lock_mgr = LockManager(config={
            "locks_dir": os.getenv("OPENCLAW_WORKSPACE", ".") + "/locks",
            "my_id": "test_orchestration",
        })

        # Test acquire
        logger.info("Acquiring lock on 'culturemech'...")
        acquired = lock_mgr.acquire_lock("culturemech", "test_operation", timeout=60)
        if not acquired:
            logger.error("❌ Failed to acquire lock")
            return False

        logger.info("✓ Lock acquired")

        # Test check
        lock_data = lock_mgr.check_lock("culturemech")
        if not lock_data:
            logger.error("❌ Lock check failed")
            return False

        logger.info(f"✓ Lock verified: locked_by={lock_data['locked_by']}")

        # Test release
        logger.info("Releasing lock...")
        released = lock_mgr.release_lock("culturemech")
        if not released:
            logger.error("❌ Failed to release lock")
            return False

        logger.info("✓ Lock released")

        # Verify released
        lock_data = lock_mgr.check_lock("culturemech")
        if lock_data:
            logger.error("❌ Lock still exists after release")
            return False

        logger.info("✓ Lock release verified")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False


def test_lock_conflict():
    """Test that lock prevents concurrent access."""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Lock Conflict Detection")
    logger.info("="*60)

    try:
        from lock_manager import LockManager

        # Create two lock managers (simulating two Claudes)
        lock_mgr1 = LockManager(config={
            "locks_dir": os.getenv("OPENCLAW_WORKSPACE", ".") + "/locks",
            "my_id": "orchestration_claude",
        })

        lock_mgr2 = LockManager(config={
            "locks_dir": os.getenv("OPENCLAW_WORKSPACE", ".") + "/locks",
            "my_id": "mediaingredientmech_claude",
        })

        # Manager 1 acquires lock
        logger.info("Manager 1 acquiring lock...")
        acquired1 = lock_mgr1.acquire_lock("mediaingredientmech", "pipeline_operation", timeout=60)
        if not acquired1:
            logger.error("❌ Manager 1 failed to acquire lock")
            return False

        logger.info("✓ Manager 1 has lock")

        # Manager 2 tries to acquire same lock (should fail)
        logger.info("Manager 2 attempting to acquire same lock...")
        acquired2 = lock_mgr2.acquire_lock("mediaingredientmech", "manual_edit", timeout=60, wait=False)
        if acquired2:
            logger.error("❌ Manager 2 should NOT have acquired lock")
            return False

        logger.info("✓ Manager 2 correctly blocked")

        # Check lock details
        lock_data = lock_mgr2.check_lock("mediaingredientmech")
        logger.info(f"Lock held by: {lock_data['locked_by']}")
        logger.info(f"Operation: {lock_data['operation']}")

        # Manager 1 releases
        logger.info("Manager 1 releasing lock...")
        lock_mgr1.release_lock("mediaingredientmech")

        # Manager 2 can now acquire
        logger.info("Manager 2 attempting to acquire lock again...")
        acquired2 = lock_mgr2.acquire_lock("mediaingredientmech", "manual_edit", timeout=60)
        if not acquired2:
            logger.error("❌ Manager 2 failed to acquire lock after release")
            return False

        logger.info("✓ Manager 2 acquired lock after release")

        # Cleanup
        lock_mgr2.release_lock("mediaingredientmech")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False


def test_lock_expiration():
    """Test that locks auto-expire."""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Lock Expiration")
    logger.info("="*60)

    try:
        from lock_manager import LockManager

        lock_mgr = LockManager(config={
            "locks_dir": os.getenv("OPENCLAW_WORKSPACE", ".") + "/locks",
            "my_id": "test_orchestration",
        })

        # Acquire lock with short timeout
        logger.info("Acquiring lock with 3-second timeout...")
        acquired = lock_mgr.acquire_lock("communitymech", "test_operation", timeout=3)
        if not acquired:
            logger.error("❌ Failed to acquire lock")
            return False

        logger.info("✓ Lock acquired")

        # Check lock exists
        lock_data = lock_mgr.check_lock("communitymech")
        if not lock_data:
            logger.error("❌ Lock doesn't exist")
            return False

        # Wait for expiration
        logger.info("Waiting 5 seconds for expiration...")
        time.sleep(5)

        # Check lock expired
        lock_data = lock_mgr.check_lock("communitymech")
        if lock_data:
            logger.error("❌ Lock didn't expire")
            return False

        logger.info("✓ Lock expired as expected")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False


def test_context_manager():
    """Test lock context manager."""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Context Manager")
    logger.info("="*60)

    try:
        from lock_manager import LockManager

        lock_mgr = LockManager(config={
            "locks_dir": os.getenv("OPENCLAW_WORKSPACE", ".") + "/locks",
            "my_id": "test_orchestration",
        })

        logger.info("Testing context manager...")

        with lock_mgr.lock("culturemech", "test_operation", timeout=60):
            logger.info("✓ Inside context manager, lock acquired")

            # Verify lock exists
            lock_data = lock_mgr.check_lock("culturemech")
            if not lock_data:
                logger.error("❌ Lock not found inside context")
                return False

        # After context, lock should be released
        lock_data = lock_mgr.check_lock("culturemech")
        if lock_data:
            logger.error("❌ Lock not released after context")
            return False

        logger.info("✓ Lock automatically released after context")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False


def test_status_manager():
    """Test status file management."""
    logger.info("\n" + "="*60)
    logger.info("TEST 5: Status Manager")
    logger.info("="*60)

    try:
        from lock_manager import StatusManager

        status_mgr = StatusManager(config={
            "status_dir": os.getenv("OPENCLAW_WORKSPACE", ".") + "/status",
            "my_id": "orchestration_claude",
        })

        # Update status
        logger.info("Updating status to 'busy'...")
        status_mgr.update_status(
            status="busy",
            current_operation="ingredient_curation_pipeline",
            last_completed={
                "type": "test_operation",
                "result": "success",
            }
        )

        logger.info("✓ Status updated")

        # Read status
        status_data = status_mgr.get_status("orchestration_claude")
        if not status_data:
            logger.error("❌ Failed to read status")
            return False

        logger.info(f"✓ Status read: {status_data['status']}")

        # Check all status
        all_status = status_mgr.get_all_status()
        logger.info(f"✓ Found {len(all_status)} Claude instances")

        for claude_id, status in all_status.items():
            logger.info(f"  - {claude_id}: {status['status']}")

        # Update back to idle
        status_mgr.update_status(status="idle")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False


def test_global_lock():
    """Test global lock (blocks all repos)."""
    logger.info("\n" + "="*60)
    logger.info("TEST 6: Global Lock")
    logger.info("="*60)

    try:
        from lock_manager import LockManager

        lock_mgr = LockManager(config={
            "locks_dir": os.getenv("OPENCLAW_WORKSPACE", ".") + "/locks",
            "my_id": "orchestration_claude",
        })

        # Acquire global lock
        logger.info("Acquiring global lock...")
        acquired = lock_mgr.acquire_global_lock("cross_repo_pipeline")
        if not acquired:
            logger.error("❌ Failed to acquire global lock")
            return False

        logger.info("✓ Global lock acquired")

        # Check if global locked
        if not lock_mgr.is_global_locked():
            logger.error("❌ Global lock check failed")
            return False

        logger.info("✓ Global lock verified")

        # Release
        logger.info("Releasing global lock...")
        released = lock_mgr.release_global_lock()
        if not released:
            logger.error("❌ Failed to release global lock")
            return False

        logger.info("✓ Global lock released")

        # Verify released
        if lock_mgr.is_global_locked():
            logger.error("❌ Global lock still active")
            return False

        logger.info("✓ Global lock release verified")

        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False


def run_all_tests():
    """Run all coordination tests."""
    logger.info("\n" + "="*70)
    logger.info(" "*15 + "MULTI-CLAUDE COORDINATION TESTS")
    logger.info("="*70)

    # Check environment
    workspace = os.getenv("OPENCLAW_WORKSPACE")
    if not workspace:
        logger.error("❌ OPENCLAW_WORKSPACE not set")
        return 1

    logger.info(f"Workspace: {workspace}")

    # Run tests
    results = {
        "Lock Acquisition": test_lock_acquisition(),
        "Lock Conflict": test_lock_conflict(),
        "Lock Expiration": test_lock_expiration(),
        "Context Manager": test_context_manager(),
        "Status Manager": test_status_manager(),
        "Global Lock": test_global_lock(),
    }

    # Summary
    logger.info("\n" + "="*70)
    logger.info(" "*20 + "TEST SUMMARY")
    logger.info("="*70)

    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{test_name:30} {status}")

    passed = sum(1 for r in results.values() if r)
    failed = sum(1 for r in results.values() if not r)

    logger.info("\n" + "="*70)
    logger.info(f"Total: {passed} passed, {failed} failed")
    logger.info("="*70)

    if failed == 0:
        logger.info("\n🎉 ALL COORDINATION TESTS PASSED!")
        logger.info("Multi-Claude coordination system is ready for production.")
        return 0
    else:
        logger.info(f"\n⚠️  {failed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
