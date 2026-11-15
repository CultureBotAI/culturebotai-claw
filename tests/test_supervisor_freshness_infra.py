"""Fetched-blob provenance for adopted infrastructure scope, using real Git."""
import json
import subprocess

import pytest
from test_goal_freshness import git
from test_goal_freshness import isolated_git as isolated_git
from test_mech_session_supervisor import (
    cycle_instance,
    supervisor,
)
from test_mech_session_supervisor import (
    cycle_setup as cycle_setup,
)
from test_mech_session_supervisor import (
    setup as setup,
)
from test_supervisor_freshness import adoption

from kg_microbe_workflows import freshness as fresh
from plugins.lock_manager import LockManager

NOTEBOOK = '''# Infrastructure tasks

<!-- mech-infra-tasks:start -->
```yaml
schema_version: "1.0.0"
tasks:
  - task_id: local-only-task
    summary: This task exists only in the local notebook, never the fetched tree
    status: note
```
<!-- mech-infra-tasks:end -->
'''

@pytest.mark.parametrize("kind", ["untracked", "ignored", "tracked", "changed_after_gate", "missing_after_gate"])
def test_adopted_infra_only_freezes_fetched_regular_blob(cycle_setup, monkeypatch, kind):
    fixture = cycle_setup
    root = fixture.repo
    origin = root.parent / "origin.git"
    (root / "INFRA_TASKS.md").write_text(NOTEBOOK)
    (root / ".gitignore").write_text(".scratch/\n" + ("INFRA_TASKS.md\n" if kind == "ignored" else ""))
    git(root, "init", "--initial-branch=main")
    git(root, "add", "--", ".gitignore", ".claude", "workflow", "review.txt")
    if kind in {"tracked", "changed_after_gate", "missing_after_gate"}:
        git(root, "add", "--", "INFRA_TASKS.md")
    git(root, "commit", "-m", "Published fixture inputs")
    git(root.parent, "init", "--bare", "--initial-branch=main", str(origin))
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "--set-upstream", "origin", "main")
    head = git(root, "rev-parse", "HEAD")
    tree = git(root, "ls-tree", "-r", "HEAD", "--", "INFRA_TASKS.md")
    assert bool(tree) == (kind in {"tracked", "changed_after_gate", "missing_after_gate"})
    identity = fresh._repository_identity
    monkeypatch.setattr(fresh, "_repository_identity", lambda value: fixture.target["github_repository"] if value == str(origin) else identity(value))
    monkeypatch.setattr(fresh, "owner_snapshot", lambda roots, allowed: {"checked_at": fresh.utc(), "allowed": {str(k): v for k, v in allowed.items()}, "cwd_holders": {}})
    locks = LockManager({"locks_dir": root.parent / "repo-locks", "my_id": "independent-offline-review"})
    monkeypatch.setattr("plugins.lock_manager.LockManager", lambda: locks)
    simulated_sends = []
    def fake_send(_js, payload):
        simulated_sends.append(payload)
        return "sent"
    instance = cycle_instance(fixture, monkeypatch, send=fake_send)
    def local_git_only(args, **kwargs):
        assert args[0] == "git", args
        return subprocess.run(args, capture_output=True, text=True, check=True)
    instance.runner = local_git_only
    adoption(fixture)
    instance.freshness_adoption(fixture.target, fixture.ledger, activate=True)
    fixture.ledger.update(stage=6, awaiting_goal=True)
    fixture.ledger.pop("baseline_head")
    fixture.ledger.pop("baseline_status")
    if kind == "untracked":
        with pytest.raises(supervisor.FreshnessHold, match="dirty_or_staged_checkout"):
            instance.ensure_boundary_freshness(fixture.target, fixture.ledger, phase="pre_goal", apply=True)
        assert "infra_scope" not in fixture.ledger
        assert not simulated_sends
        assert (root / "INFRA_TASKS.md").read_text() == NOTEBOOK
        return
    result = instance.ensure_boundary_freshness(fixture.target, fixture.ledger, phase="pre_goal", apply=True)
    assert result["status"] == "verified", result
    assert result["after"] == result["fetched"] == head
    instance.verify_pre_goal_freshness(fixture.target, fixture.ledger)
    if kind == "changed_after_gate":
        (root / "INFRA_TASKS.md").write_text(NOTEBOOK + "\nLocal-only replacement\n")
    if kind == "missing_after_gate":
        (root / "INFRA_TASKS.md").unlink()
    if kind in {"ignored", "changed_after_gate", "missing_after_gate"}:
        with pytest.raises(supervisor.FreshnessHold, match="infrastructure"):
            instance.freeze_stage_scope(fixture.target, fixture.ledger)
        assert "infra_scope" not in fixture.ledger
        assert "baseline_head" not in fixture.ledger
        assert not (instance.directory(fixture.target) / "cycles/cycle-000001/infra-scope.json").exists()
        assert not simulated_sends
        return
    instance.freeze_stage_scope(fixture.target, fixture.ledger)
    instance.baseline(fixture.target, fixture.ledger)
    frozen = fixture.ledger["infra_scope"]
    assert frozen["content"] == NOTEBOOK
    assert frozen["tasks"][0]["task_id"] == "local-only-task"
    assert fixture.ledger["baseline_head"] == head
    baseline = fixture.ledger["baseline_status"]
    assert ("?? INFRA_TASKS.md" in baseline) == (kind == "untracked")
    decision = supervisor.decide(fixture.ledger, fixture.observation)
    assert decision["phase"] == "ready_to_dispatch", decision
    action = instance.dispatch(fixture.target, fixture.ledger, decision)
    assert action["state"] == "uncertain", action
    assert len(simulated_sends) == 1
    print(json.dumps({"kind": kind, "head": head, "fetched_tree_has_notebook": bool(tree), "freshness_status": result["status"], "baseline_status": baseline, "frozen_notebook_sha256": frozen["sha256"], "frozen_task_ids": [t["task_id"] for t in frozen["tasks"]], "decision": decision["phase"], "simulated_transport_calls": len(simulated_sends), "action_state": action["state"]}, sort_keys=True))


def test_fetched_symlink_is_not_a_regular_scope_blob(tmp_path):
    git(tmp_path, "init", "--initial-branch=main")
    (tmp_path / "target").write_text(NOTEBOOK)
    (tmp_path / "INFRA_TASKS.md").symlink_to("target")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Symlink fixture")
    head = git(tmp_path, "rev-parse", "HEAD")
    with pytest.raises(supervisor.FreshnessHold, match="regular"):
        supervisor.verify_fetched_infrastructure({"root": str(tmp_path)}, head, b"target")
