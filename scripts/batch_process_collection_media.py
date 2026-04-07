#!/usr/bin/env python3
"""Master orchestrator for collection media curation pipeline.

Coordinates all 5 pipeline stages with checkpoint/resume, multi-Claude coordination,
cost tracking, and error recovery:
  1. FETCH: Retrieve specifications from JCM/CCAP
  2. EXTRACT: Parse ingredients, identify unmapped terms
  3. CURATE: LLM-assisted ontology mapping
  4. VALIDATE: Quality checks, ontology validation
  5. EXPAND: Update CultureMech YAML files

Usage:
    # Pilot run (dry-run first)
    python scripts/batch_process_collection_media.py \
        --batch-id pilot_001 \
        --offset 0 \
        --batch-size 50 \
        --auto-accept-threshold 0.9 \
        --max-cost 10.0 \
        --dry-run

    # Production run
    python scripts/batch_process_collection_media.py \
        --batch-id batch_001 \
        --offset 0 \
        --batch-size 500 \
        --auto-accept-threshold 0.9 \
        --max-cost 100.0

    # Resume from checkpoint
    python scripts/batch_process_collection_media.py \
        --batch-id batch_001 \
        --resume
"""

import argparse
import subprocess
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import sys
import os

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.lock_manager import LockManager


# Stage definitions
STAGES = ['fetch', 'extract', 'curate', 'validate', 'expand']

# Workspace paths
WORKSPACE_ROOT = Path('workspace/curation/collection_media')
CHECKPOINT_DIR = WORKSPACE_ROOT / 'checkpoints'
FETCHED_DIR = WORKSPACE_ROOT / 'fetched'
EXTRACTED_DIR = WORKSPACE_ROOT / 'extracted'
CURATED_DIR = WORKSPACE_ROOT / 'curated'
VALIDATED_DIR = WORKSPACE_ROOT / 'validated'
EXPANDED_DIR = WORKSPACE_ROOT / 'expanded'
QUARANTINE_DIR = WORKSPACE_ROOT / 'quarantine'
REPORTS_DIR = WORKSPACE_ROOT / 'reports'


def load_checkpoint(batch_id: str) -> Optional[Dict]:
    """Load checkpoint for batch if exists."""
    checkpoint_file = CHECKPOINT_DIR / f'{batch_id}_checkpoint.yaml'

    if not checkpoint_file.exists():
        return None

    with open(checkpoint_file) as f:
        return yaml.safe_load(f)


def save_checkpoint(batch_id: str, checkpoint: Dict):
    """Save checkpoint to YAML file."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    checkpoint_file = CHECKPOINT_DIR / f'{batch_id}_checkpoint.yaml'

    with open(checkpoint_file, 'w') as f:
        yaml.dump(checkpoint, f, default_flow_style=False, sort_keys=False)


def create_initial_checkpoint(args) -> Dict:
    """Create initial checkpoint from arguments."""
    return {
        'batch_id': args.batch_id,
        'created': datetime.now().isoformat(),
        'config': {
            'batch_size': args.batch_size,
            'offset': args.offset,
            'auto_accept_threshold': args.auto_accept_threshold,
            'max_cost': args.max_cost,
            'dry_run': args.dry_run,
            'input': str(args.input),
        },
        'stages': {
            'fetch': {'status': 'pending'},
            'extract': {'status': 'pending'},
            'curate': {'status': 'pending'},
            'validate': {'status': 'pending'},
            'expand': {'status': 'pending'},
        },
        'errors': [],
        'cost_tracking': {
            'total_cost_usd': 0.0,
            'by_stage': {},
        },
    }


def run_fetch_stage(checkpoint: Dict, dry_run: bool) -> bool:
    """Execute fetch stage."""
    print("\n" + "=" * 80)
    print("STAGE 1: FETCH")
    print("=" * 80)

    batch_id = checkpoint['batch_id']
    config = checkpoint['config']

    # Prepare fetch command
    input_file = config.get('input', 'workspace/commercial_expansions/identified_media.yaml')
    cmd = [
        'python', 'scripts/fetch_collection_media.py',
        '--batch-size', str(config['batch_size']),
        '--rate-limit', '1.0',
        '--input', input_file,
        '--output', str(FETCHED_DIR / f'{batch_id}.yaml'),
    ]

    if dry_run:
        cmd.append('--dry-run')

    # Run fetch
    try:
        print(f"Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, check=True, capture_output=False)

        # Update checkpoint
        checkpoint['stages']['fetch'] = {
            'status': 'completed',
            'completed_at': datetime.now().isoformat(),
        }

        return True

    except subprocess.CalledProcessError as e:
        checkpoint['stages']['fetch']['status'] = 'failed'
        checkpoint['errors'].append({
            'stage': 'fetch',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
        })
        print(f"\n✗ Fetch stage failed: {e}")
        return False


def run_extract_stage(checkpoint: Dict) -> bool:
    """Execute extract stage."""
    print("\n" + "=" * 80)
    print("STAGE 2: EXTRACT")
    print("=" * 80)

    batch_id = checkpoint['batch_id']

    # Get MediaIngredientMech root from environment or use default
    mim_root = os.getenv(
        'MEDIAINGREDIENTMECH_ROOT',
        str(Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech')
    )

    # Prepare extract command
    cmd = [
        'python', 'scripts/extract_unmapped_ingredients.py',
        '--fetch-results', str(FETCHED_DIR / f'{batch_id}.yaml'),
        '--output', str(EXTRACTED_DIR / f'{batch_id}_unmapped.yaml'),
        '--mediaingredientmech-root', mim_root,
    ]

    # Run extract
    try:
        print(f"Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, check=True, capture_output=False)

        # Update checkpoint
        checkpoint['stages']['extract'] = {
            'status': 'completed',
            'completed_at': datetime.now().isoformat(),
        }

        return True

    except subprocess.CalledProcessError as e:
        checkpoint['stages']['extract']['status'] = 'failed'
        checkpoint['errors'].append({
            'stage': 'extract',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
        })
        print(f"\n✗ Extract stage failed: {e}")
        return False


def run_curate_stage(checkpoint: Dict, dry_run: bool) -> bool:
    """Execute curate stage."""
    print("\n" + "=" * 80)
    print("STAGE 3: CURATE")
    print("=" * 80)

    batch_id = checkpoint['batch_id']
    config = checkpoint['config']

    # Get MediaIngredientMech root
    mim_root = os.getenv(
        'MEDIAINGREDIENTMECH_ROOT',
        str(Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech')
    )

    # Prepare curate command (NOTE: This calls MediaIngredientMech's batch_curate.py)
    # For now, we'll use a simplified approach and note that full integration requires
    # converting our unmapped format to MediaIngredientMech collection format

    print("⚠️  Curation stage requires manual integration with MediaIngredientMech")
    print(f"    1. Convert {EXTRACTED_DIR / f'{batch_id}_unmapped.yaml'} to MediaIngredientMech format")
    print(f"    2. Run: cd {mim_root}")
    print(f"    3. Run: python scripts/batch_curate.py \\")
    print(f"              --batch-size 100 \\")
    print(f"              --auto-accept-threshold {config['auto_accept_threshold']} \\")
    print(f"              --data-path ../culturebotai-claw/{EXTRACTED_DIR / f'{batch_id}_unmapped.yaml'} \\")
    print(f"              --sources CHEBI,FOODON,ENVO,UBERON")
    print(f"    4. Copy results to {CURATED_DIR / f'{batch_id}_curated.yaml'}")
    print()

    # For now, mark as pending manual intervention
    checkpoint['stages']['curate']['status'] = 'pending_manual'
    checkpoint['stages']['curate']['notes'] = 'Requires manual MediaIngredientMech integration'

    return False  # Return False to pause pipeline here


def run_validate_stage(checkpoint: Dict) -> bool:
    """Execute validate stage."""
    print("\n" + "=" * 80)
    print("STAGE 4: VALIDATE")
    print("=" * 80)

    batch_id = checkpoint['batch_id']
    config = checkpoint['config']

    # Prepare validate command
    cmd = [
        'python', 'scripts/validate_mappings.py',
        '--curated', str(CURATED_DIR / f'{batch_id}_curated.yaml'),
        '--output', str(VALIDATED_DIR / f'{batch_id}_validation_report.yaml'),
        '--confidence-threshold', str(config.get('confidence_threshold', 0.5)),
    ]

    # Run validate
    try:
        print(f"Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, check=True, capture_output=False)

        # Update checkpoint
        checkpoint['stages']['validate'] = {
            'status': 'completed',
            'completed_at': datetime.now().isoformat(),
        }

        return True

    except subprocess.CalledProcessError as e:
        checkpoint['stages']['validate']['status'] = 'failed'
        checkpoint['errors'].append({
            'stage': 'validate',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
        })
        print(f"\n✗ Validate stage failed: {e}")
        return False


def run_expand_stage(checkpoint: Dict, dry_run: bool) -> bool:
    """Execute expand stage."""
    print("\n" + "=" * 80)
    print("STAGE 5: EXPAND")
    print("=" * 80)

    batch_id = checkpoint['batch_id']

    # Get CultureMech root
    cm_root = os.getenv(
        'CULTUREMECH_ROOT',
        str(Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech')
    )

    # Prepare expand command
    cmd = [
        'python', 'scripts/expand_collection_media.py',
        '--fetch-results', str(FETCHED_DIR / f'{batch_id}.yaml'),
        '--curated', str(CURATED_DIR / f'{batch_id}_curated.yaml'),
        '--cm-root', cm_root,
    ]

    if dry_run:
        cmd.append('--dry-run')

    # Run expand
    try:
        print(f"Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, check=True, capture_output=False)

        # Update checkpoint
        checkpoint['stages']['expand'] = {
            'status': 'completed',
            'completed_at': datetime.now().isoformat(),
        }

        return True

    except subprocess.CalledProcessError as e:
        checkpoint['stages']['expand']['status'] = 'failed'
        checkpoint['errors'].append({
            'stage': 'expand',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
        })
        print(f"\n✗ Expand stage failed: {e}")
        return False


def generate_final_report(checkpoint: Dict) -> str:
    """Generate final markdown report."""
    batch_id = checkpoint['batch_id']
    config = checkpoint['config']

    report_lines = [
        f"# Collection Media Curation - Batch {batch_id}",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## Configuration",
        "",
        f"- Batch ID: `{batch_id}`",
        f"- Batch size: {config['batch_size']}",
        f"- Offset: {config['offset']}",
        f"- Auto-accept threshold: {config['auto_accept_threshold']}",
        f"- Max cost: ${config['max_cost']}",
        f"- Dry run: {config['dry_run']}",
        "",
        "## Pipeline Stages",
        "",
    ]

    for stage in STAGES:
        stage_info = checkpoint['stages'][stage]
        status = stage_info.get('status', 'unknown')
        status_icon = "✅" if status == 'completed' else "⏳" if status == 'pending' else "⚠️"

        report_lines.append(f"### {status_icon} {stage.upper()}: {status}")

        if 'completed_at' in stage_info:
            report_lines.append(f"- Completed: {stage_info['completed_at']}")

        if 'notes' in stage_info:
            report_lines.append(f"- Notes: {stage_info['notes']}")

        report_lines.append("")

    # Errors
    if checkpoint.get('errors'):
        report_lines.extend([
            "## Errors",
            "",
        ])

        for error in checkpoint['errors']:
            report_lines.append(f"- **{error['stage']}**: {error['error']}")

        report_lines.append("")

    # Cost tracking
    cost_info = checkpoint.get('cost_tracking', {})
    report_lines.extend([
        "## Cost Tracking",
        "",
        f"- Total cost: ${cost_info.get('total_cost_usd', 0.0):.2f}",
        "",
    ])

    return '\n'.join(report_lines)


def main():
    parser = argparse.ArgumentParser(
        description='Master orchestrator for collection media curation pipeline'
    )
    parser.add_argument(
        '--batch-id',
        required=True,
        help='Unique batch identifier (e.g., "pilot_001", "batch_001")'
    )
    parser.add_argument(
        '--offset',
        type=int,
        default=0,
        help='Starting offset in identified_media.yaml (default: 0)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of media to process (default: 50)'
    )
    parser.add_argument(
        '--auto-accept-threshold',
        type=float,
        default=0.9,
        help='Auto-accept confidence threshold (default: 0.9)'
    )
    parser.add_argument(
        '--max-cost',
        type=float,
        default=10.0,
        help='Maximum cost budget in USD (default: 10.0)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - preview without making changes'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from existing checkpoint'
    )
    parser.add_argument(
        '--input',
        type=Path,
        default=Path('workspace/commercial_expansions/identified_media.yaml'),
        help='Input media YAML file (default: identified_media.yaml)'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No permanent changes will be made\n")

    # Acquire lock for multi-Claude coordination
    lock_manager = LockManager()
    lock_resource = f"collection_media_batch_{args.batch_id}"

    if not lock_manager.acquire_lock(lock_resource, "batch_process_collection_media"):
        print(f"✗ Failed to acquire lock for {lock_resource}")
        print("  Another Claude instance may be processing this batch.")
        return 1

    try:
        # Load or create checkpoint
        if args.resume:
            checkpoint = load_checkpoint(args.batch_id)
            if not checkpoint:
                print(f"✗ No checkpoint found for batch {args.batch_id}")
                return 1
            print(f"✓ Resuming from checkpoint: {args.batch_id}\n")
        else:
            checkpoint = create_initial_checkpoint(args)
            print(f"✓ Created new checkpoint: {args.batch_id}\n")

        # Execute pipeline stages
        stage_functions = {
            'fetch': run_fetch_stage,
            'extract': run_extract_stage,
            'curate': run_curate_stage,
            'validate': run_validate_stage,
            'expand': run_expand_stage,
        }

        for stage in STAGES:
            stage_status = checkpoint['stages'][stage]['status']

            # Skip completed stages
            if stage_status == 'completed':
                print(f"✓ Stage '{stage}' already completed, skipping")
                continue

            # Run stage
            stage_func = stage_functions[stage]

            # Pass dry_run flag to stages that support it
            if stage in ['fetch', 'curate', 'expand']:
                success = stage_func(checkpoint, args.dry_run)
            else:
                success = stage_func(checkpoint)

            # Save checkpoint after each stage
            save_checkpoint(args.batch_id, checkpoint)

            # Stop if stage failed or needs manual intervention
            if not success:
                if checkpoint['stages'][stage].get('status') == 'pending_manual':
                    print(f"\n⏸️  Pipeline paused at '{stage}' stage - manual intervention required")
                else:
                    print(f"\n✗ Pipeline failed at '{stage}' stage")
                break

        # Generate final report
        print("\n" + "=" * 80)
        print("GENERATING FINAL REPORT")
        print("=" * 80)

        report = generate_final_report(checkpoint)

        # Save report
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_file = REPORTS_DIR / f'{args.batch_id}_final_report.md'

        with open(report_file, 'w') as f:
            f.write(report)

        print(f"✓ Saved report to {report_file}\n")

        # Print summary
        print(report)

        return 0

    finally:
        # Release lock
        lock_manager.release_lock(lock_resource)


if __name__ == '__main__':
    exit(main())
