"""Validate bounded edge-curation bundles without granting scientific authority.

Complete membership is checked against explicit identifiers, never just counts.
Observation and claim payloads bind their named normalization contract, schema
and prefix-map pins as well as biological context. Native identities stay separate.
Native RecordReview documents remain the review authority for shape and scope;
their source authenticity and scientific conclusions are not certified here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from kg_microbe_reviews import ReviewError, validate_review

from .identity import (
    CurationError,
    canonical_json,
    content_id,
    context_id,
    occurrence_id,
    sha256_json,
)

MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_OCCURRENCES = 10_000
MAX_BUNDLE_REFERENCES = 50_000


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise CurationError(f"Nonfinite JSON value: {value}")


def load_bundle(path: str | Path) -> dict[str, Any]:
    """Read strict JSON and validate its internal contract, without ledger access."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_BUNDLE_BYTES + 1)
        if len(raw) > MAX_BUNDLE_BYTES:
            raise CurationError("Curation bundle exceeds the 16 MiB byte limit")
        bundle = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_nonfinite,
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise CurationError(f"Cannot read curation bundle: {exc}") from exc
    validate_bundle(bundle)
    return bundle


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(
        files("kg_microbe_curation").joinpath("schema/bundle.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _index(items: list[dict], field: str, label: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in items:
        identifier = item[field]
        if identifier in result:
            raise CurationError(f"Duplicate {label}: {identifier}")
        result[identifier] = item
    return result


def unprocessed_decision(identifier: str) -> dict[str, Any]:
    """Explicit withholding state; no assessment or scientific support is invented."""
    return {
        "occurrence_id": identifier,
        "lifecycle": "active",
        "review_state": "unprocessed",
        "conflict_state": "not_assessed",
        "disposition": "withheld",
        "claim_ids": [],
        "observation_id": None,
        "review_ids": [],
        "rationale": "Not assessed.",
    }


def decision_digest(decision: dict[str, Any]) -> str:
    """Bind proposed decision bytes without its circular review references."""
    return sha256_json({key: value for key, value in decision.items() if key != "review_ids"})


def claim_digest(claim: dict[str, Any], observations: dict[str, dict]) -> str:
    """Bind claim membership and complete observation/native-identity envelopes."""
    return sha256_json(
        {
            "claim": claim,
            "observations": [observations[key] for key in sorted(claim["observation_ids"])],
        }
    )


def validate_occurrence(record: dict[str, Any]) -> None:
    """Check the producer's exact row envelope, not the release file on disk."""
    required = {
        "occurrence_id",
        "manifest_sha256",
        "member",
        "member_sha256",
        "row_number",
        "row_sha256",
        "source_row",
    }
    if type(record) is not dict or set(record) != required:
        raise CurationError("Occurrence must contain exactly the declared envelope fields")
    if not isinstance(record["source_row"], str) or not record["source_row"]:
        raise CurationError("source_row must be nonempty UTF-8 text")
    try:
        raw = record["source_row"].encode("utf-8")
    except UnicodeError as exc:
        raise CurationError("source_row is not UTF-8 encodable") from exc
    if hashlib.sha256(raw).hexdigest() != record["row_sha256"]:
        raise CurationError("source_row checksum mismatch")
    payload = {key: record[key] for key in required - {"occurrence_id", "source_row"}}
    if occurrence_id(**payload) != record["occurrence_id"]:
        raise CurationError("Occurrence identity mismatch")


def _validate_reviews(bundle: dict, reviews: dict[str, dict]) -> None:
    for identifier, reference in reviews.items():
        document = reference["document"]
        if sha256_json(document) != reference["sha256"]:
            raise CurationError(f"Review digest mismatch: {identifier}")
        try:
            validate_review(document)
        except ReviewError as exc:
            raise CurationError(f"Invalid canonical RecordReview {identifier}: {exc}") from exc
        if identifier != document["review_id"]:
            raise CurationError(f"Review identifier mismatch: {identifier}")
        if bundle["input_sha256"] not in {item["sha256"] for item in document["source"]["inputs"]}:
            raise CurationError(f"Review is stale or unbound to this input: {identifier}")


def _decision_checks(
    decision: dict,
    observations: dict[str, dict],
    claims: dict[str, dict],
    reviews: dict[str, dict],
) -> None:
    identifier = decision["occurrence_id"]
    observation = decision["observation_id"]
    if observation is not None and observation not in observations:
        raise CurationError(f"Unknown observation for {identifier}")
    if set(decision["claim_ids"]) - claims.keys():
        raise CurationError(f"Unknown claim for {identifier}")
    if set(decision["review_ids"]) - reviews.keys():
        raise CurationError(f"Unknown review for {identifier}")
    for claim_id in decision["claim_ids"]:
        if observation not in claims[claim_id]["observation_ids"]:
            raise CurationError(f"Claim does not include this occurrence's observation: {claim_id}")
    state = decision["review_state"]
    disposition = decision["disposition"]
    if state != "reviewed" and disposition != "withheld":
        raise CurationError("Unreviewed decisions must remain withheld")
    if state == "unprocessed" and (
        decision["review_ids"] or decision["conflict_state"] != "not_assessed"
    ):
        raise CurationError("Unprocessed decisions cannot assert completed assessment")
    if state == "reviewed":
        if not decision["review_ids"]:
            raise CurationError("Reviewed decisions require canonical review evidence")
        required_targets = {identifier, *decision["claim_ids"]}
        covered: set[str] = set()
        for review_id in decision["review_ids"]:
            document = reviews[review_id]["document"]
            assessed = set(document["scope"]["reviewed_target_ids"])
            for target in document["targets"]:
                target_id = target["target_id"]
                if target_id not in required_targets or target_id not in assessed:
                    continue
                if target_id == identifier:
                    algorithm = "kg-microbe-curation-decision/v1"
                    expected = decision_digest(decision)
                else:
                    algorithm = "kg-microbe-curation-claim/v1"
                    expected = claim_digest(claims[target_id], observations)
                semantic = target.get("semantic_digest", {})
                if semantic.get("algorithm") != algorithm or semantic.get("sha256") != expected:
                    raise CurationError("Review semantic digest is stale for the decision or claim")
                covered.add(target_id)
        if required_targets - covered:
            raise CurationError("Review scope does not cover the exact occurrence and claims")
    if disposition in {"retain", "amend"}:
        if decision["lifecycle"] != "active":
            raise CurationError("Inactive occurrences cannot be retained or amended")
        if decision["conflict_state"] not in {"none_reported", "resolved"}:
            raise CurationError("Unassessed or unresolved conflicts must remain withheld")
        if not decision["claim_ids"]:
            raise CurationError("Retention or amendment requires an explicit scoped claim")
        scientific_targets: set[str] = set()
        for review_id in decision["review_ids"]:
            document = reviews[review_id]["document"]
            if (
                document["scientific_review"]
                and document["completion"] == "completed"
                and document["verdict"] in {"pass", "pass_with_limitations"}
            ):
                scientific_targets.update(document["scope"]["reviewed_target_ids"])
        if {identifier, *decision["claim_ids"]} - scientific_targets:
            raise CurationError(
                "Retention or amendment requires explicit scientific review of scope"
            )


def validate_bundle(
    bundle: dict[str, Any],
    *,
    expected_input_sha256: str | None = None,
    expected_occurrence_ids: Iterable[str] | None = None,
) -> None:
    """Validate shape, exact membership, fingerprints and review/input binding.

    External expected values must come from the verified ledger/selection. This
    function does not authenticate source documents, authorize writes, verify
    native observation normalization, or infer truth from a review verdict.
    """
    if type(bundle) is dict:
        for field in ("occurrence_ids", "decisions", "observations", "claims", "reviews"):
            limit = (
                MAX_BUNDLE_OCCURRENCES
                if field in {"occurrence_ids", "decisions"}
                else MAX_BUNDLE_REFERENCES
            )
            if isinstance(bundle.get(field), list) and len(bundle[field]) > limit:
                raise CurationError(f"{field} exceeds the bounded batch limit of {limit}")
    if len(canonical_json(bundle)) > MAX_BUNDLE_BYTES:
        raise CurationError("Curation bundle exceeds the 16 MiB byte limit")
    errors = sorted(_validator().iter_errors(bundle), key=lambda error: str(list(error.path)))
    if errors:
        raise CurationError(
            "; ".join(
                f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}"
                for error in errors[:10]
            )
        )
    if expected_input_sha256 is not None and bundle["input_sha256"] != expected_input_sha256:
        raise CurationError("Stale input: export manifest checksum differs")
    selected = set(bundle["occurrence_ids"])
    if expected_occurrence_ids is not None:
        expected = list(expected_occurrence_ids)
        if len(expected) != len(set(expected)):
            raise CurationError("Expected occurrence selection contains duplicates")
        if selected != set(expected):
            raise CurationError("Selected occurrence membership differs from the expected set")
    decisions = _index(bundle["decisions"], "occurrence_id", "occurrence decision")
    if set(decisions) != selected:
        raise CurationError("Decisions must cover every selected occurrence exactly once")
    observations = _index(bundle["observations"], "observation_id", "observation")
    claims = _index(bundle["claims"], "claim_id", "claim")
    reviews = _index(bundle["reviews"], "review_id", "review")
    for kind, records in (("observation", observations), ("claim", claims)):
        for identifier, record in records.items():
            if content_id(kind, record["payload"]) != identifier:
                raise CurationError(f"{kind} payload fingerprint mismatch")
            if context_id(record["payload"]["context"]) != record["context_id"]:
                raise CurationError(f"{kind} context fingerprint mismatch")
    for claim in claims.values():
        if set(claim["observation_ids"]) - observations.keys():
            raise CurationError("Claim references an unknown observation")
    _validate_reviews(bundle, reviews)
    for decision in decisions.values():
        _decision_checks(decision, observations, claims, reviews)
    used_observations = {
        decision["observation_id"]
        for decision in decisions.values()
        if decision["observation_id"] is not None
    }
    if observations.keys() != used_observations:
        raise CurationError("Bundle contains observations outside selected occurrence membership")
    used_claims = {
        identifier for decision in decisions.values() for identifier in decision["claim_ids"]
    }
    if claims.keys() != used_claims:
        raise CurationError("Bundle contains claims outside selected occurrence membership")
    declared_membership = {
        (observation, identifier)
        for identifier, claim in claims.items()
        for observation in claim["observation_ids"]
    }
    decision_membership = {
        (decision["observation_id"], claim)
        for decision in decisions.values()
        for claim in decision["claim_ids"]
    }
    if declared_membership != decision_membership:
        raise CurationError("Claim observation membership is not fully represented by decisions")
    used_reviews = {
        identifier for decision in decisions.values() for identifier in decision["review_ids"]
    }
    if reviews.keys() != used_reviews:
        raise CurationError("Bundle contains reviews outside selected decision membership")
