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

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .providers import ALL_CAPABILITIES, PROVIDERS, canonical_provider

WEIGHT_KEYS = ("synthesis_weight", "speed_weight", "cost_weight")


class ProfileError(ValueError):
    """A research focus profile is missing, malformed, or self-inconsistent."""


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

    def focus(self, name: str | None = None) -> Focus:
        """Resolve a focus by name, defaulting to the profile's `default_focus`."""
        key = name or self.default_focus
        if key not in self.focuses:
            raise ProfileError(
                f"Unknown focus {key!r}; choose one of: "
                f"{', '.join(sorted(self.focuses))}"
            )
        return self.focuses[key]


def _number(value: Any, where: str) -> float:
    # bool is an int subclass, and `synthesis_weight: yes` is a YAML bool. Silently
    # scoring it as 1 would be worse than refusing it.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{where} must be a number, got {value!r}")
    return float(value)


def _parse_stage(focus_name: str, stage_name: str, stage: Any) -> Stage:
    if not isinstance(stage, Mapping):
        raise ProfileError(f"Stage {focus_name}.{stage_name} must be a mapping")

    raw_capabilities = stage.get("capabilities", {})
    if not isinstance(raw_capabilities, Mapping):
        raise ProfileError(
            f"Stage {focus_name}.{stage_name}.capabilities must be a mapping"
        )

    # str() rather than bare set(): a YAML complex key would be unhashable and
    # raise TypeError instead of this message.
    unknown = {str(cap) for cap in raw_capabilities} - ALL_CAPABILITIES
    if unknown:
        raise ProfileError(
            f"Stage {focus_name}.{stage_name}.capabilities names unknown "
            f"capability/ies {sorted(unknown)}; no provider declares them, so they "
            f"would silently score 0. Choose one of: "
            f"{', '.join(sorted(ALL_CAPABILITIES))}"
        )

    capabilities = {
        str(name): _number(
            weight, f"Stage {focus_name}.{stage_name}.capabilities[{name!r}]"
        )
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
        objective=str(stage.get("objective", "")),
        capabilities=capabilities,
        weights=weights,
    )


def _parse_adjustments(focus_name: str, focus: Mapping[str, Any]) -> dict[str, float]:
    adjustments = focus.get("provider_adjustments", {})
    # Unconditional: an explicit `provider_adjustments: null` must fail here
    # rather than crash later with AttributeError.
    if not isinstance(adjustments, Mapping):
        raise ProfileError(
            f"Focus {focus_name!r}.provider_adjustments must be a mapping"
        )

    canonical: dict[str, float] = {}
    for raw_name, value in adjustments.items():
        name = canonical_provider(str(raw_name))
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
        canonical[name] = _number(
            value, f"Focus {focus_name!r}.provider_adjustments[{raw_name!r}]"
        )
    return canonical


def _parse_focus(focus_name: str, focus: Any) -> Focus:
    if not isinstance(focus, Mapping):
        raise ProfileError(f"Focus {focus_name!r} must be a mapping")
    stages = focus.get("stages")
    if not isinstance(stages, Mapping) or not stages:
        raise ProfileError(f"Focus {focus_name!r} requires a non-empty 'stages' mapping")

    priorities = focus.get("source_priorities", [])
    if isinstance(priorities, str) or not isinstance(priorities, (list, tuple)):
        raise ProfileError(
            f"Focus {focus_name!r}.source_priorities must be a list, got "
            f"{priorities!r}"
        )

    return Focus(
        name=focus_name,
        label=str(focus.get("label", focus_name)),
        objective=str(focus.get("objective", "")),
        source_priorities=tuple(str(item) for item in priorities),
        provider_adjustments=_parse_adjustments(focus_name, focus),
        stages={
            str(name): _parse_stage(focus_name, str(name), stage)
            for name, stage in stages.items()
        },
    )


def parse_profile(data: Any, *, path: Path | None = None) -> ResearchProfile:
    """Validate an already-loaded profile mapping."""
    if not isinstance(data, Mapping):
        where = f": {path}" if path else ""
        raise ProfileError(f"Provider profile must be a YAML mapping{where}")

    focuses = data.get("focuses")
    if not isinstance(focuses, Mapping) or not focuses:
        raise ProfileError("Provider profile requires a non-empty 'focuses' mapping")

    default_focus = data.get("default_focus")
    if default_focus not in focuses:
        raise ProfileError(
            f"default_focus {default_focus!r} is not defined under focuses "
            f"({', '.join(sorted(str(key) for key in focuses))})"
        )

    return ResearchProfile(
        mech=str(data.get("mech", "Mech")),
        target=str(data.get("target", "")),
        evidence_policy=str(data.get("evidence_policy", "")),
        default_focus=str(default_focus),
        focuses={
            str(name): _parse_focus(str(name), focus) for name, focus in focuses.items()
        },
        path=path,
    )


def load_profile(path: Path) -> ResearchProfile:
    """Read and validate a Mech research profile from disk."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"Cannot read research profile {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError(f"Research profile {path} is not valid YAML: {exc}") from exc
    return parse_profile(data, path=path)
