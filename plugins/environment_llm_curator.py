"""
Environment LLM Curator

LLM-assisted environment curation with PMID discovery.

Adapts the LLMCurator pattern from ingredient curation for environment-specific needs:
- Identifies ENVO terms for media source environments
- Discovers PMIDs linking media to environments
- Provides reasoning and confidence scores
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

from plugins.environment_curator import EnvironmentSuggestion, EnvironmentTerm, Evidence

logger = logging.getLogger(__name__)


class EnvironmentLLMCurator:
    """LLM-assisted curation for environment mappings with citation discovery."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None
    ):
        """
        Initialize environment LLM curator.

        Args:
            model: Claude model identifier
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Set it with: export ANTHROPIC_API_KEY=your-api-key"
            )

        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError(
                "anthropic package not installed. "
                "Install with: pip install anthropic"
            )

    def suggest_environment(
        self,
        media: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> EnvironmentSuggestion:
        """
        Get LLM suggestion for environment with PMID citation.

        Args:
            media: Media record dictionary
            context: Optional additional context

        Returns:
            EnvironmentSuggestion with ENVO term, PMID, and reasoning
        """
        media_id = media.get("id", "UNKNOWN")
        media_name = media.get("name", "Unknown")

        prompt = self._build_prompt(media, context)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=0,  # Deterministic
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            # Parse response
            content = response.content[0].text
            suggestion = self._parse_response(content, media_id, media_name)

            logger.info(
                f"LLM suggested {suggestion.environment.envo_id} for '{media_name}' "
                f"with confidence {suggestion.environment.confidence}, "
                f"citation: {suggestion.evidence.reference}"
            )

            return suggestion

        except Exception as e:
            logger.error(f"LLM API error for {media_id}: {e}")
            raise

    def _build_prompt(
        self,
        media: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build prompt for environment curation."""
        context = context or {}

        # Extract media info
        media_id = media.get("id", "UNKNOWN")
        media_name = media.get("name", "Unknown")
        category = media.get("category", "UNKNOWN")
        description = media.get("description", "")
        ph = media.get("pH", "")

        # Extract organism info
        organism_info = media.get("organism_info", media.get("target_organisms", ""))

        # Extract ingredients (key ones that might signal environment)
        ingredients = media.get("ingredients", [])
        key_ingredients = []
        for ing in ingredients[:10]:  # First 10
            preferred_term = ing.get("preferred_term", "")
            concentration = ing.get("concentration", {})
            if concentration:
                conc_str = f"{concentration.get('value', '')} {concentration.get('unit', '')}"
                key_ingredients.append(f"{preferred_term} ({conc_str})")
            else:
                key_ingredients.append(preferred_term)

        # Extract existing references
        existing_refs = media.get("references", [])
        ref_str = ", ".join(existing_refs[:3]) if existing_refs else "None"

        # Build prompt
        prompt = f"""You are an expert microbiology curator identifying source environments for culture media.

**Task:** Identify the PRIMARY source environment for this medium with PMID citation support.

**Medium Information:**
- ID: {media_id}
- Name: {media_name}
- Category: {category}
- pH: {ph or "Not specified"}

**Description:**
{description[:500] if description else "Not available"}

**Target Organisms:**
{organism_info[:300] if organism_info else "Not specified"}

**Key Ingredients:**
{', '.join(key_ingredients[:10])}

**Existing References:**
{ref_str}

**Your Task:**
1. Identify the PRIMARY source environment this medium targets
2. Find a PMID (PubMed ID) that supports this environment assertion
3. Provide reasoning for your choice

**Output Format (JSON):**
{{
  "environment": {{
    "preferred_term": "sea water",
    "envo_id": "ENVO:00002149",
    "envo_label": "sea water",
    "confidence": 0.95
  }},
  "evidence": {{
    "reference": "PMID:12345678",
    "snippet": "This medium was designed for isolation of marine bacteria from coastal seawater samples.",
    "explanation": "Original publication describes medium development for marine bacteria isolation",
    "supports": "SUPPORT"
  }},
  "reasoning": "Medium name includes 'Marine', high NaCl concentration (25 g/L) indicates seawater salinity, target organisms are halophilic bacteria from marine environments",
  "alternative_terms": ["marine water", "coastal water"],
  "search_strategy": "Searched PubMed for '{media_name} marine bacteria isolation' to find original publication"
}}

**Critical Requirements:**
1. **ENVO ID Format**: Must be ENVO:NNNNNNN or ENVO:NNNNNNNN (7-8 digits)
2. **Common ENVO Terms for Microbiology**:
   - ENVO:00002149 = sea water (marine)
   - ENVO:00002982 = soil
   - ENVO:00000044 = peatland
   - ENVO:00002011 = freshwater
   - ENVO:01000030 = hydrothermal vent
   - ENVO:00002044 = hypersaline lake
   - ENVO:00002150 = coastal water
   - ENVO:00002982 = soil
   - ENVO:00000134 = permafrost

3. **Citation Requirements**:
   - PREFER PMIDs: Search PubMed for medium name + organism ecology + "isolation" or "cultivation"
   - ACCEPT DOIs if PMID unavailable
   - Use "INFERRED" ONLY if no citation found (will trigger manual review)
   - **NEVER fabricate PMIDs** - if you're not confident in the PMID, use "INFERRED"

4. **Confidence Scoring**:
   - 0.95-1.0: Direct citation with explicit environment statement
   - 0.85-0.94: Strong inference from name + organisms + composition
   - 0.70-0.84: Moderate inference, some ambiguity
   - <0.70: Uncertain, needs expert review

5. **Environment Selection**:
   - Choose the MOST SPECIFIC appropriate environment
   - If multiple environments apply, choose the primary one
   - Consider: medium name, organism ecology, ingredient composition, pH, salinity

**Example Signals:**
- "Marine" in name + high NaCl → ENVO:00002149 (sea water)
- "Soil" in name + neutral pH → ENVO:00002982 (soil)
- Low pH (3-4) + humic acids → ENVO:00000044 (peatland)
- Thermophilic organisms + sulfur compounds → ENVO:01000030 (hydrothermal vent)
- High NaCl (>30 g/L) → ENVO:00002044 (hypersaline lake)

**Search Strategy Examples:**
- For "Marine Agar 2216": Search "Marine Agar 2216 Zobell marine bacteria"
- For "R2A Medium": Search "R2A medium freshwater bacteria heterotrophic"
- For custom media: Search "{media_name} {organism type} isolation {environment hint}"

**Output only valid JSON. Do not include any text before or after the JSON object.**
"""

        return prompt

    def _parse_response(
        self,
        content: str,
        media_id: str,
        media_name: str
    ) -> EnvironmentSuggestion:
        """Parse LLM response into EnvironmentSuggestion."""
        try:
            # Extract JSON from response (handle potential markdown)
            json_str = content.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            # Extract environment
            env_data = data.get("environment", {})
            environment = EnvironmentTerm(
                preferred_term=env_data.get("preferred_term", "unknown"),
                envo_id=env_data.get("envo_id", "ENVO:00000000"),
                envo_label=env_data.get("envo_label"),
                confidence=float(env_data.get("confidence", 0.0))
            )

            # Extract evidence
            ev_data = data.get("evidence", {})
            evidence = Evidence(
                reference=ev_data.get("reference", "INFERRED"),
                snippet=ev_data.get("snippet", ""),
                explanation=ev_data.get("explanation", ""),
                supports=ev_data.get("supports", "SUPPORT")
            )

            # Create suggestion
            suggestion = EnvironmentSuggestion(
                media_id=media_id,
                media_name=media_name,
                environment=environment,
                evidence=evidence,
                reasoning=data.get("reasoning", ""),
                alternative_terms=data.get("alternative_terms", []),
                search_strategy=data.get("search_strategy")
            )

            return suggestion

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}\nContent: {content}")
            # Return fallback suggestion
            return self._create_fallback_suggestion(media_id, media_name, content)

        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return self._create_fallback_suggestion(media_id, media_name, content)

    def _create_fallback_suggestion(
        self,
        media_id: str,
        media_name: str,
        raw_content: str
    ) -> EnvironmentSuggestion:
        """Create fallback suggestion when parsing fails."""
        return EnvironmentSuggestion(
            media_id=media_id,
            media_name=media_name,
            environment=EnvironmentTerm(
                preferred_term="unknown environment",
                envo_id="ENVO:00000000",  # Invalid, will fail validation
                envo_label="unknown",
                confidence=0.0
            ),
            evidence=Evidence(
                reference="INFERRED",
                snippet="",
                explanation=f"LLM response parsing failed: {raw_content[:100]}",
                supports="NEUTRAL"
            ),
            reasoning="Failed to parse LLM response"
        )


# Singleton instance
_environment_llm_curator = None


def get_environment_llm_curator(
    model: str = "claude-sonnet-4-20250514",
    api_key: Optional[str] = None
) -> EnvironmentLLMCurator:
    """Get or create environment LLM curator singleton."""
    global _environment_llm_curator

    if _environment_llm_curator is None:
        _environment_llm_curator = EnvironmentLLMCurator(
            model=model,
            api_key=api_key
        )

    return _environment_llm_curator
