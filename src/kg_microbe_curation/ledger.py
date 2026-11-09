"""Stream verified occurrence exports into an external, transactional SQLite index.

The index is an initial local backend, not the authoritative evidence archive.
Input shards remain immutable. Full decision bundles are retained append-only;
one current-state view prevents coverage counts from multiplying with reviews.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from .contract import unprocessed_decision, validate_bundle, validate_occurrence
from .identity import CONTRACT, CurationError, canonical_json

LEDGER_FORMAT = "kg-microbe-curation-ledger/v1"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_OCCURRENCE_BYTES = 32 * 1024 * 1024
_FIELDS = ("lifecycle", "review_state", "conflict_state", "disposition")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode(data: bytes) -> Any:
    try:
        value = json.loads(data, object_pairs_hook=_unique_object)
        canonical_json(value)
        return value
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CurationError(f"invalid JSON: {exc}") from exc


def _open_regular(path: Path) -> BinaryIO:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise CurationError(f"cannot open regular input: {path.name}") from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise CurationError(f"input must be a regular file: {path.name}")
    return os.fdopen(descriptor, "rb")


def _read_json(path: Path) -> tuple[bytes, Any]:
    with _open_regular(path) as handle:
        data = handle.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise CurationError("JSON document exceeds the size bound")
    return data, _decode(data)


def _basename(value: Any) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise CurationError("artifact path must be one basename")
    if value in {".", ".."} or "\\" in value or "\x00" in value:
        raise CurationError("unsafe artifact basename")
    return value


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CurationError(f"{field} must be an integer >= {minimum}")
    return value


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise CurationError("ledger must be an existing regular file")
    connection = sqlite3.connect(
        path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
        uri=True,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        if _metadata(connection).get("format") != LEDGER_FORMAT:
            raise CurationError("unsupported ledger format")
    except Exception:
        connection.close()
        raise
    return connection


def _metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        row[0]: json.loads(row[1]) for row in connection.execute("SELECT key,value FROM metadata")
    }


def _set_metadata(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)",
        (key, canonical_json(value).decode()),
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE occurrences(
            occurrence_id TEXT PRIMARY KEY,
            member TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            row_sha256 TEXT NOT NULL,
            source_row TEXT NOT NULL,
            UNIQUE(member,row_number)
        );
        CREATE TABLE bundles(
            bundle_sha256 TEXT PRIMARY KEY,
            parent_revision TEXT NOT NULL,
            revision TEXT NOT NULL UNIQUE,
            document TEXT NOT NULL
        );
        CREATE TABLE current_decisions(
            occurrence_id TEXT PRIMARY KEY REFERENCES occurrences(occurrence_id),
            lifecycle TEXT NOT NULL,
            review_state TEXT NOT NULL,
            conflict_state TEXT NOT NULL,
            disposition TEXT NOT NULL,
            bundle_sha256 TEXT REFERENCES bundles(bundle_sha256)
        );
        CREATE TABLE coverage_counts(
            dimension TEXT NOT NULL,
            value TEXT NOT NULL,
            count INTEGER NOT NULL CHECK(count >= 0),
            PRIMARY KEY(dimension,value)
        );
    """)


def _rows(handle: BinaryIO) -> Iterator[bytes]:
    while line := handle.readline(MAX_OCCURRENCE_BYTES + 1):
        if len(line) > MAX_OCCURRENCE_BYTES:
            raise CurationError("occurrence line exceeds the size bound")
        yield line


def ingest_export(export_directory: Path, database: Path) -> dict[str, Any]:
    """Verify every exported shard and atomically create a new ledger file."""
    export_directory = export_directory.resolve(strict=True)
    database = database.absolute()
    if database.exists() or database.is_symlink():
        raise CurationError("refusing to replace an existing ledger")
    if database.resolve().is_relative_to(export_directory):
        raise CurationError("ledger output must be outside the immutable export")
    manifest_bytes, manifest = _read_json(export_directory / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("contract") != CONTRACT:
        raise CurationError("unsupported occurrence export contract")
    if type(manifest.get("format_version")) is not int or manifest["format_version"] != 1:
        raise CurationError("unsupported occurrence export version")
    if manifest.get("format") != "edge-occurrence-export":
        raise CurationError("input must be an occurrence export")
    if manifest.get("source_manifest_file") != "source-manifest.json":
        raise CurationError("unexpected source manifest filename")
    source_bytes, source = _read_json(export_directory / "source-manifest.json")
    if _hash(source_bytes) != manifest.get("source_manifest_sha256"):
        raise CurationError("source manifest does not match its digest")
    if source != manifest.get("source_manifest"):
        raise CurationError("source manifest bytes and parsed declaration disagree")
    if not isinstance(source, dict):
        raise CurationError("source manifest must be an object")
    if type(source.get("manifest_version")) is not int or source["manifest_version"] != 1:
        raise CurationError("unsupported source manifest version")
    source_members = source.get("members")
    verified_members = manifest.get("members")
    if not isinstance(source_members, dict) or not source_members:
        raise CurationError("source manifest must declare nonempty members")
    if not isinstance(verified_members, dict) or set(verified_members) != set(source_members):
        raise CurationError("verified member set differs from the source manifest")
    for name, original in source_members.items():
        _basename(name)
        verified = verified_members[name]
        if not isinstance(original, dict) or set(original) != {"sha256", "bytes", "rows"}:
            raise CurationError("invalid source member descriptor")
        if not isinstance(original["sha256"], str) or not re.fullmatch(
            "[0-9a-f]{64}", original["sha256"]
        ):
            raise CurationError("invalid source member digest")
        _integer(original["bytes"], "source member bytes")
        _integer(original["rows"], "source member rows")
        if not isinstance(verified, dict) or any(
            type(original[key]) is not type(verified.get(key)) or original[key] != verified.get(key)
            for key in original
        ):
            raise CurationError("producer verification disagrees with source member")
    selection = manifest.get("selection", {})
    if not isinstance(selection, dict):
        raise CurationError("export selection must be an object")
    if manifest.get("input_complete") is not True:
        raise CurationError("producer must have verified every input member")
    member = _basename(selection.get("edge_member"))
    try:
        source_member = source["members"][member]
        declared_member = manifest["members"][member]
        header = declared_member["header"]
    except (KeyError, TypeError) as exc:
        raise CurationError("missing edge member declaration") from exc
    if (
        not isinstance(header, list)
        or not all(isinstance(item, str) and item for item in header)
        or len(header) != len(set(header))
        or not {"subject", "predicate", "object"}.issubset(header)
    ):
        raise CurationError("invalid edge header")
    header_row = declared_member.get("header_row")
    if (
        not isinstance(header_row, str)
        or header_row.removesuffix("\n").removesuffix("\r").split("\t") != header
    ):
        raise CurationError("header text disagrees with declared columns")
    total = _integer(source_member["rows"], "source rows")
    selected = _integer(selection.get("exported_rows"), "exported rows")
    if selected > total:
        raise CurationError("exported count exceeds source count")
    limit = _integer(selection.get("max_rows"), "selection max_rows")
    if selected != (min(limit, total) if limit else total):
        raise CurationError("exported count differs from the declared selection")
    complete = selected == total
    if selection.get("complete_export") is not complete:
        raise CurationError("export completeness declaration is inconsistent")
    shards = manifest.get("shards")
    if not isinstance(shards, list):
        raise CurationError("shards must be a list")
    names = [_basename(shard.get("file")) for shard in shards if isinstance(shard, dict)]
    if len(names) != len(shards) or len(set(names)) != len(names):
        raise CurationError("invalid or duplicate shard descriptors")
    if set(names) & {"manifest.json", "source-manifest.json"}:
        raise CurationError("shard path collides with a manifest")
    database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{database.name}.", dir=database.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    connection = sqlite3.connect(staging)
    try:
        _create_schema(connection)
        row_count = 0
        member_digest = hashlib.sha256(header_row.encode("utf-8"))
        member_bytes = len(header_row.encode("utf-8"))
        for shard in shards:
            digest = hashlib.sha256()
            byte_count = 0
            shard_rows = 0
            first_row = row_count + 1
            with _open_regular(export_directory / shard["file"]) as handle:
                before = os.fstat(handle.fileno())
                for line in _rows(handle):
                    digest.update(line)
                    byte_count += len(line)
                    occurrence = _decode(line)
                    validate_occurrence(occurrence)
                    row_count += 1
                    shard_rows += 1
                    if (
                        occurrence["manifest_sha256"] != manifest["source_manifest_sha256"]
                        or occurrence["member"] != member
                        or occurrence["member_sha256"] != source_member["sha256"]
                        or occurrence["row_number"] != row_count
                        or row_count > selected
                    ):
                        raise CurationError("occurrence does not match the selected source rows")
                    raw = occurrence["source_row"]
                    body = raw.removesuffix("\n").removesuffix("\r")
                    if "\n" in body:
                        raise CurationError(
                            "source occurrence must contain exactly one physical row"
                        )
                    values = body.split("\t")
                    if len(values) != len(header):
                        raise CurationError("source row width differs from header")
                    member_digest.update(raw.encode("utf-8"))
                    member_bytes += len(raw.encode("utf-8"))
                    connection.execute(
                        "INSERT INTO occurrences VALUES (?,?,?,?,?)",
                        (
                            occurrence["occurrence_id"],
                            member,
                            row_count,
                            occurrence["row_sha256"],
                            raw,
                        ),
                    )
                    decision = unprocessed_decision(occurrence["occurrence_id"])
                    connection.execute(
                        "INSERT INTO current_decisions VALUES (?,?,?,?,?,NULL)",
                        (occurrence["occurrence_id"], *(decision[key] for key in _FIELDS)),
                    )
                after = os.fstat(handle.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise CurationError("export shard changed while reading")
            if (
                digest.hexdigest() != shard.get("sha256")
                or byte_count != _integer(shard.get("bytes"), "shard bytes")
                or shard_rows != _integer(shard.get("rows"), "shard rows", 1)
                or _integer(shard.get("first_row"), "first row", 1) != first_row
                or _integer(shard.get("last_row"), "last row", 1) != row_count
            ):
                raise CurationError("shard digest, size or row coverage does not match")
        if row_count != selected:
            raise CurationError("export does not cover the declared selected row count")
        if complete and (
            member_digest.hexdigest() != source_member["sha256"]
            or member_bytes != source_member["bytes"]
        ):
            raise CurationError("complete occurrence export does not reconstruct the source member")
        if _read_json(export_directory / "manifest.json")[0] != manifest_bytes:
            raise CurationError("export manifest changed while reading")
        if _read_json(export_directory / "source-manifest.json")[0] != source_bytes:
            raise CurationError("source manifest changed while reading")
        input_sha = _hash(manifest_bytes)
        metadata = {
            "format": LEDGER_FORMAT,
            "input_sha256": input_sha,
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "edge_member": member,
            "header": header,
            "source_rows": total,
            "selected_rows": row_count,
            "complete_export": complete,
            "source_verification": "producer_attested; exported_shards_verified_locally",
            "applied_bundles": 0,
            "revision": _hash(canonical_json({"format": LEDGER_FORMAT, "input_sha256": input_sha})),
        }
        for key, value in metadata.items():
            _set_metadata(connection, key, value)
        if row_count:
            defaults = unprocessed_decision("")
            connection.executemany(
                "INSERT INTO coverage_counts VALUES (?,?,?)",
                ((field, defaults[field], row_count) for field in _FIELDS),
            )
        connection.commit()
        connection.close()
        with staging.open("rb") as handle:
            os.fsync(handle.fileno())
        os.link(staging, database)  # Atomic publication fails if another writer won.
    except (sqlite3.Error, KeyError, TypeError, OSError) as exc:
        raise CurationError(f"could not create ledger: {exc}") from exc
    finally:
        connection.close()
        staging.unlink(missing_ok=True)
    return coverage(database)


def _coverage(connection: sqlite3.Connection) -> dict[str, Any]:
    result = _metadata(connection)
    for field in _FIELDS:
        result[field] = {}
    for field, value, count in connection.execute(
        "SELECT dimension,value,count FROM coverage_counts"
    ):
        if field not in _FIELDS or count <= 0:
            raise CurationError("invalid coverage counter")
        result[field][value] = count
    if any(sum(result[field].values()) != result["selected_rows"] for field in _FIELDS):
        raise CurationError("ledger counters do not reconcile")
    result["accounted_rows"] = sum(result["disposition"].values())
    result["current_decision_rows"] = result["accounted_rows"]
    result["coverage_basis"] = "transactional_counters"
    return result


def coverage(database: Path) -> dict[str, Any]:
    """Read one consistent revision using counters, without scanning occurrences."""
    connection = _connect(database, readonly=True)
    try:
        connection.execute("BEGIN")
        return _coverage(connection)
    finally:
        connection.close()


def audit(database: Path) -> dict[str, Any]:
    """Explicitly reconcile membership and counters; this operation scans the ledger."""
    connection = _connect(database, readonly=True)
    try:
        connection.execute("BEGIN")
        result = _coverage(connection)
        for table in ("occurrences", "current_decisions"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count != result["selected_rows"]:
                raise CurationError("ledger membership does not reconcile")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise CurationError("ledger contains broken references")
        for field in _FIELDS:
            actual = dict(
                connection.execute(
                    f"SELECT {field},COUNT(*) FROM current_decisions GROUP BY {field}"
                )
            )
            if actual != result[field]:
                raise CurationError("ledger counter drift detected")
        if (
            connection.execute("SELECT COUNT(*) FROM bundles").fetchone()[0]
            != result["applied_bundles"]
        ):
            raise CurationError("ledger history count does not reconcile")
        result["audit_scope"] = (
            "membership_references_and_counters; not_source_evidence_reverification"
        )
        result["reconciled"] = True
        return result
    finally:
        connection.close()


def lookup(database: Path, occurrence_id: str) -> dict[str, Any]:
    """Retrieve exact source text and the current decision with retained history."""
    connection = _connect(database, readonly=True)
    try:
        connection.execute("BEGIN")
        row = connection.execute(
            "SELECT * FROM occurrences JOIN current_decisions USING(occurrence_id) WHERE occurrence_id=?",
            (occurrence_id,),
        ).fetchone()
        if row is None:
            raise CurationError("unknown release occurrence")
        result = dict(row)
        result["header"] = _metadata(connection)["header"]
        if row["bundle_sha256"]:
            result["bundle"] = json.loads(
                connection.execute(
                    "SELECT document FROM bundles WHERE bundle_sha256=?", (row["bundle_sha256"],)
                ).fetchone()[0]
            )
        return result
    finally:
        connection.close()


def apply_bundle(
    database: Path, bundle: dict[str, Any], *, expected_revision: str
) -> dict[str, Any]:
    """Append an input-bound bundle and atomically replace only its selected states."""
    encoded = canonical_json(bundle)
    if len(encoded) > MAX_JSON_BYTES:
        raise CurationError("review bundle exceeds the size bound")
    digest = _hash(encoded)
    connection = _connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        metadata = _metadata(connection)
        if metadata["revision"] != expected_revision:
            raise CurationError("stale ledger revision; inspect current decisions before retrying")
        identifiers = bundle.get("occurrence_ids", [])
        validate_bundle(
            bundle,
            expected_input_sha256=metadata["input_sha256"],
            expected_occurrence_ids=identifiers,
        )
        for identifier in identifiers:
            if (
                connection.execute(
                    "SELECT 1 FROM occurrences WHERE occurrence_id=?", (identifier,)
                ).fetchone()
                is None
            ):
                raise CurationError("bundle targets an occurrence outside this ledger")
        if connection.execute("SELECT 1 FROM bundles WHERE bundle_sha256=?", (digest,)).fetchone():
            raise CurationError("bundle already applied; refusing to replay historical decisions")
        revision = _hash(
            canonical_json({"parent_revision": expected_revision, "bundle_sha256": digest})
        )
        connection.execute(
            "INSERT INTO bundles VALUES (?,?,?,?)",
            (digest, expected_revision, revision, encoded.decode()),
        )
        for decision in bundle["decisions"]:
            previous = connection.execute(
                "SELECT lifecycle,review_state,conflict_state,disposition FROM current_decisions WHERE occurrence_id=?",
                (decision["occurrence_id"],),
            ).fetchone()
            if previous is None:
                raise CurationError("selected occurrence has no current decision")
            for field in _FIELDS:
                if previous[field] == decision[field]:
                    continue
                removed = connection.execute(
                    "UPDATE coverage_counts SET count=count-1 WHERE dimension=? AND value=? AND count>0",
                    (field, previous[field]),
                )
                if removed.rowcount != 1:
                    raise CurationError("missing coverage counter")
                connection.execute(
                    "INSERT INTO coverage_counts VALUES (?,?,1) ON CONFLICT(dimension,value) DO UPDATE SET count=count+1",
                    (field, decision[field]),
                )
            connection.execute(
                "UPDATE current_decisions SET lifecycle=?,review_state=?,conflict_state=?,disposition=?,bundle_sha256=? WHERE occurrence_id=?",
                (*(decision[key] for key in _FIELDS), digest, decision["occurrence_id"]),
            )
        _set_metadata(connection, "revision", revision)
        _set_metadata(connection, "applied_bundles", metadata["applied_bundles"] + 1)
        connection.execute("DELETE FROM coverage_counts WHERE count=0")
        result = _coverage(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return result
