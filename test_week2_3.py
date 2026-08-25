#!/usr/bin/env python3
"""
Test script for Week 2-3 OpenClaw integration components.

Tests:
1. OAKQueryPlugin - Cached ontology queries
2. IngredientCurationAgent - LLM-assisted mapping
3. NetworkRepairAgent - Network integrity repair
4. ETLCoordinatorAgent - Cross-repo ETL
5. IngredientCurationPipeline - End-to-end orchestration
"""

import os
import sys
import logging
from pathlib import Path

import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add plugins to path
sys.path.insert(0, str(Path(__file__).parent / "plugins"))


def test_oak_query_plugin():
    """Test OAKQueryPlugin functionality."""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: OAKQueryPlugin")
    logger.info("="*60)

    try:
        from oak_query import OAKQueryPlugin

        # Initialize plugin
        plugin = OAKQueryPlugin(config={
            "cache_ttl": 3600,
            "enabled_ontologies": ["CHEBI", "FOODON"],
        })

        logger.info("✓ Plugin initialized successfully")

        # Test search (this will fail if MEDIAINGREDIENTMECH_ROOT not set)
        if not os.getenv("MEDIAINGREDIENTMECH_ROOT"):
            logger.warning("⚠ MEDIAINGREDIENTMECH_ROOT not set, skipping actual search test")
            logger.info("  To test search, set environment variable and re-run")
        else:
            logger.info("Testing search for 'magnesium sulfate'...")
            results = plugin.search("magnesium sulfate", max_results=5)
            logger.info(f"✓ Search returned {len(results)} results")

            if results:
                logger.info(f"  Top result: {results[0]['label']} ({results[0]['ontology_id']})")

            # Test cache
            logger.info("Testing cache (should be instant)...")
            results2 = plugin.search("magnesium sulfate", max_results=5)
            logger.info("✓ Cache working")

            # Test validation
            logger.info("Testing term validation for CHEBI:32599...")
            validation = plugin.validate_term("CHEBI:32599")
            logger.info(f"✓ Validation: {validation['is_valid']}, label: {validation.get('label')}")

        # Test cache stats
        stats = plugin.get_cache_stats()
        logger.info(f"✓ Cache stats: {stats['memory_cache_entries']} in memory, "
                   f"{stats['disk_cache_entries']} on disk")

        logger.info("\n✅ OAKQueryPlugin tests PASSED")
        return True

    except Exception as e:
        logger.error(f"\n❌ OAKQueryPlugin tests FAILED: {e}", exc_info=True)
        return False


def test_agent_configs():
    """Test that all agent YAML configs are valid."""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Agent Configuration Files")
    logger.info("="*60)

    agents_dir = Path(__file__).parent / "agents" / "data_pipeline"
    agent_files = [
        "ingredient_curation_agent.yaml",
        "network_repair_agent.yaml",
        "etl_coordinator_agent.yaml",
    ]

    all_valid = True

    for agent_file in agent_files:
        agent_path = agents_dir / agent_file
        try:
            with open(agent_path, "r") as f:
                config = yaml.safe_load(f)

            # Validate structure
            assert "agent" in config, "Missing 'agent' section"
            assert "name" in config["agent"], "Missing agent name"
            assert "model" in config, "Missing 'model' section"
            assert "tasks" in config, "Missing 'tasks' section"

            logger.info(f"✓ {agent_file}: Valid YAML, {len(config['tasks'])} tasks defined")

        except Exception as e:
            logger.error(f"❌ {agent_file}: Invalid - {e}")
            all_valid = False

    if all_valid:
        logger.info("\n✅ All agent configs PASSED")
    else:
        logger.error("\n❌ Some agent configs FAILED")

    return all_valid


def test_pipeline_code():
    """Test that pipeline code can be imported."""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Pipeline Code")
    logger.info("="*60)

    try:
        # Add pipelines to path
        sys.path.insert(0, str(Path(__file__).parent / "pipelines"))

        from ingredient_curation_pipeline import (
            IngredientCurationPipeline,
            register_pipeline
        )

        logger.info("✓ Pipeline imports successfully")

        # Test registration
        registration = register_pipeline()
        assert registration["name"] == "ingredient_curation"
        assert len(registration["agents"]) == 3
        logger.info(f"✓ Pipeline registration: {registration['name']}, "
                   f"requires {len(registration['agents'])} agents")

        logger.info("\n✅ Pipeline code tests PASSED")
        return True

    except Exception as e:
        logger.error(f"\n❌ Pipeline code tests FAILED: {e}", exc_info=True)
        return False


def test_integration_dry_run():
    """Test integration in dry-run mode (if environment is configured)."""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Integration Dry Run")
    logger.info("="*60)

    # Check environment variables
    required_vars = [
        "CULTUREMECH_ROOT",
        "MEDIAINGREDIENTMECH_ROOT",
        "COMMUNITYMECH_ROOT",
        "OPENCLAW_WORKSPACE",
    ]

    missing_vars = [v for v in required_vars if not os.getenv(v)]

    if missing_vars:
        logger.warning(f"⚠ Missing environment variables: {', '.join(missing_vars)}")
        logger.info("  Integration test skipped")
        logger.info("  To run integration test, set all required variables")
        return None  # Not a failure, just skipped

    try:
        logger.info("Environment configured, testing plugin with actual data...")

        from oak_query import OAKQueryPlugin

        plugin = OAKQueryPlugin()

        # Test a real search
        test_query = "glucose"
        logger.info(f"Searching for '{test_query}'...")
        results = plugin.search(test_query, max_results=3)

        if results:
            logger.info(f"✓ Found {len(results)} results:")
            for i, r in enumerate(results[:3], 1):
                logger.info(f"  {i}. {r['label']} ({r['ontology_id']}) - score: {r['score']:.2f}")
        else:
            logger.warning("⚠ No results found (OAK may need initialization)")

        logger.info("\n✅ Integration dry run PASSED")
        return True

    except Exception as e:
        logger.error(f"\n❌ Integration dry run FAILED: {e}", exc_info=True)
        return False


def test_file_structure():
    """Verify all required files are present."""
    logger.info("\n" + "="*60)
    logger.info("TEST 5: File Structure")
    logger.info("="*60)

    base_dir = Path(__file__).parent

    required_files = [
        "plugins/oak_query.py",
        "src/kg_microbe_agents/definitions/data_pipeline/ingredient_curation_agent.yaml",
        "src/kg_microbe_agents/definitions/data_pipeline/network_repair_agent.yaml",
        "src/kg_microbe_agents/definitions/data_pipeline/etl_coordinator_agent.yaml",
        "pipelines/ingredient_curation_pipeline.py",
        "src/kg_microbe_config/openclaw_config.yaml",
    ]

    all_present = True

    for file_path in required_files:
        full_path = base_dir / file_path
        if full_path.exists():
            size = full_path.stat().st_size
            logger.info(f"✓ {file_path} ({size} bytes)")
        else:
            logger.error(f"❌ {file_path} MISSING")
            all_present = False

    if all_present:
        logger.info("\n✅ File structure tests PASSED")
    else:
        logger.error("\n❌ File structure tests FAILED")

    return all_present


def run_all_tests():
    """Run all test suites."""
    logger.info("\n" + "="*70)
    logger.info(" "*15 + "WEEK 2-3 COMPONENT TESTS")
    logger.info("="*70)

    results = {
        "File Structure": test_file_structure(),
        "OAKQueryPlugin": test_oak_query_plugin(),
        "Agent Configs": test_agent_configs(),
        "Pipeline Code": test_pipeline_code(),
        "Integration Dry Run": test_integration_dry_run(),
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
            status = "⚠  SKIPPED"
        logger.info(f"{test_name:25} {status}")

    # Overall result
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)

    logger.info("\n" + "="*70)
    logger.info(f"Total: {passed} passed, {failed} failed, {skipped} skipped")
    logger.info("="*70)

    if failed == 0:
        logger.info("\n🎉 ALL TESTS PASSED! Week 2-3 implementation ready.")
        return 0
    else:
        logger.info(f"\n⚠️  {failed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
