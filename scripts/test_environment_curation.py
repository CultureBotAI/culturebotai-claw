#!/usr/bin/env python3
"""
Test Environment Curation Pipeline

Quick integration test with 5 hand-picked media to verify:
- LLM curator generates suggestions
- PubMed validation works
- ENVO validation works
- Evidence scoring works
- Decision routing works
"""

import sys
from pathlib import Path
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.environment_curation_pipeline import EnvironmentCurationPipeline

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Test media: 5 hand-picked examples with clear environment signals
TEST_MEDIA = [
    {
        "id": "TEST:00001",
        "name": "Marine Agar 2216",
        "category": "marine",
        "description": "Standard medium for cultivation of heterotrophic marine bacteria",
        "target_organisms": "Heterotrophic marine bacteria",
        "ingredients": [
            {"preferred_term": "sodium chloride", "concentration": {"value": 19.45, "unit": "g/L"}},
            {"preferred_term": "peptone", "concentration": {"value": 5.0, "unit": "g/L"}},
            {"preferred_term": "yeast extract", "concentration": {"value": 1.0, "unit": "g/L"}}
        ],
        "pH": 7.6,
        "references": ["ZoBell, 1941"]
    },
    {
        "id": "TEST:00002",
        "name": "R2A Medium",
        "category": "general",
        "description": "Low-nutrient medium for heterotrophic bacteria from potable water",
        "target_organisms": "Freshwater heterotrophic bacteria",
        "ingredients": [
            {"preferred_term": "yeast extract", "concentration": {"value": 0.5, "unit": "g/L"}},
            {"preferred_term": "proteose peptone", "concentration": {"value": 0.5, "unit": "g/L"}},
            {"preferred_term": "glucose", "concentration": {"value": 0.5, "unit": "g/L"}}
        ],
        "pH": 7.2,
        "references": ["Reasoner and Geldreich, 1985"]
    },
    {
        "id": "TEST:00003",
        "name": "Acidic Peatland Medium",
        "category": "specialized",
        "description": "For cultivation of acidophilic bacteria from peatland environments",
        "target_organisms": "Acidophilic peatland bacteria",
        "ingredients": [
            {"preferred_term": "humic acid", "concentration": {"value": 1.0, "unit": "g/L"}},
            {"preferred_term": "glucose", "concentration": {"value": 2.0, "unit": "g/L"}}
        ],
        "pH": 4.0,
        "references": []
    },
    {
        "id": "TEST:00004",
        "name": "Thermophilic Soil Extract",
        "category": "specialized",
        "description": "For thermophilic bacteria from geothermal soils",
        "target_organisms": "Thermophilic bacteria, hot springs",
        "ingredients": [
            {"preferred_term": "soil extract", "concentration": {"value": 10.0, "unit": "g/L"}},
            {"preferred_term": "yeast extract", "concentration": {"value": 2.0, "unit": "g/L"}}
        ],
        "pH": 7.0,
        "conditions": {"temperature": "60°C"},
        "references": []
    },
    {
        "id": "TEST:00005",
        "name": "Generic Broth",
        "category": "general",
        "description": "General purpose growth medium",
        "target_organisms": "Various bacteria",
        "ingredients": [
            {"preferred_term": "peptone", "concentration": {"value": 5.0, "unit": "g/L"}},
            {"preferred_term": "beef extract", "concentration": {"value": 3.0, "unit": "g/L"}}
        ],
        "pH": 7.0,
        "references": []
    }
]


def main():
    """Run test curation."""
    print("\n" + "="*80)
    print("ENVIRONMENT CURATION PIPELINE - INTEGRATION TEST")
    print("="*80)
    print(f"\nTest media: {len(TEST_MEDIA)}")
    for i, media in enumerate(TEST_MEDIA, 1):
        print(f"  {i}. {media['name']} ({media['id']})")

    # Initialize pipeline
    print("\n" + "-"*80)
    print("Initializing pipeline...")
    print("-"*80)

    try:
        pipeline = EnvironmentCurationPipeline(config={
            "batch_size": 5,
            "auto_accept_threshold": 0.90,
            "manual_review_threshold": 0.70,
            "max_cost_per_run": 10.00
        })
        print("✓ Pipeline initialized")
    except Exception as e:
        print(f"✗ Pipeline initialization failed: {e}")
        return 1

    # Run curation
    print("\n" + "-"*80)
    print("Running curation pipeline...")
    print("-"*80)

    try:
        results = pipeline.run(
            media_records=TEST_MEDIA,
            batch_size=5,
            tier=None,  # Test all
            auto_accept_threshold=0.90,
            dry_run=True,  # Always dry-run for test
            require_citations=True
        )
        print("✓ Pipeline execution complete")
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        return 1

    # Display results
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)

    metrics = results.get('metrics', {})
    print(f"\nTotal suggestions: {metrics.get('total_suggestions', 0)}")
    print(f"Auto-accepted: {metrics.get('auto_accepted', 0)} ({metrics.get('auto_accept_rate', 0):.1%})")
    print(f"Manual review: {metrics.get('manual_review', 0)}")
    print(f"Rejected: {metrics.get('rejected', 0)}")
    print(f"PMID discovery rate: {metrics.get('pmid_discovery_rate', 0):.1%}")

    # Show details for each suggestion
    print("\n" + "-"*80)
    print("SUGGESTION DETAILS")
    print("-"*80)

    for i, suggestion in enumerate(results.get('suggestions', []), 1):
        print(f"\n[{i}] {suggestion.media_name} ({suggestion.media_id})")
        print(f"    Environment: {suggestion.environment.preferred_term} ({suggestion.environment.envo_id})")
        print(f"    Confidence: {suggestion.environment.confidence:.2f}")
        print(f"    Citation: {suggestion.evidence.reference}")
        print(f"    Evidence Quality: {suggestion.evidence_quality_score:.2f}")
        print(f"    Decision: {suggestion.decision}")
        print(f"    Reasoning: {suggestion.reasoning[:100]}...")

    # Validation checks
    print("\n" + "="*80)
    print("VALIDATION CHECKS")
    print("="*80)

    checks_passed = 0
    checks_total = 5

    # Check 1: All suggestions generated
    if metrics.get('total_suggestions', 0) == len(TEST_MEDIA):
        print("✓ All 5 media generated suggestions")
        checks_passed += 1
    else:
        print(f"✗ Expected 5 suggestions, got {metrics.get('total_suggestions', 0)}")

    # Check 2: No pipeline errors
    if len(results.get('errors', [])) == 0:
        print("✓ No pipeline errors")
        checks_passed += 1
    else:
        print(f"✗ {len(results.get('errors', []))} errors occurred")
        for error in results.get('errors', []):
            print(f"   - {error}")

    # Check 3: All suggestions have valid decisions
    valid_decisions = sum(
        1 for s in results.get('suggestions', [])
        if s.decision in ["AUTO_ACCEPT", "MANUAL_REVIEW", "REJECT"]
    )
    if valid_decisions == len(TEST_MEDIA):
        print("✓ All suggestions have valid decisions")
        checks_passed += 1
    else:
        print(f"✗ Only {valid_decisions}/{len(TEST_MEDIA)} have valid decisions")

    # Check 4: Evidence quality scores calculated
    scored = sum(
        1 for s in results.get('suggestions', [])
        if s.evidence_quality_score >= 0.0
    )
    if scored == len(TEST_MEDIA):
        print("✓ All suggestions have evidence quality scores")
        checks_passed += 1
    else:
        print(f"✗ Only {scored}/{len(TEST_MEDIA)} have quality scores")

    # Check 5: At least one ENVO term validated
    envo_validated = sum(
        1 for s in results.get('suggestions', [])
        if s.ontology_valid
    )
    if envo_validated > 0:
        print(f"✓ {envo_validated}/{len(TEST_MEDIA)} ENVO terms validated")
        checks_passed += 1
    else:
        print("✗ No ENVO terms validated")

    # Summary
    print("\n" + "="*80)
    print(f"CHECKS PASSED: {checks_passed}/{checks_total}")
    print("="*80)

    if checks_passed == checks_total:
        print("\n✅ All validation checks passed!")
        print("\nNext steps:")
        print("  1. Set ANTHROPIC_API_KEY environment variable")
        print("  2. Run pilot batch with real media from CultureMech")
        print("  3. Review manual queue and collect metrics")
        return 0
    else:
        print(f"\n⚠️  {checks_total - checks_passed} validation checks failed")
        print("Review errors above and fix issues before pilot run")
        return 1


if __name__ == "__main__":
    sys.exit(main())
