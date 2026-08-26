"""Loading and strict validation of a Mech's research focus profile.

The profile (`conf/deep_research_provider.yaml` in each Mech) is the part that
stays domain-owned: the evidence target, the source priorities, and the stage
weights. This module owns only its *shape*.

Validation is fail-closed and deliberately the strictest of the five variants
this replaces. All five accepted the same file format but validated it to three
different depths: CultureMech and ProteinTraitsMech rejected a non-numeric
capability weight, stage weight, or provider adjustment; MediaIngredientMech and
CommunityMech did not, so `synthesis_weight: null` loaded cleanly and raised an
uncaught TypeError later inside scoring. TraitMech diverged further. A profile
that is accepted here is accepted identically for every Mech.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .providers import ALL_CAPABILITIES, PROVIDERS, canonical_provider

WEIGHT_KEYS = ("synthesis_weight", "speed_weight", "cost_weight")
TOP_LEVEL_KEYS = frozenset({"mech", "target", "evidence_policy", "default_focus", "focuses"})
FOCUS_KEYS = frozenset(
    {"label", "objective", "source_priorities", "provider_adjustments", "stages"}
)
STAGE_KEYS = frozenset({"objective", "capabilities", *WEIGHT_KEYS})


class ProfileError(ValueError):
    """A research focus profile is missing, malformed, or self-inconsistent."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses duplicate keys at every mapping depth."""

    # Do not inherit path resolvers installed process-wide by unrelated PyYAML
    # consumers. A root resolver with a null tag otherwise makes ordinary
    # profile mappings unconstructable and introduces test/import-order drift.
    yaml_path_resolvers: dict[Any, Any] = {}


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    """Construct one mapping without PyYAML's silent last-key-wins behavior."""

    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found an unhashable mapping key {key!r}",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate mapping key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _strict_keys(value: Mapping[Any, Any], allowed: frozenset[str], where: str) -> None:
    """Require string keys and reject fields this profile contract does not own."""

    non_strings = [key for key in value if not isinstance(key, str)]
    if non_strings:
        raise ProfileError(
            f"{where} keys must be strings, got " + ", ".join(repr(key) for key in non_strings)
        )
    unknown = set(value) - allowed
    if unknown:
        raise ProfileError(f"{where} has unknown key(s): {', '.join(sorted(unknown))}")


def _nonempty_string(value: Any, where: str) -> str:
    """Return a trimmed required string, rejecting missing or blank values."""

    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{where} must be a non-empty string, got {value!r}")
    return value.strip()


def _optional_string(value: Any, where: str) -> str:
    """Return a trimmed optional string without coercing arbitrary YAML values."""

    if not isinstance(value, str):
        raise ProfileError(f"{where} must be a string, got {value!r}")
    return value.strip()


def _mapping_name(value: Any, where: str) -> str:
    """Validate a dynamic mapping key without silently string-coercing it."""

    name = _nonempty_string(value, where)
    if name != value:
        raise ProfileError(f"{where} must not have surrounding whitespace, got {value!r}")
    return name


@dataclass(frozen=True)
class Stage:
    """One stage of a focus (discovery, synthesis, verification, ...)."""

    name: str
    objective: str
    capabilities: Mapping[str, float]
    weights: Mapping[str, float]

    def weight(self, key: str) -> float:
        return float(self.weights.get(key, 0.0))


@dataclass(frozen=True)
class Focus:
    """A named research focus and its ordered stages."""

    name: str
    label: str
    objective: str
    source_priorities: tuple[str, ...]
    provider_adjustments: Mapping[str, float]
    stages: Mapping[str, Stage]


@dataclass(frozen=True)
class ResearchProfile:
    """A validated Mech research profile."""

    mech: str
    target: str
    evidence_policy: str
    default_focus: str
    focuses: Mapping[str, Focus]
    path: Path | None = field(default=None, compare=False)
    source_sha256: str | None = field(default=None, compare=False)

    def focus(self, name: str | None = None) -> Focus:
        """Resolve a focus by name, defaulting to the profile's `default_focus`."""
        key = name or self.default_focus
        if key not in self.focuses:
            raise ProfileError(
                f"Unknown focus {key!r}; choose one of: {', '.join(sorted(self.focuses))}"
            )
        return self.focuses[key]


def _number(value: Any, where: str) -> float:
    # bool is an int subclass, and `synthesis_weight: yes` is a YAML bool. Silently
    # scoring it as 1 would be worse than refusing it.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{where} must be a number, got {value!r}")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ProfileError(f"{where} must be a finite number, got {value!r}") from exc
    if not math.isfinite(number):
        raise ProfileError(f"{where} must be a finite number, got {value!r}")
    return number


def _parse_stage(focus_name: str, stage_name: str, stage: Any) -> Stage:
    if not isinstance(stage, Mapping):
        raise ProfileError(f"Stage {focus_name}.{stage_name} must be a mapping")
    _strict_keys(stage, STAGE_KEYS, f"Stage {focus_name}.{stage_name}")

    raw_capabilities = stage.get("capabilities", {})
    if not isinstance(raw_capabilities, Mapping):
        raise ProfileError(f"Stage {focus_name}.{stage_name}.capabilities must be a mapping")

    non_strings = [key for key in raw_capabilities if not isinstance(key, str)]
    if non_strings:
        raise ProfileError(
            f"Stage {focus_name}.{stage_name}.capabilities keys must be strings, got "
            + ", ".join(repr(key) for key in non_strings)
        )
    unknown = set(raw_capabilities) - ALL_CAPABILITIES
    if unknown:
        raise ProfileError(
            f"Stage {focus_name}.{stage_name}.capabilities names unknown "
            f"capability/ies {sorted(unknown)}; no provider declares them, so they "
            f"would silently score 0. Choose one of: "
            f"{', '.join(sorted(ALL_CAPABILITIES))}"
        )

    capabilities = {
        name: _number(weight, f"Stage {focus_name}.{stage_name}.capabilities[{name!r}]")
        for name, weight in raw_capabilities.items()
    }
    # `.get(key, 0)` only supplies the default when the key is ABSENT; an explicit
    # `speed_weight: null` still returns None, so every key is checked here rather
    # than left to fail inside scoring.
    weights = {
        key: _number(stage.get(key, 0), f"Stage {focus_name}.{stage_name}.{key}")
        for key in WEIGHT_KEYS
    }
    return Stage(
        name=stage_name,
        objective=_nonempty_string(
            stage.get("objective"), f"Stage {focus_name}.{stage_name}.objective"
        ),
        capabilities=capabilities,
        weights=weights,
    )


def _parse_adjustments(focus_name: str, focus: Mapping[str, Any]) -> dict[str, float]:
    adjustments = focus.get("provider_adjustments", {})
    # Unconditional: an explicit `provider_adjustments: null` must fail here
    # rather than crash later with AttributeError.
    if not isinstance(adjustments, Mapping):
        raise ProfileError(f"Focus {focus_name!r}.provider_adjustments must be a mapping")
    non_strings = [key for key in adjustments if not isinstance(key, str)]
    if non_strings:
        raise ProfileError(
            f"Focus {focus_name!r}.provider_adjustments keys must be strings, got "
            + ", ".join(repr(key) for key in non_strings)
        )

    canonical: dict[str, float] = {}
    for raw_name, value in adjustments.items():
        name = canonical_provider(raw_name)
        if name not in PROVIDERS:
            raise ProfileError(
                f"Focus {focus_name!r}.provider_adjustments names unknown provider "
                f"{raw_name!r} (resolved to {name!r}); choose one of: "
                f"{', '.join(sorted(PROVIDERS))}"
            )
        if name in canonical:
            raise ProfileError(
                f"Focus {focus_name!r}.provider_adjustments has multiple keys "
                f"resolving to provider {name!r} (e.g. {raw_name!r}); use a single "
                f"canonical key per provider"
            )
        canonical[name] = _number(value, f"Focus {focus_name!r}.provider_adjustments[{raw_name!r}]")
    return canonical


def _parse_focus(focus_name: str, focus: Any) -> Focus:
    if not isinstance(focus, Mapping):
        raise ProfileError(f"Focus {focus_name!r} must be a mapping")
    _strict_keys(focus, FOCUS_KEYS, f"Focus {focus_name!r}")
    stages = focus.get("stages")
    if not isinstance(stages, Mapping) or not stages:
        raise ProfileError(f"Focus {focus_name!r} requires a non-empty 'stages' mapping")
    parsed_stages: dict[str, Stage] = {}
    for raw_name, stage in stages.items():
        stage_name = _mapping_name(raw_name, f"Focus {focus_name!r} stage name")
        parsed_stages[stage_name] = _parse_stage(focus_name, stage_name, stage)

    priorities = focus.get("source_priorities", [])
    if isinstance(priorities, str) or not isinstance(priorities, (list, tuple)):
        raise ProfileError(
            f"Focus {focus_name!r}.source_priorities must be a list, got {priorities!r}"
        )
    if any(not isinstance(item, str) or not item.strip() for item in priorities):
        raise ProfileError(
            f"Focus {focus_name!r}.source_priorities entries must be non-empty strings"
        )

    return Focus(
        name=focus_name,
        label=_optional_string(focus.get("label", focus_name), f"Focus {focus_name!r}.label"),
        objective=_optional_string(focus.get("objective", ""), f"Focus {focus_name!r}.objective"),
        source_priorities=tuple(item.strip() for item in priorities),
        provider_adjustments=_parse_adjustments(focus_name, focus),
        stages=parsed_stages,
    )


def parse_profile(
    data: Any,
    *,
    path: Path | None = None,
    source_sha256: str | None = None,
) -> ResearchProfile:
    """Validate an already-loaded profile mapping."""
    if not isinstance(data, Mapping):
        where = f": {path}" if path else ""
        raise ProfileError(f"Provider profile must be a YAML mapping{where}")
    _strict_keys(data, TOP_LEVEL_KEYS, "Provider profile")

    focuses = data.get("focuses")
    if not isinstance(focuses, Mapping) or not focuses:
        raise ProfileError("Provider profile requires a non-empty 'focuses' mapping")
    parsed_focuses: dict[str, Focus] = {}
    for raw_name, focus in focuses.items():
        focus_name = _mapping_name(raw_name, "Provider profile focus name")
        parsed_focuses[focus_name] = _parse_focus(focus_name, focus)

    default_focus = _mapping_name(data.get("default_focus"), "default_focus")
    if default_focus not in parsed_focuses:
        raise ProfileError(
            f"default_focus {default_focus!r} is not defined under focuses "
            f"({', '.join(sorted(parsed_focuses))})"
        )

    return ResearchProfile(
        mech=_nonempty_string(data.get("mech"), "mech"),
        target=_nonempty_string(data.get("target"), "target"),
        evidence_policy=_nonempty_string(data.get("evidence_policy"), "evidence_policy"),
        default_focus=default_focus,
        focuses=parsed_focuses,
        path=path,
        source_sha256=source_sha256,
    )


def load_profile(path: Path) -> ResearchProfile:
    """Read and validate a Mech research profile from one byte snapshot.

    ``source_sha256`` is bound to the exact bytes parsed here. Research-result
    records can therefore cite the profile that produced their plan without a
    second read and its accompanying time-of-check/time-of-use gap.
    """
    path = Path(path)
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise ProfileError(f"Cannot read research profile {path}: {exc}") from exc
    return load_profile_bytes(source, path=path)


def load_profile_bytes(source: bytes, *, path: Path | None = None) -> ResearchProfile:
    """Parse and checksum one caller-supplied immutable profile byte snapshot."""

    try:
        text = source.decode("utf-8")
    except UnicodeError as exc:
        where = f" {path}" if path is not None else ""
        raise ProfileError(f"Cannot read research profile{where}: {exc}") from exc
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        where = f" {path}" if path is not None else ""
        raise ProfileError(f"Research profile{where} is not valid YAML: {exc}") from exc
    return parse_profile(
        data,
        path=path,
        source_sha256=hashlib.sha256(source).hexdigest(),
    )
