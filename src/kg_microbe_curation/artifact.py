"""Validate external analytical manifests without claiming scientific approval.

This contract describes immutable Parquet generations. It neither reads the
partition files nor authenticates their contents: the storage reader must check
every declared file, physical schema, hash and logical reconciliation itself.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from .identity import CONTRACT, CurationError, canonical_json

ARTIFACT_CONTRACT = "kg-microbe-curation-artifact/v1"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
TABLE_NAMES = (
    "occurrences", "current_decisions", "bundles", "metadata", "coverage_counts",
    "observations", "claims", "reviews", "evidence", "memberships", "history",
)


def validate_relative_path(value: str) -> None:
    """Reject traversal, alias spellings and platform-dependent relative paths."""
    if (
        not isinstance(value, str) or not value or len(value) > 4096
        or "\\" in value or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CurationError("Artifact path must be a bounded relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute() or any(part in {".", ".."} for part in value.split("/"))
        or str(path) != value or any(len(part) > 255 for part in path.parts)
    ):
        raise CurationError("Artifact path contains traversal or a noncanonical spelling")


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(files("kg_microbe_curation").joinpath("schema/artifact.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_artifact_manifest(manifest: dict[str, Any]) -> None:
    """Check bounded shape, table membership and declared accounting consistency.

    This is a pure check. Successful validation is not file verification,
    atomic publication, approval of a decision, or proof of source authenticity.
    """
    if len(canonical_json(manifest)) > MAX_MANIFEST_BYTES:
        raise CurationError("Artifact manifest exceeds the 16 MiB byte limit")
    errors = sorted(_validator().iter_errors(manifest), key=lambda item: str(list(item.path)))
    if errors:
        raise CurationError("Invalid artifact manifest: " + "; ".join(
            f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}"
            for error in errors[:10]
        ))
    if manifest["identity_contract"] != CONTRACT:
        raise CurationError("Unsupported occurrence identity contract")
    source = manifest["source"]
    validate_relative_path(source["edge_member"])
    selected = source["selected_rows"]
    for key in ("selected_rows", "source_rows"):
        if type(source[key]) is not int:
            raise CurationError("Source row counts must be exact integers")
    if selected > source["source_rows"]:
        raise CurationError("Selected rows exceed the source population")
    if source["complete_export"] and selected != source["source_rows"]:
        raise CurationError("Complete export does not cover the source population")
    paths: set[str] = set()
    for name, table in manifest["tables"].items():
        if table["schema"] != f"edgemech-table/{name}/v1":
            raise CurationError(f"Unsupported table schema: {name}")
        if type(table["rows"]) is not int:
            raise CurationError("Table row counts must be exact integers")
        total = 0
        for partition in table["partitions"]:
            path = partition["path"]
            validate_relative_path(path)
            if not path.endswith(".parquet") or path in paths:
                raise CurationError("Partitions must be unique Parquet paths across all tables")
            paths.add(path)
            if type(partition["rows"]) is not int or type(partition["bytes"]) is not int:
                raise CurationError("Partition counts must be exact integers")
            total += partition["rows"]
        if total != table["rows"]:
            raise CurationError(f"Partition rows do not reconcile for {name}")
    for name in ("occurrences", "current_decisions"):
        if manifest["tables"][name]["rows"] != selected:
            raise CurationError(f"{name} does not account for every selected occurrence")
    for dimension, counts in manifest["counters"].items():
        if any(type(count) is not int for count in counts.values()):
            raise CurationError("Coverage counters must be exact integers")
        if sum(counts.values()) != selected:
            raise CurationError(f"Coverage counter does not reconcile: {dimension}")
    for key in ("buckets", "row_group_size"):
        if type(manifest["layout"][key]) is not int:
            raise CurationError("Layout sizes must be exact integers")
