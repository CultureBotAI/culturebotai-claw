"""Deferred audit rows never claim installation (#1174, retained from #1074).

The helper double isolates the caller's row contract from the actual private
receipt validator, whose exact identities are covered separately.
"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from test_governance_consumer_admission import KEY, native_admitted

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.cycle_release_audit import audit_release

HELPER = "kg_microbe_governance.private_audit_coverage"


@pytest.fixture(scope="module")
def deferred_admission(tmp_path_factory):
    """Read-only audit cases share the expensive protected-history fixture."""
    return native_admitted(tmp_path_factory.mktemp("deferred-admission"))


def install_helper(monkeypatch, item, policy, *, failure=None):
    """Strict external contract double, recording delegation rather than receipts."""
    calls = []
    helper = ModuleType(HELPER)

    def exact_coverage(consumers, roots, deferred):
        calls.append("coverage")
        if set(roots) & set(deferred) or set(roots) | set(deferred) != set(consumers):
            raise GovernanceError("Incomplete or overlapping test coverage")

    def validate_admission(observed, declaration):
        calls.append("admission")
        assert observed is item and declaration == policy
        if failure:
            raise GovernanceError(failure)

    def deferred_row(observed):
        calls.append("row")
        assert observed is item
        return {"key": KEY, "state": "private_verification_required", "issues": [],
                "installation_verified": False, "checked_artifacts": 0}

    helper.exact_coverage = exact_coverage
    helper.validate_admission = validate_admission
    helper.deferred_row = deferred_row
    monkeypatch.setitem(sys.modules, HELPER, helper)
    return calls


def test_default_and_explicit_empty_obligations_are_equivalent(tmp_path):
    claw, roots, *_ = native_admitted(tmp_path, installed=True)
    implicit = audit_release(claw, roots)
    explicit = audit_release(claw, roots, private_obligations={})
    assert implicit == explicit and implicit["ok"]


def test_deferred_admission_never_becomes_full_fleet_success(deferred_admission, monkeypatch):
    claw, original_roots, policy, *_ = deferred_admission
    roots = dict(original_roots)
    roots.pop(KEY)
    item = SimpleNamespace(key=KEY)
    calls = install_helper(monkeypatch, item, policy)
    result = audit_release(claw, roots, private_obligations={KEY: item})
    assert calls == ["coverage", "admission", "row"]
    assert result["public_component_ok"] is True and result["ok"] is False
    assert result["expected_consumers"] == sorted([*roots, KEY])
    row = next(r for r in result["repositories"] if r["key"] == KEY)
    assert row["state"] == "private_verification_required"
    assert not row["installation_verified"] and row["checked_artifacts"] == 0
    assert result["counts"]["private_verification_required"] == 1


@pytest.mark.parametrize("mutation", ["missing_public", "overlap", "unknown"])
def test_private_hook_delegates_exact_coverage(deferred_admission, monkeypatch, mutation):
    claw, original_roots, policy, *_ = deferred_admission
    roots = dict(original_roots)
    item = SimpleNamespace(key=KEY)
    install_helper(monkeypatch, item, policy)
    deferred = {KEY: item}
    if mutation != "overlap":
        roots.pop(KEY)
    if mutation == "missing_public":
        roots.pop("traitmech")
    elif mutation == "unknown":
        deferred["unknownmech"] = item
    with pytest.raises(GovernanceError, match="coverage"):
        audit_release(claw, roots, private_obligations=deferred)


def test_private_helper_binding_failure_is_not_swallowed(deferred_admission, monkeypatch):
    claw, original_roots, policy, *_ = deferred_admission
    roots = dict(original_roots)
    roots.pop(KEY)
    item = SimpleNamespace(key=KEY)
    calls = install_helper(monkeypatch, item, policy, failure="Private source binding mismatch")
    with pytest.raises(GovernanceError, match="source binding"):
        audit_release(claw, roots, private_obligations={KEY: item})
    assert calls == ["coverage", "admission"]


@pytest.mark.parametrize("bad_ref", [True, "wrong_content"])
def test_deferred_source_objects_still_authenticate(tmp_path, monkeypatch, bad_ref):
    claw, roots, policy, *_ = native_admitted(tmp_path, bad_ref=bad_ref)
    roots.pop(KEY)
    item = SimpleNamespace(key=KEY)
    install_helper(monkeypatch, item, policy)
    with pytest.raises(GovernanceError):
        audit_release(claw, roots, private_obligations={KEY: item})


def test_private_deferral_does_not_mask_public_failure(tmp_path, monkeypatch):
    from test_governance_cycle_release_audit import PIN, commit, put

    claw, roots, policy, *_ = native_admitted(tmp_path)
    roots.pop(KEY)
    put(roots["traitmech"], PIN, "f" * 40 + "\n")
    commit(roots["traitmech"])
    item = SimpleNamespace(key=KEY)
    install_helper(monkeypatch, item, policy)
    result = audit_release(claw, roots, private_obligations={KEY: item})
    assert not result["public_component_ok"] and not result["ok"]
    row = next(r for r in result["repositories"] if r["key"] == "traitmech")
    assert any(issue["code"] == "unexpected_pin" for issue in row["issues"])


@pytest.mark.parametrize(
    "bad_row",
    [
        {"key": "other", "state": "private_verification_required", "issues": [], "installation_verified": False, "checked_artifacts": 0},
        {"key": KEY, "state": "installed_infrastructure", "issues": [], "installation_verified": False, "checked_artifacts": 0},
        {"key": KEY, "state": "private_verification_required", "issues": [], "installation_verified": True, "checked_artifacts": 0},
        {"key": KEY, "state": "private_verification_required", "issues": [], "installation_verified": False, "checked_artifacts": 22},
        {"key": KEY, "state": "private_verification_required", "issues": [], "installation_verified": False, "checked_artifacts": False},
        {"key": KEY, "state": "private_verification_required", "issues": ["failure"], "installation_verified": False, "checked_artifacts": 0},
        None,
    ],
)
def test_deferred_row_contract_rejects_forged_verification_or_counts(deferred_admission, monkeypatch, bad_row):
    claw, original_roots, policy, *_ = deferred_admission
    roots = dict(original_roots)
    roots.pop(KEY)
    item = SimpleNamespace(key=KEY)
    install_helper(monkeypatch, item, policy)
    sys.modules[HELPER].deferred_row = lambda _observed: bad_row
    with pytest.raises(GovernanceError, match="unverified-state contract"):
        audit_release(claw, roots, private_obligations={KEY: item})
