"""The pending admission exposes identity without claiming scaffold deployment."""

from pathlib import Path

import pytest
import yaml

from kg_microbe_config import default_config_path
from kg_microbe_embeddings.rollout import load_rollout
from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_governance import load_governance_manifest
from kg_microbe_merge_queue import load_policy
from plugins.repository_settings import RepositoryConfigurationError, RepositorySettings

ROOT = Path(__file__).resolve().parents[1]


def test_scaleup_identity_is_consistent_across_runtime_surfaces():
    fleet = load_fleet_manifest()
    mech = fleet.get("scaleupmech")
    assert mech.github == "CultureBotAI/ScaleupMech"
    assert mech.environment_variable == "SCALEUPMECH_ROOT"
    assert mech.package_path == "src/scaleupmech"
    assert mech.schema_paths == ("src/scaleupmech/schema/scaleupmech.yaml",)
    assert mech.record_globs == ("data/scale_transfers/*.yaml",)
    consumer = load_governance_manifest().consumer_for("scaleupmech")
    assert (consumer.github, consumer.package_path) == (mech.github, mech.package_path)
    config = yaml.safe_load(default_config_path().read_text())
    assert config["repositories"][mech.key]["path"] == "${SCALEUPMECH_ROOT}"
    assert "SCALEUPMECH_ROOT=/absolute/path/to/ScaleupMech" in (ROOT / ".env.example").read_text()
    research = yaml.safe_load((ROOT / "src/kg_microbe_research/schema/research.yaml").read_text())
    assert "ScaleupMech" in research["enums"]["MechEnum"]["permissible_values"]


def test_empty_main_admission_does_not_enable_unverified_implementation():
    mech = load_fleet_manifest().get("scaleupmech")
    assert {key for key, cap in mech.capabilities.items() if cap.is_enabled} == {"vendored_sync"}
    assert mech.serialization is not None
    assert not mech.serialization.verified
    assert not mech.serialization.options
    plan = load_rollout()["mechs"]["scaleupmech"]
    assert plan["revision"] == "38f8157fc960299f2458f4916dd581ce1b5d0262"
    assert plan["native"] == "no_pipeline_in_audited_source"
    assert plan["sets"]["record-text"]["state"] == "planned"


def test_queue_mapping_names_the_scaffold_check_without_enabling_rules():
    assert load_policy()["scaleupmech"] == {
        ".github/workflows/validate-strict.yaml": ["validate-strict"],
    }


def test_new_member_is_visible_without_a_configured_root():
    settings = RepositorySettings.from_environment(environ={})
    assert "scaleupmech" in settings.names
    assert "scaleupmech" in settings.unconfigured
    assert "scaleupmech" not in settings.paths
    with pytest.raises(RepositoryConfigurationError, match="SCALEUPMECH_ROOT"):
        settings.get_target("scaleupmech")


@pytest.mark.parametrize("key", ["edison_key_discovery", "environment_coverage",
                                 "unmapped_inventory_input", "causal_graph_coverage", "metpo_proposal"])
def test_withheld_capability_reasons_describe_scale_transfer_scope(key):
    """Copied assay-specific reasons do not describe the Scaleup domain (#1076)."""
    capability = load_fleet_manifest().get("scaleupmech").capabilities[key]
    assert not capability.is_enabled
    assert capability.reason is not None
    reason = capability.reason.lower()
    assert "assay" not in reason
    assert "scale" in reason
