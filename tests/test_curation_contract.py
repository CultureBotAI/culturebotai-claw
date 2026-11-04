"""Scientific status stays explicit; provenance and complete scope are enforced."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from kg_microbe_curation.contract import (
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_OCCURRENCES,
    claim_digest,
    decision_digest,
    load_bundle,
    unprocessed_decision,
    validate_bundle,
    validate_occurrence,
)
from kg_microbe_curation.identity import (
    CONTRACT,
    CurationError,
    canonical_json,
    content_id,
    context_id,
    occurrence_id,
    sha256_json,
)


def occurrence(row_number=1, source_row="NCBITaxon:1\tbiolink:related_to\tCHEBI:1\n"):
    item = {
        "manifest_sha256": "a" * 64, "member": "merged-kg_edges.tsv",
        "member_sha256": "b" * 64, "row_number": row_number,
        "row_sha256": hashlib.sha256(source_row.encode()).hexdigest(),
    }
    return {**item, "source_row": source_row, "occurrence_id": occurrence_id(**item)}


@pytest.fixture
def bundle():
    identifiers = [occurrence(i)["occurrence_id"] for i in (1, 2)]
    return {
        "contract": CONTRACT, "input_sha256": "c" * 64, "occurrence_ids": identifiers,
        "decisions": [unprocessed_decision(value) for value in identifiers],
        "observations": [], "claims": [], "reviews": [],
    }


def add_observation_and_claim(bundle):
    payload = {
        "subject": "NCBITaxon:1", "predicate": "biolink:related_to", "object": "CHEBI:1",
        "context": {"strain": "test strain", "temperature": {"value": 30, "unit": "Cel"}},
        "interpretation": {
            "normalization_contract": "fixture/normalized-observation-v1",
            "normalizer_contract_sha256": "1" * 64, "schema_sha256": "2" * 64,
            "prefix_map_sha256": "3" * 64,
        },
        "provided_by": ["source:A"], "evidence": ["PMID:1"], "relation": "source:relation",
    }
    observation = {
        "observation_id": content_id("observation", payload), "payload": payload,
        "context_id": context_id(payload["context"]),
        "native_identity": {
            "identifier": "native:unchanged-identifier", "algorithm": "fixture/native-v2",
            "normalizer_contract_sha256": "d" * 64, "schema_sha256": "e" * 64,
            "prefix_map_sha256": "f" * 64,
        },
    }
    claim_payload = {
        "subject": payload["subject"], "predicate": payload["predicate"],
        "object": payload["object"], "context": payload["context"],
        "interpretation": deepcopy(payload["interpretation"]),
        "epistemic_kind": "observational",
    }
    claim = {
        "claim_id": content_id("claim", claim_payload), "payload": claim_payload,
        "context_id": context_id(claim_payload["context"]),
        "observation_ids": [observation["observation_id"]],
    }
    bundle["observations"].append(observation)
    bundle["claims"].append(claim)
    for decision in bundle["decisions"]:
        decision.update(observation_id=observation["observation_id"], claim_ids=[claim["claim_id"]])


def attach_review(bundle, *, scientific=False):
    """Use the real canonical RecordReview validator, without mocking its rules."""
    review_id = "20261104T010000Z-synthetic"
    for decision in bundle["decisions"]:
        decision.update(review_state="reviewed", review_ids=[review_id])
    observations = {row["observation_id"]: row for row in bundle["observations"]}
    targets = []
    for decision in bundle["decisions"]:
        targets.append({
            "target_id": decision["occurrence_id"], "path": "snapshot/manifest.json",
            "selector": decision["occurrence_id"], "label": "Synthetic occurrence decision",
            "kind": "snapshot_row", "ownership_note": "Synthetic test, no maintained science.",
            "semantic_digest": {"algorithm": "kg-microbe-curation-decision/v1",
                                "sha256": decision_digest(decision),
                                "description": "Exact proposed decision without circular review IDs."},
        })
    for claim in bundle["claims"]:
        targets.append({
            "target_id": claim["claim_id"], "path": "snapshot/manifest.json",
            "selector": claim["claim_id"], "label": "Synthetic scoped claim",
            "kind": "snapshot_row", "ownership_note": "Synthetic test, no maintained science.",
            "semantic_digest": {"algorithm": "kg-microbe-curation-claim/v1",
                                "sha256": claim_digest(claim, observations),
                                "description": "Claim, membership and observation envelopes."},
        })
    target_ids = [row["target_id"] for row in targets]
    document = {
        "schema_version": "1.0.0", "review_id": review_id, "kind": "batch",
        "repository": "Example/FixtureMech", "title": "Synthetic contract check",
        "started_at": "2026-11-04T00:59:00Z", "finished_at": "2026-11-04T01:00:00Z",
        "reviewer": {"identity": "Synthetic test fixture", "kind": "agent" if scientific else "deterministic",
                     "independence": "not_applicable", "independence_basis": "Synthetic offline test."},
        "skill": "test-fixture", "completion": "completed", "verdict": "pass",
        "scientific_review": scientific, "summary": "Fixture only; no real scientific assertion.",
        "source": {"git_revision": "a" * 40, "state": "git_commit",
                   "inputs": [{"path": "snapshot/manifest.json", "sha256": bundle["input_sha256"], "role": "snapshot"}]},
        "scope": {"description": "Exact fixture targets", "selection": "Explicit fixture IDs",
                  "coverage": "full", "population_size": len(target_ids), "reviewed_target_ids": target_ids},
        "targets": targets,
        "checks": [{"check_id": "fixture", "name": "Fixture scope", "status": "passed",
                    "required": True, "summary": "Fixture target inspected", "target_ids": target_ids,
                    "evidence_ids": ["fixture"]}],
        "evidence": [{"evidence_id": "fixture", "kind": "record_content", "reference": "fixture:source",
                      "accessed_at": "2026-11-04T00:59:30Z", "support": "supports", "summary": "Synthetic evidence."}],
        "assessments": [{"assessment_id": "fixture", "area": "scope", "topic": "Exact fixture scope",
                         "outcome": "supported", "summary": "Synthetic only", "target_ids": target_ids,
                         "evidence_ids": ["fixture"]}],
        "findings": [], "actions": [], "limitations": [],
    }
    bundle["reviews"] = [{"review_id": review_id, "sha256": sha256_json(document), "document": document}]


def test_canonical_json_is_exact_typed_utf8_not_semantic_normalization():
    assert canonical_json({"z": [1, "1", True, None], "é": " μ "}) == (
        '{"z":[1,"1",true,null],"é":" μ "}'.encode()
    )
    assert context_id({"x": ["a", "b"]}) != context_id({"x": ["b", "a"]})
    assert context_id({"x": None}) != context_id({})
    assert context_id({"x": 1}) != context_id({"x": "1"})
    assert context_id({"x": "a", "y": "b"}) == context_id({"y": "b", "x": "a"})


@pytest.mark.parametrize("value", [{1: "coercion"}, {"x": float("nan")}, {"x": float("inf")},
                                   {"x": (1, 2)}, {"x": {1, 2}}, {"x": "\ud800"}])
def test_canonical_json_rejects_lossy_nonfinite_or_invalid_unicode(value):
    with pytest.raises(CurationError):
        canonical_json(value)


def test_occurrence_protocol_preserves_duplicates_and_exact_row_terminators():
    first = occurrence()
    second = occurrence(2)
    crlf = occurrence(source_row=first["source_row"].replace("\n", "\r\n"))
    assert len({first["occurrence_id"], second["occurrence_id"], crlf["occurrence_id"]}) == 3
    payload = {key: value for key, value in first.items() if key not in {"source_row", "occurrence_id"}}
    wire = json.dumps({"contract": CONTRACT, "kind": "occurrence", "payload": payload},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    assert first["occurrence_id"] == "urn:kg-microbe:occurrence:v1:" + hashlib.sha256(wire).hexdigest()
    validate_occurrence(first)
    first["source_row"] = first["source_row"].rstrip("\n")
    with pytest.raises(CurationError, match="checksum"):
        validate_occurrence(first)


@pytest.mark.parametrize("field,value", [("row_number", True), ("row_number", 0),
                                         ("member_sha256", "bad"), ("member", " ")])
def test_occurrence_identity_refuses_ambiguous_inputs(field, value):
    payload = {key: item for key, item in occurrence().items() if key not in {"source_row", "occurrence_id"}}
    payload[field] = value
    with pytest.raises(CurationError):
        occurrence_id(**payload)


def test_new_bundle_is_explicitly_unprocessed_and_withheld(bundle):
    validate_bundle(bundle, expected_input_sha256="c" * 64,
                    expected_occurrence_ids=reversed(bundle["occurrence_ids"]))
    assert {row["disposition"] for row in bundle["decisions"]} == {"withheld"}
    assert {row["conflict_state"] for row in bundle["decisions"]} == {"not_assessed"}


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "replacement"])
def test_membership_checks_identifiers_not_only_counts(bundle, change):
    if change == "missing":
        bundle["decisions"].pop()
    elif change == "extra":
        bundle["decisions"].append(unprocessed_decision(occurrence(3)["occurrence_id"]))
    elif change == "duplicate":
        bundle["decisions"][1] = deepcopy(bundle["decisions"][0])
    else:
        bundle["decisions"][1]["occurrence_id"] = occurrence(3)["occurrence_id"]
    with pytest.raises(CurationError, match="selected occurrence|Duplicate"):
        validate_bundle(bundle)


def test_external_scope_and_snapshot_are_required_to_match(bundle):
    with pytest.raises(CurationError, match="Stale input"):
        validate_bundle(bundle, expected_input_sha256="d" * 64)
    with pytest.raises(CurationError, match="membership"):
        validate_bundle(bundle, expected_occurrence_ids=[bundle["occurrence_ids"][0]])
    bundle["input_sha256"] += "\n"
    with pytest.raises(CurationError, match="does not match"):
        validate_bundle(bundle)


def test_native_identifier_is_retained_and_multiple_claims_are_allowed(bundle):
    add_observation_and_claim(bundle)
    second = deepcopy(bundle["claims"][0])
    second["payload"]["epistemic_kind"] = "computational"
    second["claim_id"] = content_id("claim", second["payload"])
    bundle["claims"].append(second)
    bundle["decisions"][0]["claim_ids"].append(second["claim_id"])
    validate_bundle(bundle)
    assert bundle["observations"][0]["native_identity"]["identifier"] == "native:unchanged-identifier"


def test_identical_lexical_claims_and_observations_have_distinct_interpretation_ids(bundle):
    add_observation_and_claim(bundle)
    for kind in ("observation", "claim"):
        original = bundle[kind + "s"][0]
        for field in original["payload"]["interpretation"]:
            changed = deepcopy(original["payload"])
            changed["interpretation"][field] = (
                "fixture/different-normalizer-v2" if field == "normalization_contract" else "4" * 64
            )
            assert content_id(kind, changed) != original[kind + "_id"], (kind, field)
            assert context_id(changed["context"]) == original["context_id"]
    validate_bundle(bundle)


@pytest.mark.parametrize("kind", ["observation", "claim"])
def test_missing_interpretation_is_rejected_even_with_a_recomputed_fingerprint(bundle, kind):
    add_observation_and_claim(bundle)
    record = bundle[kind + "s"][0]
    del record["payload"]["interpretation"]
    record[kind + "_id"] = content_id(kind, record["payload"])
    with pytest.raises(CurationError, match="interpretation.*required property"):
        validate_bundle(bundle)


def test_interpretation_requires_a_name_and_strict_pins(bundle):
    add_observation_and_claim(bundle)
    for kind in ("observation", "claim"):
        for field in bundle[kind + "s"][0]["payload"]["interpretation"]:
            malformed = deepcopy(bundle)
            interpretation = malformed[kind + "s"][0]["payload"]["interpretation"]
            interpretation[field] = " " if field == "normalization_contract" else "a" * 64 + "\n"
            with pytest.raises(CurationError, match="does not match"):
                validate_bundle(malformed)
            del interpretation[field]
            with pytest.raises(CurationError, match="required property"):
                validate_bundle(malformed)


def test_interpretation_change_cannot_reuse_review_after_ids_and_membership_are_updated(bundle):
    add_observation_and_claim(bundle)
    attach_review(bundle)
    validate_bundle(bundle)
    observation = bundle["observations"][0]
    observation["payload"]["interpretation"]["schema_sha256"] = "4" * 64
    observation["observation_id"] = content_id("observation", observation["payload"])
    claim = bundle["claims"][0]
    claim["payload"]["interpretation"]["schema_sha256"] = "4" * 64
    claim["claim_id"] = content_id("claim", claim["payload"])
    claim["observation_ids"] = [observation["observation_id"]]
    for decision in bundle["decisions"]:
        decision.update(observation_id=observation["observation_id"], claim_ids=[claim["claim_id"]])
    with pytest.raises(CurationError, match="semantic digest|scope"):
        validate_bundle(bundle)
    attach_review(bundle)
    validate_bundle(bundle)


@pytest.mark.parametrize("kind", ["observation", "claim"])
def test_scientific_context_changes_invalidate_identity(bundle, kind):
    add_observation_and_claim(bundle)
    bundle[kind + "s"][0]["payload"]["context"] = {"strain": "different strain"}
    with pytest.raises(CurationError, match="fingerprint"):
        validate_bundle(bundle)


def test_unreferenced_objects_and_dangling_membership_are_rejected(bundle):
    add_observation_and_claim(bundle)
    bundle["decisions"][0]["claim_ids"] = ["urn:kg-microbe:claim:v1:" + "0" * 64]
    with pytest.raises(CurationError, match="Unknown claim"):
        validate_bundle(bundle)
    bundle["decisions"][0]["claim_ids"] = []
    bundle["decisions"][1]["claim_ids"] = []
    with pytest.raises(CurationError, match="outside selected"):
        validate_bundle(bundle)


def test_every_claim_observation_membership_needs_an_explicit_decision(bundle):
    add_observation_and_claim(bundle)
    observation = deepcopy(bundle["observations"][0])
    observation["payload"]["provided_by"] = ["source:B"]
    observation["observation_id"] = content_id("observation", observation["payload"])
    bundle["observations"].append(observation)
    bundle["claims"][0]["observation_ids"].append(observation["observation_id"])
    bundle["decisions"][1].update(observation_id=observation["observation_id"], claim_ids=[])
    with pytest.raises(CurationError, match="fully represented"):
        validate_bundle(bundle)


def test_canonical_review_does_not_automatically_promote_science(bundle):
    attach_review(bundle)
    validate_bundle(bundle)
    assert all(row["disposition"] == "withheld" for row in bundle["decisions"])
    bundle["decisions"][0]["disposition"] = "retain"
    with pytest.raises(CurationError, match="semantic digest"):
        validate_bundle(bundle)


def test_retention_needs_explicit_science_and_assessed_conflicts(bundle):
    add_observation_and_claim(bundle)
    for decision in bundle["decisions"]:
        decision.update(disposition="retain", conflict_state="none_reported")
    attach_review(bundle)
    with pytest.raises(CurationError, match="explicit scientific review"):
        validate_bundle(bundle)
    attach_review(bundle, scientific=True)
    validate_bundle(bundle)
    bundle["decisions"][0]["conflict_state"] = "unresolved"
    attach_review(bundle, scientific=True)
    with pytest.raises(CurationError, match="conflicts"):
        validate_bundle(bundle)


@pytest.mark.parametrize("change", ["review_bytes", "review_input", "decision", "native_identity"])
def test_review_reuse_is_bound_to_exact_inputs_and_current_scope(bundle, change):
    add_observation_and_claim(bundle)
    attach_review(bundle)
    if change == "review_bytes":
        bundle["reviews"][0]["document"]["summary"] = "Different review"
    elif change == "review_input":
        document = bundle["reviews"][0]["document"]
        document["source"]["inputs"][0]["sha256"] = "0" * 64
        bundle["reviews"][0]["sha256"] = sha256_json(document)
    elif change == "decision":
        bundle["decisions"][0]["rationale"] = "Changed since review"
    else:
        bundle["observations"][0]["native_identity"]["schema_sha256"] = "0" * 64
    with pytest.raises(CurationError, match="digest|stale|unbound"):
        validate_bundle(bundle)


def test_schema_rejects_undeclared_fields_and_lossy_json_reader(bundle, tmp_path):
    path = tmp_path / "bundle.json"
    path.write_bytes(canonical_json(bundle))
    assert load_bundle(path) == bundle
    path.write_text('{"contract":"first","contract":"second"}')
    with pytest.raises(CurationError, match="Duplicate JSON key"):
        load_bundle(path)
    bundle["decisions"][0]["approved"] = True
    with pytest.raises(CurationError, match="Additional properties"):
        validate_bundle(bundle)


def test_reader_refuses_oversized_file_before_parsing(tmp_path):
    path = tmp_path / "oversized.json"
    with path.open("wb") as handle:
        handle.truncate(MAX_BUNDLE_BYTES + 1)
    with pytest.raises(CurationError, match="16 MiB"):
        load_bundle(path)


@pytest.mark.parametrize("command", ["validate-bundle", "apply"])
@pytest.mark.parametrize("input_kind", ["fifo", "symlink"])
def test_cli_rejects_nonregular_bundle_before_read_or_apply(bundle, tmp_path, command, input_kind):
    """CLAW #759: both bundle entrypoints must refuse pipes promptly and never follow links."""
    path = tmp_path / "bundle.json"
    original = tmp_path / "original.json"
    original_bytes = canonical_json(bundle)
    original.write_bytes(original_bytes)
    if input_kind == "fifo":
        os.mkfifo(path)
    else:
        path.symlink_to(original)
    database = tmp_path / "must-not-create.sqlite"
    args = (["validate-bundle", str(path)] if command == "validate-bundle" else [
        "apply", "--bundle", str(path), "--database", str(database),
        "--expected-revision", "0" * 64,
    ])
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "kg_microbe_curation", *args],
        cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2 and "regular file" in result.stderr
    assert not database.exists()
    assert original.read_bytes() == original_bytes


def test_in_memory_bundle_size_and_selected_count_are_bounded(bundle):
    oversized = deepcopy(bundle)
    oversized["occurrence_ids"] = [bundle["occurrence_ids"][0]] * (MAX_BUNDLE_OCCURRENCES + 1)
    with pytest.raises(CurationError, match="bounded batch limit"):
        validate_bundle(oversized)
    bundle["decisions"][0]["rationale"] = "x" * MAX_BUNDLE_BYTES
    with pytest.raises(CurationError, match="16 MiB"):
        validate_bundle(bundle)
