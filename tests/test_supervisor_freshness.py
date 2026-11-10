"""Adopted freshness binds actual boundaries without changing active legacy goals."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_mech_session_supervisor import (
    GOAL,
    HEAD,
    MERGE,
    cycle_instance,
    supervisor,
    write_goal_evidence,
)
from test_mech_session_supervisor import cycle_setup as cycle_setup
from test_mech_session_supervisor import setup as setup

from kg_microbe_workflows.freshness import FreshnessError, save_receipt
from kg_microbe_workflows.freshness_contract import contract_sha256

NEW = "d" * 40


def adoption(fixture, *, cycle=1, predecessor=None, ledger=None):
    ledger = ledger or fixture.ledger
    record = {
        "schema_version": "1.0.0", "authority": "approved_boundary_adoption",
        "repository_key": fixture.target["repository_key"],
        "github_repository": fixture.target["github_repository"], "repository_root": str(fixture.repo),
        "canonical_release_commit": "e" * 40, "contract_sha256": contract_sha256(),
        "boundary": {"run_id": ledger["run_id"], "cycle": cycle, "stage": 1,
                     "workflow_sha256": ledger["workflow"]["sha256"], "predecessor_receipt_sha256": predecessor},
        "approval": {"record_id": "offline-fixture-approval", "approved_at": "2026-01-01T00:00:00Z", "approved_by": "fixture"},
    }
    path = fixture.runtime / "freshness-adoption.json"
    raw = (json.dumps(record, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    fixture.target["freshness_adoption"] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    return record


def engine_fixture(instance, fixture, monkeypatch, *, new_head=NEW, before=None):
    events = []
    def gate(target, **kwargs):
        events.append((kwargs["phase"], fixture.remote.head, kwargs["merge_commits"]))
        assert kwargs["owner_check"]() == {fixture.target["pid"]: " ".join(fixture.target["process_identity"].split())}
        if before:
            before(kwargs["phase"])
        old = fixture.remote.head
        fixture.remote.head = new_head
        report = {"schema_version": "1.0.0", "repository_key": target.name,
                  "repository": target.expected_repository, "checkout": str(target.path),
                  "status": "verified", "reason": "observed_revision_verified", "phase": kwargs["phase"],
                  "boundary_id": kwargs["boundary_id"], "policy_sha256": kwargs["policy_sha256"],
                  "before": old, "fetched": new_head, "after": new_head, "default_branch": "main",
                  "apply": True, "verified_at": supervisor.now()}
        report["receipt"] = save_receipt(kwargs["receipt_dir"], report)
        return report
    instance.freshness_runner = gate
    def inventory(target, report, **kwargs):
        events.append(("inventory", fixture.remote.head))
        assert target.path == fixture.repo
        assert report["after"] == fixture.remote.head
        assert kwargs["boundary_id"] == report["boundary_id"]
        return fixture.remote.head
    monkeypatch.setattr("kg_microbe_workflows.freshness.verify_inventory_head", inventory)
    # This fixture models Git through a fake remote; real-blob controls below
    # exercise the production reader against an actual isolated repository.
    monkeypatch.setattr(supervisor, "verify_fetched_infrastructure",
                        lambda target, revision, raw: events.append(("infra_blob", revision)))
    return events


def adopt_active(instance, fixture, monkeypatch, *, head=HEAD):
    adoption(fixture)
    instance.freshness_adoption(fixture.target, fixture.ledger, activate=True)
    engine_fixture(instance, fixture, monkeypatch, new_head=head)
    instance.ensure_boundary_freshness(fixture.target, fixture.ledger, phase="pre_goal", apply=True)


def test_unadopted_legacy_goal_has_no_engine_or_source_mutation(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    original = copy.deepcopy(fixture.ledger)
    monkeypatch.setattr(instance, "freshness_runner", lambda *_a, **_k: pytest.fail("unadopted engine"))
    assert instance.ensure_boundary_freshness(fixture.target, fixture.ledger, phase="pre_goal", apply=True) == {"status": "not_adopted"}
    assert fixture.ledger == original
    instance.save(fixture.target, fixture.ledger)
    instance.sweep(apply=False)
    status = supervisor.read_json(instance.directory(fixture.target) / "status.json")
    assert status["repository_freshness"] == {"status": "not_adopted", "proposal_configured": False}


def test_initial_adoption_precedes_scope_and_baseline(cycle_setup, monkeypatch):
    fixture = cycle_setup
    # This fixture uses the real stage-key branch without fetching GitHub scope.
    fixture.target["_workflow"]["stages"][0]["key"] = "open_issue_triage"
    adoption(fixture, ledger={**fixture.ledger, "workflow": supervisor.pin_workflow(fixture.target["_workflow"])})
    monkeypatch.setattr(supervisor, "freeze_open_issues", lambda *_a, **_k: pytest.fail("freeze before gate"))
    ledger = supervisor.new_ledger(fixture.config, fixture.target)
    assert ledger["freshness_initial_pending"] and "issue_scope" not in ledger
    instance = cycle_instance(fixture, monkeypatch)
    events = engine_fixture(instance, fixture, monkeypatch)
    def scope(_target, candidate):
        events.append(("freeze", fixture.remote.head))
        assert candidate["repository_freshness"]["pre_goal"]["after"] == NEW
        candidate["issue_scope"] = {"fresh_from": NEW}
    monkeypatch.setattr(instance, "freeze_stage_scope", scope)
    active = instance.initialize_freshness(fixture.target, ledger, fixture.observation, apply=True)
    assert events[0][0] == "pre_goal"
    assert next(row for row in events if row[0] == "freeze") == ("freeze", NEW)
    assert active["baseline_head"] == NEW and active["awaiting_goal"]
    assert active["adopted_goal"] == GOAL
    assert "baseline_head" not in ledger and ledger["adopted_goal"] is None


@pytest.mark.parametrize("damage", ["active", "prompt", "wrong_identity", "existing_baseline", "already_frozen"])
def test_initial_adoption_never_retrofits_active_or_frozen_work(cycle_setup, monkeypatch, damage):
    fixture = cycle_setup
    adoption(fixture)
    ledger = supervisor.new_ledger(fixture.config, fixture.target)
    observed = copy.deepcopy(fixture.observation)
    if damage == "active":
        observed["goal_state"] = "active"
    elif damage == "prompt":
        observed["ready"] = False
    elif damage == "wrong_identity":
        observed["goal_identity"]["start_step_index"] += 1
    elif damage == "existing_baseline":
        ledger["baseline_head"] = HEAD
    else:
        ledger["issue_scope"] = {"frozen": True}
    before = copy.deepcopy(ledger)
    instance = cycle_instance(fixture, monkeypatch)
    instance.freshness_runner = lambda *_a, **_k: pytest.fail("must not synchronize")
    with pytest.raises(supervisor.FreshnessHold, match="pristine assessed"):
        instance.initialize_freshness(fixture.target, ledger, observed, apply=True)
    assert ledger == before


def test_configured_record_does_not_adopt_existing_midstage(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adoption(fixture)
    before = copy.deepcopy(fixture.ledger)
    assert instance.freshness_adoption(fixture.target, fixture.ledger) is None
    assert fixture.ledger == before


def test_gate_failure_cannot_freeze_advance_or_spend_closure_repairs(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    receipt = write_goal_evidence(fixture, fixture.ledger)
    fixture.remote.snapshot()
    instance.save(fixture.target, fixture.ledger)
    supervisor.atomic_json(instance.directory(fixture.target) / "completion.json", receipt)
    before_actions = copy.deepcopy(fixture.ledger["actions"])
    instance.freshness_runner = lambda *_a, **_k: {"status": "hold", "reason": "another_live_owner"}
    monkeypatch.setattr(instance, "freeze_stage_scope", lambda *_a, **_k: pytest.fail("freeze after hold"))
    result = instance.sweep(apply=True)
    after = supervisor.read_json(instance.directory(fixture.target) / "ledger.json")
    assert result["sessions"][0]["phase"] == "blocked"
    status = supervisor.read_json(instance.directory(fixture.target) / "status.json")
    assert status["decision"]["blocker"] == "repository_freshness"
    assert after["stage"] == 1 and after["completed_stages"] == []
    assert after["actions"] == before_actions
    assert after["baseline_head"] == HEAD and after["workflow"] == fixture.ledger["workflow"]


def test_exact_actual_merge_checked_before_postmerge_and_next_inventory(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    events = engine_fixture(instance, fixture, monkeypatch)
    receipt = write_goal_evidence(fixture, fixture.ledger)
    fixture.remote.snapshot()
    instance.save(fixture.target, fixture.ledger)
    supervisor.atomic_json(instance.directory(fixture.target) / "completion.json", receipt)
    monkeypatch.setattr(instance, "dispatch", lambda *_a, **_k: {"state": "not-sent", "reason": "offline test"})
    instance.sweep(apply=True)
    after = supervisor.read_json(instance.directory(fixture.target) / "ledger.json")
    assert [row[0] for row in events if row[0] != "inventory"] == ["post_merge", "pre_goal"]
    assert events[0] == ("post_merge", HEAD, (MERGE,))
    assert after["stage"] == 2 and after["baseline_head"] == NEW
    closed = after["completed_stages"][0]
    assert closed["repository_freshness"]["pre_goal"]["after"] == HEAD
    assert closed["repository_freshness"]["post_merge"]["after"] == NEW
    assert after["workflow"] == fixture.ledger["workflow"]


@pytest.mark.parametrize("damage", ["unmerged", "wrong_head", "wrong_base", "missing_merge"])
def test_claimed_merge_is_not_freshness_authority(cycle_setup, monkeypatch, damage):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    if damage == "unmerged":
        fixture.remote.pr["merged"] = False
    elif damage == "wrong_head":
        fixture.remote.pr["head"]["sha"] = NEW
    elif damage == "wrong_base":
        fixture.remote.pr["base"]["ref"] = "feature"
    else:
        fixture.remote.pr["merge_commit_sha"] = None
    with pytest.raises(supervisor.FreshnessHold, match="actually merged"):
        instance.freshness_merged_commits(fixture.target, fixture.receipt)


def test_no_change_still_requires_saved_preinventory_proof(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    original_baseline = fixture.ledger["baseline_head"]
    proof = fixture.ledger["repository_freshness"]["pre_goal"]
    proof["after"] = NEW
    with pytest.raises(supervisor.FreshnessHold, match="immutable freshness receipt"):
        instance.verify_goal_freshness_record(fixture.target, fixture.ledger)
    assert fixture.ledger["baseline_head"] == original_baseline


def test_remote_move_after_frozen_scope_holds_dispatch_without_refreeze(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    fixture.ledger["awaiting_goal"] = True
    fixture.ledger["issue_scope"] = {"fixed": "original"}
    before = copy.deepcopy(fixture.ledger)
    def moved(*_a, **_k):
        raise FreshnessError("remote_revision_moved_after_freeze")
    monkeypatch.setattr("kg_microbe_workflows.freshness.verify_inventory_head", moved)
    monkeypatch.setattr(instance, "freeze_stage_scope", lambda *_a, **_k: pytest.fail("cannot refreeze"))
    instance.check_workflow(fixture.target, fixture.ledger)
    with pytest.raises(supervisor.FreshnessHold, match="remote_revision_moved"):
        instance.dispatch(fixture.target, fixture.ledger, supervisor.decide(fixture.ledger, fixture.observation))
    assert fixture.ledger == before


def test_observation_cannot_fetch_or_activate(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adoption(fixture)
    ledger = supervisor.new_ledger(fixture.config, fixture.target)
    instance.freshness_runner = lambda *_a, **_k: pytest.fail("observe cannot fetch")
    with pytest.raises(supervisor.FreshnessHold, match="authorized apply"):
        instance.initialize_freshness(fixture.target, ledger, fixture.observation, apply=False)
    assert "repository_freshness" not in ledger


@pytest.mark.parametrize("wrong_predecessor", [False, True])
def test_adoption_only_at_exact_verified_final_closure(cycle_setup, monkeypatch, wrong_predecessor):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    fixture.ledger["stage"] = 6
    receipt = write_goal_evidence(fixture, fixture.ledger)
    fixture.remote.snapshot()
    before = copy.deepcopy(fixture.ledger)
    adoption(fixture, cycle=2, predecessor=("f" * 64 if wrong_predecessor else supervisor.digest(receipt)))
    events = engine_fixture(instance, fixture, monkeypatch)
    if wrong_predecessor:
        with pytest.raises(supervisor.FreshnessHold, match="adoption refused"):
            instance.advance(fixture.target, fixture.ledger, receipt, {"status": "merged"}, "native_completed", apply=True)
        assert not events
    else:
        next_stage = instance.advance(fixture.target, fixture.ledger, receipt, {"status": "merged"}, "native_completed", apply=True)
        assert (next_stage["cycle"], next_stage["stage"]) == (2, 1)
        assert next_stage["repository_freshness"]["adoption"]["boundary"]["predecessor_receipt_sha256"] == supervisor.digest(receipt)
        assert next_stage["baseline_head"] == NEW
        assert next_stage["workflow"] == before["workflow"]
        assert "repository_freshness" not in next_stage["completed_stages"][-1]
    assert fixture.ledger == before


def test_infrastructure_freeze_reads_updated_revision_after_gate(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    fixture.ledger["stage"] = 4
    review = write_goal_evidence(fixture, fixture.ledger)
    review_data = supervisor.goal_output_data(review, fixture.ledger, fixture.target)
    fixture.ledger["completed_stages"].append({"stage": 4, "cycle": 1, "goal_evidence": review["goal_outputs"]["goal_evidence"],
                                              "goal_evidence_snapshot": review_data})
    fixture.ledger["stage"] = 5
    receipt = write_goal_evidence(fixture, fixture.ledger)
    fixture.remote.snapshot()
    before = copy.deepcopy(fixture.ledger)
    def update(_phase):
        path = fixture.repo / "INFRA_TASKS.md"
        path.write_text(path.read_text() + "\nExternal backlog commit is now present.\n")
    events = engine_fixture(instance, fixture, monkeypatch, before=update)
    after = instance.advance(fixture.target, fixture.ledger, receipt, {"status": "merged"}, "native_completed", apply=True)
    assert events[0][0] == "pre_goal"
    assert "External backlog commit" in after["infra_scope"]["content"]
    assert after["baseline_head"] == NEW
    assert fixture.ledger == before


def test_archived_scope_is_never_overwritten_on_retry(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    fixture.ledger["stage"] = 6
    path = instance.directory(fixture.target) / "cycles/cycle-000001/infra-scope.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"evidence": "retain exactly"}\n')
    original = path.read_bytes()
    with pytest.raises(supervisor.FreshnessHold, match="already has an archived"):
        instance.freeze_stage_scope(fixture.target, fixture.ledger)
    assert path.read_bytes() == original


def test_owner_callback_rechecks_native_state_at_every_mutation_gate(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    def gate(_target, **kwargs):
        assert kwargs["owner_check"]() == {fixture.target["pid"]: " ".join(fixture.target["process_identity"].split())}
        fixture.observation["goal_state"] = "active"
        kwargs["owner_check"]()
        pytest.fail("changed native state must hold")
    instance.freshness_runner = gate
    before = copy.deepcopy(fixture.ledger)
    with pytest.raises(supervisor.FreshnessHold, match="completed idle boundary"):
        instance.ensure_boundary_freshness(fixture.target, fixture.ledger, phase="pre_goal", apply=True)
    assert fixture.ledger == before


def test_native_ps_column_padding_is_normalized_only_for_owner_scan(cycle_setup, monkeypatch):
    fixture = cycle_setup
    original = "1234  ttys030  Mon Nov  9 10:00:00 2026 agy"
    fixture.target["process_identity"] = original
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    assert fixture.target["process_identity"] == original
    assert fixture.ledger["repository_freshness"]["pre_goal"]["status"] == "verified"


@pytest.mark.parametrize("missing_proof", [False, True])
def test_no_change_closure_cannot_bypass_preinventory_gate(cycle_setup, monkeypatch, missing_proof):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    events = engine_fixture(instance, fixture, monkeypatch)
    receipt = copy.deepcopy(fixture.receipt)
    receipt.update(status="no_changes", pr=None, issues=[],
                   no_changes={"head_sha": HEAD, "explanation": "Audited scope already satisfied",
                               "no_goal_owned_changes": True, "no_open_goal_pr": True})
    if missing_proof:
        del fixture.ledger["repository_freshness"]["pre_goal"]
    fixture.remote.snapshot()
    instance.save(fixture.target, fixture.ledger)
    supervisor.atomic_json(instance.directory(fixture.target) / "completion.json", receipt)
    monkeypatch.setattr(instance, "dispatch", lambda *_a, **_k: {"state": "not-sent", "reason": "offline test"})
    instance.sweep(apply=True)
    after = supervisor.read_json(instance.directory(fixture.target) / "ledger.json")
    if missing_proof:
        assert not events
        assert after["stage"] == 1 and after["completed_stages"] == []
        assert after["phase"] == "blocked" and after["baseline_head"] == HEAD
    else:
        assert [row[0] for row in events if row[0] != "inventory"] == ["pre_goal"]
        assert after["stage"] == 2 and after["baseline_head"] == NEW
        closed = after["completed_stages"][0]
        assert closed["verification"]["status"] == "no_changes"
        assert closed["repository_freshness"]["pre_goal"]["after"] == HEAD
    assert fixture.ledger["baseline_head"] == HEAD


def test_input_controller_lock_blocks_freshness_without_native_input(cycle_setup, monkeypatch):
    fixture = cycle_setup
    instance = cycle_instance(fixture, monkeypatch)
    adopt_active(instance, fixture, monkeypatch)
    instance.freshness_runner = lambda *_a, **_k: pytest.fail("another input controller owns boundary")
    path = Path(fixture.config["input_lock_dir"]) / (Path(fixture.target["tty"]).name + ".lock")
    before = copy.deepcopy(fixture.ledger)
    with supervisor.file_lock(path), pytest.raises(supervisor.FreshnessHold, match="freshness held"):
        instance.ensure_boundary_freshness(fixture.target, fixture.ledger, phase="pre_goal", apply=True)
    assert fixture.ledger == before
