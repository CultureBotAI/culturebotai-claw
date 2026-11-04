"""Fetch the abstracts the declared quote gate needs, and nothing else.

The gate itself never fetches. This separate command runs the gate over the
Mech's declared selectors, takes exactly the citations it reports as
MISSING_CACHE, and writes their PubMed abstracts in the format the gate reads.
Without --apply it only reports what it would fetch.

* A PMID's abstract comes from NCBI E-utilities efetch.
* A DOI is looked up in PubMed (esearch `"<doi>"[doi]`). Its abstract is
  accepted only from a single PubMed record that itself lists that DOI.
* An existing cache file is never rewritten, and no file is written for a
  record without an abstract, so the gate keeps reporting MISSING_CACHE.
* Requests are anonymous: no e-mail address or tool registration is sent.
  NCBI_API_KEY, when set, raises the rate limit and is never printed.

A cached abstract records what PubMed returned on the retrieval date. It does
not establish that the source supports a claim, or the right to redistribute
the text; a Mech that commits caches follows its own source-rights policy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kg_microbe_evidence import (
    CAPABILITY,
    EvidenceConfig,
    EvidenceError,
    cache_file_name,
    normalize_doi,
    parse_cache_text,
    validate_corpus,
)
from kg_microbe_fleet import FleetManifestError, load_fleet_manifest
from kg_microbe_fleet.roots import claw_root
from plugins.lock_manager import LockManager, resolve_workspace_root
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
    RepositoryTarget,
    merged_repository_environment,
)

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
USER_AGENT = "culturebotai-claw-evidence-fetch/1 (+https://github.com/CultureBotAI/culturebotai-claw)"
BATCH = 200
ATTEMPTS = 3
# NCBI's published limits: 3 requests/second anonymously, 10 with a key.
DEFAULT_RATE, KEYED_RATE = 3.0, 10.0

Transport = Callable[[str, Mapping[str, str]], bytes]


class FetchError(RuntimeError):
    """A request failed after retries; `partial` says what was already written."""

    def __init__(self, message: str, partial: dict[str, Any]):
        super().__init__(message)
        self.partial = partial


def http_transport(url: str, params: Mapping[str, str]) -> bytes:
    """POST form parameters; the body keeps long ID lists out of the URL."""
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(params).encode("ascii"),
        headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 -- fixed NCBI URLs
        return response.read()


@dataclass(frozen=True)
class Article:
    pmid: str
    title: str
    authors: tuple[str, ...]
    journal: str
    year: str
    paragraphs: tuple[str, ...]
    dois: frozenset[str]


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def parse_articles(payload: bytes) -> dict[str, Article]:
    """PubmedArticle records by PMID. Book records carry no journal abstract here."""
    articles: dict[str, Article] = {}
    for node in ET.fromstring(payload).findall("PubmedArticle"):
        pmid = (node.findtext("MedlineCitation/PMID") or "").strip()
        article = node.find("MedlineCitation/Article")
        if not pmid.isdigit() or article is None:
            continue
        paragraphs = []
        for part in article.findall("Abstract/AbstractText"):
            text = _text(part)
            if text:
                label = part.attrib.get("Label", "")
                paragraphs.append(f"**{label}:** {text}" if label else text)
        identifiers = [e.text or "" for e in article.findall("ELocationID") if e.get("EIdType") == "doi"]
        identifiers += [e.text or "" for e in node.findall("PubmedData/ArticleIdList/ArticleId")
                        if e.get("IdType") == "doi"]
        authors = tuple(
            " ".join(filter(None, (a.findtext("LastName"), a.findtext("Initials"))))
            for a in article.findall("AuthorList/Author") if a.findtext("LastName"))
        articles[pmid] = Article(
            pmid=pmid, title=_text(article.find("ArticleTitle")), authors=authors,
            journal=_text(article.find("Journal/Title")),
            year=(article.findtext("Journal/JournalIssue/PubDate/Year") or "").strip(),
            paragraphs=tuple(paragraphs),
            dois=frozenset(d for d in (normalize_doi(i) for i in identifiers) if d))
    return articles


def render(kind: str, identifier: str, article: Article, retrieved: dt.date) -> str | None:
    """The cache text, or None when it would not read back as exactly this abstract."""
    if not article.paragraphs:
        return None
    lines = [f"# {kind}:{identifier}", ""]
    for label, value in (("Title", article.title), ("Authors", ", ".join(article.authors)),
                         ("Journal", article.journal), ("Year", article.year)):
        if value:
            lines.append(f"**{label}:** {value}")
    if kind == "DOI":
        lines.append(f"**PMID:** {article.pmid}")
    lines.append(f"**Source:** PubMed https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/, "
                 f"retrieved {retrieved.isoformat()}")
    body = "\n\n".join(article.paragraphs)
    text = "\n".join([*lines, "", "## Abstract", "", body, ""])
    try:
        if parse_cache_text(text, kind, identifier) != body:
            return None
    except EvidenceError:
        return None
    return text


def _search_ids(payload: bytes) -> list[str]:
    """PMIDs from one esearch reply; a malformed reply is an error, not "no match" (#739)."""
    data = json.loads(payload)
    result = data.get("esearchresult") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise ValueError("esearch reply has no esearchresult object")
    # A query PubMed rejects carries an error and no idlist: it names no record.
    ids = result.get("idlist", [])
    if not isinstance(ids, list) or any(not isinstance(i, str) or not i.isdigit() for i in ids):
        raise ValueError("esearch reply has a malformed idlist")
    return ids


def plan(report: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Exactly the PMIDs and DOIs the gate reported as MISSING_CACHE."""
    pmids: set[str] = set()
    dois: set[str] = set()
    for row in report["results"]:
        if row["verdict"] == "MISSING_CACHE":
            kind, _, identifier = row["reference"].partition(":")
            if kind == "PMID":
                pmids.add(identifier)
            elif kind == "DOI":
                dois.add(identifier)
    return sorted(pmids, key=int), sorted(dois)


@dataclass
class _Session:
    transport: Transport
    pause: float
    api_key: str | None
    sleep: Callable[[float], None]
    requests: int = 0

    def call(self, url: str, params: dict[str, str]) -> bytes:
        if self.api_key:
            params = {**params, "api_key": self.api_key}
        for attempt in range(ATTEMPTS):
            if self.requests:
                self.sleep(self.pause)
            self.requests += 1
            try:
                return self.transport(url, params)
            except Exception as exc:  # noqa: BLE001 -- retried, then reported
                if attempt == ATTEMPTS - 1:
                    # The message never includes params: they may hold the key.
                    raise OSError(f"{url} failed after {ATTEMPTS} attempts: {type(exc).__name__}") from None
                self.sleep(self.pause * 2 ** (attempt + 1))
        raise AssertionError("unreachable")


@dataclass
class FetchResult:
    # Everything the gate reports as uncached, and the part this run covers;
    # they differ only under --limit (#740).
    missing_pmids: list[str] = field(default_factory=list)
    missing_dois: list[str] = field(default_factory=list)
    planned_pmids: list[str] = field(default_factory=list)
    planned_dois: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    no_abstract: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    doi_unresolved: list[str] = field(default_factory=list)
    doi_ambiguous: list[str] = field(default_factory=list)
    doi_unverified: list[str] = field(default_factory=list)
    unrenderable: list[str] = field(default_factory=list)
    requests: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {name: value for name, value in self.__dict__.items()}


def _cache_root(root: Path, config: EvidenceConfig, *, create: bool) -> Path:
    root = root.resolve()
    cache = root / config.cache_dir
    if any(p.is_symlink() for p in (cache, *cache.parents) if p != root and p.is_relative_to(root)):
        raise EvidenceError("cache directory and its parents must not be symlinks")
    if not cache.resolve().is_relative_to(root):
        raise EvidenceError("cache directory resolves outside the active repository")
    if create:
        cache.mkdir(parents=True, exist_ok=True)
    return cache


def _write_new(cache: Path, name: str, text: str) -> bool:
    """Create one cache file atomically; never replace an existing one."""
    target = cache / name
    if target.exists() or target.is_symlink():
        return False
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache, delete=False,
                                     prefix=".fetch-", suffix=".tmp") as stream:
        temporary = Path(stream.name)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, target)  # fails rather than replacing a concurrent file
        except FileExistsError:
            return False
    finally:
        temporary.unlink(missing_ok=True)
    return True


def fetch_missing(
    root: Path, config: EvidenceConfig, report: Mapping[str, Any], *,
    transport: Transport = http_transport, apply: bool = False, limit: int | None = None,
    api_key: str | None = None, rate: float | None = None,
    sleep: Callable[[float], None] = time.sleep, today: dt.date | None = None,
) -> FetchResult:
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")  # 0 would slice past the DOI reserve (#751)
    missing_pmids, missing_dois = plan(report)
    pmids, dois = missing_pmids, missing_dois
    if limit is not None:
        # A canary must take the batch's paths: when both kinds are pending,
        # at least one DOI is covered, so --limit 2 runs both (#744). Whatever
        # the PMIDs leave unused goes to DOIs.
        reserve = min(len(dois), max(1, limit // 2)) if dois and pmids else 0
        pmids = pmids[:limit - reserve]
        dois = dois[:limit - len(pmids)]
    result = FetchResult(missing_pmids=missing_pmids, missing_dois=missing_dois,
                         planned_pmids=pmids, planned_dois=dois)
    if not (pmids or dois):
        return result
    # Checked in a dry run too, so a dry run fails exactly where --apply would (#745).
    cache = _cache_root(root, config, create=False)
    if not apply:
        return result
    cache.mkdir(parents=True, exist_ok=True)
    retrieved = today or dt.datetime.now(dt.timezone.utc).date()
    session = _Session(transport, 1.0 / (rate or (KEYED_RATE if api_key else DEFAULT_RATE)), api_key, sleep)

    def efetch(ids: Iterable[str]) -> dict[str, Article]:
        found: dict[str, Article] = {}
        ids = list(ids)
        for start in range(0, len(ids), BATCH):
            chunk = ids[start:start + BATCH]
            payload = session.call(EFETCH, {"db": "pubmed", "id": ",".join(chunk),
                                            "retmode": "xml", "rettype": "abstract"})
            articles = parse_articles(payload)
            # Identity is the returned record's own PMID; nothing else is trusted.
            found.update({pmid: a for pmid, a in articles.items() if pmid in chunk})
        return found

    def store(kind: str, identifier: str, article: Article) -> None:
        text = render(kind, identifier, article, retrieved)
        label = f"{kind}:{identifier}"
        if text is None:
            (result.no_abstract if not article.paragraphs else result.unrenderable).append(label)
        elif _write_new(cache, cache_file_name(kind, identifier), text):
            result.written.append(label)
        else:
            result.skipped_existing.append(label)

    try:
        articles = efetch(pmids)
        for pmid in pmids:
            if pmid in articles:
                store("PMID", pmid, articles[pmid])
            else:
                result.not_found.append(f"PMID:{pmid}")
        candidates: dict[str, str] = {}
        for doi in dois:
            if '"' in doi:  # cannot be quoted as one PubMed phrase without guessing
                result.doi_unresolved.append(f"DOI:{doi}")
                continue
            payload = session.call(ESEARCH, {"db": "pubmed", "term": f'"{doi}"[doi]',
                                             "retmode": "json", "retmax": "2"})
            ids = _search_ids(payload)
            if not ids:
                result.doi_unresolved.append(f"DOI:{doi}")
            elif len(ids) > 1:
                result.doi_ambiguous.append(f"DOI:{doi}")
            else:
                candidates[doi] = ids[0]
        articles = efetch(sorted(set(candidates.values()), key=int))
        for doi, pmid in candidates.items():
            article = articles.get(pmid)
            if article is None:
                result.not_found.append(f"DOI:{doi}")
            elif doi not in article.dois:
                result.doi_unverified.append(f"DOI:{doi}")
            else:
                store("DOI", doi, article)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        result.requests = session.requests
        raise FetchError(f"fetch stopped: {exc}", result.as_dict()) from exc
    result.requests = session.requests
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mech", required=True)
    parser.add_argument("--root", type=Path, help="exact active Mech checkout, with origin identity verified")
    parser.add_argument("--apply", action="store_true", help="fetch and write caches; omitted means dry-run")
    parser.add_argument("--limit", type=int, help="fetch at most this many sources (a canary)")
    parser.add_argument("--json", type=Path, help="also write the result as JSON here")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.json is not None and (not args.json.parent.is_dir() or args.json.is_dir()):
        parser.error(f"--json must name a file in an existing directory: {args.json}")
    try:
        manifest = load_fleet_manifest()
        mech = manifest.mechs.get(args.mech)
        if mech is None:
            raise EvidenceError(f"unknown Mech: {args.mech}")
        capability = mech.capability(CAPABILITY)
        if capability is None or not capability.is_enabled:
            reason = capability.reason if capability else "undeclared"
            raise EvidenceError(f"{args.mech}: evidence validation is not enabled: {reason}")
        config = EvidenceConfig.from_settings(capability.settings)
        if args.root is not None:
            target = RepositoryTarget(mech.key, args.root.expanduser().resolve(), mech.github)
        else:
            dotenv = claw_root() / ".env"
            env = merged_repository_environment(dotenv if dotenv.exists() else None)
            target = RepositorySettings.from_environment(environ=env, manifest=manifest).get_target(mech.key)
        target.open()

        def run() -> FetchResult:
            report = validate_corpus(target.path, mech.record_globs, config, missing_ledger_ok=True)
            if report["errors"]:
                raise EvidenceError(f"{len(report['errors'])} records could not be read; the plan would be incomplete")
            return fetch_missing(target.path, config, report, apply=args.apply, limit=args.limit,
                                 transport=http_transport, api_key=os.environ.get("NCBI_API_KEY") or None)
        try:
            if args.apply:
                # Plan and write under one hold of the repository lock (AGENTS.md; #746, #749).
                with LockManager().lock(mech.key, "evidence-fetch"):
                    result = run()
            else:
                result = run()
                if result.planned_pmids or result.planned_dois:
                    resolve_workspace_root()  # the dry run fails where --apply's lock would (#750)
            outcome, code = result.as_dict(), 0
        except FetchError as exc:
            print(f"evidence fetch: {exc}", file=sys.stderr)
            outcome, code = exc.partial, 1
    except (EvidenceError, FleetManifestError, RepositoryConfigurationError, OSError, ValueError,
            RuntimeError) as exc:  # RuntimeError: the repository lock is held elsewhere
        print(f"evidence fetch: {exc}", file=sys.stderr)
        return 2
    mode = "applied" if args.apply else "dry run, nothing fetched or written"
    print(f"{mech.key} ({mode}): {len(outcome['missing_pmids'])} PMIDs and "
          f"{len(outcome['missing_dois'])} DOIs lack a cache; this run covers "
          f"{len(outcome['planned_pmids'])} and {len(outcome['planned_dois'])}")
    for name in ("written", "skipped_existing", "no_abstract", "not_found", "doi_unresolved",
                 "doi_ambiguous", "doi_unverified", "unrenderable"):
        if outcome[name]:
            print(f"  {name}: {len(outcome[name])}")
    if args.json is not None:
        try:
            args.json.write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"evidence fetch: could not write {args.json}: {exc}", file=sys.stderr)
            return max(code, 2)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
