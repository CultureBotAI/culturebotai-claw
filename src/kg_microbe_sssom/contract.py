"""What a Mech's SSSOM mapping file must hold to, checked once for the fleet.

MediaIngredientMech, CultureMech and TraitMech publish SSSOM today, and they
agree on more than they know.
Measured across six real files -- MediaIngredientMech's 2,993-row canonical
ingredient mapping and its research proposal, three of CultureMech's ChEBI
exports, and TraitMech's METPO proposal -- eight columns appear in every one:

    subject_id  subject_label  predicate_id  object_id  object_label
    mapping_justification  confidence  comment

All eight are SSSOM slots. That shared core is what this checks, and it is not
an invention: it is what the fleet already writes.

Past the core they diverge, and some of the divergence is drift rather than
choice. Checked against the installed sssom_schema 1.0.0, three column names in
use are **not SSSOM slots at all**:

    source              MediaIngredientMech (2 files)
    validation_method   MediaIngredientMech (2 files)
    mapping_method      CultureMech (2 files)

`other` and `mapping_source` are standard, which is worth saying because they
look like the odd ones out and are not. The point is not that a Mech may never
add a column -- SSSOM allows extensions -- but that an extension should be a
declared decision rather than a name someone reached for, because a consumer
reading `source` has no way to know whether it means `mapping_source`,
`subject_source` or something else.

Two rows asserting the same triple are not a duplicate either. SSSOM records
independent evidence as separate rows differing in `mapping_justification`, and
CultureMech has 1,819 such pairs across two files -- every one legitimate, and
not one an identical row. Only a repeated *row* is a repeat.

A row that records "nothing matched" is not a broken row. CultureMech writes
3,664 of them with `predicate_id: semapv:Unmapped` and no object, which is a
deliberate convention and the same idea as SSSOM's `sssom:NoTermFound`. Treating
those as missing identifiers would have reported thousands of correct rows and
buried the four findings that matter.

The curie_map is the other half. SSSOM CURIEs are only resolvable through the
`# curie_map:` preamble, and TraitMech's proposal files carry no preamble at
all -- so a reader cannot expand `METPO:0000001` without knowing the convention
out of band. A file that declares prefixes it never uses is untidy; a file that
uses prefixes it never declares is unreadable, and only the second is an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import yaml  # type: ignore[import-untyped]

__all__ = [
    "CORE_COLUMNS",
    "Finding",
    "MappingFile",
    "SsssomProfile",
    "check_file",
    "check_mapping",
    "read_mapping",
]

#: Present in every SSSOM file the fleet publishes today, and all SSSOM slots.
CORE_COLUMNS = (
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "confidence",
    "comment",
)

# A CURIE's prefix. Deliberately not a full CURIE grammar: the question here is
# only "which prefixes does this file rely on", so that the curie_map can be
# checked for covering them.
_PREFIX = re.compile(r"^([A-Za-z][A-Za-z0-9._-]*):")

_ID_COLUMNS = ("subject_id", "object_id", "predicate_id")

# A row that records "nothing matched" deliberately has no object. CultureMech
# writes 3,664 of them with `predicate_id: semapv:Unmapped`, and SSSOM has
# `sssom:NoTermFound` for the same idea. Reporting those as empty identifiers
# would bury four real findings under thousands of correct rows -- the failure
# mode that makes a check something people learn to ignore.
_UNMAPPED_PREDICATES = frozenset({"semapv:unmapped", "sssom:notermfound"})
_NO_TERM_FOUND = "sssom:notermfound"


def _is_unmapped(row: dict[str, str]) -> bool:
    predicate = (row.get("predicate_id") or "").strip().casefold()
    obj = (row.get("object_id") or "").strip().casefold()
    return predicate in _UNMAPPED_PREDICATES or obj == _NO_TERM_FOUND


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str
    row: int | None = None

    def __str__(self) -> str:
        where = f" (row {self.row})" if self.row is not None else ""
        return f"{self.code}: {self.detail}{where}"


@dataclass
class MappingFile:
    """A parsed SSSOM TSV: its preamble, its columns and its rows."""

    curie_map: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    columns: tuple[str, ...] = ()
    rows: list[dict[str, str]] = field(default_factory=list)
    preamble_lines: int = 0


@dataclass(frozen=True)
class SsssomProfile:
    """The per-Mech half: which non-slot columns this repository has declared.

    An extension named here is a decision on the record. One that is not is a
    finding, which is the whole point -- SSSOM permits extensions, so the only
    way an undeclared one can be caught is by declaring the rest.
    """

    extensions: tuple[str, ...] = ()
    #: Prefixes the file may use without declaring them in its curie_map,
    #: for the few that are universally understood.
    implicit_prefixes: tuple[str, ...] = ("http", "https", "urn")


def _slot_names() -> frozenset[str]:
    """SSSOM's own slot list, read from the installed schema rather than typed.

    Typing the list here would make this check an opinion about SSSOM instead
    of a use of it, and `other` and `mapping_source` are exactly the kind of
    slot a person guesses wrong.
    """
    try:
        from sssom_schema import __file__ as schema_init
    except ImportError:  # pragma: no cover - exercised through the fallback test
        return frozenset()
    schema = Path(schema_init).parent / "schema" / "sssom_schema.yaml"
    try:
        document = yaml.safe_load(schema.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):  # pragma: no cover - unreadable install
        return frozenset()
    return frozenset(document.get("slots") or ())


def read_mapping(text: str) -> MappingFile:
    """Split an SSSOM TSV into its `#` preamble and its table."""
    preamble: list[str] = []
    body: list[str] = []
    for line in text.splitlines():
        if not body and line.startswith("#"):
            preamble.append(line[1:])
            continue
        if line.strip():
            body.append(line)

    metadata: dict[str, object] = {}
    if preamble:
        try:
            loaded = yaml.safe_load("\n".join(preamble))
            if isinstance(loaded, dict):
                metadata = loaded
        except yaml.YAMLError:
            metadata = {}

    curie_map = metadata.get("curie_map")
    columns: tuple[str, ...] = ()
    rows: list[dict[str, str]] = []
    if body:
        columns = tuple(body[0].split("\t"))
        for line in body[1:]:
            values = line.split("\t")
            # A short row is a real defect, but reading it as a dict of what is
            # there lets the column-count rule report it once rather than every
            # rule failing on a missing key.
            rows.append(dict(zip(columns, values)))
    return MappingFile(
        curie_map=curie_map if isinstance(curie_map, dict) else {},
        metadata=metadata,
        columns=columns,
        rows=rows,
        preamble_lines=len(preamble),
    )


def _prefixes_used(mapping: MappingFile) -> set[str]:
    found: set[str] = set()
    for row in mapping.rows:
        for column in _ID_COLUMNS:
            match = _PREFIX.match((row.get(column) or "").strip())
            if match:
                found.add(match.group(1))
    return found


def check_mapping(
    mapping: MappingFile, profile: SsssomProfile | None = None
) -> list[Finding]:
    """Judge a parsed mapping file against the shared contract."""
    profile = profile or SsssomProfile()
    findings: list[Finding] = []

    if not mapping.columns:
        return [Finding("EMPTY_FILE", "no header row, so there is nothing to check")]

    missing = [c for c in CORE_COLUMNS if c not in mapping.columns]
    if missing:
        findings.append(
            Finding(
                "MISSING_CORE_COLUMN",
                f"{missing} absent; every SSSOM file the fleet publishes carries "
                f"all of {list(CORE_COLUMNS)}",
            )
        )

    duplicated = sorted({c for c in mapping.columns if mapping.columns.count(c) > 1})
    if duplicated:
        findings.append(
            Finding("DUPLICATE_COLUMN", f"{duplicated} appears more than once")
        )

    slots = _slot_names()
    if slots:
        undeclared = [
            c
            for c in mapping.columns
            if c not in slots and c not in profile.extensions
        ]
        if undeclared:
            findings.append(
                Finding(
                    "UNDECLARED_EXTENSION",
                    f"{undeclared} are not SSSOM slots and are not declared as "
                    f"extensions; a consumer cannot tell what they mean",
                )
            )

    if not mapping.curie_map:
        findings.append(
            Finding(
                "NO_CURIE_MAP",
                "no `# curie_map:` preamble, so the CURIEs in this file cannot "
                "be expanded without knowing the convention out of band",
            )
        )
    else:
        undeclared_prefixes = sorted(
            p
            for p in _prefixes_used(mapping)
            if p not in mapping.curie_map and p not in profile.implicit_prefixes
        )
        if undeclared_prefixes:
            findings.append(
                Finding(
                    "PREFIX_NOT_IN_CURIE_MAP",
                    f"{undeclared_prefixes} used but not declared; those CURIEs "
                    f"cannot be resolved",
                )
            )

    width = len(mapping.columns)
    seen: dict[tuple[str, ...], int] = {}
    for number, row in enumerate(mapping.rows, start=1):
        if len(row) != width:
            findings.append(
                Finding(
                    "RAGGED_ROW",
                    f"{len(row)} value(s) for {width} column(s)",
                    row=number,
                )
            )
        unmapped = _is_unmapped(row)
        for column in _ID_COLUMNS:
            value = (row.get(column) or "").strip()
            if not value:
                if unmapped and column == "object_id":
                    continue
                findings.append(
                    Finding("EMPTY_IDENTIFIER", f"{column} is empty", row=number)
                )
            elif not _PREFIX.match(value) and not value.startswith("http"):
                findings.append(
                    Finding(
                        "NOT_A_CURIE",
                        f"{column}={value!r} is neither a CURIE nor an IRI",
                        row=number,
                    )
                )
        confidence = (row.get("confidence") or "").strip()
        if confidence:
            try:
                score = float(confidence)
            except ValueError:
                findings.append(
                    Finding(
                        "CONFIDENCE_NOT_A_NUMBER", f"confidence={confidence!r}", row=number
                    )
                )
            else:
                if not 0.0 <= score <= 1.0:
                    findings.append(
                        Finding(
                            "CONFIDENCE_OUT_OF_RANGE",
                            f"confidence={score} is outside 0..1",
                            row=number,
                        )
                    )
        object_value = (row.get("object_id") or "").strip()
        # `sssom:NoTermFound` *is* the sanctioned way to fill object_id for a
        # no-match, so it is not a contradiction -- only a real term is.
        if unmapped and object_value and object_value.casefold() != _NO_TERM_FOUND:
            findings.append(
                Finding(
                    "UNMAPPED_ROW_HAS_AN_OBJECT",
                    f"predicate says nothing matched but object_id is "
                    f"{object_value!r}",
                    row=number,
                )
            )

        # The whole row, not just the triple. SSSOM records independent
        # evidence for one mapping as separate rows differing in
        # mapping_justification, and CultureMech has 1,819 such pairs across two
        # files -- every one legitimate, none an identical row. Keying on the
        # triple alone reported all of them and would have made this check noise.
        key = tuple(
            (row.get(column) or "").strip() for column in mapping.columns
        )
        if any(key):
            first = seen.get(key)
            if first is not None:
                findings.append(
                    Finding(
                        "DUPLICATE_MAPPING",
                        f"an identical row was already written at row {first}",
                        row=number,
                    )
                )
            else:
                seen[key] = number
    return findings


def check_file(path: Path, profile: SsssomProfile | None = None) -> list[Finding]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return check_mapping(read_mapping(text), profile)


def check_files(
    paths: Iterable[Path], profile: SsssomProfile | None = None
) -> dict[str, list[Finding]]:
    return {str(p): check_file(p, profile) for p in sorted(paths)}


def summarise(findings: Sequence[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return counts
