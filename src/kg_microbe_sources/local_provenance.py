"""Gitignore-independent local provenance lookup across Mech workspaces and LBNL harvests.

During Mech record review, 9,113 standard-priority DOIs and cached abstracts live
inside single-repo ``research_notes/``, ``references_cache/``, ``data/raw/``, or
central LBNL harvest TSVs (``doi_metadata_enriched.tsv``,
``cas_common_chemistry_enriched.tsv``) rather than on the top-level curated YAML.
Many of these directories are gitignored, so ordinary ``rg`` / ``git grep``
invocation misses them unless ``--no-ignore`` is used.

This module provides a deterministic, gitignore-independent Python scanner that:
1. Extracts DOIs, PMIDs, CAS Registry Numbers, ChEBI IDs, and Standard InChIKeys
   from a Mech record file or explicit query tokens.
2. Searches local Mech directories and central harvest tables for matching hits,
   classifying each match by provenance tier (``research_cache``, ``raw_table``,
   ``curation_table``, ``curated_record``, ``harvest_tsv``).
3. Flags ACS DOIs (``10.1021/*``) so the reviewer or CLI can automatically probe
   ACS Figshare Supporting Information (``<doi>.s001``).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kg_microbe_sources.acs_figshare import ACS_DOI_PREFIX

_DOI_URL_PREFIX_RE = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
    re.IGNORECASE,
)
_DOI_FIND_RE = re.compile(
    r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s\"'<>)\],;]+)",
    re.IGNORECASE,
)
_PMID_FIND_RE = re.compile(r"\bPMID:\s*(\d{4,10})\b", re.IGNORECASE)
_CAS_FIND_RE = re.compile(r"\b(?:CAS-RN:\s*)?(\d{2,7}-\d{2}-\d)\b")
_CHEBI_FIND_RE = re.compile(r"\b(CHEBI:\d+)\b", re.IGNORECASE)
_INCHIKEY_FIND_RE = re.compile(r"\b([A-Z]{14}-[A-Z]{10}-[A-Z])\b")

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "site",
        "dist",
        "build",
    }
)
_TEXT_SUFFIXES = frozenset(
    {
        ".yaml",
        ".yml",
        ".tsv",
        ".csv",
        ".json",
        ".jsonl",
        ".md",
        ".txt",
    }
)
_MAX_FILE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class LocalProvenanceHit:
    """A single line match in a local Mech repository or LBNL harvest file."""

    root: str
    category: str
    relative_path: str
    line_number: int
    matched_token: str
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary representation."""
        return asdict(self)


@dataclass(frozen=True)
class LocalProvenanceReport:
    """Aggregated local provenance hits and detected ACS DOIs for a review query."""

    tokens: tuple[str, ...]
    acs_dois: tuple[str, ...]
    hits: tuple[LocalProvenanceHit, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary representation."""
        return {
            "tokens": list(self.tokens),
            "acs_dois": list(self.acs_dois),
            "hit_count": len(self.hits),
            "hits": [h.to_dict() for h in self.hits],
        }


def normalize_doi(raw: str) -> str:
    """Normalize a DOI string to lowercase ``10.xxxx/...`` without URL prefix or trailing punctuation."""
    cleaned = _DOI_URL_PREFIX_RE.sub("", (raw or "").strip()).strip()
    cleaned = cleaned.rstrip(".,;:)]}>'\"")
    return cleaned.lower()


def is_valid_cas_rn(cas_rn: str) -> bool:
    """Return ``True`` if ``cas_rn`` has valid ``<d1>-<d2>-<check>`` syntax and CAS check digit."""
    parts = (cas_rn or "").strip().split("-")
    if len(parts) != 3:
        return False
    first, second, check = parts
    if not (2 <= len(first) <= 7 and len(second) == 2 and len(check) == 1):
        return False
    if not (first.isdigit() and second.isdigit() and check.isdigit()):
        return False
    body_digits = first + second
    weighted_sum = sum(
        (idx + 1) * int(digit) for idx, digit in enumerate(reversed(body_digits))
    )
    return (weighted_sum % 10) == int(check)


def extract_citations_from_text(text: str) -> list[str]:
    """Extract normalized DOIs, PMIDs, CAS-RNs, ChEBI IDs, and Standard InChIKeys from text."""
    seen: dict[str, None] = {}

    for match in _DOI_FIND_RE.finditer(text):
        doi = normalize_doi(match.group(1))
        if doi:
            seen.setdefault(doi, None)

    for match in _PMID_FIND_RE.finditer(text):
        seen.setdefault(f"PMID:{match.group(1)}", None)

    for match in _CHEBI_FIND_RE.finditer(text):
        seen.setdefault(match.group(1).upper(), None)

    for match in _INCHIKEY_FIND_RE.finditer(text):
        seen.setdefault(match.group(1), None)

    for match in _CAS_FIND_RE.finditer(text):
        candidate_cas = match.group(1)
        if is_valid_cas_rn(candidate_cas):
            seen.setdefault(candidate_cas, None)

    return list(seen.keys())


def classify_provenance_path(relative_path: str) -> str:
    """Classify a relative path into a provenance tier."""
    norm = relative_path.replace("\\", "/").lstrip("./")
    parts = [p.lower() for p in norm.split("/") if p]
    if any(p in {"research_notes", "references_cache", "literature_cache"} for p in parts):
        return "research_cache"
    if len(parts) >= 2 and parts[0] == "data" and parts[1] == "raw":
        return "raw_table"
    if parts and parts[0] in {"curation", "evidence"}:
        return "curation_table"
    if any(
        p in {".temp", "mech-chemicals-and-acs-dois"}
        or p.endswith("_enriched.tsv")
        or p.endswith("_master.tsv")
        for p in parts
    ):
        return "harvest_tsv"
    if parts and parts[0] in {"kb", "data"}:
        return "curated_record"
    return "other"


def _iter_candidate_files(root: Path) -> Iterable[tuple[Path, str]]:
    """Yield ``(file_path, relative_path)`` across ``root`` without respecting ``.gitignore``."""
    if root.is_file():
        yield root, root.name
        return
    if not root.is_dir():
        return

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        base = Path(dirpath)
        for fname in sorted(filenames):
            fpath = base / fname
            if fpath.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if fpath.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            rel = str(fpath.relative_to(root))
            yield fpath, rel


def search_local_provenance(
    tokens: Sequence[str],
    search_roots: Sequence[Path],
    *,
    max_hits_per_root: int = 200,
) -> LocalProvenanceReport:
    """Search ``search_roots`` (including gitignored caches/raw tables) for ``tokens``."""
    cleaned_tokens: list[str] = []
    seen_tokens: set[str] = set()
    for raw_tok in tokens:
        tok = (raw_tok or "").strip()
        if not tok:
            continue
        if tok.lower().startswith(("10.", "doi:", "http://doi.org/", "https://doi.org/")):
            tok = normalize_doi(tok)
        if tok and tok not in seen_tokens:
            seen_tokens.add(tok)
            cleaned_tokens.append(tok)

    acs_dois = tuple(
        sorted({t for t in cleaned_tokens if t.lower().startswith(ACS_DOI_PREFIX)})
    )
    if not cleaned_tokens:
        return LocalProvenanceReport(tokens=(), acs_dois=(), hits=())

    lowered_pairs = [(tok, tok.lower()) for tok in cleaned_tokens]
    hits: list[LocalProvenanceHit] = []

    for root in search_roots:
        root_hits = 0
        root_label = root.name or str(root)
        for fpath, rel_path in _iter_candidate_files(root):
            if root_hits >= max_hits_per_root:
                break
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            content_lower = content.lower()
            if not any(tok_low in content_lower for _, tok_low in lowered_pairs):
                continue

            category = classify_provenance_path(rel_path)
            for line_no, line in enumerate(content.splitlines(), start=1):
                line_low = line.lower()
                for orig_tok, tok_low in lowered_pairs:
                    if tok_low in line_low:
                        snippet = line.strip()
                        if len(snippet) > 240:
                            snippet = snippet[:237] + "..."
                        hits.append(
                            LocalProvenanceHit(
                                root=root_label,
                                category=category,
                                relative_path=rel_path,
                                line_number=line_no,
                                matched_token=orig_tok,
                                snippet=snippet,
                            )
                        )
                        root_hits += 1
                        break
                if root_hits >= max_hits_per_root:
                    break

    return LocalProvenanceReport(
        tokens=tuple(cleaned_tokens),
        acs_dois=acs_dois,
        hits=tuple(hits),
    )
