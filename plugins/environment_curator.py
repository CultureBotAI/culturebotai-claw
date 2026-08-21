"""
Environment Curator Plugin

Provides environment-specific curation logic including:
- EnvironmentSuggestion data structure
- Prioritization scoring for media selection
- Environment signal extraction
- Evidence quality scoring

Used by EnvironmentCurationPipeline for citation-backed environment curation.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentTerm:
    """ENVO environment term."""
    preferred_term: str
    envo_id: str
    envo_label: Optional[str] = None
    confidence: float = 0.0  # 0.0-1.0


@dataclass
class Evidence:
    """Citation evidence for environment assertion."""
    reference: str  # PMID:XXXXXXXX, DOI:..., or "INFERRED"
    snippet: str
    explanation: str
    supports: str = "SUPPORT"  # SUPPORT, REFUTE, NEUTRAL


@dataclass
class EnvironmentSuggestion:
    """
    LLM-generated environment suggestion with citation.

    This is the core data structure passed through the validation pipeline.
    """
    media_id: str
    media_name: str
    environment: EnvironmentTerm
    evidence: Evidence
    reasoning: str
    alternative_terms: List[str] = field(default_factory=list)
    search_strategy: Optional[str] = None

    # Quality scores (set by validation pipeline)
    citation_validity_score: float = 0.0  # Gate 3
    snippet_accuracy_score: float = 0.0  # Gate 3
    envo_correctness_score: float = 0.0  # Gate 4
    reasoning_coherence_score: float = 0.0  # Manual or heuristic
    evidence_quality_score: float = 0.0  # Overall (Gates 3-5)

    # Validation status
    schema_valid: bool = False  # Gate 1
    ontology_valid: bool = False  # Gate 2
    citation_valid: bool = False  # Gate 3
    cross_consistent: bool = False  # Gate 4
    overall_valid: bool = False  # All gates passed

    # Decision
    decision: str = "PENDING"  # AUTO_ACCEPT, MANUAL_REVIEW, REJECT

    def calculate_evidence_quality_score(self):
        """
        Calculate overall evidence quality score.

        Weights:
        - Citation validity: 40%
        - Snippet accuracy: 30%
        - ENVO correctness: 20%
        - Reasoning coherence: 10%
        """
        self.evidence_quality_score = (
            self.citation_validity_score * 0.40 +
            self.snippet_accuracy_score * 0.30 +
            self.envo_correctness_score * 0.20 +
            self.reasoning_coherence_score * 0.10
        )
        return self.evidence_quality_score

    def determine_decision(
        self,
        auto_accept_threshold: float = 0.90,
        manual_review_threshold: float = 0.70
    ):
        """
        Determine curation decision based on quality scores.

        Args:
            auto_accept_threshold: Threshold for automatic acceptance
            manual_review_threshold: Minimum threshold for manual review

        Returns:
            Decision: AUTO_ACCEPT, MANUAL_REVIEW, or REJECT
        """
        # Must pass all validation gates
        if not (self.schema_valid and self.ontology_valid and
                self.citation_valid and self.cross_consistent):
            self.decision = "REJECT"
            self.overall_valid = False
            return self.decision

        # Calculate overall score if not already done
        if self.evidence_quality_score == 0.0:
            self.calculate_evidence_quality_score()

        # Check confidence + evidence quality
        combined_score = min(
            self.environment.confidence,
            self.evidence_quality_score
        )

        if combined_score >= auto_accept_threshold:
            self.decision = "AUTO_ACCEPT"
            self.overall_valid = True
        elif combined_score >= manual_review_threshold:
            self.decision = "MANUAL_REVIEW"
            self.overall_valid = True
        else:
            self.decision = "REJECT"
            self.overall_valid = False

        return self.decision


class EnvironmentSignalExtractor:
    """
    Extract environment signals from media metadata.

    Signals include:
    - Name patterns ("Marine", "Soil", "Freshwater")
    - Salinity markers (high NaCl → marine)
    - pH extremes (acidic → peatland/hot spring)
    - Organism ecology hints
    - Ingredient environmental markers
    """

    # Environment keywords in media names
    ENVIRONMENT_KEYWORDS = {
        "marine": ["marine", "sea water", "seawater", "ocean", "coastal"],
        "soil": ["soil", "terrestrial", "earth"],
        "freshwater": ["freshwater", "lake", "river", "pond"],
        "hydrothermal": ["hydrothermal", "vent", "geothermal"],
        "peatland": ["peat", "bog", "fen", "mire"],
        "halophilic": ["halophil", "hypersaline", "salt lake"],
        "acidic": ["acidic", "acidophil"],
        "alkaline": ["alkaline", "alkaliphil", "soda lake"],
    }

    @staticmethod
    def extract_name_signals(media_name: str) -> List[str]:
        """Extract environment signals from media name."""
        signals = []
        name_lower = media_name.lower()

        for env, keywords in EnvironmentSignalExtractor.ENVIRONMENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in name_lower:
                    signals.append(env)
                    break

        return signals

    @staticmethod
    def extract_salinity_signal(ingredients: List[Dict[str, Any]]) -> Optional[str]:
        """
        Extract salinity signal from ingredients.

        High NaCl (>1% w/v) suggests marine or halophilic environment.
        """
        for ingredient in ingredients:
            preferred_term = ingredient.get("preferred_term", "").lower()
            concentration = ingredient.get("concentration", {})

            if "nacl" in preferred_term or "sodium chloride" in preferred_term:
                value_str = concentration.get("value", "0")
                unit = concentration.get("unit", "")

                try:
                    value = float(value_str)

                    # Convert to g/L if needed
                    if unit in ["G_PER_L", "g/L"]:
                        g_per_l = value
                    elif unit in ["PERCENT", "%"]:
                        g_per_l = value * 10  # 1% = 10 g/L
                    elif unit in ["MOLAR", "M"]:
                        g_per_l = value * 58.44  # NaCl MW = 58.44
                    else:
                        continue

                    # Thresholds
                    if g_per_l > 30:  # ~3% = hypersaline
                        return "halophilic"
                    elif g_per_l > 10:  # ~1% = marine
                        return "marine"

                except (ValueError, TypeError):
                    continue

        return None

    @staticmethod
    def extract_ph_signal(ph_value: Optional[str]) -> Optional[str]:
        """
        Extract pH signal.

        Low pH (< 4.5) suggests acidic environments (peatland, hot spring).
        High pH (> 9) suggests alkaline environments (soda lake).
        """
        if not ph_value:
            return None

        try:
            # Parse pH (handle ranges like "3.5-4.5")
            ph_str = str(ph_value).replace("pH", "").strip()

            if "-" in ph_str:
                ph_parts = ph_str.split("-")
                ph = (float(ph_parts[0]) + float(ph_parts[1])) / 2
            else:
                ph = float(ph_str)

            if ph < 4.5:
                return "acidic"
            elif ph > 9.0:
                return "alkaline"

        except (ValueError, TypeError):
            pass

        return None

    @staticmethod
    def extract_organism_signal(organism_info: Optional[Dict[str, Any]]) -> List[str]:
        """
        Extract environment signals from organism information.

        Looks for ecology hints in organism names or descriptions.
        """
        signals = []

        if not organism_info:
            return signals

        organism_text = str(organism_info).lower()

        # Marine indicators
        if any(word in organism_text for word in ["marine", "ocean", "sea", "halophil"]):
            signals.append("marine")

        # Thermophilic indicators
        if any(word in organism_text for word in ["thermophil", "hyperthermophil", "thermal"]):
            signals.append("hydrothermal")

        # Soil indicators
        if any(word in organism_text for word in ["soil", "terrestrial", "rhizosphere"]):
            signals.append("soil")

        # Acidophilic indicators
        if "acidophil" in organism_text:
            signals.append("acidic")

        return signals


class MediaPrioritizer:
    """
    Prioritize media for environment curation.

    Scoring algorithm:
    - Name clarity: 30%
    - Organism context: 25%
    - Usage frequency: 20%
    - Cross-linking: 15%
    - Curation confidence: 10%
    """

    @staticmethod
    def score_media(media: Dict[str, Any]) -> float:
        """
        Calculate priority score for a media record.

        Args:
            media: Media record dictionary

        Returns:
            Priority score (0.0-1.0, higher = higher priority)
        """
        name_score = MediaPrioritizer._score_name_clarity(media.get("name", ""))
        organism_score = MediaPrioritizer._score_organism_context(media.get("organism_info"))
        usage_score = MediaPrioritizer._score_usage_frequency(media)
        linking_score = MediaPrioritizer._score_cross_linking(media)
        confidence_score = MediaPrioritizer._score_curation_confidence(media)

        total_score = (
            name_score * 0.30 +
            organism_score * 0.25 +
            usage_score * 0.20 +
            linking_score * 0.15 +
            confidence_score * 0.10
        )

        return total_score

    @staticmethod
    def _score_name_clarity(name: str) -> float:
        """Score how clear the medium name is about environment."""
        signals = EnvironmentSignalExtractor.extract_name_signals(name)

        # More signals = clearer
        if len(signals) >= 2:
            return 1.0
        elif len(signals) == 1:
            return 0.7
        elif any(word in name.lower() for word in ["medium", "agar", "broth"]):
            return 0.3  # Generic but standard name
        else:
            return 0.1  # Unclear name

    @staticmethod
    def _score_organism_context(organism_info: Optional[Dict[str, Any]]) -> float:
        """Score strength of organism context."""
        if not organism_info:
            return 0.0

        signals = EnvironmentSignalExtractor.extract_organism_signal(organism_info)
        return min(len(signals) * 0.4, 1.0)

    @staticmethod
    def _score_usage_frequency(media: Dict[str, Any]) -> float:
        """Score usage frequency (placeholder - would need usage data)."""
        # TODO: Implement based on actual usage statistics
        # For now, return medium score
        return 0.5

    @staticmethod
    def _score_cross_linking(media: Dict[str, Any]) -> float:
        """Score potential for cross-repo linking."""
        # Check if media has existing references
        references = media.get("references", [])
        if references:
            return 0.8

        # Check if media has structured organism info
        if media.get("organism_info"):
            return 0.6

        return 0.2

    @staticmethod
    def _score_curation_confidence(media: Dict[str, Any]) -> float:
        """Estimate likelihood of successful curation."""
        # Combine all signals
        name_signals = EnvironmentSignalExtractor.extract_name_signals(
            media.get("name", "")
        )
        organism_signals = EnvironmentSignalExtractor.extract_organism_signal(
            media.get("organism_info")
        )
        has_references = bool(media.get("references"))

        signal_count = len(name_signals) + len(organism_signals)

        if signal_count >= 2 and has_references:
            return 1.0
        elif signal_count >= 2:
            return 0.8
        elif signal_count >= 1:
            return 0.6
        else:
            return 0.3

    @staticmethod
    def identify_tier(priority_score: float) -> int:
        """
        Identify tier based on priority score.

        Args:
            priority_score: Score from 0.0-1.0

        Returns:
            Tier (1, 2, or 3)
        """
        if priority_score >= 0.70:
            return 1  # High-confidence, high-impact
        elif priority_score >= 0.40:
            return 2  # Medium difficulty, strategic
        else:
            return 3  # Long-tail


class EvidenceQualityScorer:
    """Score evidence quality for environment assertions."""

    @staticmethod
    def score_citation_validity(
        pmid: str,
        pmid_exists: bool,
        abstract_available: bool
    ) -> float:
        """
        Score citation validity.

        Args:
            pmid: PMID reference
            pmid_exists: Whether PMID exists in PubMed
            abstract_available: Whether abstract is available

        Returns:
            Score 0.0-1.0
        """
        if pmid == "INFERRED":
            return 0.0  # No citation

        if not pmid_exists:
            return 0.0  # Invalid PMID

        if abstract_available:
            return 1.0  # Valid with abstract

        return 0.5  # Valid but no abstract

    @staticmethod
    def score_snippet_accuracy(
        snippet: str,
        abstract_text: str,
        medium_name: str
    ) -> float:
        """
        Score snippet accuracy.

        Args:
            snippet: Claimed snippet from publication
            abstract_text: Full abstract text
            medium_name: Medium name to check

        Returns:
            Score 0.0-1.0
        """
        if not snippet or not abstract_text:
            return 0.0

        abstract_lower = abstract_text.lower()
        snippet_lower = snippet.lower()

        # Exact match
        if snippet_lower in abstract_lower:
            return 1.0

        # Partial match (word overlap)
        snippet_words = set(snippet_lower.split())
        abstract_words = set(abstract_lower.split())
        overlap = snippet_words & abstract_words
        score = len(overlap) / len(snippet_words) if snippet_words else 0.0

        # Bonus if medium name is mentioned
        if medium_name.lower() in abstract_lower:
            score = min(score + 0.2, 1.0)

        return score

    @staticmethod
    def score_reasoning_coherence(reasoning: str) -> float:
        """
        Score reasoning coherence (basic heuristic).

        Args:
            reasoning: LLM reasoning text

        Returns:
            Score 0.0-1.0
        """
        if not reasoning:
            return 0.0

        # Length check (too short = not detailed enough)
        if len(reasoning) < 20:
            return 0.3

        # Check for key phrases
        good_phrases = [
            "indicates", "suggests", "based on", "because",
            "environment", "organism", "medium", "designed"
        ]
        phrase_count = sum(1 for phrase in good_phrases if phrase in reasoning.lower())

        score = min(phrase_count * 0.2 + 0.4, 1.0)
        return score
