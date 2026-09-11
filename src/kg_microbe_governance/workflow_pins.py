"""Offline action/runtime contract for canonical, byte-governed workflows."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Iterator

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from .artifacts.scripts.check_vendored_sync import GovernanceError, parse_manifest

CONTRACT_PATH = Path("src/kg_microbe_governance/workflow_pins.json")
MANIFEST_PATH = Path("src/kg_microbe_governance/vendored_artifacts.json")
SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
UV_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GovernanceError(f"Duplicate workflow pin key: {key}")
        result[key] = value
    return result


def load_pin_contract(path: Path | None = None) -> dict:
    """Reject mutable revisions, missing labels, and ambiguous pin declarations."""
    content = (path.read_text() if path else files(__package__).joinpath(
        "workflow_pins.json"
    ).read_text())
    document = json.loads(content, object_pairs_hook=_unique_pairs)
    if not isinstance(document, dict) or set(document) != {"version", "actions", "uv_version"}:
        raise GovernanceError("Workflow pins require version, actions and uv_version")
    if type(document["version"]) is not int or document["version"] != 1:
        raise GovernanceError("Unsupported workflow pins version")
    actions = document["actions"]
    if not isinstance(actions, dict) or not actions:
        raise GovernanceError("Workflow action pins must be a nonempty mapping")
    for action, pin in actions.items():
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", action):
            raise GovernanceError(f"Expected an action repository: {action}")
        if not isinstance(pin, dict) or set(pin) != {"sha", "version"}:
            raise GovernanceError(f"{action}: pin requires sha and version")
        if not isinstance(pin["sha"], str) or not SHA.fullmatch(pin["sha"]):
            raise GovernanceError(f"{action}: pin must be a lowercase 40-hex SHA")
        if not isinstance(pin["version"], str) or not VERSION.fullmatch(pin["version"]):
            raise GovernanceError(f"{action}: version must be a full release tag, such as v1.2.3")
    if not isinstance(document["uv_version"], str) or not UV_VERSION.fullmatch(document["uv_version"]):
        raise GovernanceError("uv_version must be an exact version, such as 0.12.5")
    return document


def _mapping(node: Node) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        raise GovernanceError("Expected a workflow YAML mapping")
    result = {}
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.value in result:
            raise GovernanceError("Non-scalar or duplicate workflow YAML key")
        result[key.value] = value
    return result


def _walk(node: Node, ancestors: tuple[int, ...] = ()) -> Iterator[dict[str, Node]]:
    if id(node) in ancestors:
        raise GovernanceError("Cyclic YAML aliases are not supported in governed workflows")
    ancestors = (*ancestors, id(node))
    if isinstance(node, MappingNode):
        mapping = _mapping(node)
        yield mapping
        for value in mapping.values():
            yield from _walk(value, ancestors)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            yield from _walk(value, ancestors)


def render_workflow(content: str, contract: dict) -> str:
    """Render only action pin lines and uv inputs; preserve all other workflow bytes.

    Inspect parsed YAML nodes, so quoted keys, flow mappings, reusable jobs,
    duplicate keys, and nested steps cannot escape a line-oriented scan.
    The maintained source uses one scalar per line; unfamiliar formatting fails
    closed rather than rewriting unrelated YAML or the model prompt.
    """
    try:
        document = yaml.compose(content, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise GovernanceError(f"Invalid governed workflow YAML: {exc}") from exc
    if document is None:
        raise GovernanceError("Empty governed workflow")
    edits: dict[tuple[int, int], str] = {}
    uses_count = 0
    for mapping in _walk(document):
        if "uses" not in mapping:
            continue
        uses_count += 1
        node = mapping["uses"]
        if not isinstance(node, ScalarNode) or node.start_mark.line != node.end_mark.line:
            raise GovernanceError("uses must be a single-line scalar")
        action, separator, _ref = node.value.partition("@")
        if not separator or action not in contract["actions"]:
            raise GovernanceError(f"Action missing from fleet pin contract: {node.value}")
        pin = contract["actions"][action]
        end = content.find("\n", node.end_mark.index)
        if end < 0:
            end = len(content)
        suffix = content[node.end_mark.index:end]
        if suffix.strip() and not suffix.lstrip().startswith("#"):
            raise GovernanceError("uses must have its own line in governed workflows")
        edits[node.start_mark.index, end] = f"{action}@{pin['sha']} # {pin['version']}"
        if action == "astral-sh/setup-uv":
            inputs = _mapping(mapping["with"]) if "with" in mapping else {}
            version = inputs.get("version")
            if not isinstance(version, ScalarNode):
                raise GovernanceError("setup-uv requires an explicit with.version input")
            if version.start_mark.line != version.end_mark.line:
                raise GovernanceError("setup-uv with.version must be a single-line scalar")
            edits[version.start_mark.index, version.end_mark.index] = f'"{contract["uv_version"]}"'
    if not uses_count:
        raise GovernanceError("Governed workflow has no action references")
    for (start, end), replacement in sorted(edits.items(), reverse=True):
        content = content[:start] + replacement + content[end:]
    return content


def workflow_entries(root: Path) -> list[dict]:
    """Discover every canonical workflow from the governed artifact registry."""
    data = (root / MANIFEST_PATH).read_bytes()
    parse_manifest(data)
    entries = [entry for entry in json.loads(data)["artifacts"]
               if entry["target"].startswith(".github/workflows/")]
    source_root = root / "src/kg_microbe_governance/artifacts/workflows"
    discovered = {path.relative_to(root).as_posix() for path in source_root.rglob("*")
                  if path.suffix in {".yml", ".yaml"}}
    registered = {entry["source"] for entry in entries}
    if not entries or discovered != registered:
        raise GovernanceError("Canonical workflow files and governance registry differ")
    return entries


def check_workflow_pins(root: Path) -> None:
    """CI gate: pinned action refs, version labels, runtime input, and checksums."""
    contract = load_pin_contract(root / CONTRACT_PATH)
    for entry in workflow_entries(root):
        path = root / entry["source"]
        content = path.read_text()
        if render_workflow(content, contract) != content:
            raise GovernanceError(f"{entry['source']}: action/runtime pins differ from fleet contract")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise GovernanceError(f"{entry['source']}: governed workflow checksum drift")
