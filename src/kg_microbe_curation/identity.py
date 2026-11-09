"""Versioned content identities; no biological or native-observation normalization.

JSON object keys are sorted; scalar types, Unicode, whitespace within strings,
and array order are retained. These fingerprints do not replace a producer's
schema-dependent native observation identifier. Valid observation and claim
payloads include required interpretation pins, checked by the bundle contract;
their biological context fingerprint remains a separate identity.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

CONTRACT = "kg-microbe-curation/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_KIND = re.compile(r"[a-z][a-z0-9-]*\Z")


class CurationError(ValueError):
    """The supplied curation artifact violates the declared contract."""


def _json_value(value: Any) -> None:
    """Reject coercions that json.dumps would otherwise silently perform."""
    if value is None or type(value) in (str, bool, int, float):
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise CurationError("JSON object keys must be strings")
            _json_value(item)
        return
    raise CurationError(f"Unsupported JSON value type: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """Return exact v1 canonical UTF-8 JSON bytes, rejecting lossy/nonfinite input."""
    try:
        _json_value(value)
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise CurationError(f"Cannot encode canonical JSON: {exc}") from exc


def sha256_json(value: Any) -> str:
    """Hash canonical JSON bytes, without adding an identity envelope."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def content_id(kind: str, payload: dict[str, Any]) -> str:
    """Identify a typed v1 payload, separate from all native observation IDs."""
    if not isinstance(kind, str) or not _KIND.fullmatch(kind):
        raise CurationError("Invalid identity kind")
    if type(payload) is not dict:
        raise CurationError("Identity payload must be a JSON object")
    digest = sha256_json({"contract": CONTRACT, "kind": kind, "payload": payload})
    return f"urn:kg-microbe:{kind}:v1:{digest}"


def occurrence_id(
    *,
    manifest_sha256: str,
    member: str,
    member_sha256: str,
    row_number: int,
    row_sha256: str,
) -> str:
    """Bind one data-row occurrence to exact release and member bytes.

    ``row_number`` is one-based and excludes the header. ``row_sha256`` hashes
    the exact UTF-8 row, including its original terminator when present.
    """
    for name, value in (
        ("manifest_sha256", manifest_sha256),
        ("member_sha256", member_sha256),
        ("row_sha256", row_sha256),
    ):
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise CurationError(f"{name} must be a lowercase SHA-256 digest")
    if not isinstance(member, str) or not member.strip():
        raise CurationError("member must be nonblank")
    if type(row_number) is not int or row_number < 1:
        raise CurationError("row_number must be a positive integer")
    return content_id(
        "occurrence",
        {
            "manifest_sha256": manifest_sha256,
            "member": member,
            "member_sha256": member_sha256,
            "row_number": row_number,
            "row_sha256": row_sha256,
        },
    )


def context_id(payload: dict[str, Any]) -> str:
    """Fingerprint exact context; no taxon, condition, unit or list normalization."""
    return content_id("context", payload)
