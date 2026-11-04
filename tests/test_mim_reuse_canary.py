"""Scope controls prevent ingredient review from approving biological edges."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/run_mim_reuse_canary.py"
SPEC = importlib.util.spec_from_file_location("mim_reuse_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


@pytest.fixture
def mapping():
    """Synthetic data exercise scope; these are not scientific approvals."""
    row = {
        "subject_id": "MIM:fixture",
        "predicate_id": "skos:exactMatch",
        "object_id": "CHEBI:15377",
        "other": "specific supplied form",
    }
    decision = {"row_sha256": canary.payload_digest(row), "disposition": "SUPPORTED"}
    dependency = "a" * 64
    request = {"kind": "mim_mapping_payload", "payload": row, "dependency_sha256": dependency}
    return row, decision, request, dependency


def test_exact_mapping_reuse_is_not_a_new_scientific_review(mapping):
    result = canary.classify_reuse(*mapping)
    assert result["eligible_for_reuse"] is True
    assert result["independent_scientific_review"] is False
    assert result["biological_claim_approved"] is False


def test_same_endpoint_does_not_approve_growth(mapping):
    row, decision, _, dependency = mapping
    request = {
        "kind": "biological_claim",
        "subject": "fixture:organism",
        "predicate": "fixture:grows_on",
        "object": row["object_id"],
        "dependency_sha256": dependency,
    }
    result = canary.classify_reuse(row, decision, request, dependency)
    assert result["outcome"] == "endpoint_only"
    assert result["eligible_for_reuse"] is False
    assert result["biological_claim_approved"] is False


def test_native_withhold_is_preserved_for_identical_payload(mapping):
    row, decision, request, dependency = mapping
    result = canary.classify_reuse(row, dict(decision, disposition="WITHHOLD"), request, dependency)
    assert result["outcome"] == "native_withheld_mapping"
    assert result["eligible_for_reuse"] is False


def test_same_triple_different_form_cannot_borrow_review(mapping):
    row, decision, request, dependency = mapping
    result = canary.classify_reuse(
        row, decision, dict(request, payload=dict(row, other="other form")), dependency
    )
    assert result["outcome"] == "scope_mismatch"
    assert result["eligible_for_reuse"] is False


def test_changed_evidence_dependency_invalidates_unchanged_mapping(mapping):
    row, decision, request, dependency = mapping
    result = canary.classify_reuse(
        row, decision, dict(request, dependency_sha256="b" * 64), dependency
    )
    assert result["outcome"] == "stale_dependencies"
    assert result["eligible_for_reuse"] is False


def test_receipt_is_complete_and_cannot_overwrite_existing_result(tmp_path):
    output = tmp_path / "receipt.json"
    report = {"status": "fixture", "actual_kg_edges_approved": 0}
    canary.publish_new(output, report)
    saved = output.read_bytes()
    assert canary.read_json(saved) == report
    with pytest.raises(FileExistsError):
        canary.publish_new(output, {"status": "replacement"})
    assert output.read_bytes() == saved
    assert list(tmp_path.glob(".mim-canary-*")) == []
