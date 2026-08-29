"""Shared validated-write primitives for the CultureBotAI fleet."""

from __future__ import annotations

from .registry import (
    REGISTRY_VERSION,
    RegistryError,
    WriterEntry,
    calls_shared_record_writer,
    discover_corpus_writers,
    load_registry,
    overdue,
    parse_registry,
)
from .transaction import (
    DEFAULT_JOURNAL_RETENTION,
    JOURNAL_VERSION,
    Change,
    ValidatedWriteTransaction,
    ValidationFailed,
    Validator,
    WriteError,
    WriteResult,
    recover,
)

__all__ = [
    "REGISTRY_VERSION",
    "RegistryError",
    "WriterEntry",
    "calls_shared_record_writer",
    "discover_corpus_writers",
    "load_registry",
    "overdue",
    "parse_registry",
    "DEFAULT_JOURNAL_RETENTION",
    "JOURNAL_VERSION",
    "Change",
    "ValidatedWriteTransaction",
    "ValidationFailed",
    "Validator",
    "WriteError",
    "WriteResult",
    "recover",
]
