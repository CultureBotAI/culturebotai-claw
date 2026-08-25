"""Validated repository settings shared by cross-repository plugins.

Repository paths are security boundaries: an unset environment variable must
never be interpreted as the current working directory.  This module resolves
and validates those paths once, retains useful configuration errors for each
repository, and revalidates Git identity immediately before an operation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

import yaml  # type: ignore[import-untyped]
from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from kg_microbe_fleet import load_fleet_manifest


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


@dataclass(frozen=True)
class RepositoryDefinition:
    """Static identity and environment-variable mapping for a repository."""

    environment_variable: str
    expected_repository: str


def _definitions_from_manifest() -> "dict[str, RepositoryDefinition]":
    """Derive the repository registry from the canonical fleet manifest.

    The registry used to be a literal here, which is how it drifted to three
    Mechs while other components knew four or five. Deriving it means adding a
    repository to ``conf/fleet.yaml`` is sufficient.
    """

    manifest = load_fleet_manifest()
    return {
        key: RepositoryDefinition(mech.environment_variable, mech.github)
        for key, mech in manifest.mechs.items()
    }


DEFAULT_REPOSITORIES: Mapping[str, RepositoryDefinition] = _definitions_from_manifest()

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
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
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
        host = parsed.hostname
        value = parsed.path
    else:
        return None

    # A different host can spoof the same path, so the remote host is part of
    # the repository identity boundary.
    if host is None or host.lower() != "github.com":
        return None

    parts = [part for part in value.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    repository = parts[-1]
    if repository.lower().endswith(".git"):
        repository = repository[:-4]
    return f"{parts[-2]}/{repository}"


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
            origin_urls = list(repo.remote("origin").urls)
        except (ValueError, AttributeError, GitCommandError) as exc:
            raise RepositoryConfigurationError(
                f"Repository '{self.name}' has no origin remote; expected "
                f"{self.expected_repository}"
            ) from exc

        identities = {
            identity.lower()
            for url in origin_urls
            if (identity := _repository_identity(url)) is not None
        }
        if self.expected_repository.lower() not in identities:
            actual = ", ".join(sorted(identities)) or "unrecognizable origin URL"
            raise RepositoryConfigurationError(
                f"Repository '{self.name}' origin identity mismatch: expected "
                f"{self.expected_repository}, found {actual}"
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
    ) -> "RepositorySettings":
        """Build settings from repository config and environment variables.

        ``config["repositories"]`` may override a path. Paths may contain
        shell-style ``$VAR`` or ``${VAR}`` references; missing references are
        rejected. Expected Git identities are fixed by
        :data:`DEFAULT_REPOSITORIES`, rather than configurable by callers.
        """

        config = config or {}
        env = os.environ if environ is None else environ
        configured_repositories = config.get("repositories", {})
        if not isinstance(configured_repositories, Mapping):
            raise RepositoryConfigurationError("'repositories' must be a mapping")

        unknown = set(configured_repositories) - set(DEFAULT_REPOSITORIES)
        if unknown:
            names = ", ".join(sorted(str(name) for name in unknown))
            raise RepositoryConfigurationError(
                f"Unknown repositories in config: {names}"
            )

        targets: dict[str, RepositoryTarget] = {}
        errors: dict[str, str] = {}
        unconfigured: list[str] = []

        for name, definition in DEFAULT_REPOSITORIES.items():
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

        return cls(targets, errors, tuple(DEFAULT_REPOSITORIES), tuple(unconfigured))

    @classmethod
    def from_file(
        cls,
        config_path: Path,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "RepositorySettings":
        """Load and validate the repository section of an OpenClaw YAML file."""

        loaded = load_configuration(config_path)
        return cls.from_environment(loaded, environ=environ)

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

        try:
            expanded = Template(raw_path.strip()).substitute(environ)
        except (KeyError, ValueError) as exc:
            # `path: ${THIS_REPO_ROOT}` with that variable unset means the
            # repository is simply not set up on this machine — the same
            # condition as an absent path, reached by a different route. Any
            # OTHER unresolved variable is a genuine configuration defect (a
            # typo, or a dependency on an undeclared variable) and stays fatal.
            missing = exc.args[0] if isinstance(exc, KeyError) and exc.args else None
            if missing == environment_variable:
                raise RepositoryNotConfiguredError(
                    f"Repository '{name}' path is not configured; set "
                    f"{environment_variable}"
                ) from exc
            raise RepositoryConfigurationError(
                f"Repository '{name}' path contains an unexpanded variable: {raw_path}"
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
