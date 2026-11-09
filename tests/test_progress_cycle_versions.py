"""Cycle-v2 progress retains v1 history and cannot count six goals as seven."""
from __future__ import annotations

import copy

import pytest
from test_progress_model import add_closure, collect, repo, runtime, save_ledger
from test_progress_prs import session, write  # noqa: F401 -- fixture is reused

import kg_microbe_progress as progress
from kg_microbe_progress import prs


def v2(ledger, *, cycle=1):
    ledger.update(cycle=cycle, parent_version="2.0.0")
    ledger.setdefault("cycle_versions", {})[str(cycle)] = "2.0.0"


def test_six_v2_closures_do_not_complete_a_seven_goal_cycle(tmp_path):
    root, ledger = runtime(tmp_path, stage=7)
    v2(ledger)
    for stage in range(1, 7):
        add_closure(root, ledger, stage=stage)
    history, snapshot = collect(root)
    assert snapshot["totals"]["completed_goals"] == 6
    assert snapshot["totals"]["completed_cycles"] == 0
    assert repo(snapshot)["stages"][0]["key"] == "open_issue_triage"
    assert repo(snapshot)["current"]["stage_id"] == "infrastructure"
    assert len(repo(snapshot)["stages"]) == 7
    ledger.update(stage=1, cycle=2)
    ledger["cycle_versions"]["2"] = "2.0.0"
    add_closure(root, ledger, stage=7, cycle=1)
    history, snapshot = collect(root, history)
    assert snapshot["totals"]["completed_cycles"] == 1
    assert snapshot["totals"]["completed_goals"] == 7


def test_v1_to_v2_boundary_preserves_public_history_and_old_stage_numbers(tmp_path):
    root, ledger = runtime(tmp_path, stage=6)
    for stage in range(1, 6):
        add_closure(root, ledger, stage=stage)
    old, snapshot = collect(root)
    original_closures = copy.deepcopy(old["closures"])
    assert repo(snapshot)["current"]["stage_id"] == "infrastructure"
    ledger["cycle_versions"] = {"1": "1.0.0"}
    v2(ledger, cycle=2)
    ledger["stage"] = 1
    add_closure(root, ledger, stage=6, cycle=1)
    history, snapshot = collect(root, old)
    assert history["closures"][:5] == original_closures
    assert history["closures"][5]["stage_number"] == 6
    assert history["closures"][5]["stage_id"] == "infrastructure"
    assert "parent_version" not in history["closures"][5]
    assert snapshot["totals"]["completed_cycles"] == 1
    assert repo(snapshot)["current"]["stage_number"] == 1
    assert repo(snapshot)["current"]["stage_id"] == "open_issue_triage"
    assert repo(snapshot)["current"]["parent_version"] == "2.0.0"
    progress.validate_bundle(history, snapshot)


def test_mid_cycle_parent_change_is_rejected_even_without_closures(tmp_path):
    root, ledger = runtime(tmp_path, stage=2)
    old, _ = collect(root)
    v2(ledger)
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError, match="inside an active cycle"):
        collect(root, old)


@pytest.mark.parametrize("version", ["3.0.0", "", None, 2])
def test_unknown_or_malformed_cycle_version_is_not_legacy(tmp_path, version):
    root, ledger = runtime(tmp_path)
    ledger["parent_version"] = version
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError, match="version"):
        collect(root)


def test_cycle_history_version_conflict_is_rejected(tmp_path):
    root, ledger = runtime(tmp_path)
    v2(ledger)
    ledger["cycle_versions"]["1"] = "1.0.0"
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError, match="contradicts history"):
        collect(root)


def test_v2_current_version_does_not_relabel_old_unversioned_closure(tmp_path):
    root, ledger = runtime(tmp_path, stage=1, cycle=2)
    v2(ledger, cycle=2)
    add_closure(root, ledger, stage=1, cycle=1)
    history, _ = collect(root)
    assert history["closures"][0]["stage_id"] == "add_records"
    assert "parent_version" not in history["closures"][0]


def test_v1_stage_seven_is_rejected(tmp_path):
    root, _ = runtime(tmp_path, stage=7)
    with pytest.raises(progress.ProgressError, match="invalid stage"):
        collect(root)


def test_public_cycle_cannot_mix_parent_versions(tmp_path):
    root, ledger = runtime(tmp_path, stage=3)
    v2(ledger)
    add_closure(root, ledger, stage=1)
    history, _ = collect(root)
    history["closures"][0].pop("parent_version")
    history["closures"][0]["stage_id"] = "add_records"
    with pytest.raises(progress.ProgressError, match="mix parent versions"):
        progress.validate_history(history)


def test_stage_seven_pr_registration_requires_v2_pinned_cycle(session):  # noqa: F811 -- imported pytest fixture
    session.ledger["stage"] = 7
    write(session.root / "ledger.json", session.ledger)
    write(session.root / "status.json", prs._context(session.ledger))
    with pytest.raises(prs.AssociationError, match="outside the pinned cycle"):
        prs.register_pr(session.root, 42)
    v2(session.ledger)
    write(session.root / "ledger.json", session.ledger)
    result = prs.register_pr(session.root, 42)
    assert result["stage"] == 7
    assert prs.gather_associations([session.runtime]) == [result]
