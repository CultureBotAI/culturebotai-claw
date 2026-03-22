#!/usr/bin/env python3
"""
Week 4 Step 1: OAK Verification

Verify that oaklib is installed and can access ontologies.
This script tests the OAKQueryPlugin with real ontology data.
"""

import os
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Add plugins to path
sys.path.insert(0, str(Path(__file__).parent / "plugins"))

def test_oak_installation():
    """Test that oaklib is installed and importable."""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: OAK Installation")
    logger.info("="*60)

    try:
        import oaklib
        logger.info(f"✓ oaklib imported successfully (version: {oaklib.__version__ if hasattr(oaklib, '__version__') else 'unknown'})")
        return True
    except ImportError as e:
        logger.error(f"❌ Failed to import oaklib: {e}")
        return False


def test_oak_adapter_loading():
    """Test that OAK adapters can be loaded."""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: OAK Adapter Loading")
    logger.info("="*60)

    try:
        from oaklib import get_adapter

        # Test CHEBI adapter
        logger.info("Testing CHEBI adapter...")
        chebi_adapter = get_adapter("sqlite:obo:chebi")
        logger.info("✓ CHEBI adapter loaded successfully")

        # Try a simple query
        logger.info("Testing basic search...")
        results = list(chebi_adapter.basic_search("glucose"))
        logger.info(f"✓ Search returned {len(results)} results")

        if results:
            # Get label for first result
            first_id = results[0]
            label = chebi_adapter.label(first_id)
            logger.info(f"  Example: {first_id} -> {label}")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to load OAK adapter: {e}")
        logger.info("  Note: First run may take 10-30 minutes to download ontologies")
        return False


def test_oak_query_plugin():
    """Test OAKQueryPlugin with real data."""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: OAKQueryPlugin Integration")
    logger.info("="*60)

    try:
        from oak_query import OAKQueryPlugin

        # Initialize plugin
        plugin = OAKQueryPlugin(config={
            "cache_ttl": 3600,
            "enabled_ontologies": ["CHEBI", "FOODON"],
        })
        logger.info("✓ Plugin initialized")

        # Test search
        logger.info("Testing search for 'glucose'...")
        results = plugin.search("glucose", max_results=5)
        logger.info(f"✓ Search returned {len(results)} results")

        if not results:
            logger.warning("⚠ No results found. OAK may still be initializing.")
            logger.info("  Try running again in a few minutes if this is first run.")
            return None

        # Display top results
        logger.info("\nTop results:")
        for i, result in enumerate(results[:3], 1):
            logger.info(f"  {i}. {result['label']}")
            logger.info(f"     ID: {result['ontology_id']}")
            logger.info(f"     Source: {result['source']}")
            logger.info(f"     Score: {result['score']:.3f}")

        # Test validation
        if results:
            test_id = results[0]['ontology_id']
            logger.info(f"\nTesting validation for {test_id}...")
            validation = plugin.validate_term(test_id)
            logger.info(f"✓ Valid: {validation['is_valid']}, Label: {validation.get('label')}")

        # Test caching
        logger.info("\nTesting cache (second query should be instant)...")
        import time
        start = time.time()
        results2 = plugin.search("glucose", max_results=5)
        elapsed = time.time() - start
        logger.info(f"✓ Cache query completed in {elapsed*1000:.1f}ms")

        # Cache stats
        stats = plugin.get_cache_stats()
        logger.info(f"\nCache statistics:")
        logger.info(f"  Memory entries: {stats['memory_cache_entries']}")
        logger.info(f"  Disk entries: {stats['disk_cache_entries']}")
        logger.info(f"  Disk size: {stats['disk_cache_size_mb']:.2f} MB")

        return True

    except Exception as e:
        logger.error(f"❌ OAKQueryPlugin test failed: {e}", exc_info=True)
        return False


def test_common_ingredients():
    """Test with common ingredient names from the project."""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Common Ingredient Queries")
    logger.info("="*60)

    try:
        from oak_query import OAKQueryPlugin

        plugin = OAKQueryPlugin(config={
            "enabled_ontologies": ["CHEBI", "FOODON"],
        })

        # Common ingredients to test
        test_ingredients = [
            "glucose",
            "sodium chloride",
            "magnesium sulfate",
            "agar",
            "yeast extract",
        ]

        results_summary = []

        for ingredient in test_ingredients:
            logger.info(f"\nSearching for '{ingredient}'...")
            results = plugin.search(ingredient, max_results=3)

            if results:
                top = results[0]
                logger.info(f"✓ Found: {top['label']} ({top['ontology_id']})")
                logger.info(f"  Confidence: {top['score']:.3f}")
                results_summary.append({
                    "ingredient": ingredient,
                    "found": True,
                    "top_match": top['label'],
                    "ontology_id": top['ontology_id'],
                    "confidence": top['score'],
                })
            else:
                logger.warning(f"⚠ No results for '{ingredient}'")
                results_summary.append({
                    "ingredient": ingredient,
                    "found": False,
                })

        # Summary
        logger.info("\n" + "="*60)
        logger.info("SUMMARY")
        logger.info("="*60)
        found_count = sum(1 for r in results_summary if r.get('found'))
        logger.info(f"Successfully mapped: {found_count}/{len(test_ingredients)} ingredients")

        for r in results_summary:
            if r.get('found'):
                logger.info(f"✓ {r['ingredient']}: {r['ontology_id']} (score: {r['confidence']:.3f})")
            else:
                logger.info(f"✗ {r['ingredient']}: No match")

        return found_count == len(test_ingredients)

    except Exception as e:
        logger.error(f"❌ Common ingredient test failed: {e}", exc_info=True)
        return False


def run_verification():
    """Run all verification tests."""
    logger.info("\n" + "="*70)
    logger.info(" "*15 + "WEEK 4 STEP 1: OAK VERIFICATION")
    logger.info("="*70)

    # Check environment
    mediaingredient_root = os.getenv("MEDIAINGREDIENTMECH_ROOT")
    if not mediaingredient_root:
        logger.error("❌ MEDIAINGREDIENTMECH_ROOT not set")
        logger.info("  Please set environment variable and re-run")
        return 1

    logger.info(f"MediaIngredientMech root: {mediaingredient_root}")

    # Run tests
    results = {
        "OAK Installation": test_oak_installation(),
        "OAK Adapter Loading": test_oak_adapter_loading(),
        "OAKQueryPlugin": test_oak_query_plugin(),
        "Common Ingredients": test_common_ingredients(),
    }

    # Summary
    logger.info("\n" + "="*70)
    logger.info(" "*20 + "TEST SUMMARY")
    logger.info("="*70)

    for test_name, result in results.items():
        if result is True:
            status = "✅ PASSED"
        elif result is False:
            status = "❌ FAILED"
        else:
            status = "⚠  INCOMPLETE (may need more time)"
        logger.info(f"{test_name:30} {status}")

    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    incomplete = sum(1 for r in results.values() if r is None)

    logger.info("\n" + "="*70)
    logger.info(f"Total: {passed} passed, {failed} failed, {incomplete} incomplete")
    logger.info("="*70)

    if failed == 0 and incomplete == 0:
        logger.info("\n🎉 OAK VERIFICATION COMPLETE! Ready for Step 2.")
        return 0
    elif incomplete > 0:
        logger.info("\n⏳ OAK may still be downloading ontologies. Wait 10-30 minutes and re-run.")
        return 2
    else:
        logger.info(f"\n⚠️  {failed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    exit_code = run_verification()
    sys.exit(exit_code)
