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


class RepositoryConfigurationError(ValueError):
    """Raised when a configured repository cannot be trusted."""


@dataclass(frozen=True)
class RepositoryDefinition:
    """Static identity and environment-variable mapping for a repository."""

    environment_variable: str
    expected_repository: str


DEFAULT_REPOSITORIES: Mapping[str, RepositoryDefinition] = {
    "culturemech": RepositoryDefinition("CULTUREMECH_ROOT", "CultureBotAI/CultureMech"),
    "mediaingredientmech": RepositoryDefinition(
        "MEDIAINGREDIENTMECH_ROOT", "CultureBotAI/MediaIngredientMech"
    ),
    "communitymech": RepositoryDefinition(
        "COMMUNITYMECH_ROOT", "CultureBotAI/CommunityMech"
    ),
}


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
    ) -> None:
        self._targets = dict(targets)
        self._errors = dict(errors)
        self._repository_names = repository_names

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
            except RepositoryConfigurationError as exc:
                errors[name] = str(exc)
            else:
                targets[name] = target

        return cls(targets, errors, tuple(DEFAULT_REPOSITORIES))

    @classmethod
    def from_file(
        cls,
        config_path: Path,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "RepositorySettings":
        """Load and validate the repository section of an OpenClaw YAML file."""

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
            raise RepositoryConfigurationError(
                f"Repository '{name}' path is not configured; set {environment_variable}"
            )
        if not isinstance(expected_repository, str) or "/" not in expected_repository:
            raise RepositoryConfigurationError(
                f"Repository '{name}' expected_repository must be 'owner/repository'"
            )

        try:
            expanded = Template(raw_path.strip()).substitute(environ)
        except (KeyError, ValueError) as exc:
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
        """Return a copy of per-repository configuration errors."""

        return dict(self._errors)

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
