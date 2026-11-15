"""Anonymous, bounded metadata reads for explicitly declared public consumers."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Collection

from . import private_scaleup_audit as manual

MAX_METADATA_BYTES = 256 * 1024
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class PublicRepositoryMetadata:
    """No credentials, redirects, arbitrary API paths, or private audit access."""

    def __init__(self, repositories: Collection[str]):
        manual.require(
            len(repositories) <= 100
            and all(
                isinstance(name, str)
                and REPOSITORY.fullmatch(name) is not None
                and name.casefold() != manual.PRIVATE.casefold()
                for name in repositories
            ),
            "transport_refused",
        )
        self._repositories = frozenset(repositories)
        self._opener = urllib.request.build_opener(manual.NoRedirect())

    def get(self, repository: str) -> dict:
        manual.require(
            isinstance(repository, str) and repository in self._repositories,
            "transport_refused",
        )
        request = urllib.request.Request(
            "https://api.github.com/repos/" + repository,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "claw-public-governance-audit",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                manual.require(response.status == 200, "transport_refused")
                raw = response.read(MAX_METADATA_BYTES + 1)
            manual.require(len(raw) <= MAX_METADATA_BYTES, "transport_refused")
            value = manual.parse_json(raw)
            manual.require(
                isinstance(value, dict)
                and value.get("full_name") == repository
                and value.get("private") is False
                and value.get("default_branch") == "main",
                "source_unverified",
            )
            return value
        except (OSError, ValueError, urllib.error.URLError):
            raise manual.AuditError("transport_refused") from None
