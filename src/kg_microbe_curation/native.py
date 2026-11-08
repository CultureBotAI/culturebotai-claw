"""Pinned native-assertion transport; inherited review is never a new review."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from .artifact import validate_relative_path
from .identity import CurationError, canonical_json, content_id, sha256_json

NATIVE_CONTRACT = "kg-microbe-native-assertion/v1"
MAX_NATIVE_BYTES = 16 * 1024 * 1024


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    package = files("kg_microbe_curation")
    schema = json.loads(package.joinpath("schema/native_assertion.json").read_text())
    # Keep the standalone schema usable while failing closed on semantic drift.
    bundle_schema = json.loads(package.joinpath("schema/bundle.json").read_text())
    if schema["$defs"]["interpretation"] != bundle_schema["$defs"]["interpretation"]:
        raise CurationError("Native interpretation schema diverged from the canonical contract")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def native_assertion_id(assertion: dict[str, Any]) -> str:
    """Bind the entire native transport, including evidence and inherited scope."""
    if type(assertion) is not dict:
        raise CurationError("Native assertion must be an object")
    return content_id("native-assertion", {
        key: value for key, value in assertion.items() if key != "assertion_id"
    })


def _file_key(locator: dict[str, Any]) -> tuple[str, str, str]:
    validate_relative_path(locator["path"])
    # GitHub owner/repository names are case-insensitive. Preserve the original
    # envelope and exact Git path; only the internal file lookup is normalized.
    return locator["repository"].casefold(), locator["commit"], locator["path"]


def validate_native_assertion(assertion: dict[str, Any]) -> None:
    """Validate exact transport bindings without reading or approving native data.

    Adapters must verify native bytes and scientific eligibility separately.
    Successful validation never grants retain/amend authority to a curation
    decision: the existing scientific RecordReview gate is unchanged.
    """
    if len(canonical_json(assertion)) > MAX_NATIVE_BYTES:
        raise CurationError("Native assertion exceeds the 16 MiB byte limit")
    errors = sorted(_validator().iter_errors(assertion), key=lambda item: str(list(item.path)))
    if errors:
        raise CurationError("Invalid native assertion: " + "; ".join(
            f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}"
            for error in errors[:10]
        ))
    if native_assertion_id(assertion) != assertion["assertion_id"]:
        raise CurationError("Native assertion identity mismatch")
    locator = assertion["native_locator"]
    if sha256_json(assertion["payload"]["native_payload"]) != locator["payload_sha256"]:
        raise CurationError("Native payload binding mismatch")
    review = assertion["native_review"]
    if sha256_json(review["payload"]) != review["payload_sha256"]:
        raise CurationError("Native review payload binding mismatch")
    statuses = {
        "supported": "inherited_native_review",
        "withheld": "native_withheld_decision",
        "unassessed": "unassessed",
    }
    if assertion["assurance"] != statuses[review["status"]]:
        raise CurationError("Inherited assurance contradicts the native review state")
    if review["status"] == "supported" and assertion["payload"]["object"] is None:
        raise CurationError("Supported assertions require an explicit target")
    if (review["locator"] is None) != (review["sha256"] is None):
        raise CurationError("Review locator and document digest must be present together")
    if review["status"] != "unassessed" and review["locator"] is None:
        raise CurationError("Inherited decisions require exact native review provenance")
    evidence_ids: set[str] = set()
    files_by_key: dict[tuple[str, str, str], str] = {}
    for evidence in assertion["evidence"]:
        if evidence["evidence_id"] in evidence_ids:
            raise CurationError("Duplicate native evidence identifier")
        evidence_ids.add(evidence["evidence_id"])
        key = _file_key(evidence["locator"])
        if key in files_by_key and files_by_key[key] != evidence["sha256"]:
            raise CurationError("Conflicting native evidence file digests")
        files_by_key[key] = evidence["sha256"]
    if files_by_key.get(_file_key(locator)) != locator["source_sha256"]:
        raise CurationError("Native source file is absent from the evidence closure")
    if review["locator"] is not None:
        if files_by_key.get(_file_key(review["locator"])) != review["sha256"]:
            raise CurationError("Native review file is absent from the evidence closure")
