"""Cross-record consistency scanning for the CultureBotAI fleet."""

from __future__ import annotations

from .scanner import (
    COMPARED_FIELDS,
    Disagreement,
    Group,
    Record,
    ScannerError,
    find_disagreements,
    group_records,
    load_corpus,
    load_record,
    normalize_name,
    scan,
)

__all__ = [
    "COMPARED_FIELDS",
    "Disagreement",
    "Group",
    "Record",
    "ScannerError",
    "find_disagreements",
    "group_records",
    "load_corpus",
    "load_record",
    "normalize_name",
    "scan",
]
