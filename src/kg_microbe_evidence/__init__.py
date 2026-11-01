"""Offline quote-against-source checks, distinct from scientific claim review.

A match means a normalized quote occurs in the identified cached source body.
It does not prove that the source supports the assertion, its generality, or its
causal interpretation. No cache fetching, repair or provider access occurs here.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
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
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*\Z")
_PMID = re.compile(r"(?:PMID:)?([0-9]+)\Z", re.IGNORECASE)


class EvidenceError(ValueError):
    """An input or declaration cannot be interpreted without guessing."""


def normalize(text: str) -> str:
    """The explicit MIM comparison contract: NFKC, whitespace, lowercase."""
    return " ".join(unicodedata.normalize("NFKC", text).split()).lower()


@dataclass(frozen=True)
class EvidenceConfig:
    cache_dir: str
    reference_fields: tuple[str, ...] = ("pmid", "doi", "reference")
    snippet_fields: tuple[str, ...] = ("snippet", "excerpt", "supporting_text")
    evidence_fields: tuple[str, ...] = ("evidence",)
    evidence_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        path = PurePosixPath(self.cache_dir)
        if (not self.cache_dir or path.is_absolute() or ".." in path.parts
                or "\\" in self.cache_dir or str(path) != self.cache_dir or self.cache_dir == "."):
            raise EvidenceError("cache_dir must be a normalized repository-relative directory")
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
        allowed = {"cache_dir", "reference_fields", "snippet_fields", "evidence_fields", "evidence_paths"}
        if set(settings) - allowed:
            raise EvidenceError(f"unknown evidence settings: {sorted(set(settings) - allowed)}")
        if not isinstance(settings.get("cache_dir"), str):
            raise EvidenceError("evidence validation requires cache_dir")
        values: dict[str, Any] = {"cache_dir": settings["cache_dir"]}
        for name in allowed - {"cache_dir"}:
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
        self._cache: dict[str, CachedSource | QuoteResult] = {}

    def _source(self, pmid: str) -> CachedSource | QuoteResult:
        if pmid in self._cache:
            return self._cache[pmid]
        reference = f"PMID:{pmid}"
        path = self.cache_root / f"PMID_{pmid}.md"
        relative = path.relative_to(self.root).as_posix()
        try:
            if not path.resolve().is_relative_to(self.root):
                raise EvidenceError("cache resolves outside the active repository")
            if path.is_symlink() or self.cache_root.is_symlink():
                raise EvidenceError("cache files and directory must not be symlinks")
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            header = re.match(r"\A#\s+PMID:([0-9]+)\s*\n", text)
            if header is None or header.group(1) != pmid:
                raise EvidenceError("cache header does not identify the cited PMID")
            headings = list(re.finditer(r"(?im)^##\s+Abstract\s*$", text))
            if len(headings) != 1:
                raise EvidenceError("cache requires exactly one explicit Abstract section")
            remainder = text[headings[0].end():]
            body = re.split(r"(?m)^#{1,2}\s+", remainder, maxsplit=1)[0].strip()
            if not body:
                raise EvidenceError("cache abstract is empty")
            result: CachedSource | QuoteResult = CachedSource(body, relative, hashlib.sha256(raw).hexdigest())
        except FileNotFoundError:
            result = QuoteResult("MISSING_CACHE", reference, "No supported PMID markdown cache; no source was fetched.", cache_path=relative)
        except (OSError, UnicodeError, EvidenceError) as exc:
            result = QuoteResult("INVALID_CACHE", reference, str(exc), cache_path=relative)
        self._cache[pmid] = result
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
        for field, ref in references:
            match = _PMID.fullmatch(ref)
            if field == "pmid" and match is None:
                return QuoteResult("INVALID_EVIDENCE", detail="pmid must identify a PMID", quote_sha256=quote_hash)
            # Bare numbers are PMIDs only in their explicit native PMID slot.
            # A DOI (even one that happens to look numeric) is never a PMID.
            if field != "doi" and match and (field == "pmid" or ref.upper().startswith("PMID:")):
                pmids.add(match.group(1))
        if len(pmids) > 1:
            return QuoteResult("INVALID_EVIDENCE", detail="Conflicting PMID references", quote_sha256=quote_hash)
        if not pmids:
            return QuoteResult("UNSUPPORTED_REFERENCE", references[0][1], "Only identified PMID abstract caches are supported; other sources remain unverified.", quote_hash)
        pmid = next(iter(pmids))
        source = self._source(pmid)
        if isinstance(source, QuoteResult):
            return QuoteResult(source.verdict, source.reference, source.detail, quote_hash, source.cache_path, source.cache_sha256)
        verdict = "OK" if normalize(quote) in normalize(source.body) else "SNIPPET_NOT_IN_SOURCE"
        return QuoteResult(verdict, f"PMID:{pmid}",
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


def validate_corpus(root: Path, globs: Sequence[str], config: EvidenceConfig) -> dict[str, Any]:
    """Read every selected record. Malformed/unreadable input cannot disappear."""
    root = root.resolve()
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
    counts = Counter(row["verdict"] for row in results)
    return {"records": len(files), "evidence_items": len(results),
        "quote_validated_items": counts["OK"], "verdicts": {v: counts[v] for v in VERDICTS},
        "errors": errors, "results": results, "cache_dir": config.cache_dir,
        "evidence_paths": list(config.evidence_paths), "unmeasured_items": len(unmeasured),
        "unmeasured": unmeasured,
        "comparison": "NFKC + collapsed whitespace + lowercase substring in identified abstract body",
        "limits": "Quote occurrence is not scientific claim support, scope, source-rights clearance or human review. Unsupported sources are unverified."}


def exit_code(report: Mapping[str, Any], *, strict: bool) -> int:
    blocked = STRICT_BLOCKING if strict else BLOCKING
    return 2 if report["errors"] or any(report["verdicts"][v] for v in blocked) else 0
