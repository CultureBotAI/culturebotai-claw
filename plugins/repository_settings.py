"""Validated repository settings shared by cross-repository plugins.

Repository paths are security boundaries: an unset environment variable must
never be interpreted as the current working directory.  This module resolves
and validates those paths once, retains useful configuration errors for each
repository, and revalidates Git identity immediately before an operation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import StringIO
from math import isfinite
from pathlib import Path
from string import Template
from types import MappingProxyType
from typing import Any, Mapping, Optional, cast
from urllib.parse import urlparse

import yaml  # type: ignore[import-untyped]
from dotenv import dotenv_values
from dotenv.parser import parse_stream
from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from kg_microbe_fleet import FleetManifest, UniqueKeySafeLoader, load_fleet_manifest

_MAX_ENVIRONMENT_EXPANSIONS = 32
_ESCAPED_DOLLAR_SENTINEL = "\ue000KG_MICROBE_ESCAPED_DOLLAR\ue001"


class RepositoryConfigurationError(ValueError):
    """Raised when a configured repository cannot be trusted."""


class RepositoryNotConfiguredError(RepositoryConfigurationError):
    """Raised when a repository has no configured path at all.

    Distinct from its parent because "you do not have this repository cloned"
    and "this repository is configured but untrustworthy" warrant different
    handling by a preflight command. It remains a
    :class:`RepositoryConfigurationError` so every existing ``except`` clause,
    and every fail-closed access path, is unchanged.
    """


def merged_repository_environment(
    dotenv_path: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Return repository-root variables with exported values taking precedence.

    Dotenv loading is always explicit: callers choose the exact file rather
    than searching from their current directory. An explicitly selected path
    must be a regular, non-symlink file. The process environment is never
    mutated and unrelated values are never printed.
    """

    exported = dict(os.environ if environ is None else environ)
    if dotenv_path is None:
        return exported

    path = dotenv_path.expanduser()
    if path.is_symlink():
        raise RepositoryConfigurationError(
            f"dotenv file must be a regular, non-symlink file: {path}"
        )
    if not path.exists():
        raise RepositoryConfigurationError(f"dotenv file does not exist: {path}")
    if not path.is_file():
        raise RepositoryConfigurationError(
            f"dotenv path must be a regular file: {path}"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RepositoryConfigurationError(
            f"unable to read dotenv file {path}: {exc}"
        ) from exc
    seen: set[str] = set()
    for binding in parse_stream(StringIO(text)):
        if binding.error:
            raise RepositoryConfigurationError(
                f"dotenv file is malformed at line {binding.original.line}: {path}"
            )
        if binding.key is None:
            continue
        if binding.key in seen:
            raise RepositoryConfigurationError(
                f"dotenv file has duplicate key {binding.key!r}: {path}"
            )
        seen.add(binding.key)

    # Prevalidation above is necessary because python-dotenv otherwise logs a
    # warning and returns a partial mapping for malformed input.
    # Expansion belongs to the repository-path resolver below. Letting
    # python-dotenv interpolate here silently turns an unknown variable into
    # an empty string (for example ``${MISSING}/repo`` becomes ``/repo``),
    # which can redirect an operation to an unintended checkout.
    loaded = dotenv_values(stream=StringIO(text), verbose=False, interpolate=False)
    merged = {
        key: value
        for key, value in loaded.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    merged.update(exported)
    return merged


@dataclass(frozen=True)
class RepositoryDefinition:
    """Static identity and environment-variable mapping for a repository."""

    environment_variable: str
    expected_repository: str
    display_name: str = ""


def repository_definitions(
    manifest: Optional[FleetManifest] = None,
) -> "dict[str, RepositoryDefinition]":
    """Derive the repository registry from the canonical fleet manifest.

    The registry used to be a literal here, which is how it drifted to three
    Mechs while other components knew four or five. Deriving it means adding a
    repository to the manifest is sufficient.

    ``display_name`` is carried for consumers that need presentation metadata.
    The definitions are resolved when settings are built, never frozen at
    import time, so a command can load one manifest and inject that same
    snapshot into every consumer.
    """

    manifest = manifest or load_fleet_manifest()
    return {
        key: RepositoryDefinition(
            mech.environment_variable, mech.github, mech.display_name
        )
        for key, mech in manifest.mechs.items()
    }


# Backward-compatible read-only snapshot for callers that imported the symbol
# before the fleet manifest was centralized. Supported commands deliberately
# call ``repository_definitions(manifest)`` instead so one command uses one
# injected manifest snapshot. New integrations should do the same.
DEFAULT_REPOSITORIES: Mapping[str, RepositoryDefinition] = MappingProxyType(
    repository_definitions()
)

KNOWN_CONFIGURATION_SECTIONS = {
    "openclaw",
    "repositories",
    "agents",
    "plugins",
    "pipelines",
    "safety",
    "monitoring",
    "performance",
}


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or isfinite(value))
    )


def configuration_structure_errors(config: Mapping[str, Any]) -> list[str]:
    """Return structural errors for the configuration surfaces consumed here."""

    errors: list[str] = []
    unknown = set(config) - KNOWN_CONFIGURATION_SECTIONS
    if unknown:
        names = ", ".join(sorted(str(key) for key in unknown))
        errors.append(f"Unknown top-level configuration keys: {names}")

    for section in KNOWN_CONFIGURATION_SECTIONS:
        value = config.get(section)
        if section in config and not isinstance(value, Mapping):
            errors.append(f"'{section}' must be a mapping")

    section_keys = {
        "openclaw": {"version", "mode", "log_level", "workspace"},
        "agents": {"discovery_paths", "defaults"},
        "plugins": {"enabled", "paths"},
        "safety": {
            "require_approval_for",
            "create_backups",
            "backup_directory",
            "allowed_operations",
        },
        "monitoring": {
            "enable_logging",
            "log_directory",
            "metrics_enabled",
            "cost_tracking",
            "max_cost_per_run",
        },
        "performance": {"parallel_agents", "cache_enabled", "cache_ttl"},
    }
    for section, allowed in section_keys.items():
        section_value = config.get(section)
        if not isinstance(section_value, Mapping):
            continue
        unknown_section_keys = set(section_value) - allowed
        if unknown_section_keys:
            names = ", ".join(sorted(str(key) for key in unknown_section_keys))
            errors.append(f"'{section}' has unknown keys: {names}")

    repositories = config.get("repositories")
    if isinstance(repositories, Mapping):
        allowed_repository_keys = {
            "path",
            "type",
            "package_manager",
            "task_runner",
            "description",
        }
        for name, repository in repositories.items():
            if isinstance(repository, str):
                continue
            if not isinstance(repository, Mapping):
                errors.append(
                    f"'repositories.{name}' must be a mapping or path string"
                )
                continue
            unknown_repository_keys = set(repository) - allowed_repository_keys
            if unknown_repository_keys:
                unknown_names = ", ".join(
                    sorted(str(key) for key in unknown_repository_keys)
                )
                errors.append(
                    f"'repositories.{name}' has unknown keys: {unknown_names}"
                )
            for key, value in repository.items():
                if key in allowed_repository_keys and not isinstance(value, str):
                    errors.append(f"'repositories.{name}.{key}' must be a string")

    def expect(section: str, key: str, expected: type, description: str) -> None:
        section_value = config.get(section)
        if not isinstance(section_value, Mapping) or key not in section_value:
            return
        value = section_value[key]
        if expected is float:
            valid = _is_number(value)
        elif expected is int:
            valid = isinstance(value, int) and not isinstance(value, bool)
        else:
            valid = isinstance(value, expected)
        if not valid:
            errors.append(f"'{section}.{key}' must be {description}")

    def expect_string_list(section: str, key: str) -> None:
        section_value = config.get(section)
        if not isinstance(section_value, Mapping) or key not in section_value:
            return
        value = section_value[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"'{section}.{key}' must be a list of strings")

    def expect_range(
        mapping: Mapping[str, Any],
        key: str,
        label: str,
        *,
        minimum: float,
        maximum: float | None = None,
    ) -> None:
        value = mapping.get(key)
        if not _is_number(value):
            return
        numeric_value = cast("int | float", value)
        if numeric_value < minimum or (
            maximum is not None and numeric_value > maximum
        ):
            bounds = (
                f"between {minimum:g} and {maximum:g}"
                if maximum is not None
                else f"at least {minimum:g}"
            )
            errors.append(f"'{label}.{key}' must be {bounds}")

    for key in ("version", "mode", "log_level", "workspace"):
        expect("openclaw", key, str, "a string")
    expect_string_list("agents", "discovery_paths")
    expect("agents", "defaults", dict, "a mapping")
    expect_string_list("plugins", "enabled")
    expect_string_list("plugins", "paths")
    expect_string_list("safety", "require_approval_for")
    expect("safety", "create_backups", bool, "a boolean")
    expect("safety", "backup_directory", str, "a string")
    expect("safety", "allowed_operations", dict, "a mapping")
    expect("monitoring", "enable_logging", bool, "a boolean")
    expect("monitoring", "log_directory", str, "a string")
    expect("monitoring", "metrics_enabled", bool, "a boolean")
    expect("monitoring", "cost_tracking", bool, "a boolean")
    expect("monitoring", "max_cost_per_run", float, "a number")
    expect("performance", "parallel_agents", int, "an integer")
    expect("performance", "cache_enabled", bool, "a boolean")
    expect("performance", "cache_ttl", float, "a number")
    monitoring = config.get("monitoring")
    if isinstance(monitoring, Mapping):
        expect_range(
            monitoring,
            "max_cost_per_run",
            "monitoring",
            minimum=0,
        )
    performance = config.get("performance")
    if isinstance(performance, Mapping):
        expect_range(performance, "parallel_agents", "performance", minimum=1)
        expect_range(performance, "cache_ttl", "performance", minimum=0)

    pipelines = config.get("pipelines")
    if isinstance(pipelines, Mapping):
        for name, pipeline in pipelines.items():
            if not isinstance(pipeline, Mapping):
                errors.append(f"'pipelines.{name}' must be a mapping")
                continue
            pipeline_types = {
                "description": (str, "a string"),
                "batch_size": (int, "an integer"),
                "auto_accept_threshold": (float, "a number"),
                "max_cost_per_run": (float, "a number"),
                "dry_run_default": (bool, "a boolean"),
                "canonical_storage": (str, "a string"),
                "sync_mode": (str, "a string"),
                "min_synonym_overlap": (float, "a number"),
            }
            allowed_pipeline_keys = set(pipeline_types) | {
                "quality_gates",
                "deduplication_strategies",
            }
            unknown_pipeline_keys = set(pipeline) - allowed_pipeline_keys
            if unknown_pipeline_keys:
                unknown_names = ", ".join(
                    sorted(str(key) for key in unknown_pipeline_keys)
                )
                errors.append(
                    f"'pipelines.{name}' has unknown keys: {unknown_names}"
                )
            for key, (expected, description) in pipeline_types.items():
                if key not in pipeline:
                    continue
                value = pipeline[key]
                if expected is float:
                    valid = _is_number(value)
                elif expected is int:
                    valid = isinstance(value, int) and not isinstance(value, bool)
                else:
                    valid = isinstance(value, expected)
                if not valid:
                    errors.append(f"'pipelines.{name}.{key}' must be {description}")
            expect_range(pipeline, "batch_size", f"pipelines.{name}", minimum=1)
            expect_range(
                pipeline,
                "auto_accept_threshold",
                f"pipelines.{name}",
                minimum=0,
                maximum=1,
            )
            expect_range(
                pipeline,
                "max_cost_per_run",
                f"pipelines.{name}",
                minimum=0,
            )
            expect_range(
                pipeline,
                "min_synonym_overlap",
                f"pipelines.{name}",
                minimum=0,
                maximum=1,
            )
            for key in ("quality_gates", "deduplication_strategies"):
                value = pipeline.get(key)
                if value is not None and (
                    not isinstance(value, list)
                    or not all(isinstance(item, str) for item in value)
                ):
                    errors.append(f"'pipelines.{name}.{key}' must be a list of strings")

    agents = config.get("agents")
    if isinstance(agents, Mapping) and isinstance(agents.get("defaults"), Mapping):
        defaults = agents["defaults"]
        default_types = {
            "temperature": float,
            "max_tokens": int,
            "timeout": int,
            "retry_on_failure": bool,
            "max_retries": int,
        }
        unknown_default_keys = set(defaults) - set(default_types)
        if unknown_default_keys:
            names = ", ".join(sorted(str(key) for key in unknown_default_keys))
            errors.append(f"'agents.defaults' has unknown keys: {names}")
        for key, expected in default_types.items():
            if key not in defaults:
                continue
            value = defaults[key]
            if expected is float:
                valid = _is_number(value)
            elif expected is int:
                valid = isinstance(value, int) and not isinstance(value, bool)
            else:
                valid = isinstance(value, expected)
            if not valid:
                errors.append(f"'agents.defaults.{key}' has the wrong type")
        expect_range(defaults, "temperature", "agents.defaults", minimum=0, maximum=2)
        expect_range(defaults, "max_tokens", "agents.defaults", minimum=1)
        expect_range(defaults, "timeout", "agents.defaults", minimum=1)
        expect_range(defaults, "max_retries", "agents.defaults", minimum=0)

    safety = config.get("safety")
    if isinstance(safety, Mapping):
        operations = safety.get("allowed_operations")
        if isinstance(operations, Mapping):
            for name, allowed in operations.items():
                if not isinstance(allowed, bool):
                    errors.append(
                        f"'safety.allowed_operations.{name}' must be a boolean"
                    )

    return errors


def load_configuration(config_path: Path) -> Mapping[str, Any]:
    """Load a YAML configuration and reject unsupported structure."""

    try:
        loaded = yaml.load(
            config_path.read_text(encoding="utf-8"),
            Loader=UniqueKeySafeLoader,
        )
    except (OSError, yaml.YAMLError) as exc:
        raise RepositoryConfigurationError(
            f"Unable to load configuration {config_path}: {exc}"
        ) from exc
    if not isinstance(loaded, Mapping):
        raise RepositoryConfigurationError(
            f"Configuration {config_path} must contain a YAML mapping"
        )
    errors = configuration_structure_errors(loaded)
    if errors:
        raise RepositoryConfigurationError("; ".join(errors))
    return loaded


def _repository_identity(remote_url: str) -> Optional[str]:
    """Return a GitHub ``owner/repository`` from common remote URL forms."""

    value = remote_url.strip().rstrip("/")
    if not value:
        return None

    # Convert Git's SCP-like syntax (git@github.com:owner/repo.git) to a path.
    host: Optional[str]
    if "://" not in value and ":" in value:
        host, value = value.split(":", 1)
        host = host.rsplit("@", 1)[-1]
    elif "://" in value:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in {"https", "ssh"}:
            return None
        try:
            port = parsed.port
        except ValueError:
            return None
        expected_port = 443 if parsed.scheme.lower() == "https" else 22
        if port not in {None, expected_port} or parsed.query or parsed.fragment:
            return None
        host = parsed.hostname
        value = parsed.path
    else:
        return None

    # A different host can spoof the same path, so the remote host is part of
    # the repository identity boundary.
    if host is None or host.lower() != "github.com":
        return None

    parts = [part for part in value.strip("/").split("/") if part]
    if len(parts) != 2:
        return None
    repository = parts[-1]
    if repository.lower().endswith(".git"):
        repository = repository[:-4]
    return f"{parts[0]}/{repository}"


@dataclass(frozen=True)
class RepositoryTarget:
    """A resolved repository target with its expected Git identity."""

    name: str
    path: Path
    expected_repository: str

    def open(self) -> Repo:
        """Open and revalidate this exact Git worktree and its ``origin``."""

        if not self.path.exists():
            raise RepositoryConfigurationError(
                f"Repository '{self.name}' path does not exist: {self.path}"
            )
        if not self.path.is_dir():
            raise RepositoryConfigurationError(
                f"Repository '{self.name}' path is not a directory: {self.path}"
            )

        try:
            repo = Repo(self.path, search_parent_directories=False)
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            raise RepositoryConfigurationError(
                f"Repository '{self.name}' path is not a Git repository: {self.path}"
            ) from exc

        worktree = repo.working_tree_dir
        if worktree is None or Path(worktree).resolve() != self.path:
            raise RepositoryConfigurationError(
                f"Repository '{self.name}' path must be the Git worktree root: "
                f"{self.path}"
            )

        try:
            fetch_urls = repo.git.remote("get-url", "--all", "origin").splitlines()
            push_urls = repo.git.remote(
                "get-url", "--push", "--all", "origin"
            ).splitlines()
        except (ValueError, AttributeError, GitCommandError) as exc:
            raise RepositoryConfigurationError(
                f"Repository '{self.name}' has no origin remote; expected "
                f"{self.expected_repository}"
            ) from exc

        expected = self.expected_repository.lower()
        for purpose, urls in (("fetch", fetch_urls), ("push", push_urls)):
            identities = [_repository_identity(url) for url in urls if url.strip()]
            normalized = [identity.lower() for identity in identities if identity]
            if (
                not urls
                or len(identities) != len(urls)
                or len(normalized) != len(urls)
                or any(identity != expected for identity in normalized)
            ):
                actual = ", ".join(sorted(set(normalized)))
                if len(normalized) != len(urls):
                    actual = f"{actual + ', ' if actual else ''}unrecognizable URL"
                raise RepositoryConfigurationError(
                    f"Repository '{self.name}' origin identity mismatch for {purpose}: "
                    f"expected only {self.expected_repository}, found "
                    f"{actual or 'no URL'}"
                )
        return repo


class RepositorySettings:
    """Resolve repository configuration without allowing unsafe fallbacks.

    Invalid settings are retained per repository so callers can instantiate a
    plugin and receive a structured error for the requested target.  No invalid
    path is exposed through :attr:`paths` or returned by :meth:`get_target`.
    """

    def __init__(
        self,
        targets: Mapping[str, RepositoryTarget],
        errors: Mapping[str, str],
        repository_names: tuple[str, ...],
        unconfigured: tuple[str, ...] = (),
    ) -> None:
        self._targets = dict(targets)
        self._errors = dict(errors)
        self._repository_names = repository_names
        self._unconfigured = unconfigured

    @classmethod
    def from_environment(
        cls,
        config: Optional[Mapping[str, Any]] = None,
        environ: Optional[Mapping[str, str]] = None,
        manifest: Optional[FleetManifest] = None,
    ) -> "RepositorySettings":
        """Build settings from repository config and environment variables.

        ``config["repositories"]`` may override a path. Paths may contain
        shell-style ``$VAR`` or ``${VAR}`` references; missing references are
        rejected. Expected Git identities are fixed by the canonical fleet
        manifest, rather than configurable by callers. A caller may pass an
        already-loaded manifest so every part of one command uses the exact
        same fleet snapshot.
        """

        config = config or {}
        env = os.environ if environ is None else environ
        definitions = repository_definitions(manifest)
        configured_repositories = config.get("repositories", {})
        if not isinstance(configured_repositories, Mapping):
            raise RepositoryConfigurationError("'repositories' must be a mapping")

        unknown = set(configured_repositories) - set(definitions)
        if unknown:
            names = ", ".join(sorted(str(name) for name in unknown))
            raise RepositoryConfigurationError(
                f"Unknown repositories in config: {names}"
            )

        targets: dict[str, RepositoryTarget] = {}
        errors: dict[str, str] = {}
        unconfigured: list[str] = []

        for name, definition in definitions.items():
            override = configured_repositories.get(name, {})
            if isinstance(override, str):
                raw_path: Any = override
            elif isinstance(override, Mapping):
                raw_path = override.get(
                    "path", env.get(definition.environment_variable)
                )
            else:
                errors[name] = (
                    f"Repository '{name}' configuration must be a mapping or path string"
                )
                continue

            try:
                target = cls._resolve_target(
                    name=name,
                    raw_path=raw_path,
                    environment_variable=definition.environment_variable,
                    expected_repository=definition.expected_repository,
                    environ=env,
                )
                # Validate eagerly so configuration errors are available before use.
                target.open()
            except RepositoryNotConfiguredError as exc:
                # Recorded in both places: `errors` keeps the historical
                # contract that every non-usable repository is reported there,
                # while `unconfigured` lets a preflight command tell "absent"
                # apart from "present but untrustworthy".
                errors[name] = str(exc)
                unconfigured.append(name)
            except RepositoryConfigurationError as exc:
                errors[name] = str(exc)
            else:
                targets[name] = target

        return cls(targets, errors, tuple(definitions), tuple(unconfigured))

    @classmethod
    def from_file(
        cls,
        config_path: Path,
        environ: Optional[Mapping[str, str]] = None,
        manifest: Optional[FleetManifest] = None,
    ) -> "RepositorySettings":
        """Load and validate the repository section of an OpenClaw YAML file."""

        loaded = load_configuration(config_path)
        return cls.from_environment(loaded, environ=environ, manifest=manifest)

    @staticmethod
    def _resolve_target(
        *,
        name: str,
        raw_path: Any,
        environment_variable: str,
        expected_repository: Any,
        environ: Mapping[str, str],
    ) -> RepositoryTarget:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise RepositoryNotConfiguredError(
                f"Repository '{name}' path is not configured; set {environment_variable}"
            )
        if not isinstance(expected_repository, str) or "/" not in expected_repository:
            raise RepositoryConfigurationError(
                f"Repository '{name}' expected_repository must be 'owner/repository'"
            )

        expanded = raw_path.strip()
        if _ESCAPED_DOLLAR_SENTINEL in expanded or any(
            _ESCAPED_DOLLAR_SENTINEL in value for value in environ.values()
        ):
            raise RepositoryConfigurationError(
                f"Repository '{name}' path contains a reserved expansion marker"
            )

        seen: set[str] = set()
        for expansion_count in range(_MAX_ENVIRONMENT_EXPANSIONS + 1):
            # Preserve Template's ``$$`` escape across recursive rounds. A
            # replacement value may itself contain ``$$``, so protection is
            # applied at every level and restored only after all identifiers
            # have been resolved.
            protected = expanded.replace("$$", _ESCAPED_DOLLAR_SENTINEL)
            if protected in seen:
                raise RepositoryConfigurationError(
                    f"Repository '{name}' path has cyclic variable expansion: "
                    f"{raw_path}"
                )
            seen.add(protected)

            template = Template(protected)
            try:
                identifiers = template.get_identifiers()
            except ValueError as exc:
                raise RepositoryConfigurationError(
                    f"Repository '{name}' path contains an invalid variable: "
                    f"{raw_path}"
                ) from exc

            missing = [
                identifier for identifier in identifiers if identifier not in environ
            ]
            if missing:
                # `path: ${THIS_REPO_ROOT}` with that variable unset means the
                # repository is simply not set up on this machine. Every
                # other missing identifier—including one reached through a
                # configured root—is a fatal configuration defect.
                if (
                    expanded == raw_path.strip()
                    and identifiers == [environment_variable]
                    and missing == [environment_variable]
                ):
                    raise RepositoryNotConfiguredError(
                        f"Repository '{name}' path is not configured; set "
                        f"{environment_variable}"
                    )
                raise RepositoryConfigurationError(
                    f"Repository '{name}' path contains an unexpanded variable: "
                    f"{raw_path}"
                )

            if not identifiers:
                expanded = protected.replace(_ESCAPED_DOLLAR_SENTINEL, "$")
                break
            if expansion_count == _MAX_ENVIRONMENT_EXPANSIONS:
                raise RepositoryConfigurationError(
                    f"Repository '{name}' path exceeded "
                    f"{_MAX_ENVIRONMENT_EXPANSIONS} variable-expansion levels: "
                    f"{raw_path}"
                )
            try:
                expanded = template.substitute(environ)
            except (KeyError, ValueError) as exc:  # defensive mapping/template guard
                raise RepositoryConfigurationError(
                    f"Repository '{name}' path contains an unexpanded variable: "
                    f"{raw_path}"
                ) from exc
        path = Path(expanded).expanduser()
        if not path.is_absolute():
            raise RepositoryConfigurationError(
                f"Repository '{name}' path must be absolute: {raw_path}"
            )
        path = path.resolve()
        return RepositoryTarget(name, path, expected_repository)

    @property
    def names(self) -> tuple[str, ...]:
        """Return all known repository names, including invalid configurations."""

        return self._repository_names

    @property
    def paths(self) -> dict[str, Path]:
        """Return a copy containing only validated repository paths."""

        return {name: target.path for name, target in self._targets.items()}

    @property
    def errors(self) -> dict[str, str]:
        """Return a copy of per-repository configuration errors.

        Includes repositories that are merely unconfigured; see
        :attr:`unconfigured` to separate those out.
        """

        return dict(self._errors)

    @property
    def unconfigured(self) -> tuple[str, ...]:
        """Return repositories whose only problem is having no configured path.

        These are still unusable — :meth:`get_target` and
        :meth:`open_repository` raise for them exactly as before. The
        distinction exists so that not having every Mech cloned locally is not
        reported as a configuration defect.
        """

        return self._unconfigured

    @property
    def invalid(self) -> dict[str, str]:
        """Return configured-but-untrustworthy repositories.

        This is :attr:`errors` minus :attr:`unconfigured`: the problems that
        represent a genuine misconfiguration rather than an absent checkout.
        """

        skip = set(self._unconfigured)
        return {
            name: message
            for name, message in self._errors.items()
            if name not in skip
        }

    def get_target(self, name: str) -> RepositoryTarget:
        """Return a trusted target, revalidating it at operation time."""

        if name not in self._repository_names:
            raise RepositoryConfigurationError(f"Unknown repository: {name}")
        if name in self._errors:
            raise RepositoryConfigurationError(self._errors[name])
        target = self._targets[name]
        target.open()
        return target

    def open_repository(self, name: str) -> Repo:
        """Open a configured repository after operation-time validation."""

        if name not in self._repository_names:
            raise RepositoryConfigurationError(f"Unknown repository: {name}")
        if name in self._errors:
            raise RepositoryConfigurationError(self._errors[name])
        return self._targets[name].open()
