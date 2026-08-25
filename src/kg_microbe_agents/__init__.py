"""Validated access to packaged declarative agent definitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml  # type: ignore[import-untyped]

from kg_microbe_fleet import (
    FleetManifest,
    UniqueKeySafeLoader,
    load_fleet_manifest,
)


class AgentDefinitionError(ValueError):
    """Raised when a declarative agent cannot be resolved safely."""


_AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class AgentDefinition:
    """One validated agent and its manifest-resolved repository scope."""

    path: Path
    document: Mapping[str, Any]
    name: str
    agent_type: str
    description: str
    model: str
    repository_keys: tuple[str, ...]


def agents_root() -> Path:
    """Return the source or installed directory containing agent YAML files."""

    root = Path(__file__).resolve().parent / "definitions"
    if not root.is_dir():
        raise AgentDefinitionError("Unable to locate packaged agent definitions")
    return root


def find_agent_file(agent_name: str) -> Path:
    """Resolve one public agent name without path fragments or ambiguity."""

    return load_named_agent(agent_name).path


def _validate_agent_name(agent_name: str) -> str:
    """Validate the exact identifier accepted by ``agent run``."""

    if not isinstance(agent_name, str) or not _AGENT_NAME_PATTERN.fullmatch(
        agent_name
    ):
        raise AgentDefinitionError(f"Invalid agent name: {agent_name!r}")
    return agent_name


def _contains_unresolved_profile(value: Any) -> bool:
    if isinstance(value, str):
        return "capability_profile." in value
    if isinstance(value, Mapping):
        return any(_contains_unresolved_profile(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_unresolved_profile(item) for item in value)
    return False


def load_agent_definition(
    path: Path,
    manifest: FleetManifest | None = None,
) -> AgentDefinition:
    """Parse one definition and resolve its optional fleet capability scope."""

    manifest = manifest or load_fleet_manifest()
    try:
        loaded = yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=UniqueKeySafeLoader,
        )
    except (OSError, yaml.YAMLError) as exc:
        raise AgentDefinitionError(f"Unable to load agent {path}: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise AgentDefinitionError(f"Agent {path} root must be a mapping")

    metadata = loaded.get("agent")
    if not isinstance(metadata, Mapping):
        raise AgentDefinitionError(f"Agent {path} agent must be a mapping")
    tasks = loaded.get("tasks")
    if not isinstance(tasks, Mapping):
        raise AgentDefinitionError(f"Agent {path} tasks must be a mapping")

    def required_text(mapping: Mapping[str, Any], key: str, label: str) -> str:
        value = mapping.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AgentDefinitionError(f"{label}.{key} must be a non-empty string")
        return value.strip()

    name = required_text(metadata, "name", f"Agent {path}.agent")
    try:
        _validate_agent_name(name)
    except AgentDefinitionError as exc:
        raise AgentDefinitionError(f"Agent {path}.agent.name is invalid: {name!r}") from exc
    agent_type = required_text(metadata, "type", f"Agent {path}.agent")
    description = required_text(metadata, "description", f"Agent {path}.agent")
    model_config = loaded.get("model", {})
    if not isinstance(model_config, Mapping):
        raise AgentDefinitionError(f"Agent {path} model must be a mapping")
    model = model_config.get("model", "unspecified")
    if not isinstance(model, str) or not model.strip():
        raise AgentDefinitionError(f"Agent {path}.model.model must be a string")

    scope = loaded.get("repository_scope")
    repository_keys: tuple[str, ...] = ()
    if scope is not None:
        if not isinstance(scope, Mapping):
            raise AgentDefinitionError(
                f"Agent {path} repository_scope must be a mapping"
            )
        unknown = set(scope) - {"source", "capability"}
        if unknown:
            raise AgentDefinitionError(
                f"Agent {path} repository_scope has unknown keys: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        if scope.get("source") != "fleet_manifest":
            raise AgentDefinitionError(
                f"Agent {path} repository_scope.source must be fleet_manifest"
            )
        capability = scope.get("capability")
        if not isinstance(capability, str) or capability not in manifest.capability_names:
            raise AgentDefinitionError(
                f"Agent {path} repository_scope.capability is unknown: {capability!r}"
            )
        repository_keys = manifest.with_capability(capability)
        if not repository_keys:
            raise AgentDefinitionError(
                f"Agent {path} capability {capability!r} enables no repositories"
            )

    if _contains_unresolved_profile(loaded):
        raise AgentDefinitionError(
            f"Agent {path} references capability_profile, but no executable "
            "profile resolver is defined"
        )

    return AgentDefinition(
        path=path,
        document=loaded,
        name=name,
        agent_type=agent_type,
        description=description,
        model=model.strip(),
        repository_keys=repository_keys,
    )


def load_agent_definitions(
    manifest: FleetManifest | None = None,
) -> tuple[AgentDefinition, ...]:
    """Load every packaged definition and enforce unique public names."""

    manifest = manifest or load_fleet_manifest()
    definitions = tuple(
        load_agent_definition(path, manifest)
        for path in sorted(agents_root().rglob("*.yaml"))
    )
    names = [definition.name for definition in definitions]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise AgentDefinitionError(
            "Packaged agent definitions have duplicate names: "
            + ", ".join(duplicates)
        )
    return definitions


def load_named_agent(
    agent_name: str,
    manifest: FleetManifest | None = None,
) -> AgentDefinition:
    """Resolve and validate a packaged agent by its declared public name."""

    name = _validate_agent_name(agent_name)
    matches = [
        definition
        for definition in load_agent_definitions(manifest)
        if definition.name == name
    ]
    if len(matches) != 1:
        raise AgentDefinitionError(f"Unknown or ambiguous agent: {name}")
    return matches[0]
