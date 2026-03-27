#!/usr/bin/env python3
"""
Simple runner for the Unified Ingredient Mapping Pipeline.

Usage:
    python run_ingredient_mapping.py --batch-size 50 --threshold 0.85 --min-occurrences 10
    python run_ingredient_mapping.py --batch-size 5 --dry-run  # Test run
"""

import sys
import logging
from pathlib import Path
from dotenv import load_dotenv
import click

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment
load_dotenv()

# Import pipeline
from pipelines.unified_ingredient_mapping_pipeline import UnifiedIngredientMappingPipeline

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


@click.command()
@click.option('--batch-size', type=int, default=20, help='Number of ingredients to process (1-100)')
@click.option('--threshold', type=float, default=0.90, help='Confidence threshold for auto-acceptance (0.7-1.0)')
@click.option('--min-occurrences', type=int, default=2, help='Only process ingredients with >= N occurrences')
@click.option('--dry-run', is_flag=True, default=True, help='Preview mode - don\'t save changes')
@click.option('--production', is_flag=True, help='Run in production mode (saves changes)')
def main(batch_size, threshold, min_occurrences, dry_run, production):
    """
    Run the unified ingredient mapping pipeline.

    Examples:

        # Test with 5 ingredients (dry-run)
        python run_ingredient_mapping.py --batch-size 5

        # Production run with 50 ingredients
        python run_ingredient_mapping.py --batch-size 50 --threshold 0.85 --min-occurrences 10 --production
    """
    # If --production flag is set, disable dry-run
    if production:
        dry_run = False

    logger.info("=== Unified Ingredient Mapping Pipeline ===")
    logger.info(f"Batch size: {batch_size}")
    logger.info(f"Threshold: {threshold}")
    logger.info(f"Min occurrences: {min_occurrences}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")

    if not dry_run:
        click.confirm('⚠️  Running in PRODUCTION mode - changes will be saved. Continue?', abort=True)

    try:
        # Initialize pipeline
        pipeline = UnifiedIngredientMappingPipeline()

        # Run pipeline
        report = pipeline.run(
            batch_size=batch_size,
            auto_accept_threshold=threshold,
            dry_run=dry_run,
            min_occurrences=min_occurrences
        )

        # Print summary
        print("\n" + "="*60)
        print("PIPELINE SUMMARY")
        print("="*60)
        print(f"Auto-accepted:  {report['summary']['auto_accepted']}")
        print(f"Manual review:  {report['summary']['manual_review']}")
        print(f"Rejected:       {report['summary']['rejected']}")
        print(f"Duration:       {report['duration_seconds']:.1f}s")
        print(f"Success:        {report['summary']['success']}")

        if report['errors']:
            print(f"\n⚠️  Errors: {len(report['errors'])}")
            for error in report['errors']:
                print(f"  - {error}")

        print("="*60)

        sys.exit(0 if report['summary']['success'] else 1)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
