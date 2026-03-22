#!/usr/bin/env python3
"""
Phase 2 Pilot Test Runner - Orchestration-Only Mode

Tests the multi-Claude coordination system by:
1. Acquiring a lock for MediaIngredientMech
2. Running ingredient curation via existing tools
3. Releasing the lock
4. Generating a report

This tests orchestration coordination without requiring full OpenClaw SDK.
"""

import os
import sys
import subprocess
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


def run_pilot_test(
    batch_size: int = 11,
    auto_accept_threshold: float = 0.9,
    dry_run: bool = True,
    min_occurrences: int = 1,
):
    """
    Run Phase 2 pilot test in orchestration-only mode.

    Args:
        batch_size: Number of ingredients to process
        auto_accept_threshold: Confidence threshold for auto-acceptance
        dry_run: If True, don't save changes
        min_occurrences: Only process ingredients with >= this many occurrences
    """
    logger.info("=" * 70)
    logger.info("Phase 2 Pilot Test - Orchestration-Only Mode")
    logger.info("=" * 70)
    logger.info(f"Batch size: {batch_size}")
    logger.info(f"Auto-accept threshold: {auto_accept_threshold}")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"Min occurrences: {min_occurrences}")
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
    result = {"status": "unknown"}  # Initialize result

    try:
        logger.info("Step 1: Acquiring lock for MediaIngredientMech")
        logger.info("-" * 70)

        # Acquire lock
        acquired = lock_mgr.acquire_lock(
            resource="mediaingredientmech",
            operation=f"ingredient_curation_pilot: {batch_size} ingredients from KM2 medium",
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
            current_operation="ingredient_curation_pilot",
        )

        logger.info("Step 2: Running ingredient curation")
        logger.info("-" * 70)
        logger.info(f"Mode: Orchestration-only (delegating to MediaIngredientMech)")
        logger.info(f"Target: {mediaingredient_root}")
        logger.info("")

        if dry_run:
            logger.info("DRY RUN: Simulating curation process")
            logger.info("  • Would process up to {} unmapped ingredients".format(batch_size))
            logger.info("  • Would use existing LLMCurator with Claude Sonnet 4")
            logger.info("  • Would validate with OntologyClient (CHEBI, FOODON, ENVO, etc.)")
            logger.info("  • Would auto-accept mappings with confidence >= {}".format(auto_accept_threshold))
            logger.info("")

            # In dry-run, just check what's available
            unmapped_file = Path(mediaingredient_root) / "data" / "curated" / "unmapped_ingredients.yaml"
            if unmapped_file.exists():
                logger.info(f"✓ Found unmapped ingredients file: {unmapped_file}")

                # Try to count records
                try:
                    with open(unmapped_file, 'r') as f:
                        data = yaml.safe_load(f)
                        if data and 'ingredients' in data:
                            total_unmapped = len(data['ingredients'])
                            logger.info(f"  Total unmapped ingredients: {total_unmapped}")
                            logger.info(f"  Would process: min({batch_size}, {total_unmapped}) = {min(batch_size, total_unmapped)}")
                except Exception as e:
                    logger.warning(f"  Could not parse file: {e}")
            else:
                logger.warning(f"✗ Unmapped ingredients file not found: {unmapped_file}")

            result = {
                "status": "dry_run_success",
                "batch_size": batch_size,
                "dry_run": True,
            }
        else:
            logger.info("LIVE RUN: Executing actual curation")
            logger.info("")

            # Run the batch curation script
            cmd = [
                "python", "scripts/batch_curate.py",
                "--batch-size", str(batch_size),
                "--auto-accept-threshold", str(auto_accept_threshold),
                "--min-occurrences", str(min_occurrences),
            ]
            logger.info(f"Executing: {' '.join(cmd)}")
            logger.info(f"Working directory: {mediaingredient_root}")
            logger.info("")

            try:
                result_proc = subprocess.run(
                    cmd,
                    cwd=mediaingredient_root,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout
                )

                logger.info("Output:")
                logger.info(result_proc.stdout)

                if result_proc.stderr:
                    logger.warning("Errors:")
                    logger.warning(result_proc.stderr)

                if result_proc.returncode == 0:
                    result = {
                        "status": "success",
                        "batch_size": batch_size,
                        "dry_run": False,
                        "exit_code": 0,
                    }
                    logger.info("✓ Curation completed successfully")
                else:
                    result = {
                        "status": "failed",
                        "batch_size": batch_size,
                        "dry_run": False,
                        "exit_code": result_proc.returncode,
                    }
                    logger.error(f"✗ Curation failed with exit code {result_proc.returncode}")

            except subprocess.TimeoutExpired:
                logger.error("✗ Curation timed out after 10 minutes")
                result = {
                    "status": "timeout",
                    "batch_size": batch_size,
                    "dry_run": False,
                }
            except Exception as e:
                logger.error(f"✗ Curation failed: {e}")
                result = {
                    "status": "error",
                    "batch_size": batch_size,
                    "dry_run": False,
                    "error": str(e),
                }

        logger.info("")
        logger.info("Step 3: Releasing lock")
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
                "type": "ingredient_curation_pilot",
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

    # Generate report
    report = {
        "pilot_test": "phase_2_orchestration_only",
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

    report_file = reports_dir / f"pilot_test_{start_time.strftime('%Y%m%d_%H%M%S')}.yaml"
    with open(report_file, 'w') as f:
        yaml.dump(report, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Report saved to: {report_file}")
    logger.info("")

    return 0 if result.get("status") in ["dry_run_success", "success"] else 1


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 2 Pilot Test - Orchestration-Only Mode",
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

    args = parser.parse_args()

    return run_pilot_test(
        batch_size=args.batch_size,
        auto_accept_threshold=args.auto_accept_threshold,
        dry_run=args.dry_run,
        min_occurrences=args.min_occurrences,
    )


if __name__ == "__main__":
    sys.exit(main())
