"""Canonical fleet manifest: the one list of Mech repositories.

Every fleet-facing component must derive its repository list from
``src/kg_microbe_fleet/fleet.yaml`` through this module. Independent lists are how
ProteinTraitsMech came to be missing from core configuration while appearing in
the fleet PR sweep, and how the cross-Mech sync skill settled on a fourth
repository set of its own.

The loader validates fail-closed. A malformed manifest raises rather than
yielding a partial fleet, because a silently short repository list is
indistinguishable from a correct one at the call site.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from math import isfinite
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Optional

import yaml  # type: ignore[import-untyped]

__all__ = [
    "FleetManifestError",
    "CapabilitySettingDefinition",
    "CapabilityDefinition",
    "Capability",
    "MechDefinition",
    "FleetManifest",
    "load_fleet_manifest",
    "default_manifest_path",
    "CAPABILITY_STATUSES",
    "STATUSES_REQUIRING_REASON",
    "VENDORED_ROLES",
    "UniqueKeySafeLoader",
]

# The manifest ships *inside* this package rather than at the repository root.
# Installed console commands need it after the source checkout is absent; it is
# declared in ``[tool.setuptools.package-data]``. Consumers load a snapshot at
# command time and may inject that same object into repository settings.
MANIFEST_ENVIRONMENT_VARIABLE = "KG_MICROBE_FLEET_MANIFEST"
MANIFEST_FILENAME = "fleet.yaml"

CAPABILITY_STATUSES = frozenset({"enabled", "disabled", "not_applicable"})
# A capability that is off must say why. Without this, "absent" and
# "deliberately excluded" look identical in the manifest.
STATUSES_REQUIRING_REASON = frozenset({"disabled", "not_applicable"})
VENDORED_ROLES = frozenset({"hub", "spoke"})
SETTING_TYPES = frozenset(
    {"boolean", "integer", "number", "string", "string_list"}
)

SUPPORTED_VERSIONS = frozenset({1})

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_GITHUB_IDENTITY_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?/"
    r"[A-Za-z0-9_.-]+$"
)


class UniqueKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    """Safe YAML loader that rejects keys PyYAML would silently overwrite."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "expected a mapping node",
                node.start_mark,
            )

        # Expand YAML merge keys before checking so an explicit key cannot
        # silently override a value inherited through ``<<`` either.
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class FleetManifestError(ValueError):
    """Raised when the fleet manifest cannot be trusted."""


@dataclass(frozen=True)
class CapabilitySettingDefinition:
    """Validation contract for one capability setting."""

    name: str
    value_type: str
    required_when_enabled: bool = False
    minimum: Optional[float] = None


@dataclass(frozen=True)
class CapabilityDefinition:
    """One capability in the fleet-wide catalogue."""

    name: str
    settings: Mapping[str, CapabilitySettingDefinition]


@dataclass(frozen=True)
class Capability:
    """A capability declaration for one repository."""

    name: str
    status: str
    reason: Optional[str] = None
    settings: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

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
    package_path: str
    schema_paths: tuple[str, ...]
    record_globs: tuple[str, ...]
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
        capability_catalogue: Mapping[str, CapabilityDefinition],
        vendored_hub: str,
        source: Path,
    ) -> None:
        self._mechs = dict(mechs)
        self._capability_catalogue = dict(capability_catalogue)
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
    def capability_catalogue(self) -> dict[str, CapabilityDefinition]:
        """Return a copy of the canonical capability catalogue."""

        return dict(self._capability_catalogue)

    @property
    def capability_names(self) -> tuple[str, ...]:
        """Return every catalogue capability in manifest order."""

        return tuple(self._capability_catalogue)

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
    """Return the manifest path, honouring the environment override.

    The library reads the real process environment and does not implicitly
    parse ``.env``. Applications that support dotenv must load it before they
    call this function, then pass the returned manifest to all consumers.
    """

    override = os.environ.get(MANIFEST_ENVIRONMENT_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / MANIFEST_FILENAME


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FleetManifestError(f"{label} must be a mapping")
    return value


def _require_identity(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not _GITHUB_IDENTITY_PATTERN.fullmatch(value)
        or value.rsplit("/", 1)[-1] in {".", ".."}
    ):
        raise FleetManifestError(f"{label} must be 'owner/repository'")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FleetManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _require_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise FleetManifestError(
            f"{label} must start with a lowercase letter and contain only "
            "lowercase letters, digits, and underscores"
        )
    return value


def _require_environment_variable(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ENVIRONMENT_VARIABLE_PATTERN.fullmatch(value):
        raise FleetManifestError(f"{label} must be an uppercase environment variable")
    return value


def _require_relative_path(value: Any, label: str, *, glob: bool = False) -> str:
    text = _require_nonempty_string(value, label)
    if "\\" in text:
        raise FleetManifestError(f"{label} must be a repository-relative POSIX path")
    segments = text.split("/")
    path = PurePosixPath(text)
    if path.is_absolute() or any(segment in {"", ".", ".."} for segment in segments):
        raise FleetManifestError(
            f"{label} must be a repository-relative path without traversal"
        )

    has_glob = any(character in text for character in "*?[")
    if glob:
        if not has_glob:
            raise FleetManifestError(f"{label} must contain a glob pattern")
        if not text.lower().endswith((".yaml", ".yml")):
            raise FleetManifestError(f"{label} must select YAML records")
    elif has_glob:
        raise FleetManifestError(f"{label} must not contain glob metacharacters")
    return text


def _require_path_sequence(
    value: Any,
    label: str,
    *,
    glob: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FleetManifestError(f"{label} must be a non-empty list")
    paths = tuple(
        _require_relative_path(item, f"{label}[{index}]", glob=glob)
        for index, item in enumerate(value)
    )
    if len(set(paths)) != len(paths):
        raise FleetManifestError(f"{label} must not contain duplicate paths")
    return paths


def _parse_capability_catalogue(raw: Any) -> dict[str, CapabilityDefinition]:
    mapping = _require_mapping(raw, "capability_catalogue")
    if not mapping:
        raise FleetManifestError("capability_catalogue must not be empty")

    catalogue: dict[str, CapabilityDefinition] = {}
    for raw_name, raw_definition in mapping.items():
        name = _require_identifier(raw_name, "capability_catalogue key")
        label = f"capability_catalogue.{name}"
        definition = _require_mapping(raw_definition, label)
        unknown_definition_keys = set(definition) - {"settings"}
        if unknown_definition_keys:
            unknown = ", ".join(sorted(str(key) for key in unknown_definition_keys))
            raise FleetManifestError(f"{label} has unknown keys: {unknown}")

        raw_settings = definition.get("settings", {})
        settings_mapping = _require_mapping(raw_settings, f"{label}.settings")
        setting_definitions: dict[str, CapabilitySettingDefinition] = {}
        for raw_setting_name, raw_setting_definition in settings_mapping.items():
            setting_name = _require_identifier(
                raw_setting_name, f"{label}.settings key"
            )
            setting_label = f"{label}.settings.{setting_name}"
            setting_definition = _require_mapping(
                raw_setting_definition, setting_label
            )
            unknown_setting_keys = set(setting_definition) - {
                "type",
                "required_when_enabled",
                "minimum",
            }
            if unknown_setting_keys:
                unknown = ", ".join(
                    sorted(str(key) for key in unknown_setting_keys)
                )
                raise FleetManifestError(
                    f"{setting_label} has unknown keys: {unknown}"
                )

            value_type = setting_definition.get("type")
            if not isinstance(value_type, str) or value_type not in SETTING_TYPES:
                allowed = ", ".join(sorted(SETTING_TYPES))
                raise FleetManifestError(
                    f"{setting_label}.type must be one of: {allowed}"
                )
            required = setting_definition.get("required_when_enabled", False)
            if not isinstance(required, bool):
                raise FleetManifestError(
                    f"{setting_label}.required_when_enabled must be a boolean"
                )
            minimum = setting_definition.get("minimum")
            if minimum is not None:
                if value_type not in {"integer", "number"} or not isinstance(
                    minimum, (int, float)
                ) or isinstance(minimum, bool) or (
                    isinstance(minimum, float) and not isfinite(minimum)
                ):
                    raise FleetManifestError(
                        f"{setting_label}.minimum requires an integer or number setting"
                    )

            setting_definitions[setting_name] = CapabilitySettingDefinition(
                name=setting_name,
                value_type=value_type,
                required_when_enabled=required,
                minimum=float(minimum) if minimum is not None else None,
            )

        catalogue[name] = CapabilityDefinition(
            name=name,
            settings=MappingProxyType(setting_definitions),
        )
    return catalogue


def _validate_setting_value(
    value: Any,
    definition: CapabilitySettingDefinition,
    label: str,
) -> Any:
    expected = definition.value_type
    if expected == "string_list":
        if not isinstance(value, list) or not value:
            raise FleetManifestError(
                f"{label} must be a non-empty list of non-empty strings"
            )
        normalized = tuple(
            _require_nonempty_string(item, f"{label}[{index}]")
            for index, item in enumerate(value)
        )
        if len(set(normalized)) != len(normalized):
            raise FleetManifestError(f"{label} must not contain duplicate values")
        return normalized

    valid = {
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or isfinite(value)),
        "string": isinstance(value, str) and bool(value.strip()),
    }[expected]
    if not valid:
        article = "an" if expected == "integer" else "a"
        raise FleetManifestError(f"{label} must be {article} {expected}")
    if definition.minimum is not None and value < definition.minimum:
        raise FleetManifestError(
            f"{label} must be at least {definition.minimum:g}"
        )
    return value


def _parse_capabilities(
    raw: Any,
    mech_key: str,
    catalogue: Optional[Mapping[str, CapabilityDefinition]] = None,
    *,
    require_exact: bool = False,
) -> dict[str, Capability]:
    capabilities: dict[str, Capability] = {}
    if raw is None:
        if require_exact:
            raise FleetManifestError(f"mechs.{mech_key}.capabilities is required")
        return capabilities
    mapping = _require_mapping(raw, f"mechs.{mech_key}.capabilities")

    names = {
        _require_identifier(name, f"mechs.{mech_key}.capabilities key")
        for name in mapping
    }
    if require_exact:
        if catalogue is None:  # pragma: no cover - internal misuse guard
            raise AssertionError("exact capability validation requires a catalogue")
        missing = set(catalogue) - names
        unknown = names - set(catalogue)
        if missing:
            raise FleetManifestError(
                f"mechs.{mech_key}.capabilities is missing declarations: "
                + ", ".join(sorted(missing))
            )
        if unknown:
            raise FleetManifestError(
                f"mechs.{mech_key}.capabilities has unknown declarations: "
                + ", ".join(sorted(unknown))
            )

    for raw_name, declaration in mapping.items():
        name = _require_identifier(raw_name, f"mechs.{mech_key}.capabilities key")
        label = f"mechs.{mech_key}.capabilities.{name}"
        declaration_mapping = _require_mapping(declaration, label)
        unknown_declaration_keys = set(declaration_mapping) - {
            "status",
            "reason",
            "settings",
        }
        if unknown_declaration_keys:
            unknown_keys = ", ".join(
                sorted(str(key) for key in unknown_declaration_keys)
            )
            raise FleetManifestError(f"{label} has unknown keys: {unknown_keys}")
        status = declaration_mapping.get("status")
        # `isinstance` first: a list/dict from YAML is unhashable, and a bare
        # membership test would raise TypeError instead of FleetManifestError.
        if not isinstance(status, str) or status not in CAPABILITY_STATUSES:
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

        raw_settings = declaration_mapping.get("settings", {})
        settings_mapping = _require_mapping(raw_settings, f"{label}.settings")
        settings = dict(settings_mapping)
        if catalogue is not None and name in catalogue:
            setting_definitions = catalogue[name].settings
            unknown_settings = set(settings) - set(setting_definitions)
            if unknown_settings:
                raise FleetManifestError(
                    f"{label}.settings has unknown keys: "
                    + ", ".join(sorted(str(key) for key in unknown_settings))
                )
            if status == "enabled":
                missing_settings = {
                    setting_name
                    for setting_name, definition in setting_definitions.items()
                    if definition.required_when_enabled and setting_name not in settings
                }
                if missing_settings:
                    raise FleetManifestError(
                        f"{label}.settings is missing required keys: "
                        + ", ".join(sorted(missing_settings))
                    )
            for setting_name, value in settings.items():
                settings[setting_name] = _validate_setting_value(
                    value,
                    setting_definitions[setting_name],
                    f"{label}.settings.{setting_name}",
                )

        capabilities[name] = Capability(
            name=name,
            status=status,
            reason=reason,
            settings=MappingProxyType(settings),
        )

    return capabilities


@dataclass(frozen=True)
class _MechIdentity:
    key: str
    display_name: str
    github: str
    environment_variable: str
    vendored_role: str


def _parse_mech_identity(key: str, raw: Any) -> _MechIdentity:
    label = f"mechs.{key}"
    mapping = _require_mapping(raw, label)

    vendored_role = mapping.get("vendored_role")
    if not isinstance(vendored_role, str) or vendored_role not in VENDORED_ROLES:
        allowed = ", ".join(sorted(VENDORED_ROLES))
        raise FleetManifestError(
            f"{label}.vendored_role must be one of: {allowed} (got {vendored_role!r})"
        )

    # Validate declaration syntax before global duplicate/hub checks. Exact
    # catalogue coverage is enforced after those legacy identity invariants so
    # callers receive the most actionable defect first.
    _parse_capabilities(mapping.get("capabilities"), key)
    return _MechIdentity(
        key=key,
        display_name=_require_nonempty_string(
            mapping.get("display_name"), f"{label}.display_name"
        ),
        github=_require_identity(mapping.get("github"), f"{label}.github"),
        environment_variable=_require_environment_variable(
            mapping.get("environment_variable"), f"{label}.environment_variable"
        ),
        vendored_role=vendored_role,
    )


def _parse_mech(
    key: str,
    raw: Any,
    catalogue: Mapping[str, CapabilityDefinition],
) -> MechDefinition:
    label = f"mechs.{key}"
    mapping = _require_mapping(raw, label)
    allowed_keys = {
        "display_name",
        "github",
        "environment_variable",
        "package_path",
        "schema_paths",
        "record_globs",
        "vendored_role",
        "capabilities",
    }
    unknown_keys = set(mapping) - allowed_keys
    if unknown_keys:
        unknown = ", ".join(sorted(str(item) for item in unknown_keys))
        raise FleetManifestError(f"{label} has unknown keys: {unknown}")

    identity = _parse_mech_identity(key, mapping)
    schema_paths = _require_path_sequence(
        mapping.get("schema_paths"), f"{label}.schema_paths"
    )
    for index, schema_path in enumerate(schema_paths):
        if not schema_path.lower().endswith((".yaml", ".yml")):
            raise FleetManifestError(
                f"{label}.schema_paths[{index}] must identify a YAML schema"
            )
    record_globs = _require_path_sequence(
        mapping.get("record_globs"), f"{label}.record_globs", glob=True
    )
    capabilities = _parse_capabilities(
        mapping.get("capabilities"),
        key,
        catalogue,
        require_exact=True,
    )
    coverage = capabilities.get("environment_coverage")
    if coverage is not None and "record_globs" in coverage.settings:
        coverage_globs = tuple(
            _require_relative_path(
                pattern,
                f"{label}.capabilities.environment_coverage.settings."
                f"record_globs[{index}]",
                glob=True,
            )
            for index, pattern in enumerate(coverage.settings["record_globs"])
        )
        outside_profile = set(coverage_globs) - set(record_globs)
        if outside_profile:
            raise FleetManifestError(
                f"{label}.capabilities.environment_coverage.settings."
                "record_globs must be a subset of the Mech record_globs profile: "
                + ", ".join(sorted(outside_profile))
            )

    return MechDefinition(
        key=identity.key,
        display_name=identity.display_name,
        github=identity.github,
        environment_variable=identity.environment_variable,
        package_path=_require_relative_path(
            mapping.get("package_path"), f"{label}.package_path"
        ),
        schema_paths=schema_paths,
        record_globs=record_globs,
        vendored_role=identity.vendored_role,
        capabilities=MappingProxyType(capabilities),
    )


def parse_fleet_manifest(document: Any, source: Path) -> FleetManifest:
    """Validate an already-loaded manifest document."""

    mapping = _require_mapping(document, f"Fleet manifest {source}")

    version = mapping.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or (
        version not in SUPPORTED_VERSIONS
    ):
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_VERSIONS))
        raise FleetManifestError(
            f"Fleet manifest {source} version must be one of: {supported} "
            f"(got {version!r})"
        )

    raw_mechs = _require_mapping(mapping.get("mechs"), "mechs")
    if not raw_mechs:
        raise FleetManifestError("Fleet manifest must declare at least one Mech")

    mech_keys = [
        _require_identifier(key, "mechs key")
        for key in raw_mechs
    ]
    identities_by_key = {
        key: _parse_mech_identity(key, raw_mechs[key]) for key in mech_keys
    }

    identities = [mech.github.lower() for mech in identities_by_key.values()]
    if len(set(identities)) != len(identities):
        raise FleetManifestError("Fleet manifest declares a duplicate GitHub identity")

    environment_variables = [
        mech.environment_variable for mech in identities_by_key.values()
    ]
    if len(set(environment_variables)) != len(environment_variables):
        raise FleetManifestError(
            "Fleet manifest declares a duplicate environment variable"
        )

    hubs = [
        key
        for key, mech in identities_by_key.items()
        if mech.vendored_role == "hub"
    ]
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

    allowed_top_level_keys = {
        "version",
        "capability_catalogue",
        "vendored_hub",
        "mechs",
    }
    unknown_top_level_keys = set(mapping) - allowed_top_level_keys
    if unknown_top_level_keys:
        unknown = ", ".join(sorted(str(key) for key in unknown_top_level_keys))
        raise FleetManifestError(f"Fleet manifest has unknown keys: {unknown}")

    capability_catalogue = _parse_capability_catalogue(
        mapping.get("capability_catalogue")
    )
    mechs = {
        key: _parse_mech(key, raw_mechs[key], capability_catalogue)
        for key in mech_keys
    }
    return FleetManifest(
        mechs=mechs,
        capability_catalogue=capability_catalogue,
        vendored_hub=vendored_hub,
        source=source,
    )


def _load_uncached(path: Path) -> FleetManifest:
    try:
        document = yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=UniqueKeySafeLoader,
        )
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
