"""Optional helper dispatch; the separate automatic package owns receipt validation.

These tests exercise the real protected admission fixture without installing the
future helper into this prerequisite branch. Integration tests in the automatic
proposal exercise the real helper and its fixed source/identity/artifact policy.
"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from test_governance_consumer_admission import KEY, native_admitted

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.cycle_release_audit import audit_release

HELPER = "kg_microbe_governance.private_audit_coverage"


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


def test_no_helper_needed_for_default_or_explicit_empty_obligations(tmp_path, monkeypatch):
    claw, roots, *_ = native_admitted(tmp_path, installed=True)
    monkeypatch.setitem(sys.modules, HELPER, None)
    implicit = audit_release(claw, roots)
    explicit = audit_release(claw, roots, private_obligations={})
    assert implicit == explicit and implicit["ok"]


def test_nonempty_obligations_refuse_missing_helper_before_audit(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, HELPER, None)
    with pytest.raises(ModuleNotFoundError):
        audit_release(tmp_path, {}, private_obligations={KEY: object()})


def test_deferred_admission_never_becomes_full_fleet_success(tmp_path, monkeypatch):
    claw, roots, policy, *_ = native_admitted(tmp_path)
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
def test_private_hook_delegates_exact_coverage(tmp_path, monkeypatch, mutation):
    claw, roots, policy, *_ = native_admitted(tmp_path)
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


def test_private_helper_binding_failure_is_not_swallowed(tmp_path, monkeypatch):
    claw, roots, policy, *_ = native_admitted(tmp_path)
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
    ],
)
def test_deferred_row_contract_rejects_forged_verification_or_counts(tmp_path, monkeypatch, bad_row):
    claw, roots, policy, *_ = native_admitted(tmp_path)
    roots.pop(KEY)
    item = SimpleNamespace(key=KEY)
    install_helper(monkeypatch, item, policy)
    sys.modules[HELPER].deferred_row = lambda _observed: bad_row
    with pytest.raises(GovernanceError, match="unverified-state contract"):
        audit_release(claw, roots, private_obligations={KEY: item})
