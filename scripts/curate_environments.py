#!/usr/bin/env python3
"""
Environment Curation CLI

Command-line interface for citation-backed environment curation.

Usage:
    # Run pilot batch (20 media, Tier 1, dry-run)
    python curate_environments.py --batch-size 20 --tier 1 --dry-run

    # Run production batch (100 media, Tier 1, save changes)
    python curate_environments.py --batch-size 100 --tier 1

    # Review manual queue
    python curate_environments.py --review workspace/review/pending_20260322_100000.yaml

    # Prioritize candidates (identify Tier 1 media)
    python curate_environments.py --prioritize --tier 1 --limit 100
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any
import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.environment_curation_pipeline import EnvironmentCurationPipeline
from plugins.environment_curator import MediaPrioritizer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_media_records(culturemech_root: Path, media_ids: List[str] = None) -> List[Dict[str, Any]]:
    """
    Load media records from CultureMech.

    Args:
        culturemech_root: Path to CultureMech repository
        media_ids: Optional list of specific media IDs to load

    Returns:
        List of media record dictionaries
    """
    media_records = []
    data_dir = culturemech_root / "data"

    if not data_dir.exists():
        logger.error(f"CultureMech data directory not found: {data_dir}")
        return []

    # Load all YAML files in data/
    for yaml_file in data_dir.rglob("*.yaml"):
        try:
            with open(yaml_file) as f:
                media = yaml.safe_load(f)

            if not media:
                continue

            # Filter by media_ids if specified
            if media_ids and media.get("id") not in media_ids:
                continue

            media_records.append(media)

        except Exception as e:
            logger.warning(f"Failed to load {yaml_file}: {e}")

    logger.info(f"Loaded {len(media_records)} media records from {data_dir}")
    return media_records


def run_curation(args):
    """Run environment curation pipeline."""
    # Validate CultureMech root
    culturemech_root = Path(args.culturemech_root)
    if not culturemech_root.exists():
        logger.error(f"CultureMech root not found: {culturemech_root}")
        sys.exit(1)

    # Load media records
    logger.info("Loading media records...")
    media_records = load_media_records(culturemech_root, media_ids=args.media_ids)

    if not media_records:
        logger.error("No media records found")
        sys.exit(1)

    # Initialize pipeline
    logger.info("Initializing pipeline...")
    pipeline = EnvironmentCurationPipeline(config={
        "batch_size": args.batch_size,
        "auto_accept_threshold": args.threshold,
        "manual_review_threshold": 0.70,
        "max_cost_per_run": 100.00
    })

    # Run curation
    logger.info(f"Starting curation: batch_size={args.batch_size}, tier={args.tier}, "
               f"dry_run={args.dry_run}")

    results = pipeline.run(
        media_records=media_records,
        batch_size=args.batch_size,
        tier=args.tier,
        auto_accept_threshold=args.threshold,
        dry_run=args.dry_run,
        require_citations=not args.allow_inferred
    )

    # Display results
    print("\n" + "="*80)
    print("ENVIRONMENT CURATION RESULTS")
    print("="*80)
    print(f"Total suggestions: {results['metrics']['total_suggestions']}")
    print(f"Auto-accepted: {results['metrics']['auto_accepted']} "
          f"({results['metrics']['auto_accept_rate']:.1%})")
    print(f"Manual review: {results['metrics']['manual_review']}")
    print(f"Rejected: {results['metrics']['rejected']}")
    print(f"PMID discovery rate: {results['metrics']['pmid_discovery_rate']:.1%}")
    print(f"Duration: {results.get('duration_seconds', 0):.1f}s")
    print("="*80)

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes saved")

    if results['metrics']['manual_review'] > 0:
        print(f"\n📋 {results['metrics']['manual_review']} suggestions queued for manual review")
        print(f"   Review with: python curate_environments.py --review <review_file>")

    return 0 if results['metrics']['rejected'] == 0 else 1


def run_review(args):
    """Review manual queue."""
    review_file = Path(args.review)

    if not review_file.exists():
        logger.error(f"Review file not found: {review_file}")
        sys.exit(1)

    # Load review queue
    with open(review_file) as f:
        pending = yaml.safe_load(f)

    print(f"\n{'='*80}")
    print(f"MANUAL REVIEW QUEUE: {len(pending)} suggestions")
    print("="*80)

    for i, item in enumerate(pending, 1):
        print(f"\n[{i}/{len(pending)}] {item['media_name']} ({item['media_id']})")
        print(f"  Environment: {item['suggestion']['environment']['preferred_term']} "
              f"({item['suggestion']['environment']['envo_id']})")
        print(f"  Confidence: {item['suggestion']['environment']['confidence']:.2f}")
        print(f"  Citation: {item['suggestion']['evidence']['reference']}")
        print(f"  Evidence Quality: {item['scores']['evidence_quality']:.2f}")
        print(f"  Reasoning: {item['suggestion']['reasoning'][:100]}...")

        # Prompt for decision
        decision = input("\n  Decision [A]ccept / [R]eject / [S]kip / [Q]uit: ").strip().upper()

        if decision == 'Q':
            break
        elif decision == 'A':
            item['decision'] = 'ACCEPTED'
            print("  ✓ Accepted")
        elif decision == 'R':
            item['decision'] = 'REJECTED'
            notes = input("  Rejection reason: ").strip()
            item['reviewer_notes'] = notes
            print("  ✗ Rejected")
        else:
            item['decision'] = 'PENDING'
            print("  → Skipped")

    # Save updated review file
    with open(review_file, 'w') as f:
        yaml.dump(pending, f, default_flow_style=False, sort_keys=False)

    print(f"\n✓ Review file updated: {review_file}")

    # Summary
    accepted = sum(1 for item in pending if item['decision'] == 'ACCEPTED')
    rejected = sum(1 for item in pending if item['decision'] == 'REJECTED')
    still_pending = sum(1 for item in pending if item['decision'] == 'PENDING')

    print(f"\nSummary: {accepted} accepted, {rejected} rejected, {still_pending} still pending")

    return 0


def run_prioritize(args):
    """Prioritize candidates for curation."""
    culturemech_root = Path(args.culturemech_root)
    if not culturemech_root.exists():
        logger.error(f"CultureMech root not found: {culturemech_root}")
        sys.exit(1)

    # Load all media
    logger.info("Loading all media records...")
    media_records = load_media_records(culturemech_root)

    if not media_records:
        logger.error("No media records found")
        sys.exit(1)

    # Score and prioritize
    logger.info(f"Scoring {len(media_records)} media records...")
    scored_media = []

    for media in media_records:
        score = MediaPrioritizer.score_media(media)
        tier = MediaPrioritizer.identify_tier(score)
        scored_media.append({
            "media": media,
            "score": score,
            "tier": tier
        })

    # Filter by tier
    if args.tier:
        candidates = [item for item in scored_media if item["tier"] == args.tier]
    else:
        candidates = scored_media

    # Sort by score
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Take top N
    top_candidates = candidates[:args.limit]

    # Display results
    print(f"\n{'='*80}")
    print(f"TOP {len(top_candidates)} CANDIDATES (Tier {args.tier or 'All'})")
    print("="*80)

    for i, item in enumerate(top_candidates, 1):
        media = item["media"]
        print(f"{i:3d}. [{item['tier']}] {media.get('name', 'Unknown'):50s} "
              f"Score: {item['score']:.2f}  ID: {media.get('id', 'N/A')}")

    # Save to file if requested
    if args.output:
        output_file = Path(args.output)
        media_ids = [item["media"].get("id") for item in top_candidates]

        with open(output_file, 'w') as f:
            yaml.dump({"media_ids": media_ids}, f)

        print(f"\n✓ Saved media IDs to {output_file}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Citation-backed environment curation for CultureMech",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Common arguments
    parser.add_argument(
        "--culturemech-root",
        type=str,
        default="/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech",
        help="Path to CultureMech repository"
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Curate command (default)
    curate_parser = subparsers.add_parser("curate", help="Run environment curation")
    curate_parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of media to curate (default: 20)"
    )
    curate_parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3],
        help="Target tier (1=high-confidence, 2=medium, 3=long-tail)"
    )
    curate_parser.add_argument(
        "--threshold",
        type=float,
        default=0.90,
        help="Auto-accept threshold (default: 0.90)"
    )
    curate_parser.add_argument(
        "--media-ids",
        nargs="+",
        help="Specific media IDs to curate"
    )
    curate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save changes"
    )
    curate_parser.add_argument(
        "--allow-inferred",
        action="store_true",
        help="Allow auto-accept for INFERRED citations (not recommended)"
    )

    # Review command
    review_parser = subparsers.add_parser("review", help="Review manual queue")
    review_parser.add_argument(
        "review",
        type=str,
        help="Path to review file"
    )

    # Prioritize command
    prioritize_parser = subparsers.add_parser("prioritize", help="Prioritize candidates")
    prioritize_parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3],
        help="Target tier"
    )
    prioritize_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum candidates to return (default: 100)"
    )
    prioritize_parser.add_argument(
        "--output",
        type=str,
        help="Save media IDs to file"
    )

    args = parser.parse_args()

    # Default to curate if no command specified
    if not args.command:
        args.command = "curate"
        args.batch_size = 20
        args.tier = None
        args.threshold = 0.90
        args.media_ids = None
        args.dry_run = True
        args.allow_inferred = False

    # Run command
    if args.command == "curate":
        return run_curation(args)
    elif args.command == "review":
        return run_review(args)
    elif args.command == "prioritize":
        return run_prioritize(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
