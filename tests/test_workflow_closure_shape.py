"""Receipt-shape boundary tests; remote closure authority is tested separately."""
from __future__ import annotations

import copy

import pytest

from kg_microbe_workflows.closure import multi_pr_members


def receipt():
    members = []
    for number, char in ((365, "a"), (367, "b")):
        head = char * 40
        members.append({
            "number": number, "head_sha": head, "branch": f"fix-{number}",
            "base": "main", "merge_commit_sha": str(number % 10) * 40,
            "review": {"status": "complete", "remaining_findings": 0, "head_sha": head},
            "validation": [{"command": "pytest", "status": "passed", "head_sha": head}],
            "cleanup": {"checkout_ready": True, "local_branch_deleted": True,
                        "remote_branch_deleted": True},
        })
    last = members[-1]
    return {
        "schema_version": 2, "status": "completed", "prs": members,
        "pr": {key: last[key] for key in ("number", "head_sha", "branch", "base")},
        **{key: copy.deepcopy(last[key]) for key in ("review", "validation", "cleanup")},
        "issues": [{"number": 361, "pr_number": 365}],
        "evidence_attributions": [{"path": "reviews/c3/s5/evidence.yaml", "sha256": "c" * 64,
                                  "pr_number": 367, "commit_sha": "b" * 40}],
    }


def test_shape_preserves_legacy_receipts_without_manufacturing_members():
    legacy = {"schema_version": 2, "status": "completed", "pr": {"number": 365}}
    original = copy.deepcopy(legacy)
    assert multi_pr_members(legacy) == []
    assert legacy == original


def test_shape_keeps_order_and_final_head_without_mutating_input():
    data = receipt()
    original = copy.deepcopy(data)
    members = multi_pr_members(data)
    assert [item["number"] for item in members] == [365, 367]
    assert data == original


@pytest.mark.parametrize("value", [None, False, {}, [], [receipt()["prs"][0]]])
def test_present_invalid_members_never_fall_back_to_single(value):
    data = receipt()
    data["prs"] = value
    del data["evidence_attributions"]  # Distinguish explicit malformed opt-in from legacy fallback.
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("path", ["/absolute.yaml", "../escape.yaml", "a/../b.yaml",
                                   "a//b.yaml", "a/./b.yaml", "a\\b.yaml", "a\x00b.yaml"])
def test_evidence_path_must_be_unambiguous_and_repository_relative(path):
    data = receipt()
    data["evidence_attributions"][0]["path"] = path
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("location", ["member", "issue", "evidence"])
@pytest.mark.parametrize("number", [True, 365.0, "365"])
def test_pr_identity_requires_an_integer_not_coercion(location, number):
    data = receipt()
    if location == "member":
        data["prs"][0]["number"] = number
    elif location == "issue":
        data["issues"][0]["pr_number"] = number
    else:
        data["evidence_attributions"][0]["pr_number"] = number
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("field", ["number", "head_sha", "merge_commit_sha", "branch"])
def test_repeated_pr_identity_is_rejected(field):
    data = receipt()
    data["prs"][1][field] = data["prs"][0][field]
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("field", ["pr", "review", "validation", "cleanup"])
def test_top_level_final_proof_cannot_disagree(field):
    data = receipt()
    data[field] = {} if field != "validation" else []
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("field", ["head_sha", "merge_commit_sha"])
def test_member_commit_identity_is_exact_sha(field):
    data = receipt()
    data["prs"][0][field] = "a" * 39
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("field", ["review", "validation", "cleanup"])
def test_earlier_member_needs_its_own_complete_proof(field):
    data = receipt()
    data["prs"][0][field] = {} if field != "validation" else []
    with pytest.raises(ValueError):
        multi_pr_members(data)


def test_evidence_attribution_cannot_be_smuggled_into_legacy_receipt():
    data = receipt()
    del data["prs"]
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("location", ["issue", "evidence"])
def test_attribution_cannot_point_outside_the_ordered_set(location):
    data = receipt()
    data["issues" if location == "issue" else "evidence_attributions"][0]["pr_number"] = 999
    with pytest.raises(ValueError):
        multi_pr_members(data)


def test_evidence_path_has_exactly_one_producer():
    data = receipt()
    duplicate = copy.deepcopy(data["evidence_attributions"][0])
    duplicate["pr_number"] = 365
    data["evidence_attributions"].append(duplicate)
    with pytest.raises(ValueError):
        multi_pr_members(data)


@pytest.mark.parametrize("location", ["member", "evidence"])
def test_unknown_attribution_fields_are_rejected(location):
    data = receipt()
    data["prs" if location == "member" else "evidence_attributions"][0]["override"] = True
    with pytest.raises(ValueError):
        multi_pr_members(data)
