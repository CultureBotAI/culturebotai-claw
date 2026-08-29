"""Shared source-catalogue model for the fleet (#132 Phase 6)."""

from kg_microbe_sources.catalogue import (
    BLOCK_REQUIRED,
    DEFAULT_SEEDER_GLOB,
    DEFAULT_STATUSES,
    GROUP_REQUIRED,
    CatalogueError,
    Finding,
    Report,
    SourceGroup,
    load_blocks,
    validate,
)

# `fetch` the function is deliberately NOT re-exported here. Binding that name
# on the package shadows `kg_microbe_sources.fetch` the module, so
# `import kg_microbe_sources.fetch` and every `monkeypatch.setattr` targeting
# something inside it stop resolving. Callers write
# `from kg_microbe_sources.fetch import fetch`, which says which one they mean.
from kg_microbe_sources.fetch import (
    CurlTransport,
    FetchError,
    FetchPlan,
    FetchResult,
    TransportResult,
    ValidationFailed,
    sha256_of,
    verify,
)

__all__ = [
    "BLOCK_REQUIRED",
    "CurlTransport",
    "FetchError",
    "FetchPlan",
    "FetchResult",
    "TransportResult",
    "ValidationFailed",
    "sha256_of",
    "verify",
    "DEFAULT_SEEDER_GLOB",
    "DEFAULT_STATUSES",
    "GROUP_REQUIRED",
    "CatalogueError",
    "Finding",
    "Report",
    "SourceGroup",
    "load_blocks",
    "validate",
]
