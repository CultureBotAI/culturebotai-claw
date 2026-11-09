"""Lossless import, complete accounting, stale-review and atomic publication checks."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from kg_microbe_curation import ledger as ledger_module
from kg_microbe_curation.__main__ import main
from kg_microbe_curation.contract import unprocessed_decision
from kg_microbe_curation.identity import CONTRACT, CurationError, canonical_json, occurrence_id
from kg_microbe_curation.ledger import apply_bundle, audit, coverage, ingest_export, lookup


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def occurrence_export(tmp_path: Path):
    """Independent producer-shaped fixture with duplicates and literal extension text."""
    directory = tmp_path / "export"
    directory.mkdir()
    header = "subject\tpredicate\tobject\trelation\tpublications\tnote\n"
    rows = [
        'NCBITaxon:1\tbiolink:has_phenotype\tMETPO:1\tRO:1\tPMID:1|PMID:2\t"literal"\\text\n',
        'NCBITaxon:1\tbiolink:has_phenotype\tMETPO:1\tRO:1\tPMID:1|PMID:2\t"literal"\\text\n',
        "NCBITaxon:1\tbiolink:has_phenotype\tMETPO:1\tRO:2\tPMID:3\tnegative\n",
    ]
    member = "edges.tsv"
    member_bytes = (header + "".join(rows)).encode()
    descriptor = {"sha256": _hash(member_bytes), "bytes": len(member_bytes), "rows": len(rows)}
    source = {
        "manifest_version": 1,
        "members": {member: descriptor},
        "provenance": {"commit": "fixture"},
    }
    source_bytes = canonical_json(source) + b"\n"
    (directory / "source-manifest.json").write_bytes(source_bytes)
    occurrences = []
    for position, row in enumerate(rows, 1):
        payload = {
            "manifest_sha256": _hash(source_bytes),
            "member": member,
            "member_sha256": descriptor["sha256"],
            "row_number": position,
            "row_sha256": _hash(row.encode()),
        }
        occurrences.append(
            {"occurrence_id": occurrence_id(**payload), **payload, "source_row": row}
        )
    shard = b"".join(canonical_json(row) + b"\n" for row in occurrences)
    (directory / "occurrences-000001.jsonl").write_bytes(shard)
    manifest = {
        "contract": CONTRACT,
        "format": "edge-occurrence-export",
        "format_version": 1,
        "source_manifest_sha256": _hash(source_bytes),
        "source_manifest": source,
        "source_manifest_file": "source-manifest.json",
        "input_complete": True,
        "members": {
            member: {**descriptor, "header": header.rstrip("\n").split("\t"), "header_row": header}
        },
        "selection": {
            "edge_member": member,
            "max_rows": 0,
            "exported_rows": 3,
            "complete_export": True,
        },
        "shards": [
            {
                "file": "occurrences-000001.jsonl",
                "sha256": _hash(shard),
                "bytes": len(shard),
                "rows": 3,
                "first_row": 1,
                "last_row": 3,
            }
        ],
    }
    (directory / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
    return directory, manifest, occurrences


def _write_manifest(directory, manifest):
    (directory / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")


def _bundle(status, occurrence):
    decision = unprocessed_decision(occurrence["occurrence_id"])
    decision.update(review_state="deferred", rationale="Source evidence not yet available.")
    return {
        "contract": CONTRACT,
        "input_sha256": status["input_sha256"],
        "occurrence_ids": [occurrence["occurrence_id"]],
        "decisions": [decision],
        "observations": [],
        "claims": [],
        "reviews": [],
    }


def test_import_preserves_occurrences_and_literal_source(occurrence_export, tmp_path):
    directory, _, rows = occurrence_export
    database = tmp_path / "ledger.sqlite"
    status = ingest_export(directory, database)
    assert status["accounted_rows"] == status["current_decision_rows"] == 3
    assert status["review_state"] == {"unprocessed": 3}
    assert status["disposition"] == {"withheld": 3}
    assert status["complete_export"] is True
    assert rows[0]["occurrence_id"] != rows[1]["occurrence_id"]
    assert rows[0]["row_sha256"] == rows[1]["row_sha256"]
    assert lookup(database, rows[0]["occurrence_id"])["source_row"] == rows[0]["source_row"]


def test_subset_is_not_claimed_as_release_coverage(occurrence_export, tmp_path):
    directory, manifest, rows = occurrence_export
    shard = canonical_json(rows[0]) + b"\n"
    (directory / manifest["shards"][0]["file"]).write_bytes(shard)
    manifest["shards"][0].update(sha256=_hash(shard), bytes=len(shard), rows=1, last_row=1)
    manifest["selection"].update(max_rows=1, exported_rows=1, complete_export=False)
    _write_manifest(directory, manifest)
    status = ingest_export(directory, tmp_path / "ledger.sqlite")
    assert status["source_rows"] == 3 and status["accounted_rows"] == 1
    assert status["complete_export"] is False


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "corruption", "symlink", "traversal", "false_complete"]
)
def test_invalid_export_does_not_publish_ledger(occurrence_export, tmp_path, mutation):
    directory, manifest, _ = occurrence_export
    path = directory / manifest["shards"][0]["file"]
    if mutation == "missing":
        manifest["shards"] = []
    elif mutation == "duplicate":
        manifest["shards"] *= 2
    elif mutation == "corruption":
        path.write_bytes(path.read_bytes().replace(b"negative", b"positive"))
    elif mutation == "symlink":
        target = tmp_path / "other.jsonl"
        path.rename(target)
        path.symlink_to(target)
    elif mutation == "traversal":
        manifest["shards"][0]["file"] = "../other.jsonl"
    else:
        manifest["selection"]["complete_export"] = False
    _write_manifest(directory, manifest)
    database = tmp_path / "ledger.sqlite"
    with pytest.raises(CurationError):
        ingest_export(directory, database)
    assert not database.exists()


def test_rehashed_changed_rows_cannot_forge_complete_member(occurrence_export, tmp_path):
    directory, manifest, rows = occurrence_export
    rows[0]["source_row"] = rows[0]["source_row"].replace("METPO:1", "METPO:9")
    rows[0]["row_sha256"] = _hash(rows[0]["source_row"].encode())
    rows[0]["occurrence_id"] = occurrence_id(
        **{
            key: rows[0][key]
            for key in ("manifest_sha256", "member", "member_sha256", "row_number", "row_sha256")
        }
    )
    shard = b"".join(canonical_json(row) + b"\n" for row in rows)
    (directory / manifest["shards"][0]["file"]).write_bytes(shard)
    manifest["shards"][0].update(sha256=_hash(shard), bytes=len(shard))
    _write_manifest(directory, manifest)
    with pytest.raises(CurationError, match="reconstruct"):
        ingest_export(directory, tmp_path / "ledger.sqlite")


def test_append_history_and_stale_update_rollback(occurrence_export, tmp_path):
    directory, _, rows = occurrence_export
    database = tmp_path / "ledger.sqlite"
    initial = ingest_export(directory, database)
    bundle = _bundle(initial, rows[0])
    updated = apply_bundle(database, bundle, expected_revision=initial["revision"])
    assert updated["review_state"] == {"deferred": 1, "unprocessed": 2}
    assert updated["accounted_rows"] == 3 and updated["applied_bundles"] == 1
    assert lookup(database, rows[0]["occurrence_id"])["bundle"] == bundle
    with pytest.raises(CurationError, match="stale ledger revision"):
        apply_bundle(database, _bundle(initial, rows[1]), expected_revision=initial["revision"])
    assert coverage(database) == updated
    with pytest.raises(CurationError, match="already applied"):
        apply_bundle(database, bundle, expected_revision=updated["revision"])
    assert coverage(database) == updated


@pytest.mark.parametrize(
    "mutation", ["stale_input", "unknown", "membership", "unsupported_approval"]
)
def test_bad_bundle_cannot_change_current_decisions(occurrence_export, tmp_path, mutation):
    directory, _, rows = occurrence_export
    database = tmp_path / "ledger.sqlite"
    initial = ingest_export(directory, database)
    bundle = _bundle(initial, rows[0])
    if mutation == "stale_input":
        bundle["input_sha256"] = "0" * 64
    elif mutation == "unknown":
        identifier = "urn:kg-microbe:occurrence:v1:" + "0" * 64
        bundle["occurrence_ids"] = [identifier]
        bundle["decisions"][0]["occurrence_id"] = identifier
    elif mutation == "membership":
        bundle["occurrence_ids"].append(rows[1]["occurrence_id"])
    else:
        bundle["decisions"][0]["disposition"] = "retain"
    with pytest.raises(CurationError):
        apply_bundle(database, bundle, expected_revision=initial["revision"])
    assert coverage(database) == initial


def test_existing_ledger_is_never_overwritten(occurrence_export, tmp_path):
    directory, _, _ = occurrence_export
    database = tmp_path / "ledger.sqlite"
    ingest_export(directory, database)
    original = database.read_bytes()
    with pytest.raises(CurationError, match="replace"):
        ingest_export(directory, database)
    assert database.read_bytes() == original


def test_cli_roundtrip_and_unknown_lookup(occurrence_export, tmp_path, capsys):
    directory, _, rows = occurrence_export
    database = tmp_path / "ledger.sqlite"
    assert main(["init", "--export", str(directory), "--database", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["accounted_rows"] == 3
    assert (
        main(["show", "--database", str(database), "--occurrence", rows[0]["occurrence_id"]]) == 0
    )
    assert json.loads(capsys.readouterr().out)["review_state"] == "unprocessed"
    assert main(["show", "--database", str(database), "--occurrence", "missing"]) == 2
    assert "unknown" in capsys.readouterr().err
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_status_and_apply_do_not_scan_the_corpus(occurrence_export, tmp_path, monkeypatch):
    """CLAW #757: bounded operations must not add whole-corpus aggregate queries."""
    directory, _, rows = occurrence_export
    database = tmp_path / "ledger.sqlite"
    initial = ingest_export(directory, database)
    statements = []
    original = ledger_module._connect

    def traced(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(ledger_module, "_connect", traced)
    assert coverage(database) == initial
    apply_bundle(database, _bundle(initial, rows[0]), expected_revision=initial["revision"])
    assert not any("GROUP BY" in statement or "COUNT(*)" in statement for statement in statements)
    assert audit(database)["reconciled"] is True


def test_explicit_audit_detects_balanced_counter_drift(occurrence_export, tmp_path):
    directory, _, _ = occurrence_export
    database = tmp_path / "ledger.sqlite"
    ingest_export(directory, database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE coverage_counts SET count=2 WHERE dimension='review_state'")
        connection.execute("INSERT INTO coverage_counts VALUES ('review_state','deferred',1)")
    with pytest.raises(CurationError, match="counter drift"):
        audit(database)


def test_coverage_keeps_one_snapshot_during_concurrent_write(
    occurrence_export, tmp_path, monkeypatch
):
    """CLAW #758: no revision-A report may contain revision-B dimensions."""
    directory, _, rows = occurrence_export
    database = tmp_path / "ledger.sqlite"
    initial = ingest_export(directory, database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    original = ledger_module._connect
    fired = False

    def traced(*args, **kwargs):
        connection = original(*args, **kwargs)

        def interleave(statement):
            nonlocal fired
            if statement.startswith("SELECT dimension") and not fired:
                fired = True
                with ThreadPoolExecutor(max_workers=1) as workers:
                    workers.submit(
                        apply_bundle,
                        database,
                        _bundle(initial, rows[0]),
                        expected_revision=initial["revision"],
                    ).result(timeout=10)

        connection.set_trace_callback(interleave)
        return connection

    monkeypatch.setattr(ledger_module, "_connect", traced)
    assert coverage(database) == initial
    assert fired
    assert coverage(database)["review_state"] == {"deferred": 1, "unprocessed": 2}


def test_fifo_manifest_is_rejected_promptly(tmp_path):
    """CLAW #759: a nonregular input must not block while opening it."""
    directory = tmp_path / "export"
    directory.mkdir()
    os.mkfifo(directory / "manifest.json")
    database = tmp_path / "ledger.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kg_microbe_curation",
            "init",
            "--export",
            str(directory),
            "--database",
            str(database),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2 and "regular file" in result.stderr
    assert not database.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "empty_auxiliary",
        "source_list",
        "selection_list",
        "boolean_version",
        "boolean_count",
        "verified_boolean_count",
        "invalid_digest",
        "extra_verified_member",
    ],
)
def test_malformed_manifest_is_rejected_before_admission(occurrence_export, tmp_path, mutation):
    """CLAW #760: every member descriptor and container has a strict shape."""
    directory, manifest, _ = occurrence_export
    if mutation == "empty_auxiliary":
        manifest["source_manifest"]["members"]["aux.tsv"] = {}
        manifest["members"]["aux.tsv"] = {}
    elif mutation == "source_list":
        manifest["source_manifest"] = []
    elif mutation == "selection_list":
        manifest["selection"] = []
    elif mutation == "boolean_version":
        manifest["source_manifest"]["manifest_version"] = True
    elif mutation == "boolean_count":
        manifest["source_manifest"]["members"]["edges.tsv"]["rows"] = True
    elif mutation == "verified_boolean_count":
        manifest["members"]["edges.tsv"]["rows"] = True
    elif mutation == "invalid_digest":
        manifest["source_manifest"]["members"]["edges.tsv"]["sha256"] = "not-a-digest"
    else:
        manifest["members"]["aux.tsv"] = {}
    source_bytes = canonical_json(manifest["source_manifest"])
    (directory / "source-manifest.json").write_bytes(source_bytes)
    manifest["source_manifest_sha256"] = _hash(source_bytes)
    _write_manifest(directory, manifest)
    database = tmp_path / "ledger.sqlite"
    with pytest.raises(CurationError):
        ingest_export(directory, database)
    assert not database.exists()
