"""Artifact manifests reconcile declared rows without asserting file authenticity."""

from copy import deepcopy

import pytest

from kg_microbe_curation.artifact import (
    ARTIFACT_CONTRACT,
    MAX_MANIFEST_BYTES,
    TABLE_NAMES,
    validate_artifact_manifest,
    validate_relative_path,
)
from kg_microbe_curation.identity import CONTRACT, CurationError


@pytest.fixture
def manifest():
    tables = {
        name: {"schema": f"edgemech-table/{name}/v1", "rows": 0,
               "logical_sha256": "e" * 64, "partitions": []}
        for name in TABLE_NAMES
    }
    for name in ("occurrences", "current_decisions"):
        tables[name].update(rows=2, partitions=[{
            "path": f"tables/{name}/bucket-0000.parquet", "sha256": "f" * 64,
            "bytes": 100, "rows": 2,
        }])
    return {
        "contract": ARTIFACT_CONTRACT, "identity_contract": CONTRACT,
        "generation": "canary-20261107", "parent_manifest_sha256": None,
        "source": {
            "input_manifest_sha256": "a" * 64, "source_manifest_sha256": "b" * 64,
            "edge_member": "merged/merged-kg_edges.tsv", "edge_member_sha256": "c" * 64,
            "sqlite_sha256": "d" * 64, "ledger_revision": "e" * 64,
            "selected_rows": 2, "source_rows": 4, "complete_export": False,
        },
        "layout": {"partitioning": "sha256-first-key-modulo/v1", "buckets": 4,
                   "row_group_size": 1000},
        "tables": tables,
        "counters": {"lifecycle": {"active": 2}, "review_state": {"deferred": 2},
                     "conflict_state": {"not_assessed": 2}, "disposition": {"withheld": 2}},
        "assurance": {"source_verification": "Synthetic fixture only", "scientific_review": False},
    }


def test_declared_manifest_is_pure_and_does_not_mutate(manifest):
    before = deepcopy(manifest)
    assert validate_artifact_manifest(manifest) is None
    assert manifest == before


def test_direct_import_and_complete_export(manifest):
    manifest["source"].update(sqlite_sha256=None, source_rows=2, complete_export=True)
    validate_artifact_manifest(manifest)


@pytest.mark.parametrize("path", [
    "../part.parquet", "/part.parquet", "a//part.parquet", "a/./part.parquet",
    "a/../part.parquet", "a\\part.parquet", "C:part.parquet", "a/part.parquet/",
    "a/part.parquet\x00", "a/part.parquet\n", ".", "", "a" * 256,
])
def test_portable_paths_fail_closed(path):
    with pytest.raises(CurationError):
        validate_relative_path(path)


def test_cross_table_partition_alias_is_rejected(manifest):
    original = manifest["tables"]["occurrences"]["partitions"][0]
    manifest["tables"]["current_decisions"]["partitions"][0]["path"] = original["path"]
    with pytest.raises(CurationError, match="unique Parquet"):
        validate_artifact_manifest(manifest)


@pytest.mark.parametrize("mutation, message", [
    (lambda m: m["tables"].pop("history"), "required property"),
    (lambda m: m["tables"]["occurrences"].update(schema="edgemech-table/claims/v1"),
     "Unsupported table schema"),
    (lambda m: m["tables"]["occurrences"]["partitions"][0].update(rows=1),
     "Partition rows do not reconcile"),
    (lambda m: m["counters"]["disposition"].update(withheld=1), "counter does not reconcile"),
    (lambda m: m["counters"]["disposition"].update(approved=0), "Invalid artifact manifest"),
    (lambda m: m["source"].update(source_rows=1), "exceed the source population"),
    (lambda m: m["source"].update(complete_export=True), "does not cover"),
    (lambda m: m["source"].update(selected_rows=2.0), "exact integers"),
    (lambda m: m["layout"].update(buckets=4.0), "exact integers"),
    (lambda m: m["tables"]["occurrences"].update(rows=2.0), "exact integers"),
    (lambda m: m["counters"]["lifecycle"].update(active=2.0), "exact integers"),
    (lambda m: m["tables"]["occurrences"]["partitions"][0].update(bytes=100.0),
     "exact integers"),
    (lambda m: m["tables"]["occurrences"]["partitions"][0].update(path="part.csv"),
     "unique Parquet"),
    (lambda m: m["source"].update(edge_member="../edges.tsv"), "traversal"),
    (lambda m: m["tables"]["history"].update(logical_sha256="A" * 64),
     "Invalid artifact manifest"),
    (lambda m: m["assurance"].update(scientific_review=True), "Invalid artifact manifest"),
    (lambda m: m.update(generation="../generation"), "Invalid artifact manifest"),
    (lambda m: m.update(contract="future/v2"), "Invalid artifact manifest"),
])
def test_inconsistent_or_ambiguous_manifests_fail(manifest, mutation, message):
    mutation(manifest)
    with pytest.raises(CurationError, match=message):
        validate_artifact_manifest(manifest)


def test_current_decisions_must_cover_selected_occurrences(manifest):
    manifest["tables"]["current_decisions"].update(rows=1)
    manifest["tables"]["current_decisions"]["partitions"][0].update(rows=1)
    with pytest.raises(CurationError, match="every selected occurrence"):
        validate_artifact_manifest(manifest)


def test_empty_generation_reconciles(manifest):
    manifest["source"].update(selected_rows=0, source_rows=0, complete_export=True)
    for table in manifest["tables"].values():
        table.update(rows=0, partitions=[])
    manifest["counters"] = {dimension: {} for dimension in manifest["counters"]}
    validate_artifact_manifest(manifest)


def test_oversized_manifest_fails_before_shape_validation(manifest):
    manifest["unrecognized_large_field"] = "x" * MAX_MANIFEST_BYTES
    with pytest.raises(CurationError, match="16 MiB byte limit"):
        validate_artifact_manifest(manifest)
