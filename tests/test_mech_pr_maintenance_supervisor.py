"""Parent 2.1 freezes separate PR scope and preserves old-cycle boundaries."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest
from test_mech_cycle_v2_migration import candidate, stage_one_receipt
from test_mech_session_supervisor import cycle_instance, supervisor
from test_mech_session_supervisor import cycle_setup as cycle_setup
from test_mech_session_supervisor import setup as setup
from test_multi_pr_receipts import duf as duf
from test_pr_maintenance import evidence as pr_evidence
from test_pr_maintenance import row, snapshot

from kg_microbe_workflows import PARENT_PATH, WorkflowError, load_document, validate_parent


def maintenance_receipt(state, rows=None):
    ledger, receipt, data = stage_one_receipt(state, empty=True)
    effective = candidate(state, version="2.1.0")
    ledger.update(workflow=supervisor.pin_workflow(effective), parent_version="2.1.0",
                  cycle_versions={"1": "2.1.0"})
    receipt["workflow_sha256"] = ledger["workflow"]["sha256"]
    data.update(parent_version="2.1.0", pr_maintenance=pr_evidence(rows)["pr_maintenance"])
    if rows:
        data["outcome"] = "completed"
    frozen = snapshot(rows)
    frozen["repository"] = state.target["github_repository"]
    raw = json.dumps(frozen, indent=2, sort_keys=True) + "\n"
    ledger["pr_scope"] = {"content": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest(),
        **{key: frozen[key] for key in ("prs", "frozen_at", "open_non_draft_limit", "limit_source")}}
    path = state.repo / receipt["goal_outputs"]["goal_evidence"]["path"]
    for kind, content in (("pr_inventory", raw), ("pr_dispositions", json.dumps({"pr_maintenance": data["pr_maintenance"]}))):
        artifact = path.parent / (kind + ".json")
        artifact.write_text(content)
        data["artifacts"].append({"path": artifact.relative_to(state.repo).as_posix(),
                                 "kind": kind, "sha256": hashlib.sha256(content.encode()).hexdigest()})
    for disposition in data["pr_maintenance"]["dispositions"]:
        disposition["resolution_evidence"] = [data["artifacts"][0]["path"]]
    save(state, receipt, data)
    return ledger, receipt, data


def save(state, receipt, data):
    path = state.repo / receipt["goal_outputs"]["goal_evidence"]["path"]
    pr_artifact = next(a for a in data["artifacts"] if a["kind"] == "pr_dispositions")
    output = state.repo / pr_artifact["path"]
    output.write_text(json.dumps({"pr_maintenance": data["pr_maintenance"]}))
    pr_artifact["sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    path.write_text(json.dumps(data))
    receipt["goal_outputs"]["goal_evidence"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_parent_policy_cannot_be_omitted_to_disable_required_outputs():
    parent = load_document(PARENT_PATH.read_bytes())
    parent.pop("pr_maintenance_policy")
    with pytest.raises(WorkflowError, match="PR maintenance.*policy"):
        validate_parent(parent)


def test_parent_cannot_remove_pr_outputs_or_owned_worktree_step():
    for kind in ("pr_inventory", "pr_dispositions", "delete_worktree"):
        parent = load_document(PARENT_PATH.read_bytes())
        values = parent["closure_policy"]["steps"] if kind == "delete_worktree" else parent["stages"][0]["required_outputs"]
        values.remove(kind)
        with pytest.raises(WorkflowError):
            validate_parent(parent)


def test_scope_binds_separate_issue_and_pr_cutoffs(cycle_setup):
    ledger, receipt, data = maintenance_receipt(cycle_setup)
    assert ledger["issue_scope"]["frozen_at"] != ledger["pr_scope"]["frozen_at"]
    assert supervisor.goal_output_data(receipt, ledger, cycle_setup.target) == data
    ledger["pr_scope"]["sha256"] = "f" * 64
    with pytest.raises(WorkflowError, match="checksum"):
        supervisor.goal_output_data(receipt, ledger, cycle_setup.target)


def test_missing_pr_output_cannot_reuse_an_old_stage_one_manifest(cycle_setup):
    ledger, receipt, data = maintenance_receipt(cycle_setup)
    data["artifacts"] = [a for a in data["artifacts"] if a["kind"] != "pr_inventory"]
    save(cycle_setup, receipt, data)
    with pytest.raises(WorkflowError, match="required|pr_inventory"):
        supervisor.goal_output_data(receipt, ledger, cycle_setup.target)


def test_green_pr_blocker_holds_otherwise_empty_issue_goal(cycle_setup):
    ledger, receipt, data = maintenance_receipt(cycle_setup, [row(green=True)])
    data["outcome"] = "blocked"
    data["pr_maintenance"]["dispositions"][0].update(status="blocked", prerequisite="Recorded missing merge authority")
    save(cycle_setup, receipt, data)
    with pytest.raises(supervisor.SupervisorError, match="PR maintenance closure prerequisites"):
        supervisor.goal_output_data(receipt, ledger, cycle_setup.target)


def test_new_parent_freezes_pr_scope_only_after_freshness_boundary(cycle_setup, monkeypatch):
    state = cycle_setup
    effective = candidate(state, version="2.1.0")
    state.target.update(_workflow=effective, stages=effective["stages"], initial_stage=1,
                        freshness_adoption={"path": "synthetic", "sha256": "a" * 64})
    monkeypatch.setattr(supervisor, "freeze_open_issues", lambda *_a, **_k: pytest.fail("premature issue freeze"))
    monkeypatch.setattr(supervisor, "freeze_open_prs", lambda *_a, **_k: pytest.fail("premature PR freeze"))
    ledger = supervisor.new_ledger(state.config, state.target)
    assert ledger["freshness_initial_pending"]
    assert "pr_scope" not in ledger and "issue_scope" not in ledger


def test_pr_scope_is_archived_and_reused_after_restart(cycle_setup, monkeypatch):
    state = cycle_setup
    ledger, _, _ = maintenance_receipt(state)
    instance = cycle_instance(state, monkeypatch)
    original = copy.deepcopy(ledger["pr_scope"])
    calls = []
    monkeypatch.setattr(supervisor, "freeze_open_issues", lambda *_a, **_k: ledger["issue_scope"])
    def freeze(*_a, **_k):
        calls.append(1)
        return copy.deepcopy(original)
    monkeypatch.setattr(supervisor, "freeze_open_prs", freeze)
    instance.freeze_stage_scope(state.target, ledger)
    instance.freeze_stage_scope(state.target, ledger)
    assert calls == [1] and ledger["pr_scope"] == original
    archive = instance.directory(state.target) / "cycles/cycle-000001/pr-scope.json"
    assert json.loads(archive.read_text()) == original


def test_new_cleanup_template_requires_evidence_without_claiming_deletion(cycle_setup):
    ledger, _, _ = maintenance_receipt(cycle_setup)
    cleanup = supervisor.receipt_template(ledger, cycle_setup.target)["cleanup"]
    assert cleanup["worktree_paths"] == []
    assert cleanup["worktree_cleanup"] == {"artifact": "", "sha256": ""}
    assert cleanup["local_branch_deleted"] is False


def test_parent_20_to_21_migration_requires_final_boundary_exact_review(cycle_setup, monkeypatch):
    state = cycle_setup
    old = candidate(state)
    ledger = copy.deepcopy(state.ledger)
    ledger.update(workflow=supervisor.pin_workflow(old), stage=7)
    state.ledger = ledger
    new = candidate(state, version="2.1.0")
    instance = cycle_instance(state, monkeypatch)
    assert instance.verify_parent_migration(state.target, ledger, new)["to_parent_version"] == "2.1.0"
    ledger["stage"] = 1
    with pytest.raises(supervisor.SupervisorError, match="cycle-boundary"):
        instance.verify_parent_migration(state.target, ledger, new)


@pytest.mark.parametrize("damage", [None, "foreign_head", "foreign_old_commit", "pre_goal_merge", "unfrozen_old_pr", "old_final_integration"])
def test_backlog_closure_keeps_old_commits_only_under_exact_frozen_ancestry(duf, monkeypatch, damage):
    """Exercise the existing full ordered Git proof with historical backlog dates.

    Receipt/evidence shape is separately tested above; here the archived DUF
    fixture isolates the changed temporal/association checks without inventing
    live native-goal adoption or weakening any production validator.
    """
    from test_multi_pr_receipts import EARLY_FIX, FIRST, LAST, write_registry
    from test_pr_maintenance import snapshot

    state = duf
    evidence = supervisor.goal_output_data(state.receipt, state.ledger, state.target)
    state.ledger["workflow"]["effective"]["parent_version"] = "2.1.0"
    state.ledger.update(parent_version="2.1.0", cycle=4, stage=1)
    state.ledger["cycle_versions"]["4"] = "2.1.0"
    state.ledger["workflow"]["effective"]["stages"][state.ledger["stage"] - 1]["key"] = "open_issue_triage"
    frozen_head = "e" * 40
    pr = row(FIRST["number"], green=True, updated="2026-10-24T12:00:00Z")
    pr.update(head_sha=frozen_head, head_branch=FIRST["branch"])
    frozen = snapshot([pr])
    frozen.update(repository=state.target["github_repository"], frozen_at="2026-10-25T17:05:00Z")
    raw = json.dumps(frozen)
    state.ledger["pr_scope"] = {"content": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest(),
        **{key: frozen[key] for key in ("prs", "frozen_at", "open_non_draft_limit", "limit_source")}}
    evidence["pr_maintenance"] = {"dispositions": [{"number": FIRST["number"], "status": "merged"}]}
    state.remote.prs[FIRST["number"]]["created_at"] = "2026-10-24T12:00:00Z"
    for commit in state.remote.commits[FIRST["number"]]:
        commit["commit"]["committer"]["date"] = "2026-10-24T12:00:00Z"
    # Earlier-goal ownership is retained; only the new integration PR is bound
    # to this goal. The snapshot supplies reviewed backlog membership.
    from kg_microbe_progress import prs
    write_registry(state, [{**prs._context(state.ledger), "schema_version": 1,
                           "pr_number": LAST["number"], "reported_at": "2026-10-25T19:10:00Z"}])
    monkeypatch.setattr(supervisor, "validate_receipt", lambda *_a, **_k: [])
    if damage == "foreign_head":
        state.remote.ancestry_fail.add((frozen_head, FIRST["head_sha"]))
    elif damage == "foreign_old_commit":
        state.remote.ancestry_fail.add((EARLY_FIX, frozen_head))
    elif damage == "pre_goal_merge":
        state.remote.prs[FIRST["number"]]["merged_at"] = "2026-10-24T13:00:00Z"
    elif damage == "unfrozen_old_pr":
        evidence["pr_maintenance"]["dispositions"] = []
    elif damage == "old_final_integration":
        state.remote.prs[LAST["number"]]["created_at"] = "2026-10-24T12:00:00Z"
    def verify():
        return supervisor.verify_ordered_prs(state.receipt, state.ledger, state.target, state.session, evidence, state.remote)
    if damage:
        with pytest.raises(supervisor.SupervisorError, match="frozen ancestry|closure window|association"):
            verify()
    else:
        assert [p["pr_number"] for p in verify()["prs"]] == [FIRST["number"], LAST["number"]]



def test_transient_pr_capture_failure_leaves_no_partial_freshness_archive(cycle_setup, monkeypatch):
    state = cycle_setup
    ledger, _, _ = maintenance_receipt(state)
    issue_scope, pr_scope = ledger.pop("issue_scope"), ledger.pop("pr_scope")
    ledger["repository_freshness"] = {"pre_goal": {"after": "a" * 40}}
    original = copy.deepcopy(ledger)
    instance = cycle_instance(state, monkeypatch)
    monkeypatch.setattr(supervisor, "freeze_open_issues", lambda *_a, **_k: issue_scope)
    def fail(*_args, **_kwargs):
        raise WorkflowError("synthetic transient PR API failure")
    monkeypatch.setattr(supervisor, "freeze_open_prs", fail)
    with pytest.raises(WorkflowError, match="transient"):
        instance.freeze_stage_scope(state.target, ledger)
    issue_path = instance.directory(state.target) / "cycles/cycle-000001/issue-scope.json"
    assert not issue_path.exists() and not issue_path.with_name("pr-scope.json").exists()
    assert ledger == original
    monkeypatch.setattr(supervisor, "freeze_open_prs", lambda *_a, **_k: pr_scope)
    instance.freeze_stage_scope(state.target, ledger)
    assert json.loads(issue_path.read_text()) == issue_scope
    assert json.loads(issue_path.with_name("pr-scope.json").read_text()) == pr_scope
    with pytest.raises(supervisor.FreshnessHold, match="archived inventory"):
        instance.freeze_stage_scope(state.target, ledger)
