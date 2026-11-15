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


def test_assay_identity_is_consistent_across_runtime_surfaces():
    fleet = load_fleet_manifest()
    mech = fleet.get("assaymech")
    assert mech.github == "CultureBotAI/AssayMech"
    assert mech.environment_variable == "ASSAYMECH_ROOT"
    assert mech.package_path == "src/assaymech"
    assert mech.schema_paths == ("src/assaymech/schema/assaymech.yaml",)
    assert mech.record_globs == ("data/assays/*.yaml",)
    consumer = load_governance_manifest().consumer_for("assaymech")
    assert (consumer.github, consumer.package_path) == (mech.github, mech.package_path)
    config = yaml.safe_load(default_config_path().read_text())
    assert config["repositories"][mech.key]["path"] == "${ASSAYMECH_ROOT}"
    assert "ASSAYMECH_ROOT=/absolute/path/to/AssayMech" in (ROOT / ".env.example").read_text()
    research = yaml.safe_load((ROOT / "src/kg_microbe_research/schema/research.yaml").read_text())
    assert "AssayMech" in research["enums"]["MechEnum"]["permissible_values"]


def test_empty_main_admission_does_not_enable_unverified_implementation():
    mech = load_fleet_manifest().get("assaymech")
    assert {key for key, cap in mech.capabilities.items() if cap.is_enabled} == {"vendored_sync"}
    assert mech.serialization is not None
    assert not mech.serialization.verified
    assert not mech.serialization.options
    plan = load_rollout()["mechs"]["assaymech"]
    assert plan["revision"] == "a85aea616168160ec7e5dc08e71f15b361455924"
    assert plan["native"] == "no_pipeline_in_audited_source"
    assert plan["sets"]["record-text"]["state"] == "planned"


def test_queue_mapping_names_the_scaffold_check_without_enabling_rules():
    assert load_policy()["assaymech"] == {
        ".github/workflows/validate-strict.yaml": ["validate-strict"],
    }


def test_new_member_is_visible_without_a_configured_root():
    settings = RepositorySettings.from_environment(environ={})
    assert "assaymech" in settings.names
    assert "assaymech" in settings.unconfigured
    assert "assaymech" not in settings.paths
    with pytest.raises(RepositoryConfigurationError, match="ASSAYMECH_ROOT"):
        settings.get_target("assaymech")
