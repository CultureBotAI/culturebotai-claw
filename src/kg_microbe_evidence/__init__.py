"""Offline quote-against-source checks, distinct from scientific claim review.

A match means a normalized quote occurs in the identified cached source body.
It does not prove that the source supports the assertion, its generality, or its
causal interpretation. No cache fetching, repair or provider access occurs here;
`kg_microbe_evidence.fetch` is the separate, explicit command that adds caches.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import tempfile
import unicodedata
import urllib.parse
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from kg_microbe_fleet import UniqueKeySafeLoader

CAPABILITY = "evidence_reference_validation"
VERDICTS = (
    "OK", "NO_QUOTE", "MISSING_REFERENCE", "MISSING_CACHE",
    "UNSUPPORTED_REFERENCE", "INVALID_EVIDENCE", "INVALID_CACHE",
    "SNIPPET_NOT_IN_SOURCE",
)
BLOCKING = frozenset({"MISSING_REFERENCE", "INVALID_EVIDENCE", "INVALID_CACHE", "SNIPPET_NOT_IN_SOURCE"})
STRICT_BLOCKING = BLOCKING | {"MISSING_CACHE", "UNSUPPORTED_REFERENCE"}
# Findings about what a curated quote says or cites can be recorded as known
# debt. INVALID_EVIDENCE and INVALID_CACHE are broken inputs: fix them instead.
KNOWN_FINDING_VERDICTS = frozenset({
    "MISSING_REFERENCE", "MISSING_CACHE", "UNSUPPORTED_REFERENCE", "SNIPPET_NOT_IN_SOURCE",
})
KNOWN_FINDING_COLUMNS = ("record", "reference", "verdict", "quote_sha256", "issue")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*\Z")
_PMID = re.compile(r"(?:PMID:)?([0-9]+)\Z", re.IGNORECASE)
_DOI_SCHEME = re.compile(r"\Adoi:\s*", re.IGNORECASE)
# A resolver URL carries the DOI percent-encoded as a URL path (RFC 3986).
_DOI_RESOLVER = re.compile(r"\A(?:https?://)?(?:www\.|dx\.)?doi\.org/", re.IGNORECASE)
# Directory indicator 10, a registrant code with optional subdivisions, a suffix.
_DOI = re.compile(r"10\.[0-9]+(?:\.[0-9]+)*/\S+\Z")
_ISSUE = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
# One path component on every supported filesystem, with room for a suffix.
MAX_CACHE_NAME = 200


class EvidenceError(ValueError):
    """An input or declaration cannot be interpreted without guessing."""


def normalize(text: str) -> str:
    """The explicit MIM comparison contract: NFKC, whitespace, lowercase."""
    return " ".join(unicodedata.normalize("NFKC", text).split()).lower()


def normalize_doi(value: str) -> str | None:
    """The DOI a citation names, in its one lowercase spelling, or None.

    DOIs are case-insensitive, so `DOI:10.1/AB` and `https://doi.org/10.1/ab`
    name one source and one cache file. A bare `10.<registrant>/<suffix>` is
    unambiguous DOI syntax. A resolver URL (`doi.org`, `www.doi.org`,
    `dx.doi.org`, with or without a scheme) encodes the DOI as a URL path, so
    only that form is percent-decoded; `doi:` and bare forms are taken
    literally, because `%` is a legal DOI character.
    """
    text = value.strip()
    resolver = _DOI_RESOLVER.match(text)
    if resolver:
        text = urllib.parse.unquote(text[resolver.end():])
    else:
        text = _DOI_SCHEME.sub("", text, count=1)
    return text.lower() if _DOI.fullmatch(text) else None


def cache_file_name(kind: str, identifier: str) -> str:
    """The cache file for one identified source: PMID_<n>.md or DOI_<encoded>.md.

    A DOI is percent-encoded whole, so `/`, `:` and every other character that
    is unsafe in a path component becomes `%XX`. The encoding is reversible, so
    two DOIs never share a file.
    """
    if kind == "PMID":
        return f"PMID_{identifier}.md"
    if kind == "DOI":
        return f"DOI_{urllib.parse.quote(identifier, safe='')}.md"
    raise EvidenceError(f"unsupported source kind: {kind}")


def parse_cache_text(text: str, kind: str, identifier: str) -> str:
    """The quotable body of one cache file, after checking whose source it is.

    The first line must name the cited source (`# PMID:<n>` or `# DOI:<doi>`)
    and there must be exactly one `## Abstract` heading. Only the text under it
    counts; title, authors and any other metadata are never quote evidence.
    """
    header = re.match(rf"\A#\s+{kind}:(\S+)\s*\n", text)
    named = header.group(1) if header else None
    if named is None or (named != identifier if kind == "PMID" else normalize_doi(named) != identifier):
        raise EvidenceError(f"cache header does not identify the cited {kind}")
    headings = list(re.finditer(r"(?im)^##\s+Abstract\s*$", text))
    if len(headings) != 1:
        raise EvidenceError("cache requires exactly one explicit Abstract section")
    remainder = text[headings[0].end():]
    body = re.split(r"(?m)^#{1,2}\s+", remainder, maxsplit=1)[0].strip()
    if not body:
        raise EvidenceError("cache abstract is empty")
    return body


def _relative_path(value: str, name: str) -> None:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts
            or "\\" in value or str(path) != value or value == "."):
        raise EvidenceError(f"{name} must be a normalized repository-relative path")


@dataclass(frozen=True)
class EvidenceConfig:
    cache_dir: str
    reference_fields: tuple[str, ...] = ("pmid", "doi", "reference")
    snippet_fields: tuple[str, ...] = ("snippet", "excerpt", "supporting_text")
    evidence_fields: tuple[str, ...] = ("evidence",)
    evidence_paths: tuple[str, ...] = ()
    known_findings: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.cache_dir, str):
            raise EvidenceError("cache_dir must be a normalized repository-relative directory")
        _relative_path(self.cache_dir, "cache_dir")
        if self.known_findings is not None:
            if not isinstance(self.known_findings, str):
                raise EvidenceError("known_findings must be a normalized repository-relative path")
            _relative_path(self.known_findings, "known_findings")
        for name in ("reference_fields", "snippet_fields", "evidence_fields"):
            fields = getattr(self, name)
            if (not isinstance(fields, tuple) or not fields
                    or any(not isinstance(f, str) or not _FIELD.fullmatch(f) for f in fields)
                    or len(set(fields)) != len(fields)):
                raise EvidenceError(f"{name} must contain distinct simple field names")
        if (not isinstance(self.evidence_paths, tuple)
                or any(not isinstance(p, str) or not _PATH.fullmatch(p)
                       or p.split(".")[-1] not in self.evidence_fields for p in self.evidence_paths)
                or len(set(self.evidence_paths)) != len(self.evidence_paths)):
            raise EvidenceError("evidence_paths must be distinct dotted selectors ending in an evidence field")

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> EvidenceConfig:
        lists = {"reference_fields", "snippet_fields", "evidence_fields", "evidence_paths"}
        allowed = lists | {"cache_dir", "known_findings"}
        if set(settings) - allowed:
            raise EvidenceError(f"unknown evidence settings: {sorted(set(settings) - allowed)}")
        if not isinstance(settings.get("cache_dir"), str):
            raise EvidenceError("evidence validation requires cache_dir")
        values: dict[str, Any] = {"cache_dir": settings["cache_dir"]}
        if "known_findings" in settings:
            if not isinstance(settings["known_findings"], str):
                raise EvidenceError("known_findings must be a repository-relative file path")
            values["known_findings"] = settings["known_findings"]
        for name in lists:
            if name in settings:
                value = settings[name]
                if not isinstance(value, (list, tuple)):
                    raise EvidenceError(f"{name} must be a list of field names")
                values[name] = tuple(value)
        return cls(**values)

    def selects(self, location: str) -> bool:
        """Select schema slots, not rows chosen by their validation outcome."""
        if not self.evidence_paths:
            return True
        relative = re.sub(r"^\$(?:\[[0-9]+\])?\.", "", location)
        container = re.sub(r"\[[0-9]+\]$", "", relative)
        selector = re.sub(r"\[[0-9]+\]", "[]", container)
        return selector in self.evidence_paths

    def validate_shapes(self, document: object) -> None:
        """Wrong shapes on declared paths are input errors, not exclusions."""
        def walk(value: object, parts: list[str], selector: str) -> None:
            if not isinstance(value, Mapping):
                raise EvidenceError(f"declared selector {selector} requires an object container")
            if len(parts) <= 1:
                return  # Evidence item shape is checked by check_item.
            field = parts[0].removesuffix("[]")
            child = value.get(field)
            if child is None:
                return  # Optional absent/null containers do not assert evidence.
            if parts[0].endswith("[]"):
                if not isinstance(child, list):
                    raise EvidenceError(f"declared selector {selector} requires {field} to be a list")
                for item in child:
                    walk(item, parts[1:], selector)
            else:
                walk(child, parts[1:], selector)

        for selector in self.evidence_paths:
            for record in document if isinstance(document, list) else [document]:
                walk(record, selector.split("."), selector)


@dataclass(frozen=True)
class QuoteResult:
    verdict: str
    reference: str = ""
    detail: str = ""
    quote_sha256: str = ""
    cache_path: str = ""
    cache_sha256: str = ""


@dataclass(frozen=True)
class CachedSource:
    body: str
    path: str
    sha256: str


class EvidenceValidator:
    """One read-only cache memo per corpus worker; never network or repair."""

    def __init__(self, root: Path, config: EvidenceConfig):
        self.root = root.resolve()
        self.config = config
        self.cache_root = self.root / config.cache_dir
        self._cache: dict[tuple[str, str], CachedSource | QuoteResult] = {}

    def _source(self, pmid: str, kind: str = "PMID") -> CachedSource | QuoteResult:
        """Read one identified cache: `# PMID:<n>` or `# DOI:<doi>`, then one Abstract."""
        key = (kind, pmid)
        if key in self._cache:
            return self._cache[key]
        reference = f"{kind}:{pmid}"
        name = cache_file_name(kind, pmid)
        if len(name) > MAX_CACHE_NAME:
            result: CachedSource | QuoteResult = QuoteResult(
                "UNSUPPORTED_REFERENCE", reference,
                "Identifier is too long for a portable cache file name; it remains unverified.")
            self._cache[key] = result
            return result
        path = self.cache_root / name
        relative = path.relative_to(self.root).as_posix()
        try:
            if not path.resolve().is_relative_to(self.root):
                raise EvidenceError("cache resolves outside the active repository")
            if path.is_symlink() or self.cache_root.is_symlink():
                raise EvidenceError("cache files and directory must not be symlinks")
            raw = path.read_bytes()
            body = parse_cache_text(raw.decode("utf-8"), kind, pmid)
            result = CachedSource(body, relative, hashlib.sha256(raw).hexdigest())
        except FileNotFoundError:
            result = QuoteResult("MISSING_CACHE", reference, f"No supported {kind} markdown cache; no source was fetched.", cache_path=relative)
        except (OSError, UnicodeError, EvidenceError) as exc:
            result = QuoteResult("INVALID_CACHE", reference, str(exc), cache_path=relative)
        self._cache[key] = result
        return result

    def check_item(self, item: object) -> QuoteResult:
        if not isinstance(item, Mapping):
            return QuoteResult("INVALID_EVIDENCE", detail="Evidence item must be an object")
        quotes: list[str] = []
        for field in self.config.snippet_fields:
            value = item.get(field)
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                return QuoteResult("INVALID_EVIDENCE", detail=f"{field} must be text")
            if normalize(value):
                quotes.append(value)
        if not quotes:
            return QuoteResult("NO_QUOTE", detail="No nonempty quote; citation presence alone is not validation")
        if len({normalize(q) for q in quotes}) != 1:
            return QuoteResult("INVALID_EVIDENCE", detail="Conflicting quote aliases")
        quote = quotes[0]
        quote_hash = hashlib.sha256(quote.encode()).hexdigest()
        references: list[tuple[str, str]] = []
        for field in self.config.reference_fields:
            value = item.get(field)
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                return QuoteResult("INVALID_EVIDENCE", detail=f"{field} must be text", quote_sha256=quote_hash)
            if value.strip():
                references.append((field, value.strip()))
        if not references:
            return QuoteResult("MISSING_REFERENCE", detail="Quote has no citation", quote_sha256=quote_hash)
        pmids: set[str] = set()
        dois: set[str] = set()
        for field, ref in references:
            match = _PMID.fullmatch(ref)
            if field == "pmid" and match is None:
                return QuoteResult("INVALID_EVIDENCE", detail="pmid must identify a PMID", quote_sha256=quote_hash)
            # Bare numbers are PMIDs only in their explicit native PMID slot.
            # A DOI (even one that happens to look numeric) is never a PMID.
            if field != "doi" and match and (field == "pmid" or ref.upper().startswith("PMID:")):
                pmids.add(match.group(1))
                continue
            # A value that names no DOI is simply not a DOI citation, as before
            # DOI support; it is never an input error of its own (#736).
            doi = normalize_doi(ref)
            if doi is not None:
                dois.add(doi)
        if len(pmids) > 1:
            return QuoteResult("INVALID_EVIDENCE", detail="Conflicting PMID references", quote_sha256=quote_hash)
        # A PMID keeps absolute precedence: DOI values beside it are not read,
        # so an item citing a PMID is checked exactly as before DOI support.
        if pmids:
            kind, identifier = "PMID", next(iter(pmids))
        elif len(dois) > 1:
            return QuoteResult("INVALID_EVIDENCE", detail="Conflicting DOI references", quote_sha256=quote_hash)
        elif dois:
            kind, identifier = "DOI", next(iter(dois))
        else:
            return QuoteResult("UNSUPPORTED_REFERENCE", references[0][1], "Only PMID and DOI citations with a retained abstract are supported; other sources remain unverified.", quote_hash)
        source = self._source(identifier, kind)
        if isinstance(source, QuoteResult):
            return QuoteResult(source.verdict, source.reference, source.detail, quote_hash, source.cache_path, source.cache_sha256)
        verdict = "OK" if normalize(quote) in normalize(source.body) else "SNIPPET_NOT_IN_SOURCE"
        return QuoteResult(verdict, f"{kind}:{identifier}",
            "Normalized quote occurs in the cached abstract; claim support still requires review." if verdict == "OK" else "Quote is absent from the cached abstract body.",
            quote_hash, source.path, source.sha256)


def iter_evidence(document: object, fields: Sequence[str], path: str = "$", *, _ancestors: frozenset[int] = frozenset()) -> Iterator[tuple[str, object]]:
    """Visit declared evidence slots at any depth; reject recursive YAML aliases."""
    if not isinstance(document, (dict, list)):
        return
    if id(document) in _ancestors:
        raise EvidenceError(f"recursive YAML alias at {path}")
    ancestors = _ancestors | {id(document)}
    if isinstance(document, list):
        for index, child in enumerate(document):
            yield from iter_evidence(child, fields, f"{path}[{index}]", _ancestors=ancestors)
    else:
        for key, value in document.items():
            location = f"{path}.{key}"
            if key in fields and value is not None and value != []:
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        yield f"{location}[{index}]", item
                else:
                    yield location, value
            # Evidence items may themselves contain evidence or recursive
            # aliases. Checking their outer quote must not terminate traversal.
            yield from iter_evidence(value, fields, location, _ancestors=ancestors)


@dataclass(frozen=True)
class KnownFinding:
    """One recorded occurrence of an issue-owned finding, reported without blocking.

    Each row excuses exactly one occurrence: two identical failing items need
    two rows, and a copy of a recorded quote blocks until it is recorded too
    (#734). The key leaves out the item's position, so reordering a record does
    not disturb it, and includes the quote's hash, so editing the quote makes
    the entry stale and the new text is checked like any other.
    """

    record: str
    reference: str
    verdict: str
    quote_sha256: str
    issue: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.record, self.reference, self.verdict, self.quote_sha256)


def _ledger_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    _relative_path(relative, "known_findings")
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part != root and part.is_relative_to(root)):
        raise EvidenceError("known_findings ledger and its directories must not be symlinks")
    if not path.resolve().is_relative_to(root):
        raise EvidenceError("known_findings ledger resolves outside the active repository")
    return path


def load_known_findings(root: Path, relative: str, *, missing_ok: bool = False) -> list[KnownFinding]:
    """Parse a declared ledger strictly; a declared but absent ledger is an error.

    `missing_ok` exists only so the ledger writer can create the first one.
    """
    path = _ledger_path(root, relative)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if missing_ok:
            return []
        raise EvidenceError(f"declared known_findings ledger is missing: {relative}") from exc
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE, strict=True))
    except csv.Error as exc:
        raise EvidenceError(f"{relative}: {exc}") from exc
    if not rows or tuple(rows[0]) != KNOWN_FINDING_COLUMNS:
        raise EvidenceError(f"{relative}: header must be {', '.join(KNOWN_FINDING_COLUMNS)}")
    findings: list[KnownFinding] = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(KNOWN_FINDING_COLUMNS):
            raise EvidenceError(f"{relative}:{number}: expected {len(KNOWN_FINDING_COLUMNS)} tab-separated fields")
        finding = KnownFinding(*row)
        record = PurePosixPath(finding.record)
        if (not finding.record or record.is_absolute() or ".." in record.parts
                or str(record) != finding.record):
            raise EvidenceError(f"{relative}:{number}: record must be a normalized repository-relative path")
        if finding.verdict not in KNOWN_FINDING_VERDICTS:
            raise EvidenceError(f"{relative}:{number}: {finding.verdict!r} cannot be recorded as a known finding")
        # A MISSING_REFERENCE finding has no citation by definition; every
        # other recordable finding names the citation it failed on (#732).
        if (finding.verdict == "MISSING_REFERENCE") != (finding.reference == ""):
            raise EvidenceError(f"{relative}:{number}: reference must be empty exactly for MISSING_REFERENCE")
        if not _SHA256.fullmatch(finding.quote_sha256):
            raise EvidenceError(f"{relative}:{number}: quote_sha256 must be a lowercase SHA-256 digest")
        if not _ISSUE.fullmatch(finding.issue):
            raise EvidenceError(f"{relative}:{number}: issue must be a GitHub issue URL")
        findings.append(finding)
    return findings


def plan_known_findings(report: Mapping[str, Any], issue: str | None) -> dict[str, Any]:
    """The ledger the current findings imply, one row per occurrence.

    Rows still matched keep their owner, new findings are owned by `issue`, and
    stale rows are dropped.
    """
    if issue is not None and not _ISSUE.fullmatch(issue):
        raise EvidenceError("issue must be a GitHub issue URL")
    rows: list[KnownFinding] = []
    kept = added = 0
    unowned: list[dict[str, Any]] = []
    for row in report["results"]:
        if row["verdict"] not in KNOWN_FINDING_VERDICTS:
            continue
        owner = row.get("known_issue") or issue
        if owner is None:
            unowned.append(row)
            continue
        kept += bool(row.get("known_issue"))
        added += not row.get("known_issue")
        rows.append(KnownFinding(row["record"], row["reference"], row["verdict"], row["quote_sha256"], owner))
    return {"rows": sorted(rows, key=lambda f: (f.key, f.issue)), "kept": kept, "added": added,
            "dropped": len(report.get("stale_known_findings", [])), "unowned": unowned}


def render_known_findings(rows: Iterable[KnownFinding]) -> str:
    """The ledger as TSV. Quote characters are literal (#733); tabs and breaks are refused."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n")
    writer.writerow(KNOWN_FINDING_COLUMNS)
    for finding in rows:
        values = [getattr(finding, column) for column in KNOWN_FINDING_COLUMNS]
        if any(re.search(r"[\t\r\n]", value) for value in values):
            raise EvidenceError("known finding fields must not contain tabs or line breaks")
        if any(len(value) > csv.field_size_limit() for value in values):
            raise EvidenceError("a known finding field is longer than the ledger reader accepts")
        try:
            writer.writerow(values)
        except csv.Error as exc:
            raise EvidenceError(f"known finding cannot be written as TSV: {exc}") from exc
    text = buffer.getvalue()
    try:
        text.encode("utf-8")  # e.g. a lone surrogate from a YAML escape (#752)
    except UnicodeEncodeError as exc:
        raise EvidenceError(f"known finding cannot be written as UTF-8: {exc}") from exc
    return text


def write_known_findings(root: Path, relative: str, rows: Iterable[KnownFinding]) -> Path:
    """Replace the ledger atomically with exactly `render_known_findings(rows)`."""
    path = _ledger_path(root, relative)
    text = render_known_findings(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent)
    temporary = Path(name)
    try:  # no temporary file survives a failed write (#752)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def validate_corpus(root: Path, globs: Sequence[str], config: EvidenceConfig, *,
                    missing_ledger_ok: bool = False) -> dict[str, Any]:
    """Read every selected record. Malformed/unreadable input cannot disappear."""
    root = root.resolve()
    known = (load_known_findings(root, config.known_findings, missing_ok=missing_ledger_ok)
             if config.known_findings else [])
    # Do not filter through is_file(): it would silently drop broken symlinks
    # and other unreadable selected inputs before the error gate sees them.
    files = sorted({path for pattern in globs for path in root.glob(pattern)})
    if not files:
        raise EvidenceError("record globs selected no files")
    validator = EvidenceValidator(root, config)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    unmeasured: list[dict[str, str]] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                raise EvidenceError("record must be a regular file inside the active repository")
            document = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeySafeLoader)
            if not isinstance(document, (dict, list)) or not document:
                raise EvidenceError("record document must be a nonempty object or collection")
            if isinstance(document, list) and any(not isinstance(item, dict) or not item for item in document):
                raise EvidenceError("record collections must contain nonempty objects")
            config.validate_shapes(document)
            for location, item in iter_evidence(document, config.evidence_fields):
                if config.selects(location):
                    results.append({"record": relative, "location": location, **asdict(validator.check_item(item))})
                else:
                    unmeasured.append({"record": relative, "location": location,
                        "shape": type(item).__name__, "reason": "outside declared evidence_paths; not quote-validated"})
        except (OSError, UnicodeError, yaml.YAMLError, ValueError, RecursionError) as exc:
            errors.append({"record": relative, "error": str(exc)})
    # Each ledger row excuses one occurrence, in document order (#734).
    available: dict[tuple[str, str, str, str], list[KnownFinding]] = defaultdict(list)
    for entry in known:
        available[entry.key].append(entry)
    for row in results:
        queue = available.get((row["record"], row["reference"], row["verdict"], row["quote_sha256"]))
        finding = queue.pop(0) if queue else None
        row["known_issue"] = finding.issue if finding else ""
    # A record that could not be read cannot show that its recorded findings
    # are gone, so its unmatched rows are not called stale.
    unreadable = {error["record"] for error in errors}
    stale = [asdict(f) for key in sorted(available) for f in available[key] if f.record not in unreadable]
    counts = Counter(row["verdict"] for row in results)
    recorded = Counter(row["verdict"] for row in results if row["known_issue"])
    return {"records": len(files), "evidence_items": len(results),
        "quote_bearing_items": len(results) - counts["NO_QUOTE"],
        "quote_validated_items": counts["OK"], "verdicts": {v: counts[v] for v in VERDICTS},
        "known_findings_ledger": config.known_findings,
        "known_findings": {v: recorded[v] for v in VERDICTS if v in KNOWN_FINDING_VERDICTS},
        "stale_known_findings": stale,
        "errors": errors, "results": results, "cache_dir": config.cache_dir,
        "evidence_paths": list(config.evidence_paths), "unmeasured_items": len(unmeasured),
        "unmeasured": unmeasured,
        "comparison": "NFKC + collapsed whitespace + lowercase substring in identified abstract body",
        "limits": "Quote occurrence is not scientific claim support, scope, source-rights clearance or human review. Unsupported sources and recorded known findings are unverified."}


def exit_code(report: Mapping[str, Any], *, strict: bool) -> int:
    """Fail on input errors, stale ledger entries, or any unrecorded blocking verdict."""
    blocked = STRICT_BLOCKING if strict else BLOCKING
    unrecorded = Counter(row["verdict"] for row in report["results"] if not row.get("known_issue"))
    return 2 if (report["errors"] or report.get("stale_known_findings")
                 or any(unrecorded[v] for v in blocked)) else 0
