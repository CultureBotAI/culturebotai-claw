"""Anonymous ACS Publications Supporting Information (`.s001`) resolver via Figshare API v2.

American Chemical Society (ACS) journals mirror article Supporting Information (SI)
files (`_si_001.pdf`, `.xlsx`, `.csv`, `.cif`, `.zip`) on the public Figshare API v2
under the child DOI `<article_doi>.s001` (and occasionally `.s002`, etc.).

This module probes `https://api.figshare.com/v2/articles/search` for `<acs_doi>.s001`,
retrieves the full Figshare article record (`https://api.figshare.com/v2/articles/<id>`),
and exposes direct `https://ndownloader.figshare.com/files/<file_id>` URLs without
requiring a browser session, API key, or institutional VPN.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kg_microbe_sources.fetch import (
    FetchPlan,
    FetchResult,
    Transport,
    ValidationFailed,
    fetch,
)

__all__ = [
    "ACS_DOI_PREFIX",
    "ACS_FIGSHARE_API_BASE",
    "AcsFigshareClient",
    "AcsFigshareError",
    "AcsSupportingFile",
    "AcsSupportingInformation",
    "derive_acs_si_doi",
    "md5_of",
    "normalize_acs_doi",
    "sanitize_supporting_filename",
    "stage_acs_supporting_file",
    "try_acs_figshare_si",
]

ACS_DOI_PREFIX = "10.1021/"
ACS_FIGSHARE_API_BASE = "https://api.figshare.com/v2"
USER_AGENT = "kg-microbe-sources/1"

_DOI_URL_PREFIX_RE = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
    re.IGNORECASE,
)
_SI_SUFFIX_RE = re.compile(r"\.s\d{3}$", re.IGNORECASE)

FigshareTransport = Callable[[str, Mapping[str, Any] | None], Any]


class AcsFigshareError(RuntimeError):
    """Raised when an ACS DOI is malformed or the Figshare API returns an unexpected payload."""


@dataclass(frozen=True)
class AcsSupportingFile:
    """One Supporting Information file hosted on ACS Figshare."""

    file_id: int
    name: str
    size: int
    download_url: str
    supplied_md5: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary representation."""
        return asdict(self)


@dataclass(frozen=True)
class AcsSupportingInformation:
    """Resolved ACS Figshare Supporting Information metadata for an ACS article DOI."""

    parent_doi: str
    si_doi: str
    article_id: int
    title: str
    url_public_html: str
    files: tuple[AcsSupportingFile, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary representation."""
        return {
            "parent_doi": self.parent_doi,
            "si_doi": self.si_doi,
            "article_id": self.article_id,
            "title": self.title,
            "url_public_html": self.url_public_html,
            "files": [f.to_dict() for f in self.files],
        }


def normalize_acs_doi(raw_doi: str) -> str:
    """Normalize an ACS DOI string to lowercase `10.1021/<suffix>` (stripping `.s001` if present).

    Raises :class:`AcsFigshareError` if the input is not an ACS (`10.1021/`) DOI.
    """
    cleaned = _DOI_URL_PREFIX_RE.sub("", (raw_doi or "").strip()).strip().lower()
    cleaned = _SI_SUFFIX_RE.sub("", cleaned)
    if not cleaned.startswith(ACS_DOI_PREFIX) or len(cleaned) <= len(ACS_DOI_PREFIX):
        raise AcsFigshareError(
            f"Expected an ACS DOI starting with '{ACS_DOI_PREFIX}', got {raw_doi!r}"
        )
    return cleaned


def derive_acs_si_doi(raw_doi: str, *, index: int = 1) -> str:
    """Return the child Figshare SI DOI (`<parent_doi>.s001`) for an ACS article DOI."""
    if index < 1 or index > 999:
        raise AcsFigshareError(f"SI index must be in 1..999, got {index}")
    parent = normalize_acs_doi(raw_doi)
    return f"{parent}.s{index:03d}"


class _UrlopenFigshareTransport:
    """Default anonymous JSON transport for Figshare API v2 (no email or API key)."""

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    def __call__(self, url: str, json_body: Mapping[str, Any] | None = None) -> Any:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data: bytes | None = None
        method = "GET"
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(dict(json_body)).encode("utf-8")
            method = "POST"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise AcsFigshareError(f"could not fetch {url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AcsFigshareError(f"Figshare returned non-JSON for {url}") from exc


class AcsFigshareClient:
    """Anonymous client for ACS Publications Supporting Information on Figshare API v2."""

    def __init__(
        self,
        *,
        api_base: str = ACS_FIGSHARE_API_BASE,
        timeout: float = 30.0,
        transport: FigshareTransport | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.transport: FigshareTransport = transport or _UrlopenFigshareTransport(
            timeout=timeout
        )

    def search_by_doi(self, si_doi: str) -> list[dict[str, Any]]:
        """Search Figshare API v2 for an exact `:doi:` query."""
        url = f"{self.api_base}/articles/search"
        payload = self.transport(url, {"search_for": f":doi: {si_doi}"})
        if not isinstance(payload, list):
            raise AcsFigshareError(
                f"Expected JSON list from {url}, got {type(payload).__name__}"
            )
        return payload

    def get_article(self, article_id: int) -> dict[str, Any]:
        """Fetch full Figshare article metadata including the `files` array."""
        url = f"{self.api_base}/articles/{article_id}"
        payload = self.transport(url, None)
        if not isinstance(payload, dict):
            raise AcsFigshareError(
                f"Expected JSON object from {url}, got {type(payload).__name__}"
            )
        return payload

    def probe_supporting_info(
        self,
        raw_doi: str,
        *,
        index: int = 1,
    ) -> AcsSupportingInformation | None:
        """Probe Figshare for `<acs_doi>.s001` and return its supporting files if present."""
        parent_doi = normalize_acs_doi(raw_doi)
        si_doi = derive_acs_si_doi(parent_doi, index=index)
        hits = self.search_by_doi(si_doi)
        matched_hit: dict[str, Any] | None = None
        for hit in hits:
            hit_doi = str(hit.get("doi") or "").strip().lower()
            if hit_doi == si_doi:
                matched_hit = hit
                break
        if matched_hit is None and hits:
            first = hits[0]
            if str(first.get("doi") or "").strip().lower().startswith(parent_doi):
                matched_hit = first
        if matched_hit is None:
            return None

        raw_article_id = matched_hit.get("id")
        if not isinstance(raw_article_id, int):
            raise AcsFigshareError(
                f"Figshare search hit for {si_doi} is missing integer 'id': {matched_hit!r}"
            )

        article = self.get_article(raw_article_id)
        files_raw = article.get("files") or []
        supporting_files: list[AcsSupportingFile] = []
        for entry in files_raw:
            if not isinstance(entry, dict):
                continue
            file_id = int(entry.get("id") or 0)
            name = str(entry.get("name") or "").strip()
            size = int(entry.get("size") or 0)
            download_url = str(entry.get("download_url") or "").strip()
            md5 = str(entry.get("supplied_md5") or entry.get("computed_md5") or "").strip()
            if file_id and name and download_url:
                supporting_files.append(
                    AcsSupportingFile(
                        file_id=file_id,
                        name=name,
                        size=size,
                        download_url=download_url,
                        supplied_md5=md5,
                    )
                )

        return AcsSupportingInformation(
            parent_doi=parent_doi,
            si_doi=str(article.get("doi") or si_doi).strip().lower(),
            article_id=raw_article_id,
            title=str(article.get("title") or matched_hit.get("title") or "").strip(),
            url_public_html=str(
                article.get("url_public_html")
                or matched_hit.get("url_public_html")
                or ""
            ).strip(),
            files=tuple(supporting_files),
        )


def try_acs_figshare_si(
    raw_doi: str,
    *,
    index: int = 1,
    timeout: float = 30.0,
    transport: FigshareTransport | None = None,
) -> AcsSupportingInformation | None:
    """Probe Figshare for `<acs_doi>.s001` and return :class:`AcsSupportingInformation` or ``None``."""
    client = AcsFigshareClient(timeout=timeout, transport=transport)
    return client.probe_supporting_info(raw_doi, index=index)


def sanitize_supporting_filename(raw_name: str) -> str:
    """Return a single-component filename stripped of path separators.

    Raises :class:`AcsFigshareError` if the resulting name is empty or a dot traversal.
    """
    cleaned = (raw_name or "").replace("\\", "/").strip()
    basename = Path(cleaned).name.strip()
    if not basename or basename in {".", ".."}:
        raise AcsFigshareError(f"Invalid Figshare supporting filename: {raw_name!r}")
    return basename


def md5_of(path_or_bytes: Path | bytes) -> str:
    """Compute the lowercase hexadecimal MD5 digest of a file path or raw bytes."""
    digest = hashlib.md5()
    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        digest.update(path_or_bytes)
        return digest.hexdigest()
    with Path(path_or_bytes).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_acs_supporting_file(
    si_file: AcsSupportingFile,
    dest_dir: Path,
    *,
    transport: Transport | None = None,
    attempts: int = 4,
    verify_md5: bool = True,
) -> FetchResult:
    """Download an :class:`AcsSupportingFile` into ``dest_dir`` with SHA-256 provenance sidecar."""
    safe_name = sanitize_supporting_filename(si_file.name)
    dest_path = Path(dest_dir) / safe_name
    plan = FetchPlan(
        url=si_file.download_url,
        destination=dest_path,
        min_bytes=max(1, si_file.size),
    )
    result = fetch(plan, transport=transport, attempts=attempts)
    expected_md5 = (si_file.supplied_md5 or "").strip().lower()
    if verify_md5 and expected_md5:
        actual_md5 = md5_of(dest_path).lower()
        if actual_md5 != expected_md5:
            dest_path.unlink(missing_ok=True)
            plan.sidecar.unlink(missing_ok=True)
            raise ValidationFailed(
                f"MD5 mismatch for {safe_name}: got {actual_md5}, expected {expected_md5}"
            )
    return result
