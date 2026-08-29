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

__all__ = [
    "BLOCK_REQUIRED",
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
