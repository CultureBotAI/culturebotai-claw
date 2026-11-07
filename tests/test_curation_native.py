"""Native reuse preserves exact inherited scope and cannot mint a scientific review."""

import json
from copy import deepcopy
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from kg_microbe_curation.contract import unprocessed_decision, validate_bundle
from kg_microbe_curation.identity import CONTRACT, CurationError, sha256_json
from kg_microbe_curation.native import (
    MAX_NATIVE_BYTES,
    NATIVE_CONTRACT,
    native_assertion_id,
    validate_native_assertion,
)


@pytest.fixture
def assertion():
    source = {"repository": "Example/NativeMech", "commit": "1" * 40,
              "path": "mappings/rows.tsv", "selector": {"source_position": 12}}
    review = {**source, "path": "reviews/native.json", "selector": {"decision": "row-12"}}
    original = {"subject_id": "Native:12", "predicate_id": "skos:exactMatch",
                "object_id": "CHEBI:12", "mapping_justification": "semapv:ManualMappingCuration"}
    decision = {"owner_record_sha256": "2" * 64, "status": "supported",
                "review_reason": "Native reason retained unchanged", "evidence_key": "proof-12"}
    item = {
        "contract": NATIVE_CONTRACT,
        "native_locator": {**source, "source_sha256": "3" * 64,
                           "payload_sha256": sha256_json(original)},
        "payload": {"subject": "Native:12", "predicate": "skos:exactMatch", "object": "CHEBI:12",
                    "context": {"scope": "native_mapping_payload_only", "withheld_is_global_ban": False},
                    "interpretation": {"normalization_contract": "native-exact-lexical/v1",
                                       "normalizer_contract_sha256": "4" * 64,
                                       "schema_sha256": "5" * 64, "prefix_map_sha256": "6" * 64},
                    "native_payload": original},
        "evidence": [
            {"evidence_id": "source", "locator": source, "sha256": "3" * 64, "ancestry": []},
            {"evidence_id": "review", "locator": review, "sha256": "7" * 64,
             "ancestry": ["source"], "payload": {"selected_proof": "preserved"}},
        ],
        "native_review": {"status": "supported", "locator": review, "sha256": "7" * 64,
                          "payload": decision, "payload_sha256": sha256_json(decision),
                          "rationale": "The adapter inherits the pinned native decision."},
        "assurance": "inherited_native_review",
        "limitations": ["No independent review of any KG occurrence or causal claim."],
        "independent_scientific_review": False,
    }
    item["assertion_id"] = native_assertion_id(item)
    return item


def rebind(assertion):
    assertion["assertion_id"] = native_assertion_id(assertion)


def test_supported_envelope_preserves_original_payload_and_review(assertion):
    before = deepcopy(assertion)
    validate_native_assertion(assertion)
    assert assertion == before


def test_packaged_schema_is_independently_usable(assertion):
    package = files("kg_microbe_curation")
    schema = json.loads(package.joinpath("schema/native_assertion.json").read_text())
    bundle = json.loads(package.joinpath("schema/bundle.json").read_text())
    assert schema["$defs"]["interpretation"] == bundle["$defs"]["interpretation"]
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(assertion)


@pytest.mark.parametrize("mutation", [
    lambda a: a["payload"]["context"].update(scope="whole_record"),
    lambda a: a["payload"]["native_payload"].update(object_id="CHEBI:13"),
    lambda a: a["evidence"][0].update(sha256="8" * 64),
    lambda a: a["native_review"].update(rationale="Changed interpretation"),
    lambda a: a["limitations"].append("Additional restriction"),
])
def test_identity_binds_every_inherited_dimension(assertion, mutation):
    mutation(assertion)
    with pytest.raises(CurationError, match="identity mismatch"):
        validate_native_assertion(assertion)


@pytest.mark.parametrize("mutation, message", [
    (lambda a: a["native_locator"].update(payload_sha256="8" * 64), "Native payload binding"),
    (lambda a: a["native_review"]["payload"].update(status="withheld"), "review payload binding"),
    (lambda a: a.update(assurance="unassessed"), "contradicts"),
    (lambda a: a["payload"].update(object=None), "explicit target"),
    (lambda a: a["native_review"].update(locator=None), "present together"),
    (lambda a: a["native_review"].update(locator=None, sha256=None), "exact native review"),
    (lambda a: a["evidence"].pop(0), "source file is absent"),
    (lambda a: a["evidence"].pop(1), "review file is absent"),
    (lambda a: a["evidence"][1].update(evidence_id="source"), "Duplicate native evidence"),
    (lambda a: a["native_locator"].update(path="../rows.tsv"), "traversal"),
    (lambda a: a.update(independent_scientific_review=True), "Invalid native assertion"),
    (lambda a: a.update(limitations=[]), "Invalid native assertion"),
    (lambda a: a["native_locator"].update(commit="main"), "Invalid native assertion"),
    (lambda a: a["native_review"].update(reviewer="invented"), "Invalid native assertion"),
])
def test_rebinding_does_not_hide_transport_errors(assertion, mutation, message):
    mutation(assertion)
    rebind(assertion)
    with pytest.raises(CurationError, match=message):
        validate_native_assertion(assertion)


def test_conflicting_file_digests_fail_even_for_different_selectors(assertion):
    duplicate = deepcopy(assertion["evidence"][0])
    duplicate.update(evidence_id="another-source", sha256="9" * 64)
    duplicate["locator"]["selector"] = {"source_position": 13}
    assertion["evidence"].append(duplicate)
    rebind(assertion)
    with pytest.raises(CurationError, match="Conflicting native evidence file digests"):
        validate_native_assertion(assertion)


def test_withheld_null_target_keeps_native_review_and_scope(assertion):
    assertion["native_review"]["status"] = "withheld"
    assertion["native_review"]["payload"]["status"] = "withheld"
    assertion["native_review"]["payload_sha256"] = sha256_json(assertion["native_review"]["payload"])
    assertion["payload"]["object"] = None
    assertion["assurance"] = "native_withheld_decision"
    rebind(assertion)
    validate_native_assertion(assertion)
    assert assertion["payload"]["context"]["withheld_is_global_ban"] is False


def test_unassessed_payload_can_exist_without_native_review(assertion):
    assertion["native_review"].update(status="unassessed", locator=None, sha256=None,
                                      payload={}, payload_sha256=sha256_json({}))
    assertion["assurance"] = "unassessed"
    assertion["evidence"].pop(1)
    rebind(assertion)
    validate_native_assertion(assertion)


def test_native_envelope_cannot_stand_in_for_canonical_scientific_review(assertion):
    occurrence = "urn:kg-microbe:occurrence:v1:" + "a" * 64
    bundle = {
        "contract": CONTRACT, "input_sha256": "b" * 64, "occurrence_ids": [occurrence],
        "decisions": [unprocessed_decision(occurrence)], "observations": [], "claims": [],
        "reviews": [{"review_id": assertion["assertion_id"], "sha256": sha256_json(assertion),
                     "document": assertion}],
    }
    with pytest.raises(CurationError):
        validate_bundle(bundle)


def test_oversized_native_transport_fails_before_identity_validation(assertion):
    assertion["payload"]["context"]["large_native_context"] = "x" * MAX_NATIVE_BYTES
    with pytest.raises(CurationError, match="16 MiB byte limit"):
        validate_native_assertion(assertion)
