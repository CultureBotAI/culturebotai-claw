"""Read-only scanner for cross-record disagreement within a Mech corpus.

The recurring defect #129 describes has no general gate: a record is internally
self-consistent but wrong, and a matching record elsewhere already has the right
answer, yet nothing surfaces the disagreement. The existing checks structurally
cannot catch it -- id/label correspondence compares a CURIE to its own ontology
label, and the QC dashboard measures completeness. Neither compares two records.

This is the narrowly scoped first step from #129: group records that plausibly
denote the same substance, report where a curated field disagrees across the
group, and stop there. It proposes nothing and writes nothing to the corpus.

Matching reuses signals already proven in this fleet rather than inventing new
ones: normalized names, synonym overlap, and a shared external identifier, as
`plugins/ingredient_deduplicator.py` does for deduplication.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Fields whose disagreement across matched records is a finding. Each is a
# curated decision about the same real-world substance, so two records that
# denote one substance should not differ.
COMPARED_FIELDS: tuple[str, ...] = (
    "ontology_id",
    "mapping_predicate",
    "ingredient_type",
)


class ScannerError(ValueError):
    """The corpus could not be read, or a record is unusable."""


def normalize_name(name: str) -> str:
    """Collapse a display name to a comparison key.

    Deliberately the same shape `ingredient_deduplicator.normalize_name` uses:
    a second normalization would group differently from the tool that already
    merges duplicates, and disagreeing about what "the same name" means is how
    two consistency tools end up contradicting each other.
    """
    return _NON_ALNUM.sub("_", (name or "").strip().lower()).strip("_")


@dataclass(frozen=True)
class Record:
    """One ingredient record, reduced to what matching and comparison need."""

    path: Path
    identifier: str
    preferred_term: str
    synonyms: frozenset[str]
    fields: Mapping[str, str]

    @property
    def name_key(self) -> str:
        return normalize_name(self.preferred_term)


@dataclass
class Disagreement:
    """One curated field on which a matched group does not agree."""

    field_name: str
    values: Mapping[str, tuple[str, ...]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "values": {
                value: sorted(paths) for value, paths in sorted(self.values.items())
            },
        }


@dataclass
class Group:
    """Records that plausibly denote the same substance."""

    key: str
    reason: str
    records: tuple[Record, ...]
    disagreements: tuple[Disagreement, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "matched_on": self.reason,
            "records": [
                {"identifier": r.identifier, "path": str(r.path),
                 "preferred_term": r.preferred_term}
                for r in sorted(self.records, key=lambda r: str(r.path))
            ],
            "disagreements": [d.as_dict() for d in self.disagreements],
        }


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def load_record(path: Path) -> Record | None:
    """Read one record, or None when it is not a usable ingredient YAML."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    identifier = _first_string(raw.get("identifier"))
    if not identifier:
        return None

    mapping = raw.get("ontology_mapping")
    mapping = mapping if isinstance(mapping, dict) else {}
    synonyms: set[str] = set()
    for entry in raw.get("synonyms") or ():
        if isinstance(entry, str):
            synonyms.add(normalize_name(entry))
        elif isinstance(entry, dict):
            text = _first_string(entry.get("value"), entry.get("text"))
            if text:
                synonyms.add(normalize_name(text))

    preferred = _first_string(raw.get("preferred_term"), path.stem)
    synonyms.add(normalize_name(preferred))
    synonyms.discard("")

    return Record(
        path=path,
        identifier=identifier,
        preferred_term=preferred,
        synonyms=frozenset(synonyms),
        fields={
            "ontology_id": _first_string(mapping.get("ontology_id")),
            "mapping_predicate": _first_string(mapping.get("mapping_predicate")),
            "ingredient_type": _first_string(raw.get("ingredient_type")),
        },
    )


def load_corpus(root: Path, glob: str = "**/*.yaml") -> tuple[list[Record], int]:
    """Every usable record under `root`, and how many files were skipped.

    The skipped count is returned rather than discarded because "0 records"
    and "0 records out of 900 files I could not read" are different answers,
    and only the first means the corpus is clean. Pointing this at a Mech whose
    records use a different shape reported the former (#161's failure, in a new
    place).
    """
    directory = Path(root)
    if not directory.is_dir():
        raise ScannerError(f"corpus directory does not exist: {directory}")
    paths = sorted(directory.glob(glob))
    records = [load_record(path) for path in paths]
    usable = [record for record in records if record is not None]
    return usable, len(paths) - len(usable)


def group_records(records: Sequence[Record]) -> list[Group]:
    """Group records that plausibly denote the same substance.

    Two signals, both already used in this fleet: an identical normalized name,
    and a shared synonym. Synonym overlap deliberately does not use a
    similarity threshold here -- a shared exact synonym is evidence, a partial
    overlap is a guess, and this scanner reports rather than proposes.
    """
    by_name: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.name_key:
            by_name[record.name_key].append(record)

    groups: list[Group] = []
    # Keyed on the exact SET of records, not on membership. Suppressing a group
    # because its members are individually known elsewhere drops genuinely new
    # pairings: two records can each sit in an agreeing name group and still
    # disagree with each other through a shared synonym, and that disagreement
    # was the one being silently dropped (#182). A record legitimately belongs
    # to more than one match relationship, and each is a separate question.
    emitted: set[frozenset[Path]] = set()

    def _emit(key: str, reason: str, members: Sequence[Record]) -> None:
        paths = frozenset(record.path for record in members)
        if len(paths) < 2 or paths in emitted:
            return
        emitted.add(paths)
        groups.append(Group(key, reason, tuple(members)))

    for key, members in sorted(by_name.items()):
        _emit(key, "identical normalized name", members)

    by_synonym: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        for synonym in record.synonyms:
            if synonym:
                by_synonym[synonym].append(record)

    for key, members in sorted(by_synonym.items()):
        _emit(key, "shared synonym", members)
    return groups


def find_disagreements(
    group: Group, fields: Iterable[str] = COMPARED_FIELDS
) -> tuple[Disagreement, ...]:
    """The compared fields on which this group does not agree.

    A field is only a disagreement when at least two records state DIFFERENT
    non-empty values. An absent value is a gap, not a contradiction, and
    reporting gaps here would bury the contradictions the scanner exists for.
    """
    found: list[Disagreement] = []
    for name in fields:
        values: dict[str, list[str]] = defaultdict(list)
        for record in group.records:
            value = record.fields.get(name, "")
            if value:
                values[value].append(str(record.path))
        if len(values) > 1:
            found.append(
                Disagreement(name, {v: tuple(p) for v, p in values.items()})
            )
    return tuple(found)


def scan(root: Path, glob: str = "**/*.yaml") -> dict[str, Any]:
    """Scan a corpus and report every matched group that disagrees."""
    records, skipped = load_corpus(root, glob)
    groups = group_records(records)
    flagged = []
    for group in groups:
        disagreements = find_disagreements(group)
        if disagreements:
            flagged.append(
                Group(group.key, group.reason, group.records, disagreements)
            )
    return {
        "root": str(root),
        "records_scanned": len(records),
        "files_skipped": skipped,
        "groups_matched": len(groups),
        "groups_disagreeing": len(flagged),
        "findings": [group.as_dict() for group in flagged],
    }
