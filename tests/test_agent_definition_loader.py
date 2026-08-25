"""Executable contracts for manifest-scoped declarative agents."""

from pathlib import Path

import pytest

from kg_microbe_agents import (
    AgentDefinitionError,
    find_agent_file,
    load_agent_definition,
    load_agent_definitions,
    load_named_agent,
)
from kg_microbe_fleet import load_fleet_manifest


def _agent(path: Path, scope: str) -> Path:
    path.write_text(
        "agent:\n"
        "  name: synthetic\n"
        "  type: test\n"
        "  description: synthetic agent\n"
        "model:\n"
        "  model: offline\n"
        "repository_scope:\n"
        f"  {scope}\n"
        "tasks:\n"
        "  inspect: {}\n",
        encoding="utf-8",
    )
    return path


def test_agent_scope_resolves_enabled_manifest_repositories(tmp_path: Path) -> None:
    manifest = load_fleet_manifest()
    path = _agent(
        tmp_path / "agent.yaml",
        "source: fleet_manifest\n  capability: testing",
    )

    definition = load_agent_definition(path, manifest)

    assert definition.repository_keys == manifest.with_capability("testing")


@pytest.mark.parametrize(
    ("scope", "message"),
    [
        ("source: filesystem\n  capability: testing", "must be fleet_manifest"),
        ("source: fleet_manifest\n  capability: testng", "is unknown"),
        (
            "source: fleet_manifest\n  capability: testing\n  capabilty: testing",
            "unknown keys: capabilty",
        ),
    ],
)
def test_agent_scope_rejects_typos(
    tmp_path: Path, scope: str, message: str
) -> None:
    path = _agent(tmp_path / "agent.yaml", scope)

    with pytest.raises(AgentDefinitionError, match=message):
        load_agent_definition(path)


def test_agent_yaml_rejects_duplicate_scope_keys(tmp_path: Path) -> None:
    path = _agent(
        tmp_path / "agent.yaml",
        "source: fleet_manifest\n  source: filesystem\n  capability: testing",
    )

    with pytest.raises(AgentDefinitionError, match="duplicate key 'source'"):
        load_agent_definition(path)


def test_unresolved_capability_profile_is_rejected(tmp_path: Path) -> None:
    path = _agent(
        tmp_path / "agent.yaml",
        "source: fleet_manifest\n  capability: testing",
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("integration: capability_profile.command\n")

    with pytest.raises(AgentDefinitionError, match="no executable profile resolver"):
        load_agent_definition(path)


@pytest.mark.parametrize("name", ["v*", "validation_age?t", "[v]alidation_agent"])
def test_agent_lookup_rejects_glob_metacharacters(name: str) -> None:
    with pytest.raises(AgentDefinitionError, match="Invalid agent name"):
        find_agent_file(name)


def test_every_declared_agent_name_is_an_exact_runnable_lookup_key() -> None:
    manifest = load_fleet_manifest()
    definitions = load_agent_definitions(manifest)

    assert len({definition.name for definition in definitions}) == len(definitions)
    for definition in definitions:
        assert load_named_agent(definition.name, manifest).path == definition.path

    assert load_named_agent("add_community_skill", manifest).name == (
        "add_community_skill"
    )
    with pytest.raises(AgentDefinitionError, match="Unknown or ambiguous"):
        load_named_agent("add_community", manifest)


def test_agent_metadata_name_must_be_a_safe_public_identifier(tmp_path: Path) -> None:
    path = _agent(
        tmp_path / "agent.yaml",
        "source: fleet_manifest\n  capability: testing",
    )
    text = path.read_text(encoding="utf-8").replace("name: synthetic", "name: bad/name")
    path.write_text(text, encoding="utf-8")

    with pytest.raises(AgentDefinitionError, match="agent.name is invalid"):
        load_agent_definition(path)
