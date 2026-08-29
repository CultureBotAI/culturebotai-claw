"""Cross-record consistency scanning for the CultureBotAI fleet."""

from __future__ import annotations

from .proposals import (
    FALLBACK_QUALITIES,
    IDENTITY_QUALITIES,
    Proposal,
    build_proposals,
    is_fallback,
    is_ontology_grounded,
    propose_for_group,
    render_markdown,
)
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
    scan_groups,
)

__all__ = [
    "FALLBACK_QUALITIES",
    "IDENTITY_QUALITIES",
    "Proposal",
    "build_proposals",
    "is_fallback",
    "is_ontology_grounded",
    "propose_for_group",
    "render_markdown",
    "scan_groups",
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
