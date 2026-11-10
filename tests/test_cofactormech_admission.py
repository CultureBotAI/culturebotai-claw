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


def test_cofactor_identity_is_consistent_across_runtime_surfaces():
    fleet = load_fleet_manifest()
    mech = fleet.get("cofactormech")
    assert mech.github == "CultureBotAI/CofactorMech"
    assert mech.environment_variable == "COFACTORMECH_ROOT"
    assert mech.package_path == "src/cofactormech"
    assert mech.schema_paths == ("src/cofactormech/schema/cofactormech.yaml",)
    assert mech.record_globs == ("data/cofactors/*.yaml",)
    consumer = load_governance_manifest().consumer_for("cofactormech")
    assert (consumer.github, consumer.package_path) == (mech.github, mech.package_path)
    config = yaml.safe_load(default_config_path().read_text())
    assert config["repositories"][mech.key]["path"] == "${COFACTORMECH_ROOT}"
    assert "COFACTORMECH_ROOT=/absolute/path/to/CofactorMech" in (ROOT / ".env.example").read_text()
    research = yaml.safe_load((ROOT / "src/kg_microbe_research/schema/research.yaml").read_text())
    assert "CofactorMech" in research["enums"]["MechEnum"]["permissible_values"]


def test_empty_main_admission_does_not_enable_unverified_implementation():
    mech = load_fleet_manifest().get("cofactormech")
    assert {key for key, cap in mech.capabilities.items() if cap.is_enabled} == {"vendored_sync"}
    assert mech.serialization is not None
    assert not mech.serialization.verified
    assert not mech.serialization.options
    plan = load_rollout()["mechs"]["cofactormech"]
    assert plan["revision"] == "3cb9d7a6ce527c84277daf6ddfd5cd56decbb4d1"
    assert plan["native"] == "no_pipeline_in_audited_source"
    assert plan["sets"]["record-text"]["state"] == "planned"


def test_queue_mapping_names_the_scaffold_check_without_enabling_rules():
    assert load_policy()["cofactormech"] == {
        ".github/workflows/validate-strict.yaml": ["validate-strict"],
    }


def test_new_member_is_visible_without_a_configured_root():
    settings = RepositorySettings.from_environment(environ={})
    assert "cofactormech" in settings.names
    assert "cofactormech" in settings.unconfigured
    assert "cofactormech" not in settings.paths
    with pytest.raises(RepositoryConfigurationError, match="COFACTORMECH_ROOT"):
        settings.get_target("cofactormech")
