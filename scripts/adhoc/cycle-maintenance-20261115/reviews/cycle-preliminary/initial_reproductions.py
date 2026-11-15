"""Independent read-only reproductions for root-owned maintenance integration.

Run from the reviewed worktree with PYTHONPATH=.:src:tests and pytest this file.
Fixtures are disposable; implementation files and GitHub state are never written.
"""
import copy
import json

import pytest
from test_mech_pr_maintenance_supervisor import maintenance_receipt
from test_mech_session_supervisor import cycle_instance, supervisor
from test_mech_session_supervisor import cycle_setup as cycle_setup
from test_mech_session_supervisor import setup as setup
from test_progress_prs import session as session

from kg_microbe_progress import prs
from kg_microbe_workflows import WorkflowError
from kg_microbe_workflows import pr_maintenance_remote as remote


def test_reopened_draft_is_accepted_by_final_inventory(monkeypatch):
    repo, head = "CultureBotAI/ExampleMech", "a" * 40
    class Observer:
        def __init__(self, *_args, **_kwargs):
            pass
        def live_pr(self, number):
            return {"number": number, "url": f"https://github.com/{repo}/pull/{number}",
                    "headRefOid": head, "state": "CLOSED", "merged": False}
        def open_prs(self):
            return ([{"number": 1, "isDraft": True, "headRefOid": head}], 1)
    monkeypatch.setattr(remote, "Observer", Observer)
    evidence = {"pr_maintenance": {"inventory": [{"number": 1, "is_draft": True}],
        "dispositions": [{"number": 1, "head_sha": head, "status": "closed_stale"}],
        "shared_check_fixes": [], "remaining_open_non_draft": [], "open_non_draft_limit": 25}}
    result = remote.verify_dispositions_live(evidence, {"github_repository": repo}, {"pr": None}, {}, None)
    assert result["prs"][0]["state"] == "CLOSED"
    print("BUG: reopened draft present in final complete inventory accepted as CLOSED")


def test_backlog_receipt_adds_new_goal_association(session):
    prs.register_pr(session.root, 42)
    old = prs._context(session.ledger)
    session.ledger.update(cycle=2, parent_version="2.1.0",
        adopted_goal={**session.ledger["adopted_goal"], "start_step_index": 99},
        completed_stages=[{key: old[key] for key in ("cycle", "stage", "goal_identity", "workflow_sha256")}],
        pr_scope={"prs": [{"number": 42}]})
    (session.root / "ledger.json").write_text(json.dumps(session.ledger))
    (session.root / "status.json").write_text(json.dumps(prs._context(session.ledger)))
    prs.register_pr(session.root, 43)
    def member(number):
        head = ("a" if number == 42 else "b") * 40
        return {"number": number, "head_sha": head,
            "merge_commit_sha": ("d" if number == 42 else "e") * 40,
            "branch": f"topic/{number}", "base": "main",
            "review": {"status": "complete", "remaining_findings": 0, "head_sha": head},
            "validation": [{"command": "pytest", "status": "passed", "head_sha": head}],
            "cleanup": {"checkout_ready": True, "local_branch_deleted": True, "remote_branch_deleted": True}}
    members = [member(42), member(43)]
    final = members[-1]
    candidate = {**prs._context(session.ledger), "schema_version": 2, "status": "completed", "prs": members,
        "pr": {key: final[key] for key in ("number", "head_sha", "branch", "base")},
        **{key: final[key] for key in ("review", "validation", "cleanup")},
        "issues": [], "evidence_attributions": []}
    (session.root / "completion.json").write_text(json.dumps(candidate))
    result = prs.collect_associations([session.runtime])
    contexts = [(r["cycle"], r["stage"]) for r in result.records if r["pr_number"] == 42]
    assert contexts == [(1, 1), (2, 1)]
    print("BUG: old PR 42 receives current-goal association from maintenance receipt:", contexts)


def test_partial_fresh_freeze_cannot_retry(cycle_setup, monkeypatch):
    state = cycle_setup
    ledger, _, _ = maintenance_receipt(state)
    ledger["repository_freshness"] = {"pre_goal": {"after": "a" * 40}}
    instance = cycle_instance(state, monkeypatch)
    scope = copy.deepcopy(ledger["issue_scope"])
    monkeypatch.setattr(supervisor, "freeze_open_issues", lambda *_a, **_k: scope)
    def fail(*_args, **_kwargs):
        raise WorkflowError("synthetic transient PR API failure")
    monkeypatch.setattr(supervisor, "freeze_open_prs", fail)
    with pytest.raises(WorkflowError, match="transient"):
        instance.freeze_stage_scope(state.target, ledger)
    issue_path = instance.directory(state.target) / "cycles/cycle-000001/issue-scope.json"
    assert issue_path.exists() and not issue_path.with_name("pr-scope.json").exists()
    with pytest.raises(supervisor.FreshnessHold, match="archived inventory"):
        instance.freeze_stage_scope(state.target, ledger)
    print("BUG: transient PR capture failure persists issue scope and then prohibits retry")
