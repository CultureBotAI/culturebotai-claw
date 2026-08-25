"""Canonical fleet manifest: the one list of Mech repositories.

Every fleet-facing component must derive its repository list from
``conf/fleet.yaml`` through this module. Independent lists are how
ProteinTraitsMech came to be missing from core configuration while appearing in
the fleet PR sweep, and how the cross-Mech sync skill settled on a fourth
repository set of its own.

The loader validates fail-closed. A malformed manifest raises rather than
yielding a partial fleet, because a silently short repository list is
indistinguishable from a correct one at the call site.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml  # type: ignore[import-untyped]

__all__ = [
    "FleetManifestError",
    "Capability",
    "MechDefinition",
    "FleetManifest",
    "load_fleet_manifest",
    "default_manifest_path",
    "CAPABILITY_STATUSES",
    "STATUSES_REQUIRING_REASON",
    "VENDORED_ROLES",
]

# Resolution order for the manifest, most specific first. The environment
# override exists because ``__file__``-relative resolution is correct for a
# source checkout but not for an installed wheel, where ``conf/`` is outside
# the package. Packaging the manifest as package data is left to the phase that
# introduces installed-mode consumers.
MANIFEST_ENVIRONMENT_VARIABLE = "KG_MICROBE_FLEET_MANIFEST"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

CAPABILITY_STATUSES = frozenset({"enabled", "disabled", "not_applicable"})
# A capability that is off must say why. Without this, "absent" and
# "deliberately excluded" look identical in the manifest.
STATUSES_REQUIRING_REASON = frozenset({"disabled", "not_applicable"})
VENDORED_ROLES = frozenset({"hub", "spoke"})

SUPPORTED_VERSIONS = frozenset({1})


class FleetManifestError(ValueError):
    """Raised when the fleet manifest cannot be trusted."""


@dataclass(frozen=True)
class Capability:
    """A capability declaration for one repository."""

    name: str
    status: str
    reason: Optional[str] = None

    @property
    def is_enabled(self) -> bool:
        return self.status == "enabled"


@dataclass(frozen=True)
class MechDefinition:
    """Identity and declared capabilities for one Mech repository."""

    key: str
    display_name: str
    github: str
    environment_variable: str
    vendored_role: str
    capabilities: Mapping[str, Capability]

    def capability(self, name: str) -> Optional[Capability]:
        return self.capabilities.get(name)

    def supports(self, name: str) -> bool:
        """Return whether ``name`` is declared enabled for this repository.

        An undeclared capability is not enabled. Treating "unmentioned" as
        "available" is what lets a capability quietly apply to a repository it
        was never verified against.
        """

        capability = self.capabilities.get(name)
        return capability is not None and capability.is_enabled


class FleetManifest:
    """The validated fleet definition."""

    def __init__(
        self,
        mechs: Mapping[str, MechDefinition],
        vendored_hub: str,
        source: Path,
    ) -> None:
        self._mechs = dict(mechs)
        self._vendored_hub = vendored_hub
        self._source = source

    @property
    def source(self) -> Path:
        return self._source

    @property
    def keys(self) -> tuple[str, ...]:
        """Return every Mech key in manifest order."""

        return tuple(self._mechs)

    @property
    def mechs(self) -> dict[str, MechDefinition]:
        return dict(self._mechs)

    @property
    def vendored_hub(self) -> str:
        return self._vendored_hub

    def get(self, key: str) -> MechDefinition:
        try:
            return self._mechs[key]
        except KeyError:
            known = ", ".join(sorted(self._mechs))
            raise FleetManifestError(
                f"Unknown Mech '{key}'; known Mechs: {known}"
            ) from None

    def environment_variables(self) -> dict[str, str]:
        """Return ``{key: environment variable}`` for every Mech."""

        return {key: mech.environment_variable for key, mech in self._mechs.items()}

    def with_capability(self, name: str) -> tuple[str, ...]:
        """Return the keys of Mechs declaring ``name`` enabled."""

        return tuple(key for key, mech in self._mechs.items() if mech.supports(name))


def default_manifest_path() -> Path:
    """Return the manifest path, honouring the environment override."""

    override = os.environ.get(MANIFEST_ENVIRONMENT_VARIABLE)
    if override:
        return Path(override).expanduser()
    return _REPOSITORY_ROOT / "conf" / "fleet.yaml"


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FleetManifestError(f"{label} must be a mapping")
    return value


def _require_identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or value.count("/") != 1 or not all(
        part.strip() for part in value.split("/")
    ):
        raise FleetManifestError(f"{label} must be 'owner/repository'")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FleetManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _parse_capabilities(raw: Any, mech_key: str) -> dict[str, Capability]:
    capabilities: dict[str, Capability] = {}
    if raw is None:
        return capabilities
    mapping = _require_mapping(raw, f"mechs.{mech_key}.capabilities")

    for name, declaration in mapping.items():
        label = f"mechs.{mech_key}.capabilities.{name}"
        declaration_mapping = _require_mapping(declaration, label)
        status = declaration_mapping.get("status")
        if status not in CAPABILITY_STATUSES:
            allowed = ", ".join(sorted(CAPABILITY_STATUSES))
            raise FleetManifestError(
                f"{label}.status must be one of: {allowed} (got {status!r})"
            )

        reason_value = declaration_mapping.get("reason")
        reason: Optional[str] = None
        if reason_value is not None:
            reason = _require_nonempty_string(reason_value, f"{label}.reason")

        if status in STATUSES_REQUIRING_REASON and not reason:
            raise FleetManifestError(
                f"{label}.reason is required when status is '{status}'"
            )

        capabilities[str(name)] = Capability(
            name=str(name), status=status, reason=reason
        )

    return capabilities


def _parse_mech(key: str, raw: Any) -> MechDefinition:
    label = f"mechs.{key}"
    mapping = _require_mapping(raw, label)

    vendored_role = mapping.get("vendored_role")
    if vendored_role not in VENDORED_ROLES:
        allowed = ", ".join(sorted(VENDORED_ROLES))
        raise FleetManifestError(
            f"{label}.vendored_role must be one of: {allowed} (got {vendored_role!r})"
        )

    return MechDefinition(
        key=key,
        display_name=_require_nonempty_string(
            mapping.get("display_name"), f"{label}.display_name"
        ),
        github=_require_identity(mapping.get("github"), f"{label}.github"),
        environment_variable=_require_nonempty_string(
            mapping.get("environment_variable"), f"{label}.environment_variable"
        ),
        vendored_role=vendored_role,
        capabilities=_parse_capabilities(mapping.get("capabilities"), key),
    )


def parse_fleet_manifest(document: Any, source: Path) -> FleetManifest:
    """Validate an already-loaded manifest document."""

    mapping = _require_mapping(document, f"Fleet manifest {source}")

    version = mapping.get("version")
    if version not in SUPPORTED_VERSIONS:
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_VERSIONS))
        raise FleetManifestError(
            f"Fleet manifest {source} version must be one of: {supported} "
            f"(got {version!r})"
        )

    raw_mechs = _require_mapping(mapping.get("mechs"), "mechs")
    if not raw_mechs:
        raise FleetManifestError("Fleet manifest must declare at least one Mech")

    mechs = {str(key): _parse_mech(str(key), value) for key, value in raw_mechs.items()}

    identities = [mech.github.lower() for mech in mechs.values()]
    if len(set(identities)) != len(identities):
        raise FleetManifestError("Fleet manifest declares a duplicate GitHub identity")

    environment_variables = [mech.environment_variable for mech in mechs.values()]
    if len(set(environment_variables)) != len(environment_variables):
        raise FleetManifestError(
            "Fleet manifest declares a duplicate environment variable"
        )

    hubs = [key for key, mech in mechs.items() if mech.vendored_role == "hub"]
    if len(hubs) != 1:
        found = ", ".join(sorted(hubs)) or "none"
        raise FleetManifestError(
            f"Fleet manifest must declare exactly one vendored hub (found: {found})"
        )

    vendored_hub = _require_nonempty_string(mapping.get("vendored_hub"), "vendored_hub")
    if vendored_hub != hubs[0]:
        raise FleetManifestError(
            f"vendored_hub is '{vendored_hub}' but the repository declaring "
            f"vendored_role 'hub' is '{hubs[0]}'"
        )

    return FleetManifest(mechs=mechs, vendored_hub=vendored_hub, source=source)


def _load_uncached(path: Path) -> FleetManifest:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FleetManifestError(
            f"Unable to load fleet manifest {path}: {exc}"
        ) from exc
    return parse_fleet_manifest(document, path)


@lru_cache(maxsize=None)
def _load_cached(resolved: Path) -> FleetManifest:
    return _load_uncached(resolved)


def load_fleet_manifest(path: Optional[Path] = None) -> FleetManifest:
    """Load and validate the fleet manifest.

    Results are cached per resolved path; pass ``path`` explicitly in tests so a
    fixture manifest never collides with the repository's own cache entry.
    """

    resolved = (path or default_manifest_path()).expanduser()
    try:
        resolved = resolved.resolve()
    except OSError as exc:  # pragma: no cover - unusual filesystem failure
        raise FleetManifestError(
            f"Unable to resolve fleet manifest path {resolved}: {exc}"
        ) from exc
    return _load_cached(resolved)
