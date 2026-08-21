"""
Ingredient Curation Pipeline

End-to-end orchestration of the ingredient curation workflow across
CultureMech and MediaIngredientMech repositories.

Workflow:
1. Extract unmapped ingredients from CultureMech (ETLCoordinatorAgent)
2. Batch curate with LLM (IngredientCurationAgent)
3. Validate mappings (ValidationAgent + OAK or existing code)
4. Import back to CultureMech (ETLCoordinatorAgent)

Note: Gracefully handles OAK unavailability by delegating to existing
MediaIngredientMech code (just curate command).
"""

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Check OAK availability
OAK_AVAILABLE = False
try:
    import sys
    mediaingredient_root = os.getenv("MEDIAINGREDIENTMECH_ROOT")
    if mediaingredient_root:
        src_path = Path(mediaingredient_root) / "src"
        if str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))
        from mediaingredientmech.utils.ontology_client import OntologyClient
        # Try to create client
        test_client = OntologyClient(sources=["CHEBI"])
        OAK_AVAILABLE = True
        logger.info("✓ OAK available for real-time queries")
except Exception as e:
    logger.warning(f"⚠ OAK unavailable (will use delegation): {e}")
    logger.info("  Pipeline will delegate to existing MediaIngredientMech code")


class IngredientCurationPipeline:
    """Orchestrate ingredient curation across repositories."""

    def __init__(self, openclaw_client, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the pipeline.

        Args:
            openclaw_client: OpenClaw client instance for agent communication
            config: Pipeline configuration
        """
        self.client = openclaw_client
        self.config = config or {}

        # Load workspace paths
        self.workspace = Path(os.getenv("OPENCLAW_WORKSPACE", "workspace"))
        self.reports_dir = self.workspace / "reports" / "ingredient_curation"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # Pipeline settings
        self.default_batch_size = self.config.get("batch_size", 20)
        self.default_threshold = self.config.get("auto_accept_threshold", 0.90)
        self.max_cost_per_run = self.config.get("max_cost_per_run", 5.00)

        logger.info(f"IngredientCurationPipeline initialized with "
                   f"batch_size={self.default_batch_size}, "
                   f"threshold={self.default_threshold}")

    def run(
        self,
        batch_size: Optional[int] = None,
        auto_accept_threshold: Optional[float] = None,
        dry_run: bool = True,
        reverse_sync: bool = False,
        min_occurrences: int = 1,
    ) -> Dict[str, Any]:
        """
        Run the complete ingredient curation pipeline.

        Args:
            batch_size: Number of ingredients to process (default from config)
            auto_accept_threshold: Confidence threshold for auto-acceptance
            dry_run: If True, don't save changes
            reverse_sync: If True, also sync back to CultureMech
            min_occurrences: Only process ingredients with >= this many occurrences

        Returns:
            Pipeline execution summary
        """
        batch_size = batch_size or self.default_batch_size
        auto_accept_threshold = auto_accept_threshold or self.default_threshold

        logger.info(f"Starting ingredient curation pipeline: "
                   f"batch_size={batch_size}, threshold={auto_accept_threshold}, "
                   f"dry_run={dry_run}, reverse_sync={reverse_sync}")

        pipeline_start = datetime.now()
        results = {
            "pipeline": "ingredient_curation",
            "start_time": pipeline_start.isoformat(),
            "parameters": {
                "batch_size": batch_size,
                "auto_accept_threshold": auto_accept_threshold,
                "dry_run": dry_run,
                "reverse_sync": reverse_sync,
                "min_occurrences": min_occurrences,
            },
            "steps": [],
            "total_cost": 0.0,
        }

        try:
            # Step 1: ETL Extract - CultureMech → MediaIngredientMech
            logger.info("Step 1: Extracting ingredients from CultureMech...")
            extraction_result = self._step_extract_unmapped(
                min_occurrences=min_occurrences,
                dry_run=dry_run,
            )
            results["steps"].append({
                "step": 1,
                "name": "extract_unmapped",
                "status": extraction_result.get("status", "unknown"),
                "result": extraction_result,
            })

            if extraction_result.get("status") != "success":
                results["status"] = "failed"
                results["error"] = "ETL extraction failed"
                return results

            # Step 2: LLM Curation - Batch suggest mappings
            logger.info("Step 2: LLM-assisted curation...")
            curation_result = self._step_curate_batch(
                batch_size=batch_size,
                auto_accept_threshold=auto_accept_threshold,
                dry_run=dry_run,
                filter_by_occurrences=min_occurrences,
            )
            results["steps"].append({
                "step": 2,
                "name": "llm_curation",
                "status": curation_result.get("status", "unknown"),
                "result": curation_result,
            })
            results["total_cost"] += curation_result.get("cost_usd", 0.0)

            if curation_result.get("status") != "success":
                results["status"] = "failed"
                results["error"] = "LLM curation failed"
                return results

            # Check cost limit
            if results["total_cost"] > self.max_cost_per_run:
                logger.warning(f"Cost limit exceeded: ${results['total_cost']:.2f} > ${self.max_cost_per_run:.2f}")
                results["status"] = "cost_limit_exceeded"
                return results

            # Step 3: Validation - Schema + Ontology
            logger.info("Step 3: Validating mappings...")
            validation_result = self._step_validate_mappings(
                curation_result.get("mappings", [])
            )
            results["steps"].append({
                "step": 3,
                "name": "validation",
                "status": validation_result.get("status", "unknown"),
                "result": validation_result,
            })

            if validation_result.get("status") != "passed":
                results["status"] = "validation_failed"
                results["error"] = "Validation failed"
                return results

            # Step 4: Optional Reverse Sync - MediaIngredientMech → CultureMech
            if reverse_sync and not dry_run:
                logger.info("Step 4: Reverse sync to CultureMech...")
                sync_result = self._step_reverse_sync()
                results["steps"].append({
                    "step": 4,
                    "name": "reverse_sync",
                    "status": sync_result.get("status", "unknown"),
                    "result": sync_result,
                })
            else:
                logger.info("Step 4: Reverse sync skipped (dry_run or disabled)")
                results["steps"].append({
                    "step": 4,
                    "name": "reverse_sync",
                    "status": "skipped",
                })

            # Pipeline success
            results["status"] = "success"
            results["end_time"] = datetime.now().isoformat()
            results["duration_seconds"] = (datetime.now() - pipeline_start).total_seconds()

            # Generate report
            self._generate_report(results)

            logger.info(f"Pipeline completed successfully: "
                       f"{curation_result.get('auto_accepted', 0)} auto-accepted, "
                       f"${results['total_cost']:.2f} cost")

            return results

        except Exception as e:
            logger.error(f"Pipeline failed with exception: {e}", exc_info=True)
            results["status"] = "error"
            results["error"] = str(e)
            results["end_time"] = datetime.now().isoformat()
            return results

    def _step_extract_unmapped(
        self,
        min_occurrences: int,
        dry_run: bool,
    ) -> Dict[str, Any]:
        """
        Step 1: Extract unmapped ingredients from CultureMech.

        Uses ETLCoordinatorAgent to:
        1. Export ingredients from CultureMech
        2. Merge with MediaIngredientMech
        3. Extract unmapped ingredients

        Returns:
            Extraction result summary
        """
        try:
            # Execute ETL coordinator task
            result = self.client.agents["etl_coordinator"].execute({
                "task": "extract_unmapped",
                "params": {
                    "source_repo": "culturemech",
                    "min_occurrences": min_occurrences,
                    "output_format": "yaml",
                },
            })

            return {
                "status": "success" if result.get("success") else "failed",
                "total_unmapped": result.get("total_unmapped", 0),
                "high_priority_count": result.get("high_priority_count", 0),
                "output_file": result.get("output_file"),
            }

        except Exception as e:
            logger.error(f"ETL extraction failed: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def _step_curate_batch(
        self,
        batch_size: int,
        auto_accept_threshold: float,
        dry_run: bool,
        filter_by_occurrences: int,
    ) -> Dict[str, Any]:
        """
        Step 2: Batch curate unmapped ingredients with LLM.

        Uses IngredientCurationAgent to:
        1. Load unmapped ingredients
        2. Generate LLM suggestions
        3. Validate with OAK (or existing validation code)
        4. Auto-accept high-confidence mappings

        If OAK unavailable, delegates to existing MediaIngredientMech code.

        Returns:
            Curation result summary
        """
        try:
            # Check if we should use delegation
            if not OAK_AVAILABLE:
                logger.info("Using delegation to existing MediaIngredientMech code")
                return self._step_curate_batch_delegation(
                    batch_size, auto_accept_threshold, dry_run, filter_by_occurrences
                )

            # Execute ingredient curation task with OAK
            result = self.client.agents["ingredient_curation"].execute({
                "task": "batch_curate",
                "params": {
                    "batch_size": batch_size,
                    "auto_accept_threshold": auto_accept_threshold,
                    "dry_run": dry_run,
                    "filter_by_occurrences": filter_by_occurrences,
                },
            })

            return {
                "status": "success" if result.get("success") else "failed",
                "total_processed": result.get("total_processed", 0),
                "auto_accepted": result.get("auto_accepted", 0),
                "manual_review_needed": result.get("manual_review_needed", 0),
                "validation_failures": result.get("validation_failures", 0),
                "cost_usd": result.get("cost_usd", 0.0),
                "mappings": result.get("mappings", []),
            }

        except Exception as e:
            logger.error(f"Curation failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "cost_usd": 0.0,
            }

    def _step_curate_batch_delegation(
        self,
        batch_size: int,
        auto_accept_threshold: float,
        dry_run: bool,
        filter_by_occurrences: int,
    ) -> Dict[str, Any]:
        """
        Delegation mode: Use existing MediaIngredientMech code.

        Runs 'just curate' command in MediaIngredientMech.

        Returns:
            Curation result summary
        """
        mediaingredient_root = os.getenv("MEDIAINGREDIENTMECH_ROOT")
        if not mediaingredient_root:
            return {
                "status": "error",
                "error": "MEDIAINGREDIENTMECH_ROOT not set",
            }

        try:
            logger.info(f"Executing 'just curate' in MediaIngredientMech (batch_size={batch_size})")

            # Build command
            cmd = ["just", "curate"]
            if dry_run:
                cmd.append("--dry-run")

            # Execute
            result = subprocess.run(
                cmd,
                cwd=mediaingredient_root,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

            if result.returncode == 0:
                # Parse output for summary (best effort)
                logger.info("✓ Curation completed via delegation")
                return {
                    "status": "success",
                    "total_processed": batch_size,  # Estimate
                    "auto_accepted": 0,  # Unknown
                    "manual_review_needed": batch_size,  # Conservative
                    "validation_failures": 0,
                    "cost_usd": 0.0,  # Not tracked in delegation mode
                    "mappings": [],
                    "delegation_mode": True,
                    "stdout": result.stdout[:500],  # First 500 chars
                }
            else:
                logger.error(f"Delegation failed: {result.stderr}")
                return {
                    "status": "failed",
                    "error": result.stderr,
                    "delegation_mode": True,
                }

        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": "Command timed out after 10 minutes",
                "delegation_mode": True,
            }
        except Exception as e:
            logger.error(f"Delegation failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "delegation_mode": True,
            }

    def _step_validate_mappings(
        self,
        mappings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Step 3: Validate all mappings using ValidationAgent and OAK.

        Validates:
        1. Schema compliance (LinkML)
        2. Ontology ID validity (OAK)
        3. Cross-repo consistency

        Returns:
            Validation result summary
        """
        try:
            # Execute validation task
            result = self.client.agents["validation"].execute({
                "task": "validate_ingredient_mappings",
                "params": {
                    "mappings": mappings,
                },
            })

            return {
                "status": "passed" if result.get("all_valid") else "failed",
                "total_validated": result.get("total_validated", 0),
                "schema_valid": result.get("schema_valid", 0),
                "ontology_valid": result.get("ontology_valid", 0),
                "failures": result.get("failures", []),
            }

        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def _step_reverse_sync(self) -> Dict[str, Any]:
        """
        Step 4: Reverse sync curated mappings back to CultureMech.

        Uses ETLCoordinatorAgent to:
        1. Export curated mappings from MediaIngredientMech
        2. Import to CultureMech
        3. Update recipes
        4. Regenerate normalized YAML

        Returns:
            Sync result summary
        """
        try:
            # Execute reverse sync task
            result = self.client.agents["etl_coordinator"].execute({
                "task": "mediaingredient_to_culturemech",
                "params": {
                    "dry_run": False,  # Actually apply changes
                    "validate_all": True,
                },
            })

            return {
                "status": "success" if result.get("success") else "failed",
                "mappings_imported": result.get("mappings_imported", 0),
                "recipes_updated": result.get("recipes_updated", 0),
                "validation_failures": result.get("validation_failures", 0),
            }

        except Exception as e:
            logger.error(f"Reverse sync failed: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def _generate_report(self, results: Dict[str, Any]):
        """Generate and save pipeline execution report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.reports_dir / f"pipeline_run_{timestamp}.yaml"

        try:
            with open(report_file, "w") as f:
                yaml.dump(results, f, default_flow_style=False, sort_keys=False)

            logger.info(f"Report saved to {report_file}")

            # Also save a summary
            summary = {
                "timestamp": results.get("start_time"),
                "status": results.get("status"),
                "batch_size": results["parameters"]["batch_size"],
                "auto_accepted": results["steps"][1]["result"].get("auto_accepted", 0)
                    if len(results["steps"]) > 1 else 0,
                "cost_usd": results.get("total_cost", 0.0),
                "duration_seconds": results.get("duration_seconds", 0),
            }

            summary_file = self.reports_dir / "latest_summary.yaml"
            with open(summary_file, "w") as f:
                yaml.dump(summary, f, default_flow_style=False)

        except Exception as e:
            logger.warning(f"Failed to save report: {e}")

    def get_status(self) -> Dict[str, Any]:
        """
        Get pipeline status and recent execution history.

        Returns:
            Status summary with recent runs
        """
        try:
            # Load latest summary
            summary_file = self.reports_dir / "latest_summary.yaml"
            if summary_file.exists():
                with open(summary_file, "r") as f:
                    latest = yaml.safe_load(f)
            else:
                latest = None

            # Count report files
            report_count = len(list(self.reports_dir.glob("pipeline_run_*.yaml")))

            return {
                "pipeline": "ingredient_curation",
                "total_runs": report_count,
                "latest_run": latest,
                "reports_directory": str(self.reports_dir),
            }

        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return {
                "pipeline": "ingredient_curation",
                "error": str(e),
            }


# Pipeline registration for OpenClaw
def register_pipeline():
    """Register the IngredientCurationPipeline with OpenClaw."""
    return {
        "name": "ingredient_curation",
        "version": "1.0.0",
        "class": IngredientCurationPipeline,
        "description": "End-to-end ingredient curation across CultureMech and MediaIngredientMech",
        "agents": [
            "etl_coordinator",
            "ingredient_curation",
            "validation",
        ],
    }
