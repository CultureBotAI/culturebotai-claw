"""Legal full-text discovery ladder for Mech curation and record review.

Given a PMID or DOI, checks legal full-text and open-supplement channels in
deterministic order without disclosing any personal email address in query
parameters or User-Agent headers:

  1. ``zotero_local``    — Read-only SQLite lookup in ``$ZOTERO_DATA_DIR/zotero.sqlite``
                           for synced PDFs in ``$ZOTERO_DATA_DIR/storage/<KEY>/*.pdf``.
  2. ``europepmc_oa``    — Anonymous Europe PMC JATS ``fullTextXML`` when ``isOpenAccess == "Y"``.
  3. ``openalex_oa``     — Anonymous OpenAlex OA location lookup (filtering out bare
                           ``doi.org`` redirects).
  4. ``biorxiv``         — Direct bioRxiv / medRxiv preprint full-text PDF for
                           ``10.1101/*`` and ``10.64898/*`` DOIs.
  5. ``osti_gov``        — Anonymous DOE OSTI.gov API for DOE/LBNL full-text reports
                           and accepted manuscripts.
  6. ``elsevier_tdm``    — Elsevier Article Retrieval XML API (``10.1016/*``) when
                           ``$ELSEVIER_API_KEY`` is set.
  7. ``springer_tdm``    — Springer Nature OpenAccess JATS API (``10.1007/*``,
                           ``10.1038/*``, ``10.1186/*``) when ``$SPRINGER_API_KEY`` is set.
  8. ``wiley_tdm``       — Wiley TDM API v1 (``10.1002/*``, ``10.1111/*``) when
                           ``$WILEY_TDM_TOKEN`` is set.
  9. ``core``            — CORE v3 API full-text lookup when ``$CORE_API_KEY`` is set.
 10. ``acs_figshare_si`` — Public ACS Publications Figshare API v2 for ``10.1021/<suffix>.s001``
                           Supporting Information when an ACS main article is paywalled.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kg_microbe_sources.acs_figshare import (
    ACS_DOI_PREFIX,
    AcsFigshareClient,
    AcsFigshareError,
)

UA = {"User-Agent": "kg-microbe-sources-fulltext/1.0"}

DOI_RESOLVER_RE = re.compile(r"https?://(dx\.)?doi\.org/", re.IGNORECASE)


@dataclass(frozen=True)
class FulltextResolution:
    """Result of running the legal full-text discovery ladder."""

    method: str
    url: str | None
    doi: str | None
    pmid: str | None
    title: str
    staged_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "doi": self.doi,
            "pmid": self.pmid,
            "title": self.title,
            "staged_path": self.staged_path,
        }


def clean_doi(doi: str | None) -> str | None:
    """Strip common URL/CURIE prefixes from a DOI string."""
    if not doi:
        return None
    cleaned = doi.strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
        "DOI:",
    ):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned or None


def _get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    if not url.startswith("https://"):
        return None
    hdr = {**UA, **(headers or {})}
    req = urllib.request.Request(url, headers=hdr)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except Exception:
        return None


def _get_text_prefix(
    url: str, headers: dict[str, str] | None = None, max_bytes: int = 32768
) -> str | None:
    if not url.startswith("https://"):
        return None
    hdr = {**UA, **(headers or {})}
    req = urllib.request.Request(url, headers=hdr)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
            if getattr(response, "status", 200) != 200:
                return None
            return response.read(max_bytes).decode("utf-8", errors="ignore")
    except Exception:
        return None


def _probe_binary_ok(
    url: str, headers: dict[str, str] | None = None, min_bytes: int = 1024
) -> bool:
    if not url.startswith("https://"):
        return False
    hdr = {**UA, **(headers or {})}
    req = urllib.request.Request(url, headers=hdr)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
            if getattr(response, "status", 200) != 200:
                return False
            chunk = response.read(min_bytes)
            return len(chunk) >= min_bytes
    except Exception:
        return False


def epmc_core(pmid: str | None, doi: str | None) -> dict[str, Any]:
    """Query Europe PMC core record for PMCID, OA status, DOI/PMID, title, and authors."""
    if pmid:
        query = f"EXT_ID:{pmid} AND SRC:MED"
    elif doi:
        query = f'DOI:"{doi}"'
    else:
        return {}
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        {"query": query, "format": "json", "resultType": "core", "pageSize": "1"}
    )
    data = _get_json(url) or {}
    results = data.get("resultList", {}).get("result") or [{}]
    first = results[0] if results else {}
    return first if isinstance(first, dict) else {}


def crossref_meta(doi: str | None) -> dict[str, Any]:
    """Retrieve title and author string from CrossRef anonymously."""
    cleaned = clean_doi(doi)
    if not cleaned:
        return {}
    data = _get_json(f"https://api.crossref.org/works/{urllib.parse.quote(cleaned)}")
    message = (data or {}).get("message", {}) if isinstance(data, dict) else {}
    if not isinstance(message, dict) or not message:
        return {}
    authors = ", ".join(
        " ".join(x for x in (a.get("given"), a.get("family")) if x)
        for a in (message.get("author") or [])[:6]
        if isinstance(a, dict)
    )
    titles = message.get("title") or [""]
    title = titles[0] if isinstance(titles, list) and titles else ""
    return {"title": str(title), "authorString": authors}


def try_zotero_local(pmid: str | None = None, doi: str | None = None) -> str | None:
    """Check local Zotero SQLite + storage directory for an already-synced PDF attachment."""
    cleaned_doi = clean_doi(doi)
    cleaned_pmid = (pmid or "").strip()
    if not cleaned_doi and not cleaned_pmid:
        return None

    zotero_env = os.environ.get("ZOTERO_DATA_DIR", "").strip()
    if not zotero_env:
        return None
    zotero_dir = Path(zotero_env)
    db_path = zotero_dir / "zotero.sqlite"
    storage_dir = zotero_dir / "storage"
    if not db_path.is_file() or not storage_dir.is_dir():
        return None

    parent_ids: set[int] = set()
    try:
        uri = f"file:{db_path}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            cur = conn.cursor()
            if cleaned_doi:
                low_doi = cleaned_doi.lower()
                cur.execute(
                    """
                    SELECT id.itemID
                    FROM itemData id
                    JOIN fields f ON id.fieldID = f.fieldID
                    JOIN itemDataValues v ON id.valueID = v.valueID
                    WHERE f.fieldName = 'DOI'
                      AND LOWER(TRIM(v.value)) IN (?, ?, ?)
                    """,
                    (low_doi, f"https://doi.org/{low_doi}", f"doi:{low_doi}"),
                )
                parent_ids.update(row[0] for row in cur.fetchall())

            if cleaned_pmid and not parent_ids:
                cur.execute(
                    """
                    SELECT id.itemID
                    FROM itemData id
                    JOIN fields f ON id.fieldID = f.fieldID
                    JOIN itemDataValues v ON id.valueID = v.valueID
                    WHERE f.fieldName = 'extra'
                      AND v.value LIKE ?
                    """,
                    (f"%PMID: {cleaned_pmid}%",),
                )
                parent_ids.update(row[0] for row in cur.fetchall())

            for parent_id in sorted(parent_ids):
                cur.execute(
                    """
                    SELECT i.key, ia.path
                    FROM itemAttachments ia
                    JOIN items i ON ia.itemID = i.itemID
                    WHERE ia.parentItemID = ?
                      AND ia.contentType = 'application/pdf'
                    """,
                    (parent_id,),
                )
                for att_key, att_path in cur.fetchall():
                    if not att_key or not att_path:
                        continue
                    if att_path.startswith("storage:"):
                        rel_name = att_path[len("storage:") :]
                        pdf_file = storage_dir / att_key / rel_name
                    else:
                        pdf_file = Path(att_path)
                    if pdf_file.is_file():
                        return f"file://{pdf_file.resolve()}"
    except Exception:
        return None
    return None


def try_europepmc(rec: dict[str, Any]) -> str | None:
    """Return Europe PMC JATS fullTextXML URL if the article is marked open access."""
    pmcid = rec.get("pmcid")
    if pmcid and rec.get("isOpenAccess") == "Y":
        return f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    return None


def _non_doi_oa_url(loc: dict[str, Any]) -> str | None:
    pdf_url = loc.get("pdf_url") or loc.get("url_for_pdf")
    landing_url = loc.get("landing_page_url") or loc.get("url")
    for candidate in (pdf_url, landing_url):
        if isinstance(candidate, str) and candidate and not DOI_RESOLVER_RE.match(candidate):
            return candidate
    return None


def try_openalex_oa(doi: str | None, pmid: str | None = None) -> str | None:
    """Anonymous OpenAlex OA location lookup (no email disclosure)."""
    cleaned_doi = clean_doi(doi)
    cleaned_pmid = (pmid or "").strip()
    if cleaned_doi:
        api_url = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(cleaned_doi)}"
    elif cleaned_pmid:
        api_url = f"https://api.openalex.org/works/pmid:{urllib.parse.quote(cleaned_pmid)}"
    else:
        return None

    data = _get_json(api_url)
    if not isinstance(data, dict):
        return None
    oa = data.get("open_access") or {}
    if not isinstance(oa, dict) or not oa.get("is_oa"):
        return None

    best = data.get("best_oa_location") or {}
    if isinstance(best, dict):
        hit = _non_doi_oa_url(best)
        if hit:
            return hit

    oa_url = oa.get("oa_url")
    if isinstance(oa_url, str) and oa_url and not DOI_RESOLVER_RE.match(oa_url):
        return oa_url

    for loc in data.get("locations") or []:
        if isinstance(loc, dict) and loc.get("is_oa"):
            hit = _non_doi_oa_url(loc)
            if hit:
                return hit
    return None


def try_unpaywall(doi: str | None) -> str | None:
    """Backward-compatible wrapper that queries OpenAlex OA anonymously."""
    return try_openalex_oa(doi)


def try_biorxiv(doi: str | None) -> str | None:
    """Check bioRxiv / medRxiv API for 10.1101 / 10.64898 preprint full-text PDFs."""
    cleaned_doi = clean_doi(doi)
    if not cleaned_doi or not cleaned_doi.startswith(("10.1101/", "10.64898/")):
        return None
    quoted = urllib.parse.quote(cleaned_doi, safe="/")
    for server in ("biorxiv", "medrxiv"):
        data = _get_json(f"https://api.biorxiv.org/details/{server}/{quoted}/na/json")
        collection = (data or {}).get("collection") if isinstance(data, dict) else None
        if collection:
            return f"https://www.{server}.org/content/{cleaned_doi}.full.pdf"
    return None


def try_osti(doi: str | None, title: str | None = None) -> str | None:
    """Check DOE OSTI.gov API for publicly accessible full-text reports or accepted manuscripts."""
    cleaned_doi = clean_doi(doi)
    if not cleaned_doi:
        return None
    url = "https://www.osti.gov/api/v1/records?" + urllib.parse.urlencode({"doi": cleaned_doi})
    records = _get_json(url, headers={"Accept": "application/json"})
    if not isinstance(records, list):
        return None
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for link in rec.get("links") or []:
            if isinstance(link, dict) and link.get("rel") == "fulltext" and link.get("href"):
                return str(link["href"])
    return None


def try_elsevier_tdm(doi: str | None) -> str | None:
    """Check Elsevier Article Retrieval API when $ELSEVIER_API_KEY is set."""
    key = os.environ.get("ELSEVIER_API_KEY", "").strip()
    cleaned_doi = clean_doi(doi)
    if not key or not cleaned_doi or not cleaned_doi.startswith("10.1016/"):
        return None
    url = (
        f"https://api.elsevier.com/content/article/doi/"
        f"{urllib.parse.quote(cleaned_doi, safe='/')}?httpAccept=text/xml"
    )
    headers = {"X-ELS-APIKey": key, "Accept": "text/xml"}
    inst_token = os.environ.get("ELSEVIER_INST_TOKEN", "").strip()
    if inst_token:
        headers["X-ELS-Insttoken"] = inst_token
    xml_prefix = _get_text_prefix(url, headers=headers)
    if xml_prefix and any(tag in xml_prefix for tag in ("<body", "<ce:sections", "<rawtext>")):
        return url
    return None


def try_springer_tdm(doi: str | None) -> str | None:
    """Check Springer Nature JATS API when $SPRINGER_API_KEY is set (never leaks key in URL)."""
    key = os.environ.get("SPRINGER_API_KEY", "").strip()
    cleaned_doi = clean_doi(doi)
    if not key or not cleaned_doi or not cleaned_doi.startswith(("10.1007/", "10.1038/", "10.1186/")):
        return None
    display_url = "https://api.springernature.com/openaccess/jats?" + urllib.parse.urlencode(
        {"q": f"doi:{cleaned_doi}"}
    )
    probe_url = display_url + "&" + urllib.parse.urlencode({"api_key": key})
    xml_prefix = _get_text_prefix(probe_url)
    if xml_prefix and "<body" in xml_prefix:
        return display_url
    return None


def try_wiley_tdm(doi: str | None) -> str | None:
    """Check Wiley TDM API v1 when $WILEY_TDM_TOKEN is set."""
    token = os.environ.get("WILEY_TDM_TOKEN", "").strip()
    cleaned_doi = clean_doi(doi)
    if not token or not cleaned_doi or not cleaned_doi.startswith(("10.1002/", "10.1111/")):
        return None
    url = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/" + urllib.parse.quote(
        cleaned_doi, safe=""
    )
    if _probe_binary_ok(url, headers={"Wiley-TDM-Client-Token": token}):
        return url
    return None


def try_core(doi: str | None, title: str | None) -> str | None:
    """Check CORE v3 API when $CORE_API_KEY is set."""
    key = os.environ.get("CORE_API_KEY", "").strip()
    cleaned_doi = clean_doi(doi)
    if not key or not (cleaned_doi or title):
        return None
    query = f'doi:"{cleaned_doi}"' if cleaned_doi else f'title:"{title}"'
    url = "https://api.core.ac.uk/v3/search/works?" + urllib.parse.urlencode(
        {"q": query, "limit": "1"}
    )
    data = _get_json(url, headers={"Authorization": f"Bearer {key}"})
    results = (data or {}).get("results") if isinstance(data, dict) else None
    for work in results or []:
        if not isinstance(work, dict):
            continue
        for link in work.get("links") or []:
            if (
                isinstance(link, dict)
                and link.get("type") in ("download", "reader")
                and link.get("url")
            ):
                return str(link["url"])
        if work.get("downloadUrl"):
            return str(work["downloadUrl"])
    return None


def try_acs_figshare_si_url(
    doi: str | None,
    *,
    client: AcsFigshareClient | None = None,
) -> str | None:
    """Probe ACS Figshare API v2 for <doi>.s001 open Supporting Information (preferring PDF)."""
    cleaned_doi = clean_doi(doi)
    if not cleaned_doi or not cleaned_doi.lower().startswith(ACS_DOI_PREFIX):
        return None
    acs_client = client or AcsFigshareClient()
    try:
        info = acs_client.probe_supporting_info(cleaned_doi)
    except (AcsFigshareError, Exception):
        return None
    if info is None or not info.files:
        return None
    for f in info.files:
        if f.download_url and f.name.lower().endswith(".pdf"):
            return f.download_url
    for f in info.files:
        if f.download_url:
            return f.download_url
    return None


def access_ladder(
    rec: dict[str, Any],
    doi: str | None,
    title: str | None,
    pmid: str | None = None,
    *,
    include_acs_si: bool = True,
    acs_client: AcsFigshareClient | None = None,
) -> tuple[str, str | None]:
    """Return ``(method, url)`` for the first legal full-text/SI hit, or ``('none', None)``."""
    resolved_pmid = pmid or rec.get("pmid")
    resolved_doi = clean_doi(doi or rec.get("doi"))
    steps: list[tuple[str, Any]] = [
        ("zotero_local", lambda: try_zotero_local(resolved_pmid, resolved_doi)),
        ("europepmc_oa", lambda: try_europepmc(rec)),
        ("openalex_oa", lambda: try_openalex_oa(resolved_doi, resolved_pmid)),
        ("biorxiv", lambda: try_biorxiv(resolved_doi)),
        ("osti_gov", lambda: try_osti(resolved_doi, title)),
        ("elsevier_tdm", lambda: try_elsevier_tdm(resolved_doi)),
        ("springer_tdm", lambda: try_springer_tdm(resolved_doi)),
        ("wiley_tdm", lambda: try_wiley_tdm(resolved_doi)),
        ("core", lambda: try_core(resolved_doi, title)),
    ]
    if include_acs_si:
        steps.append(
            (
                "acs_figshare_si",
                lambda: try_acs_figshare_si_url(resolved_doi, client=acs_client),
            )
        )
    for method, fn in steps:
        url = fn()
        if url:
            return method, url
    return "none", None


def fetch_to_staging(method: str, url: str, dest: Path) -> Path:
    """Download or copy a resolved full-text payload to a staging path outside references_cache/."""
    resolved = dest.resolve()
    if "references_cache" in resolved.parts:
        raise ValueError(
            "Refusing to stage fulltext_access output directly into references_cache/; "
            "stage into .temp/ or reports/ and use verified OA caching tools."
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)

    if url.startswith("file://"):
        src_path = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path))
        shutil.copy2(src_path, resolved)
        return resolved

    if not url.startswith("https://"):
        raise ValueError(f"Unsupported URL scheme for staging fetch: {url}")

    headers = dict(UA)
    fetch_url = url
    if method == "elsevier_tdm":
        key = os.environ.get("ELSEVIER_API_KEY", "").strip()
        if key:
            headers["X-ELS-APIKey"] = key
        headers["Accept"] = "text/xml"
        inst_token = os.environ.get("ELSEVIER_INST_TOKEN", "").strip()
        if inst_token:
            headers["X-ELS-Insttoken"] = inst_token
    elif method == "springer_tdm":
        key = os.environ.get("SPRINGER_API_KEY", "").strip()
        if key and "api_key=" not in fetch_url:
            sep = "&" if "?" in fetch_url else "?"
            fetch_url = f"{fetch_url}{sep}{urllib.parse.urlencode({'api_key': key})}"
    elif method == "wiley_tdm":
        token = os.environ.get("WILEY_TDM_TOKEN", "").strip()
        if token:
            headers["Wiley-TDM-Client-Token"] = token
    elif method == "core":
        key = os.environ.get("CORE_API_KEY", "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(fetch_url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as response:  # noqa: S310
        payload = response.read()
    if not payload:
        raise RuntimeError(f"Empty payload returned from {method} ({url})")
    resolved.write_bytes(payload)
    return resolved


def author_request_draft(rec: dict[str, Any], doi: str | None) -> str:
    """Generate a local, unsent author-request email template when no legal full text is reachable."""
    title = re.sub(r"<[^>]+>", "", str(rec.get("title", "") or "")).rstrip(".")
    authors = str(rec.get("authorString", "") or "the corresponding author")
    cleaned_doi = clean_doi(doi)
    ref = f"doi:{cleaned_doi}" if cleaned_doi else f"PMID:{rec.get('pmid', '?')}"
    return (
        f"To: <corresponding author of: {authors}>\n"
        f"Subject: Request for Methods details — {title[:70]}\n\n"
        f"Dear Author,\n\n"
        f"I am curating an open, public microbial knowledge base and would like to "
        f'cite your paper "{title}" ({ref}). The abstract does not include the experimental / '
        f"Methods details needed for curation. Could you share the relevant Methods/supplementary "
        f"text, or an author-accepted manuscript? The extracted, source-attributed data would be "
        f"published openly with full citation to your work.\n\nThank you,\nKG-Microbe curation team\n"
    )
