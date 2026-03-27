"""
Unified Ingredient Mapping Pipeline

End-to-end orchestration of ingredient curation across CultureMech
and MediaIngredientMech repositories with centralized canonical storage.

Workflow (8 steps):
1. Acquire locks on both repositories
2. Extract unmapped ingredients from both repos
3. Deduplicate into canonical set
4. Prioritize by occurrence count
5. Curate with LLM + OAK validation
6. Apply quality gates (confidence threshold)
7. Update canonical storage
8. Bidirectional sync to both repos

This replaces separate tooling in both repositories with a unified workflow.
"""

import os
import sys
import logging
import yaml
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add MediaIngredientMech to path for LLM curator
mediaingredient_root = os.getenv("MEDIAINGREDIENTMECH_ROOT")
if mediaingredient_root:
    src_path = Path(mediaingredient_root) / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

# Import plugins
from plugins.lock_manager import LockManager
from plugins.ingredient_deduplicator import IngredientDeduplicator
from plugins.ingredient_repo_synchronizer import IngredientRepoSynchronizer

# Try to import LLM curator and OAK
try:
    from mediaingredientmech.utils.llm_curator import LLMCurator
    from mediaingredientmech.utils.ontology_client import OntologyClient
    LLM_CURATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"LLM curator not available: {e}")
    LLM_CURATOR_AVAILABLE = False

logger = logging.getLogger(__name__)


class UnifiedIngredientMappingPipeline:
    """Orchestrate unified ingredient mapping across repositories."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the pipeline.

        Args:
            config: Pipeline configuration
        """
        self.config = config or {}

        # Load workspace paths
        self.workspace = Path(os.getenv("OPENCLAW_WORKSPACE", "."))
        self.canonical_dir = self.workspace / "canonical_ingredients"
        self.canonical_dir.mkdir(parents=True, exist_ok=True)

        self.reports_dir = self.workspace / "reports" / "unified_ingredient_mapping"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # Pipeline settings
        self.default_batch_size = self.config.get("batch_size", 20)
        self.default_threshold = self.config.get("auto_accept_threshold", 0.90)
        self.max_cost_per_run = self.config.get("max_cost_per_run", 5.00)

        # Repository roots
        self.culturemech_root = Path(os.getenv('CULTUREMECH_ROOT', '.'))
        self.mim_root = Path(os.getenv('MEDIAINGREDIENTMECH_ROOT', '.'))

        # Initialize plugins
        self.lock_manager = LockManager()
        self.deduplicator = IngredientDeduplicator()
        self.synchronizer = IngredientRepoSynchronizer()

        # Initialize LLM curator if available
        self.llm_curator = None
        if LLM_CURATOR_AVAILABLE:
            try:
                self.llm_curator = LLMCurator()
                logger.info("✓ LLM curator initialized")
            except Exception as e:
                logger.warning(f"Could not initialize LLM curator: {e}")

        logger.info(f"UnifiedIngredientMappingPipeline initialized: "
                   f"batch_size={self.default_batch_size}, "
                   f"threshold={self.default_threshold}")

    def run(
        self,
        batch_size: Optional[int] = None,
        auto_accept_threshold: Optional[float] = None,
        dry_run: bool = True,
        min_occurrences: int = 2,
    ) -> Dict[str, Any]:
        """
        Run the complete unified ingredient mapping pipeline.

        Args:
            batch_size: Number of ingredients to process
            auto_accept_threshold: Confidence threshold for auto-acceptance (0-1.0)
            dry_run: If True, don't save changes
            min_occurrences: Only process ingredients with >= this many occurrences

        Returns:
            Pipeline execution summary
        """
        batch_size = batch_size or self.default_batch_size
        auto_accept_threshold = auto_accept_threshold or self.default_threshold

        logger.info(f"=== Starting Unified Ingredient Mapping Pipeline ===")
        logger.info(f"Config: batch_size={batch_size}, threshold={auto_accept_threshold}, "
                   f"dry_run={dry_run}, min_occurrences={min_occurrences}")

        pipeline_start = datetime.utcnow()

        # Execution report
        report = {
            'pipeline': 'unified_ingredient_mapping',
            'started_at': pipeline_start.isoformat(),
            'config': {
                'batch_size': batch_size,
                'auto_accept_threshold': auto_accept_threshold,
                'dry_run': dry_run,
                'min_occurrences': min_occurrences,
            },
            'steps': {},
            'summary': {},
            'errors': []
        }

        try:
            # STEP 1: Acquire locks
            logger.info("\n[STEP 1/8] Acquiring locks on both repositories...")
            locks_acquired = self._step1_acquire_locks(report)

            if not locks_acquired:
                raise RuntimeError("Failed to acquire repository locks")

            # STEP 2: Extract unmapped
            logger.info("\n[STEP 2/8] Extracting unmapped ingredients from both repos...")
            culturemech_unmapped, mim_unmapped = self._step2_extract_unmapped(report)

            # STEP 3: Deduplicate
            logger.info("\n[STEP 3/8] Deduplicating unmapped ingredients...")
            deduplicated, conflicts = self._step3_deduplicate(
                culturemech_unmapped, mim_unmapped, report
            )

            # STEP 4: Prioritize
            logger.info("\n[STEP 4/8] Prioritizing by occurrence count...")
            prioritized_batch = self._step4_prioritize(
                deduplicated, batch_size, min_occurrences, report
            )

            # STEP 5: Curate (LLM + OAK)
            logger.info("\n[STEP 5/8] Curating with LLM + ontology validation...")
            curated_suggestions = self._step5_curate(prioritized_batch, report)

            # STEP 6: Quality gate
            logger.info("\n[STEP 6/8] Applying quality gates...")
            auto_accepted, manual_review, rejected = self._step6_quality_gate(
                curated_suggestions, auto_accept_threshold, report
            )

            # STEP 7: Update canonical
            logger.info("\n[STEP 7/8] Updating canonical ingredient store...")
            if not dry_run:
                self._step7_update_canonical(auto_accepted, report)
            else:
                logger.info("  [DRY RUN] Would update canonical store")
                report['steps']['step7_update_canonical'] = {
                    'status': 'dry_run',
                    'would_add': len(auto_accepted)
                }

            # STEP 8: Bidirectional sync
            logger.info("\n[STEP 8/8] Syncing to both repositories...")
            if not dry_run:
                culturemech_sync, mim_sync = self._step8_bidirectional_sync(auto_accepted, report)
            else:
                logger.info("  [DRY RUN] Would sync to both repos")
                sync_diff = self.synchronizer.generate_sync_diff(auto_accepted)
                report['steps']['step8_bidirectional_sync'] = {
                    'status': 'dry_run',
                    'diff': sync_diff
                }

        except Exception as e:
            error_msg = f"Pipeline error: {e}"
            logger.error(error_msg, exc_info=True)
            report['errors'].append(error_msg)

        finally:
            # Always release locks
            logger.info("\nReleasing locks...")
            self._release_locks()

        # Pipeline summary
        pipeline_end = datetime.utcnow()
        duration = (pipeline_end - pipeline_start).total_seconds()

        report['completed_at'] = pipeline_end.isoformat()
        report['duration_seconds'] = duration
        report['summary'] = {
            'processed': batch_size,
            'auto_accepted': len(auto_accepted) if 'auto_accepted' in locals() else 0,
            'manual_review': len(manual_review) if 'manual_review' in locals() else 0,
            'rejected': len(rejected) if 'rejected' in locals() else 0,
            'dry_run': dry_run,
            'success': len(report['errors']) == 0
        }

        # Save report
        report_file = self.reports_dir / f"run_{pipeline_start.strftime('%Y%m%d_%H%M%S')}.yaml"
        with open(report_file, 'w') as f:
            yaml.dump(report, f, default_flow_style=False)

        logger.info(f"\n=== Pipeline Complete ===")
        logger.info(f"Duration: {duration:.1f}s")
        logger.info(f"Auto-accepted: {report['summary']['auto_accepted']}")
        logger.info(f"Manual review: {report['summary']['manual_review']}")
        logger.info(f"Rejected: {report['summary']['rejected']}")
        logger.info(f"Report saved: {report_file}")

        return report

    def _step1_acquire_locks(self, report: Dict) -> bool:
        """Acquire locks on both repositories."""
        try:
            cm_locked = self.lock_manager.acquire_lock(
                "culturemech",
                "unified_ingredient_mapping",
                wait=False
            )

            mim_locked = self.lock_manager.acquire_lock(
                "mediaingredientmech",
                "unified_ingredient_mapping",
                wait=False
            )

            report['steps']['step1_acquire_locks'] = {
                'culturemech_locked': cm_locked,
                'mediaingredientmech_locked': mim_locked,
                'status': 'success' if (cm_locked and mim_locked) else 'failed'
            }

            if cm_locked and mim_locked:
                logger.info("  ✓ Locks acquired on both repositories")
                return True
            else:
                logger.error("  ✗ Failed to acquire locks")
                return False

        except Exception as e:
            logger.error(f"  ✗ Error acquiring locks: {e}")
            report['errors'].append(f"Lock acquisition failed: {e}")
            return False

    def _step2_extract_unmapped(self, report: Dict) -> tuple:
        """Extract unmapped ingredients from both repositories."""
        culturemech_unmapped = []
        mim_unmapped = []

        try:
            # Extract from CultureMech
            cm_unmapped_file = self.culturemech_root / "output" / "unmapped_ingredients.yaml"
            if cm_unmapped_file.exists():
                with open(cm_unmapped_file) as f:
                    cm_data = yaml.safe_load(f) or {}
                    culturemech_unmapped = cm_data.get('ingredients', [])
                logger.info(f"  CultureMech: {len(culturemech_unmapped)} unmapped ingredients")
            else:
                logger.warning(f"  CultureMech unmapped file not found: {cm_unmapped_file}")

            # Extract from MediaIngredientMech
            mim_unmapped_file = self.mim_root / "data" / "curated" / "unmapped_ingredients.yaml"
            if mim_unmapped_file.exists():
                with open(mim_unmapped_file) as f:
                    mim_data = yaml.safe_load(f) or {}
                    mim_unmapped = mim_data.get('ingredients', [])
                logger.info(f"  MediaIngredientMech: {len(mim_unmapped)} unmapped ingredients")
            else:
                logger.warning(f"  MediaIngredientMech unmapped file not found: {mim_unmapped_file}")

            report['steps']['step2_extract_unmapped'] = {
                'culturemech_count': len(culturemech_unmapped),
                'mediaingredientmech_count': len(mim_unmapped),
                'status': 'success'
            }

        except Exception as e:
            logger.error(f"  ✗ Error extracting unmapped: {e}")
            report['errors'].append(f"Extraction failed: {e}")

        return culturemech_unmapped, mim_unmapped

    def _step3_deduplicate(
        self,
        culturemech_unmapped: List[Dict],
        mim_unmapped: List[Dict],
        report: Dict
    ) -> tuple:
        """Deduplicate unmapped ingredients."""
        try:
            deduplicated, conflicts = self.deduplicator.deduplicate_unmapped(
                culturemech_unmapped,
                mim_unmapped
            )

            stats = self.deduplicator.get_stats()
            logger.info(f"  ✓ Deduplicated: {stats['final_count']} total "
                       f"({stats['duplicates_merged']} merged, {len(conflicts)} conflicts)")

            report['steps']['step3_deduplicate'] = {
                'stats': stats,
                'conflicts': [
                    {
                        'ingredient_a': c.ingredient_a_name,
                        'ingredient_b': c.ingredient_b_name,
                        'type': c.conflict_type,
                        'reason': c.reason
                    }
                    for c in conflicts
                ],
                'status': 'success'
            }

            return deduplicated, conflicts

        except Exception as e:
            logger.error(f"  ✗ Error deduplicating: {e}")
            report['errors'].append(f"Deduplication failed: {e}")
            return [], []

    def _step4_prioritize(
        self,
        deduplicated: List[Dict],
        batch_size: int,
        min_occurrences: int,
        report: Dict
    ) -> List[Dict]:
        """Prioritize ingredients by occurrence count."""
        try:
            # Filter by min occurrences
            filtered = [
                ing for ing in deduplicated
                if (ing.get('occurrence_count', 0) >= min_occurrences or
                    ing.get('occurrence_statistics', {}).get('total_occurrences', 0) >= min_occurrences)
            ]

            # Sort by occurrence count (descending)
            def get_occurrence_count(ing):
                return max(
                    ing.get('occurrence_count', 0),
                    ing.get('occurrence_statistics', {}).get('total_occurrences', 0)
                )

            sorted_ingredients = sorted(filtered, key=get_occurrence_count, reverse=True)

            # Take top batch_size
            batch = sorted_ingredients[:batch_size]

            logger.info(f"  ✓ Prioritized: {len(batch)} ingredients (from {len(filtered)} eligible)")

            report['steps']['step4_prioritize'] = {
                'total_eligible': len(filtered),
                'batch_size': len(batch),
                'min_occurrences': min_occurrences,
                'status': 'success'
            }

            return batch

        except Exception as e:
            logger.error(f"  ✗ Error prioritizing: {e}")
            report['errors'].append(f"Prioritization failed: {e}")
            return []

    def _step5_curate(self, batch: List[Dict], report: Dict) -> List[Dict]:
        """Curate with LLM + ontology validation."""
        suggestions = []

        if not self.llm_curator:
            logger.warning("  ⚠ LLM curator not available, skipping curation")
            report['steps']['step5_curate'] = {
                'status': 'skipped',
                'reason': 'LLM curator not available'
            }
            return suggestions

        try:
            for ingredient in batch:
                name = ingredient.get('preferred_term') or ingredient.get('parsed_chemical_name', '')

                if not name:
                    continue

                # Get LLM suggestion
                suggestion = self.llm_curator.suggest_mapping(name)

                if suggestion:
                    # Add original ingredient data
                    suggestion['original_ingredient'] = ingredient
                    suggestions.append(suggestion)

            logger.info(f"  ✓ Curated: {len(suggestions)} suggestions generated")

            report['steps']['step5_curate'] = {
                'batch_size': len(batch),
                'suggestions_generated': len(suggestions),
                'status': 'success'
            }

        except Exception as e:
            logger.error(f"  ✗ Error during curation: {e}")
            report['errors'].append(f"Curation failed: {e}")

        return suggestions

    def _step6_quality_gate(
        self,
        suggestions: List[Dict],
        threshold: float,
        report: Dict
    ) -> tuple:
        """Apply quality gates to curated suggestions."""
        auto_accepted = []
        manual_review = []
        rejected = []

        try:
            for suggestion in suggestions:
                confidence = suggestion.get('confidence_score', 0.0)

                if confidence >= threshold:
                    auto_accepted.append(suggestion)
                elif confidence >= 0.70:
                    manual_review.append(suggestion)
                else:
                    rejected.append(suggestion)

            logger.info(f"  ✓ Quality gate: {len(auto_accepted)} auto-accepted, "
                       f"{len(manual_review)} manual review, {len(rejected)} rejected")

            report['steps']['step6_quality_gate'] = {
                'threshold': threshold,
                'auto_accepted': len(auto_accepted),
                'manual_review': len(manual_review),
                'rejected': len(rejected),
                'status': 'success'
            }

        except Exception as e:
            logger.error(f"  ✗ Error in quality gate: {e}")
            report['errors'].append(f"Quality gate failed: {e}")

        return auto_accepted, manual_review, rejected

    def _step7_update_canonical(self, auto_accepted: List[Dict], report: Dict):
        """Update canonical ingredient storage."""
        try:
            mapped_file = self.canonical_dir / "mapped_ingredients.yaml"

            # Load existing
            with open(mapped_file) as f:
                canonical_data = yaml.safe_load(f) or {}

            existing_ingredients = canonical_data.get('ingredients', [])

            # Add newly mapped
            for suggestion in auto_accepted:
                original = suggestion.get('original_ingredient', {})

                mapped_ingredient = {
                    'ontology_id': suggestion.get('ontology_id'),
                    'preferred_term': suggestion.get('ontology_label'),
                    'ontology_mapping': {
                        'ontology_id': suggestion.get('ontology_id'),
                        'ontology_label': suggestion.get('ontology_label'),
                        'ontology_source': suggestion.get('ontology_source', 'CHEBI'),
                        'mapping_quality': 'LLM_ASSISTED',
                        'confidence_score': suggestion.get('confidence_score'),
                    },
                    'occurrence_statistics': original.get('occurrence_statistics', {}),
                    'mapping_status': 'MAPPED',
                    'curation_history': [{
                        'timestamp': datetime.utcnow().isoformat(),
                        'curator': 'orchestration_claude',
                        'action': 'AUTO_ACCEPTED_MAPPING',
                        'confidence_score': suggestion.get('confidence_score'),
                        'llm_assisted': True
                    }]
                }

                existing_ingredients.append(mapped_ingredient)

            # Update metadata
            canonical_data['ingredients'] = existing_ingredients
            canonical_data['metadata'] = {
                'version': '1.0.0',
                'last_updated': datetime.utcnow().isoformat(),
                'total_count': len(existing_ingredients)
            }

            # Write
            with open(mapped_file, 'w') as f:
                yaml.dump(canonical_data, f, default_flow_style=False)

            logger.info(f"  ✓ Updated canonical store: {len(auto_accepted)} added")

            report['steps']['step7_update_canonical'] = {
                'added': len(auto_accepted),
                'total_canonical_count': len(existing_ingredients),
                'status': 'success'
            }

        except Exception as e:
            logger.error(f"  ✗ Error updating canonical: {e}")
            report['errors'].append(f"Canonical update failed: {e}")

    def _step8_bidirectional_sync(self, auto_accepted: List[Dict], report: Dict) -> tuple:
        """Sync to both repositories."""
        try:
            # Prepare canonical mapped list
            canonical_mapped = [
                {
                    'ontology_id': s.get('ontology_id'),
                    'preferred_term': s.get('ontology_label'),
                    'occurrence_statistics': s.get('original_ingredient', {}).get('occurrence_statistics', {})
                }
                for s in auto_accepted
            ]

            # Sync to CultureMech
            cm_sync = self.synchronizer.sync_to_culturemech(canonical_mapped, dry_run=False)

            # Sync to MediaIngredientMech
            mim_sync = self.synchronizer.sync_to_mediaingredientmech(canonical_mapped, dry_run=False)

            logger.info(f"  ✓ Sync complete: CultureMech ({cm_sync.updated} updated), "
                       f"MediaIngredientMech ({mim_sync.added} added, {mim_sync.updated} updated)")

            report['steps']['step8_bidirectional_sync'] = {
                'culturemech': {
                    'updated': cm_sync.updated,
                    'errors': cm_sync.errors
                },
                'mediaingredientmech': {
                    'added': mim_sync.added,
                    'updated': mim_sync.updated,
                    'errors': mim_sync.errors
                },
                'status': 'success'
            }

            return cm_sync, mim_sync

        except Exception as e:
            logger.error(f"  ✗ Error syncing: {e}")
            report['errors'].append(f"Sync failed: {e}")
            return None, None

    def _release_locks(self):
        """Release all locks."""
        try:
            self.lock_manager.release_lock("culturemech")
            self.lock_manager.release_lock("mediaingredientmech")
            logger.info("  ✓ Locks released")
        except Exception as e:
            logger.warning(f"  ⚠ Error releasing locks: {e}")
