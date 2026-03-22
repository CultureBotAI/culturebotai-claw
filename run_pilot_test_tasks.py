#!/usr/bin/env python3
"""
Phase 2 Pilot Test Runner - Multi-Claude Task-Based Coordination

Creates tasks for downstream Claude Code sessions instead of calling APIs directly.
Each Claude Code session has built-in Claude access - no API keys needed!
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from plugins.lock_manager import LockManager, StatusManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_curation_task(
    workspace: Path,
    batch_size: int,
    auto_accept_threshold: float,
    min_occurrences: int,
    dry_run: bool = False,
) -> str:
    """
    Create a curation task for MediaIngredientMech Claude to process.

    Args:
        workspace: Workspace directory path
        batch_size: Number of ingredients to process
        auto_accept_threshold: Confidence threshold for auto-acceptance
        min_occurrences: Minimum occurrences filter
        dry_run: If True, task is marked as dry-run

    Returns:
        Task ID
    """
    task_id = f"curation_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    task = {
        'task_id': task_id,
        'target_repo': 'mediaingredientmech',
        'operation': 'batch_curate',
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'started_at': None,
        'completed_at': None,
        'parameters': {
            'batch_size': batch_size,
            'auto_accept_threshold': auto_accept_threshold,
            'min_occurrences': min_occurrences,
            'dry_run': dry_run,
        },
        'assigned_to': 'mediaingredientmech_claude',
        'result_file': None,
        'error': None,
        'instructions': (
            f"Process {batch_size} unmapped ingredients with:\n"
            f"- Auto-accept threshold: {auto_accept_threshold}\n"
            f"- Min occurrences: {min_occurrences}\n"
            f"- Dry run: {dry_run}\n\n"
            "Use your built-in Claude capabilities to suggest ontology mappings.\n"
            "Save results to workspace/results/ when complete."
        ),
    }

    # Ensure tasks directory exists
    tasks_dir = workspace / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)

    # Write task file
    task_file = tasks_dir / f'{task_id}.yaml'
    with open(task_file, 'w') as f:
        yaml.dump(task, f, default_flow_style=False, sort_keys=False)

    logger.info(f"✓ Created task: {task_id}")
    logger.info(f"  Task file: {task_file}")

    return task_id


def update_task_status(
    workspace: Path,
    task_id: str,
    status: str,
    **updates
):
    """Update task status."""
    task_file = workspace / 'tasks' / f'{task_id}.yaml'

    if not task_file.exists():
        logger.error(f"Task file not found: {task_file}")
        return

    with open(task_file, 'r') as f:
        task = yaml.safe_load(f)

    task['status'] = status
    for key, value in updates.items():
        task[key] = value

    with open(task_file, 'w') as f:
        yaml.dump(task, f, default_flow_style=False, sort_keys=False)


def wait_for_task_completion(
    workspace: Path,
    task_id: str,
    timeout: int = 1800,  # 30 minutes default
    poll_interval: int = 5,
) -> dict:
    """
    Wait for a task to complete and return results.

    Args:
        workspace: Workspace directory path
        task_id: Task ID to wait for
        timeout: Maximum wait time in seconds
        poll_interval: How often to check for completion

    Returns:
        Task results dictionary

    Raises:
        TimeoutError: If task doesn't complete within timeout
    """
    task_file = workspace / 'tasks' / f'{task_id}.yaml'
    result_file = workspace / 'results' / f'{task_id}.yaml'

    start_time = time.time()
    last_status = None

    logger.info(f"⏳ Waiting for task completion: {task_id}")
    logger.info(f"   Timeout: {timeout}s, checking every {poll_interval}s")
    logger.info("")

    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)

        # Check task status
        if task_file.exists():
            with open(task_file, 'r') as f:
                task = yaml.safe_load(f)

            status = task.get('status', 'pending')

            # Log status changes
            if status != last_status:
                logger.info(f"  Status: {status} ({elapsed}s elapsed)")
                last_status = status

            # Check if completed
            if status == 'complete':
                logger.info(f"✓ Task complete! ({elapsed}s elapsed)")
                logger.info("")

                # Read results
                if result_file.exists():
                    with open(result_file, 'r') as f:
                        return yaml.safe_load(f)
                else:
                    logger.warning("  ⚠ No result file found")
                    return {'status': 'complete', 'results': None}

            elif status == 'failed':
                logger.error(f"✗ Task failed! ({elapsed}s elapsed)")
                error = task.get('error', 'Unknown error')
                logger.error(f"  Error: {error}")
                return {'status': 'failed', 'error': error}

        time.sleep(poll_interval)

    # Timeout
    elapsed = int(time.time() - start_time)
    raise TimeoutError(
        f"Task {task_id} did not complete within {timeout}s (elapsed: {elapsed}s)"
    )


def run_pilot_test(
    batch_size: int = 11,
    auto_accept_threshold: float = 0.9,
    dry_run: bool = True,
    min_occurrences: int = 1,
    timeout: int = 1800,
):
    """
    Run Phase 2 pilot test using multi-Claude task-based coordination.

    Args:
        batch_size: Number of ingredients to process
        auto_accept_threshold: Confidence threshold for auto-acceptance
        dry_run: If True, don't save changes
        min_occurrences: Only process ingredients with >= this many occurrences
        timeout: Maximum wait time for task completion
    """
    logger.info("=" * 70)
    logger.info("Phase 2 Pilot Test - Multi-Claude Task-Based Coordination")
    logger.info("=" * 70)
    logger.info(f"Batch size: {batch_size}")
    logger.info(f"Auto-accept threshold: {auto_accept_threshold}")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"Min occurrences: {min_occurrences}")
    logger.info(f"Mode: Multi-Claude (no API key needed!)")
    logger.info("")

    # Load environment
    mediaingredient_root = os.getenv("MEDIAINGREDIENTMECH_ROOT")
    if not mediaingredient_root:
        logger.error("MEDIAINGREDIENTMECH_ROOT not set")
        return 1

    workspace = Path(os.getenv("OPENCLAW_WORKSPACE", "."))

    # Initialize coordination system
    lock_mgr = LockManager()
    status_mgr = StatusManager()

    start_time = datetime.now()
    result = {"status": "unknown"}

    try:
        logger.info("Step 1: Acquiring lock for MediaIngredientMech")
        logger.info("-" * 70)

        # Acquire lock
        acquired = lock_mgr.acquire_lock(
            resource="mediaingredientmech",
            operation=f"ingredient_curation_task: {batch_size} ingredients",
            timeout=3600  # 1 hour
        )

        if not acquired:
            logger.error("Failed to acquire lock - MediaIngredientMech may be locked by another process")
            return 1

        logger.info("✓ Lock acquired successfully")
        logger.info("")

        # Update status
        status_mgr.update_status(
            status="busy",
            current_operation="ingredient_curation_task",
        )

        logger.info("Step 2: Creating curation task")
        logger.info("-" * 70)

        # Create task
        task_id = create_curation_task(
            workspace=workspace,
            batch_size=batch_size,
            auto_accept_threshold=auto_accept_threshold,
            min_occurrences=min_occurrences,
            dry_run=dry_run,
        )

        logger.info("")
        logger.info("📋 Task created for MediaIngredientMech Claude")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Open MediaIngredientMech in a separate Claude Code session")
        logger.info("  2. Ask that Claude: 'Process the pending task in ../culturebotai-claw/workspace/tasks/'")
        logger.info("  3. That Claude will process ingredients using its built-in Claude access")
        logger.info("  4. This orchestration Claude will detect completion and show results")
        logger.info("")
        logger.info(f"Task file: workspace/tasks/{task_id}.yaml")
        logger.info("")

        logger.info("Step 3: Waiting for task completion")
        logger.info("-" * 70)

        if dry_run:
            logger.info("DRY RUN: Simulating task completion after 5 seconds...")
            time.sleep(5)

            # Simulate completion
            update_task_status(workspace, task_id, 'complete', completed_at=datetime.utcnow().isoformat() + 'Z')

            # Create dummy result
            results_dir = workspace / 'results'
            results_dir.mkdir(parents=True, exist_ok=True)

            dummy_result = {
                'task_id': task_id,
                'status': 'complete',
                'started_at': start_time.isoformat(),
                'completed_at': datetime.now().isoformat(),
                'duration_seconds': 5,
                'results': {
                    'processed': batch_size,
                    'auto_accepted': 0,
                    'skipped_low_confidence': 0,
                    'skipped_no_suggestion': 0,
                    'failed': 0,
                    'note': 'Dry run - no actual processing performed',
                },
            }

            result_file = results_dir / f'{task_id}.yaml'
            with open(result_file, 'w') as f:
                yaml.dump(dummy_result, f, default_flow_style=False, sort_keys=False)

            result = dummy_result
            logger.info("✓ Dry run complete (simulated)")
        else:
            # Wait for actual completion
            try:
                result = wait_for_task_completion(
                    workspace=workspace,
                    task_id=task_id,
                    timeout=timeout,
                    poll_interval=10,
                )
            except TimeoutError as e:
                logger.error(str(e))
                logger.error("")
                logger.error("The task is still pending. Possible reasons:")
                logger.error("  1. MediaIngredientMech Claude hasn't been asked to process the task yet")
                logger.error("  2. The task is taking longer than expected")
                logger.error("  3. MediaIngredientMech Claude encountered an error")
                logger.error("")
                logger.error("You can:")
                logger.error("  1. Check the task file: workspace/tasks/")
                logger.error("  2. Manually ask MediaIngredientMech Claude to process it")
                logger.error("  3. Extend the timeout and try again")
                result = {'status': 'timeout'}

        logger.info("")
        logger.info("Step 4: Releasing lock")
        logger.info("-" * 70)

    finally:
        # Always release lock
        if lock_mgr.check_lock("mediaingredientmech"):
            lock_mgr.release_lock("mediaingredientmech")
            logger.info("✓ Lock released")

        # Update status
        status_mgr.update_status(
            status="idle",
            last_completed={
                "type": "ingredient_curation_task",
                "timestamp": datetime.utcnow().isoformat(),
                "result": result.get("status", "unknown"),
            }
        )

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("")
    logger.info("=" * 70)
    logger.info("Pilot Test Complete")
    logger.info("=" * 70)
    logger.info(f"Status: {result.get('status', 'unknown')}")
    logger.info(f"Duration: {duration:.1f} seconds")
    logger.info(f"Dry run: {dry_run}")

    if result.get('status') == 'complete' and 'results' in result:
        res = result['results']
        if res:
            logger.info("")
            logger.info("Results:")
            logger.info(f"  Processed: {res.get('processed', 0)}")
            logger.info(f"  Auto-accepted: {res.get('auto_accepted', 0)}")
            logger.info(f"  Skipped (low confidence): {res.get('skipped_low_confidence', 0)}")
            logger.info(f"  Skipped (no suggestion): {res.get('skipped_no_suggestion', 0)}")
            logger.info(f"  Failed: {res.get('failed', 0)}")

    # Generate report
    report = {
        "pilot_test": "phase_2_multi_claude_task_based",
        "timestamp": start_time.isoformat(),
        "parameters": {
            "batch_size": batch_size,
            "auto_accept_threshold": auto_accept_threshold,
            "dry_run": dry_run,
            "min_occurrences": min_occurrences,
        },
        "result": result,
        "duration_seconds": duration,
    }

    # Save report
    reports_dir = workspace / "reports" / "pilot_tests"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_file = reports_dir / f"pilot_test_tasks_{start_time.strftime('%Y%m%d_%H%M%S')}.yaml"
    with open(report_file, 'w') as f:
        yaml.dump(report, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Report saved to: {report_file}")
    logger.info("")

    return 0 if result.get("status") in ["complete", "dry_run_success"] else 1


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 2 Pilot Test - Multi-Claude Task-Based Coordination",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=11,
        help="Number of ingredients to process (default: 11)",
    )
    parser.add_argument(
        "--auto-accept-threshold",
        type=float,
        default=0.9,
        help="Confidence threshold for auto-acceptance (default: 0.9)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without making changes",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=1,
        help="Only process ingredients with >= this many occurrences (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Maximum wait time for task completion in seconds (default: 1800)",
    )

    args = parser.parse_args()

    return run_pilot_test(
        batch_size=args.batch_size,
        auto_accept_threshold=args.auto_accept_threshold,
        dry_run=args.dry_run,
        min_occurrences=args.min_occurrences,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
