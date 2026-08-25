"""Fleet-wide agents must derive repository scope from the canonical manifest."""

from __future__ import annotations

from typing import Any

import yaml

from kg_microbe_agents import agents_root
from kg_microbe_fleet import load_fleet_manifest

AGENTS_ROOT = agents_root()

GENERAL_FLEET_AGENTS = {
    "dev_workflow/validation_agent.yaml": "strict_validation",
    "dev_workflow/schema_sync_agent.yaml": "schema_sync",
    "build_deployment/release_agent.yaml": "release_management",
    "build_deployment/build_coordinator_agent.yaml": "build_coordination",
    "code_development/documentation_agent.yaml": "documentation",
    "code_development/test_agent.yaml": "testing",
    "code_development/refactoring_agent.yaml": "refactoring",
}
GENERAL_AGENT_DIRECTORIES = (
    AGENTS_ROOT / "dev_workflow",
    AGENTS_ROOT / "build_deployment",
    AGENTS_ROOT / "code_development",
)


def _without_domain_dependency_graphs(value: Any) -> Any:
    """Remove explicit scientific dependency graphs before drift checks."""

    if isinstance(value, dict):
        return {
            key: _without_domain_dependency_graphs(child)
            for key, child in value.items()
            if key != "domain_specific_dependency_graph"
        }
    if isinstance(value, list):
        return [_without_domain_dependency_graphs(child) for child in value]
    return value


def test_general_agent_catalogue_covers_every_general_agent_config():
    discovered = {
        path.relative_to(AGENTS_ROOT).as_posix()
        for directory in GENERAL_AGENT_DIRECTORIES
        for path in directory.glob("*.yaml")
    }

    assert discovered == set(GENERAL_FLEET_AGENTS)


def test_general_agents_use_validated_manifest_capability_scopes():
    manifest = load_fleet_manifest()

    for relative_path, capability in GENERAL_FLEET_AGENTS.items():
        document = yaml.safe_load((AGENTS_ROOT / relative_path).read_text(encoding="utf-8"))

        assert document["repository_scope"] == {
            "source": "fleet_manifest",
            "capability": capability,
        }
        assert document["workspace"]["allowed_paths"]["source"] == (
            "repository_scope"
        )
        assert manifest.with_capability(capability) == manifest.keys
        assert all(
            capability in mech.capabilities for mech in manifest.mechs.values()
        )


def test_general_agents_do_not_embed_an_independent_mech_list():
    manifest = load_fleet_manifest()
    mech_tokens = {
        token.lower()
        for mech in manifest.mechs.values()
        for token in (mech.key, mech.display_name, mech.environment_variable)
    }

    for relative_path in GENERAL_FLEET_AGENTS:
        document = yaml.safe_load((AGENTS_ROOT / relative_path).read_text(encoding="utf-8"))
        fleet_generic_document = _without_domain_dependency_graphs(document)
        rendered = yaml.safe_dump(fleet_generic_document).lower()
        embedded = {token for token in mech_tokens if token in rendered}

        assert len(embedded) < 2, (
            f"{relative_path} embeds an independent Mech list: "
            f"{sorted(embedded)}"
        )
