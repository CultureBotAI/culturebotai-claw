"""
Environment Curation Pipeline

Orchestrates citation-backed environment curation across CultureMech and MediaIngredientMech.

Extends the proven IngredientCurationPipeline pattern with:
- LLM-assisted PMID discovery
- Multi-gate quality validation
- Auto-accept with manual review fallback
- Batch processing with cost tracking

Workflow:
1. Prioritize candidates (Tier 1/2/3)
2. LLM-assisted environment + PMID discovery
3. Citation validation (PubMed API)
4. ENVO term validation (OAK)
5. Evidence quality scoring
6. Auto-accept or queue for review
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Import plugins
from plugins.environment_curator import (
    EnvironmentSignalExtractor,
    EnvironmentSuggestion,
    EnvironmentTerm,
    Evidence,
    EvidenceQualityScorer,
    MediaPrioritizer,
)
from plugins.environment_llm_curator import get_environment_llm_curator
from plugins.oak_query import OAKQueryPlugin
from plugins.pubmed_client import get_pubmed_client

logger = logging.getLogger(__name__)


class ApplyModeUnavailableError(RuntimeError):
    """Raised when a caller requests writes before a safe writer exists."""


class EnvironmentCurationPipeline:
    """
    Orchestrate environment curation across repositories.

    Similar to IngredientCurationPipeline but specialized for environment curation.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the pipeline.

        Args:
            config: Pipeline configuration
        """
        self.config = config or {}

        # Load workspace paths
        self.workspace = Path(os.getenv("OPENCLAW_WORKSPACE", "workspace"))
        self.reports_dir = self.workspace / "reports" / "environment_curation"
        self.review_dir = self.workspace / "review"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)

        # Pipeline settings
        self.default_batch_size = self.config.get("batch_size", 20)
        self.default_threshold = self.config.get("auto_accept_threshold", 0.90)
        self.manual_review_threshold = self.config.get("manual_review_threshold", 0.70)
        self.max_cost_per_run = self.config.get("max_cost_per_run", 100.00)

        # Initialize clients
        cache_dir = self.workspace / ".cache" / "pubmed"
        self.pubmed_client = get_pubmed_client(cache_dir=cache_dir)
        self.oak_plugin = OAKQueryPlugin()

        # Initialize LLM curator
        try:
            self.llm_curator = get_environment_llm_curator()
            logger.info("LLM curator initialized successfully")
        except Exception as e:
            logger.warning(f"LLM curator initialization failed: {e}. Will use fallback.")
            self.llm_curator = None

        logger.info(f"EnvironmentCurationPipeline initialized with "
                   f"batch_size={self.default_batch_size}, "
                   f"threshold={self.default_threshold}")

    def run(
        self,
        media_records: List[Dict[str, Any]],
        batch_size: Optional[int] = None,
        tier: Optional[int] = None,
        auto_accept_threshold: Optional[float] = None,
        dry_run: bool = True,
        require_citations: bool = True
    ) -> Dict[str, Any]:
        """
        Run the complete environment curation pipeline.

        Args:
            media_records: List of media record dictionaries
            batch_size: Number of media to process
            tier: Target tier (1, 2, or 3) for prioritization
            auto_accept_threshold: Confidence threshold for auto-acceptance
            dry_run: If True, don't save changes
            require_citations: If True, require PMIDs (no INFERRED auto-accept)

        Returns:
            Pipeline execution summary
        """
        if not dry_run:
            raise ApplyModeUnavailableError(
                "Environment curation apply mode is unavailable: accepted curations "
                "do not yet have a validated, atomic writer. Run with dry_run=True."
            )

        batch_size = batch_size or self.default_batch_size
        auto_accept_threshold = auto_accept_threshold or self.default_threshold

        logger.info(f"Starting environment curation pipeline: "
                   f"batch_size={batch_size}, tier={tier}, "
                   f"threshold={auto_accept_threshold}, dry_run={dry_run}")

        start_time = datetime.now()
        results = {
            "start_time": start_time.isoformat(),
            "total_media": len(media_records),
            "batch_size": batch_size,
            "tier": tier,
            "suggestions": [],
            "auto_accepted": [],
            "manual_review": [],
            "rejected": [],
            "errors": [],
            "metrics": {},
            "status": "running",
        }

        try:
            # Step 1: Prioritize candidates
            logger.info("Step 1: Prioritizing candidates...")
            prioritized = self._prioritize_candidates(media_records, tier, batch_size)
            logger.info(f"Selected {len(prioritized)} media for curation")

            # Step 2: LLM-assisted environment + PMID discovery
            logger.info("Step 2: Generating environment suggestions...")
            suggestions = self._generate_suggestions(prioritized)
            results["suggestions"] = suggestions
            logger.info(f"Generated {len(suggestions)} suggestions")

            # Step 3-6: Validate and score each suggestion
            logger.info("Steps 3-6: Validating suggestions...")
            for suggestion in suggestions:
                try:
                    # Step 3: Citation validation
                    self._validate_citation(suggestion)

                    # Step 4: ENVO term validation
                    self._validate_envo_term(suggestion)

                    # Step 5: Evidence quality scoring
                    self._score_evidence_quality(suggestion)

                    # Step 6: Determine decision
                    suggestion.determine_decision(
                        auto_accept_threshold=auto_accept_threshold,
                        manual_review_threshold=self.manual_review_threshold
                    )

                    # Additional constraint: no auto-accept for INFERRED citations
                    if require_citations and suggestion.evidence.reference == "INFERRED":
                        if suggestion.decision == "AUTO_ACCEPT":
                            suggestion.decision = "MANUAL_REVIEW"
                            logger.info(f"Downgraded {suggestion.media_id} to MANUAL_REVIEW "
                                       f"(INFERRED citation)")

                    # Route to appropriate list
                    if suggestion.decision == "AUTO_ACCEPT":
                        results["auto_accepted"].append(suggestion)
                    elif suggestion.decision == "MANUAL_REVIEW":
                        results["manual_review"].append(suggestion)
                    else:
                        results["rejected"].append(suggestion)

                except Exception as e:
                    logger.error(f"Error processing {suggestion.media_id}: {e}")
                    results["errors"].append({
                        "media_id": suggestion.media_id,
                        "error": str(e)
                    })

            # Calculate metrics
            results["metrics"] = self._calculate_metrics(results)

            # Dry runs may emit review/report artifacts, but never source-data writes.
            self._save_manual_review_queue(results["manual_review"])

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            results["end_time"] = end_time.isoformat()
            results["duration_seconds"] = duration
            results["status"] = "partial_failure" if results["errors"] else "success"
            self._generate_report(results)

            logger.info(f"Pipeline complete in {duration:.1f}s: "
                       f"{len(results['auto_accepted'])} auto-accepted, "
                       f"{len(results['manual_review'])} for review, "
                       f"{len(results['rejected'])} rejected")

            return results

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            results["error"] = str(e)
            results["status"] = "failed"
            end_time = datetime.now()
            results["end_time"] = end_time.isoformat()
            results["duration_seconds"] = (end_time - start_time).total_seconds()
            self._generate_report(results)
            return results

    def _prioritize_candidates(
        self,
        media_records: List[Dict[str, Any]],
        tier: Optional[int],
        batch_size: int
    ) -> List[Dict[str, Any]]:
        """
        Prioritize media candidates based on tier or score.

        Args:
            media_records: All media records
            tier: Target tier (1, 2, or 3) or None for top-scoring
            batch_size: Number to select

        Returns:
            Prioritized media records
        """
        # Score all media
        scored_media = []
        for media in media_records:
            score = MediaPrioritizer.score_media(media)
            media_tier = MediaPrioritizer.identify_tier(score)
            scored_media.append({
                "media": media,
                "score": score,
                "tier": media_tier
            })

        # Filter by tier if specified
        if tier is not None:
            candidates = [item for item in scored_media if item["tier"] == tier]
        else:
            candidates = scored_media

        # Sort by score (highest first)
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # Take top N
        selected = candidates[:batch_size]

        logger.info(f"Selected {len(selected)} media: "
                   f"Tier 1={sum(1 for x in selected if x['tier'] == 1)}, "
                   f"Tier 2={sum(1 for x in selected if x['tier'] == 2)}, "
                   f"Tier 3={sum(1 for x in selected if x['tier'] == 3)}")

        return [item["media"] for item in selected]

    def _generate_suggestions(
        self,
        media_records: List[Dict[str, Any]]
    ) -> List[EnvironmentSuggestion]:
        """
        Generate environment suggestions using LLM.

        Args:
            media_records: Media to curate

        Returns:
            List of EnvironmentSuggestion objects
        """
        suggestions = []

        for media in media_records:
            try:
                if self.llm_curator:
                    # Use actual LLM curator
                    suggestion = self.llm_curator.suggest_environment(media)
                    logger.info(f"LLM generated suggestion for {media.get('id')}")
                else:
                    # Fallback to placeholder if LLM unavailable
                    logger.warning(f"Using fallback for {media.get('id')} (LLM unavailable)")
                    suggestion = self._create_placeholder_suggestion(media)

                suggestions.append(suggestion)

            except Exception as e:
                logger.error(f"Failed to generate suggestion for {media.get('id')}: {e}")
                # Try fallback on error
                try:
                    suggestion = self._create_placeholder_suggestion(media)
                    suggestions.append(suggestion)
                    logger.info(f"Used fallback suggestion for {media.get('id')} after error")
                except Exception as fallback_error:
                    logger.error(f"Fallback also failed for {media.get('id')}: {fallback_error}")

        return suggestions

    def _create_placeholder_suggestion(
        self,
        media: Dict[str, Any]
    ) -> EnvironmentSuggestion:
        """
        Create placeholder suggestion for testing.

        TODO: Replace with actual LLM call.
        """
        media_id = media.get("id", "UNKNOWN")
        media_name = media.get("name", "Unknown")

        # Extract basic signals for placeholder
        name_signals = EnvironmentSignalExtractor.extract_name_signals(media_name)
        environment_hint = name_signals[0] if name_signals else "unknown"

        # Map to ENVO term (very basic)
        envo_mapping = {
            "marine": ("sea water", "ENVO:00002149"),
            "soil": ("soil", "ENVO:00002982"),
            "freshwater": ("freshwater", "ENVO:00002011"),
            "peatland": ("peatland", "ENVO:00000044"),
        }

        preferred_term, envo_id = envo_mapping.get(
            environment_hint,
            ("unknown environment", "ENVO:00000000")  # Invalid for testing
        )

        return EnvironmentSuggestion(
            media_id=media_id,
            media_name=media_name,
            environment=EnvironmentTerm(
                preferred_term=preferred_term,
                envo_id=envo_id,
                envo_label=preferred_term,
                confidence=0.75  # Placeholder
            ),
            evidence=Evidence(
                reference="INFERRED",  # Placeholder
                snippet="Placeholder snippet for testing",
                explanation="Inferred from media name patterns",
                supports="SUPPORT"
            ),
            reasoning=f"Media name '{media_name}' suggests {environment_hint} environment"
        )

    def _validate_citation(self, suggestion: EnvironmentSuggestion):
        """Validate citation (Gate 3)."""
        reference = suggestion.evidence.reference

        if reference == "INFERRED":
            # No citation to validate
            suggestion.citation_valid = True  # Allow INFERRED but low score
            suggestion.citation_validity_score = 0.0
            suggestion.snippet_accuracy_score = 0.0
            return

        # Extract PMID
        pmid = reference.replace("PMID:", "").strip()

        # Validate via PubMed
        validation_result = self.pubmed_client.validate_citation(
            pmid=pmid,
            snippet=suggestion.evidence.snippet,
            medium_name=suggestion.media_name
        )

        suggestion.citation_valid = validation_result.valid

        if validation_result.valid:
            suggestion.citation_validity_score = 1.0 if validation_result.article else 0.5
            suggestion.snippet_accuracy_score = validation_result.snippet_score
        else:
            suggestion.citation_validity_score = 0.0
            suggestion.snippet_accuracy_score = 0.0
            logger.warning(f"Citation validation failed for {suggestion.media_id}: "
                          f"{validation_result.error}")

    def _validate_envo_term(self, suggestion: EnvironmentSuggestion):
        """Validate ENVO term (Gate 4)."""
        envo_id = suggestion.environment.envo_id

        # Check format
        import re
        if not re.match(r'^ENVO:\d{7,8}$', envo_id):
            suggestion.ontology_valid = False
            suggestion.envo_correctness_score = 0.0
            logger.warning(f"Invalid ENVO ID format: {envo_id}")
            return

        # Validate via OAK (if available)
        try:
            # OAK validation
            term_label = self.oak_plugin.label(envo_id, source="ENVO")

            if term_label:
                suggestion.ontology_valid = True
                suggestion.envo_correctness_score = 1.0
                suggestion.environment.envo_label = term_label
            else:
                suggestion.ontology_valid = False
                suggestion.envo_correctness_score = 0.0
                logger.warning(f"ENVO term not found: {envo_id}")

        except Exception as e:
            # If OAK unavailable, accept format-valid terms
            logger.warning(f"OAK validation unavailable: {e}")
            suggestion.ontology_valid = True  # Trust format
            suggestion.envo_correctness_score = 0.8  # Lower confidence

    def _score_evidence_quality(self, suggestion: EnvironmentSuggestion):
        """
        Score evidence quality (Gate 5).

        Combines:
        - Citation validity (40%)
        - Snippet accuracy (30%)
        - ENVO correctness (20%)
        - Reasoning coherence (10%)
        """
        # Reasoning coherence (basic heuristic)
        suggestion.reasoning_coherence_score = EvidenceQualityScorer.score_reasoning_coherence(
            suggestion.reasoning
        )

        # Calculate overall evidence quality
        suggestion.calculate_evidence_quality_score()

        # Schema validation (Gate 1) - always true for our generated suggestions
        suggestion.schema_valid = True

        # Cross-consistency (Gate 4) - placeholder
        suggestion.cross_consistent = True

    def _save_manual_review_queue(self, review_queue: List[EnvironmentSuggestion]):
        """Save suggestions needing manual review."""
        if not review_queue:
            return

        review_file = self.review_dir / f"pending_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"

        review_data = []
        for suggestion in review_queue:
            review_data.append({
                "media_id": suggestion.media_id,
                "media_name": suggestion.media_name,
                "suggestion": {
                    "environment": {
                        "preferred_term": suggestion.environment.preferred_term,
                        "envo_id": suggestion.environment.envo_id,
                        "confidence": suggestion.environment.confidence
                    },
                    "evidence": {
                        "reference": suggestion.evidence.reference,
                        "snippet": suggestion.evidence.snippet,
                        "explanation": suggestion.evidence.explanation
                    },
                    "reasoning": suggestion.reasoning
                },
                "scores": {
                    "evidence_quality": suggestion.evidence_quality_score,
                    "citation_validity": suggestion.citation_validity_score,
                    "snippet_accuracy": suggestion.snippet_accuracy_score,
                    "envo_correctness": suggestion.envo_correctness_score
                },
                "decision": "PENDING",
                "reviewer_notes": ""
            })

        with open(review_file, 'w') as f:
            yaml.dump(review_data, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Saved {len(review_queue)} suggestions to {review_file}")

    def _calculate_metrics(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate pipeline metrics."""
        total = len(results["suggestions"])
        auto_accepted = len(results["auto_accepted"])
        manual_review = len(results["manual_review"])
        rejected = len(results["rejected"])

        # Count PMIDs vs INFERRED
        pmid_count = sum(
            1 for s in results["suggestions"]
            if s.evidence.reference != "INFERRED"
        )

        return {
            "total_suggestions": total,
            "auto_accepted": auto_accepted,
            "manual_review": manual_review,
            "rejected": rejected,
            "auto_accept_rate": auto_accepted / total if total > 0 else 0.0,
            "pmid_discovery_rate": pmid_count / total if total > 0 else 0.0,
            "validation_failure_rate": rejected / total if total > 0 else 0.0,
        }

    def _generate_report(self, results: Dict[str, Any]):
        """Generate curation report."""
        report_file = self.reports_dir / f"curation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # Prepare serializable results
        serializable_results = {
            "start_time": results["start_time"],
            "end_time": results.get("end_time"),
            "duration_seconds": results.get("duration_seconds"),
            "total_media": results["total_media"],
            "batch_size": results["batch_size"],
            "tier": results["tier"],
            "status": results["status"],
            "metrics": results["metrics"],
            "suggestions_count": len(results["suggestions"]),
            "auto_accepted_count": len(results["auto_accepted"]),
            "manual_review_count": len(results["manual_review"]),
            "rejected_count": len(results["rejected"]),
            "errors_count": len(results["errors"]),
            "error": results.get("error"),
        }

        with open(report_file, 'w') as f:
            json.dump(serializable_results, f, indent=2)

        logger.info(f"Generated report: {report_file}")
