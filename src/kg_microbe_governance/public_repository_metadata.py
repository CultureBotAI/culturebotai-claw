"""Anonymous, bounded metadata reads for explicitly declared public consumers."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Collection
from email.message import Message

from . import private_scaleup_audit as manual

MAX_METADATA_BYTES = 256 * 1024
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
CATEGORIES = frozenset({
    "http_error", "timeout", "url_error", "io_error", "response_status",
    "response_too_large", "invalid_json", "invalid_metadata",
})
QUOTA_HEADERS = {
    "rate_limit": "X-RateLimit-Limit",
    "rate_remaining": "X-RateLimit-Remaining",
    "rate_reset": "X-RateLimit-Reset",
}


def _quota(headers: object) -> dict[str, int]:
    """Retain only bounded ASCII integers, never arbitrary header values."""
    if not isinstance(headers, (dict, Message)):
        return {}
    result = {}
    for key, name in QUOTA_HEADERS.items():
        raw = headers.get(name)
        if isinstance(raw, str) and re.fullmatch(r"[0-9]{1,10}", raw):
            value = int(raw)
            if value <= 4_294_967_295:
                result[key] = value
    return result


class PublicMetadataFailure(manual.AuditError):
    """Original fatal code plus closed observations from an admitted public read."""

    def __init__(self, repository: str, category: str, status: object, headers: object,
                 admitted: frozenset[str]):
        super().__init__("transport_refused")
        self.admitted = admitted
        self.repository = repository
        self.category = category
        self.http_status = status if type(status) is int and 100 <= status <= 599 else None
        self.quota = _quota(headers)


def diagnostic_suffix(error: Exception) -> str:
    """Reject malformed diagnostics instead of printing exception text or URLs."""
    if type(error) is not PublicMetadataFailure:
        return ""
    repository = getattr(error, "repository", None)
    category = getattr(error, "category", None)
    status = getattr(error, "http_status", None)
    quota = getattr(error, "quota", None)
    admitted = getattr(error, "admitted", None)
    if (
        not isinstance(repository, str)
        or not isinstance(admitted, frozenset) or repository not in admitted
        or len(repository) > 200
        or REPOSITORY.fullmatch(repository) is None
        or repository.casefold() == manual.PRIVATE.casefold()
        or not isinstance(category, str) or category not in CATEGORIES
        or (status is not None and (type(status) is not int or not 100 <= status <= 599))
        or not isinstance(quota, dict)
        or any(key not in QUOTA_HEADERS or type(value) is not int or not 0 <= value <= 4_294_967_295
               for key, value in quota.items())
    ):
        return ""
    fields = [f"repository={repository}", f"category={category}"]
    if status is not None:
        fields.append(f"http_status={status}")
    fields.extend(f"{key}={quota[key]}" for key in QUOTA_HEADERS if key in quota)
    return " " + " ".join(fields)


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
        category = "response_status"
        status = None
        headers = None
        try:
            with self._opener.open(request, timeout=30) as response:
                status = response.status
                headers = getattr(response, "headers", None)
                manual.require(response.status == 200, "transport_refused")
                raw = response.read(MAX_METADATA_BYTES + 1)
            category = "response_too_large"
            manual.require(len(raw) <= MAX_METADATA_BYTES, "transport_refused")
            category = "invalid_json"
            value = manual.parse_json(raw)
            category = "invalid_metadata"
            manual.require(
                isinstance(value, dict)
                and value.get("full_name") == repository
                and value.get("private") is False
                and value.get("default_branch") == "main",
                "source_unverified",
            )
            return value
        except urllib.error.HTTPError as error:
            raise PublicMetadataFailure(repository, "http_error", error.code, error.headers, self._repositories) from None
        except TimeoutError:
            raise PublicMetadataFailure(repository, "timeout", status, headers, self._repositories) from None
        except urllib.error.URLError as error:
            category = "timeout" if isinstance(error.reason, TimeoutError) else "url_error"
            raise PublicMetadataFailure(repository, category, status, headers, self._repositories) from None
        except OSError:
            raise PublicMetadataFailure(repository, "io_error", status, headers, self._repositories) from None
        except ValueError:
            # Preserve the existing fatal code even when response validation
            # failed; the category supplies context without changing the gate.
            raise PublicMetadataFailure(repository, category, status, headers, self._repositories) from None
