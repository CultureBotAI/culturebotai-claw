"""Offline release-boundary migration and complete issue-scope freeze checks (#849)."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_mech_session_supervisor import (
    FIX,
    GOAL,
    HEAD,
    cycle_instance,
    supervisor,
    write_goal_evidence,
)
from test_mech_session_supervisor import (
    cycle_setup as cycle_setup,
)
from test_mech_session_supervisor import (
    setup as setup,
)


def node(number, *, labels=()):
    return {"number": number, "title": f"Issue {number}", "updatedAt": "2026-01-01T00:00:00Z",
            "labels": {"totalCount": len(labels), "nodes": [{"name": label} for label in labels],
                       "pageInfo": {"hasNextPage": False}}}


def page(nodes, *, total=None, next_cursor=None):
    return {"data": {"repository": {"nameWithOwner": "CultureBotAI/TraitMech", "issues": {
        "totalCount": len(nodes) if total is None else total, "nodes": nodes,
        "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor}}}}}


class IssuePages:
    def __init__(self, pages=None):
        self.pages = pages or [page([])]
        self.calls = []

    def __call__(self, args, **kwargs):
        assert args[:3] == ["gh", "api", "graphql"]
        assert "owner=CultureBotAI" in args and "name=TraitMech" in args
        assert 0 < kwargs["timeout"] <= 45
        result = self.pages[len(self.calls)]
        self.calls.append(args)
        return SimpleNamespace(stdout=json.dumps(result), returncode=0, stderr="")


def candidate(setup):
    from kg_microbe_workflows import PARENT_PATH, SCHEMA_PATH, stage_keys_for_version

    directory = setup.repo / "workflow/next"
    directory.mkdir(parents=True, exist_ok=True)
    parent_path, schema_path = directory / "mech-cycle.yaml", directory / "workflow.yaml"
    parent_path.write_bytes(PARENT_PATH.read_bytes())
    schema_path.write_bytes(SCHEMA_PATH.read_bytes())
    profile = json.loads(Path(setup.target["workflow_profile_path"]).read_text())
    profile.update(schema_version="2.0.0", profile_version="2.0.0")
    profile["parent"].update(version="2.0.0", revision="d" * 40,
                             sha256=hashlib.sha256(parent_path.read_bytes()).hexdigest(),
                             schema_sha256=hashlib.sha256(schema_path.read_bytes()).hexdigest())
    profile["stages"] = [{"stage": stage, "key": key, "goal_text": f"Use the native skill for {key}",
                          "skill_paths": [".claude/skills/example/SKILL.md"], "applicability": "enabled"}
                         for stage, key in enumerate(stage_keys_for_version("2.0.0"), 1)]
    path = directory / "profile.yaml"
    path.write_text(json.dumps(profile))
    setup.target.update(workflow_next_profile_path=str(path), workflow_next_parent_path=str(parent_path),
                        workflow_next_schema_path=str(schema_path))
    effective = supervisor.load_effective(setup.config, setup.target, next_cycle=True)
    review = setup.repo / "migration-review.md"
    review.write_text("Reviewed exact six-to-seven migration at verified cycle boundary.\n")
    setup.target["workflow_parent_migration"] = {
        "from_sha256": setup.ledger["workflow"]["sha256"], "to_sha256": supervisor.digest(effective),
        "reviewed_by": "independent-reviewer", "reason": "Add issue triage before discovery in the next cycle",
        "review": {"artifact": str(review), "sha256": hashlib.sha256(review.read_bytes()).hexdigest()}}
    return effective


def with_issues(instance, remote, pages):
    def runner(args, **kwargs):
        return pages(args, **kwargs) if args[:3] == ["gh", "api", "graphql"] else remote(args, **kwargs)
    instance.runner = runner


def test_production_freeze_pages_every_issue_and_retains_original_metadata(cycle_setup):
    pages = IssuePages([page([node(i) for i in range(1, 101)], total=101, next_cursor="next"),
                        page([node(101, labels=["severity:high", "rollout:cycle-v2"])], total=101)])
    scope = supervisor.freeze_open_issues(cycle_setup.target, runner=pages)
    snapshot = json.loads(scope["content"])
    assert snapshot["total_count"] == 101 and snapshot["pages"] == 2 and snapshot["complete"] is True
    assert snapshot["issues"][100]["labels"] == ["rollout:cycle-v2", "severity:high"]
    assert scope["sha256"] == hashlib.sha256(scope["content"].encode()).hexdigest()
    assert scope["frozen_at"].endswith("Z")
    assert "cursor=next" in pages.calls[1]
    supervisor.validate_frozen_issue_scope(scope, cycle_setup.target)


@pytest.mark.parametrize("damage", ["incomplete", "count_changed", "duplicate", "labels", "future", "errors", "repository"])
def test_uncertain_or_partial_inventory_never_becomes_an_empty_scope(cycle_setup, damage):
    first = page([node(1)], total=2, next_cursor="next")
    second = page([node(2)], total=2)
    if damage == "incomplete":
        first["data"]["repository"]["issues"]["pageInfo"] = {"hasNextPage": False, "endCursor": None}
    elif damage == "count_changed":
        second["data"]["repository"]["issues"]["totalCount"] = 3
    elif damage == "duplicate":
        second["data"]["repository"]["issues"]["nodes"] = [node(1)]
    elif damage == "labels":
        first["data"]["repository"]["issues"]["nodes"][0]["labels"]["pageInfo"]["hasNextPage"] = True
    elif damage == "future":
        first["data"]["repository"]["issues"]["nodes"][0]["updatedAt"] = "2999-01-01T00:00:00Z"
    elif damage == "errors":
        first["errors"] = [{"message": "Unavailable"}]
    else:
        first["data"]["repository"]["nameWithOwner"] = "CultureBotAI/OtherMech"
    with pytest.raises(supervisor.SupervisorError, match="cannot freeze complete"):
        supervisor.freeze_open_issues(cycle_setup.target, runner=IssuePages([first, second]))


def test_capture_deadline_is_bounded_and_does_not_query_after_expiry(cycle_setup, monkeypatch):
    ticks = iter([0, 61])
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(ticks))
    pages = IssuePages()
    with pytest.raises(supervisor.SupervisorError, match="deadline"):
        supervisor.freeze_open_issues(cycle_setup.target, runner=pages)
    assert pages.calls == []


def test_inflight_six_goal_cycle_migrates_only_after_its_verified_final_closure(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    original_goal = copy.deepcopy(setup.ledger["adopted_goal"])
    setup.ledger["stage"] = 3
    historical = [{"stage": n, "cycle": 1, "goal_identity": original_goal, "receipt_sha256": str(n) * 64}
                  for n in (1, 2)]
    setup.ledger["completed_stages"] = copy.deepcopy(historical)
    effective = candidate(setup)
    pages = IssuePages([page([node(25)])])
    with_issues(instance, setup.remote, pages)
    instance.check_workflow(setup.target, setup.ledger)
    assert setup.ledger["workflow"]["effective"]["parent_version"] == "1.0.0"
    assert setup.ledger["adopted_goal"] == original_goal and pages.calls == []
    ledger = setup.ledger
    old_evidence = []
    for stage in range(3, 7):
        assert ledger["stage"] == stage and ledger["cycle"] == 1
        receipt = write_goal_evidence(setup, ledger)
        if receipt["goal_outputs"].get("goal_evidence"):
            descriptor = receipt["goal_outputs"]["goal_evidence"]
            old_evidence.append((setup.repo / descriptor["path"], descriptor["sha256"]))
        setup.remote.snapshot()
        ledger = instance.advance(setup.target, ledger, receipt, {"status": "merged"}, "native_completed")
        assert ledger["adopted_goal"] == original_goal
        if stage < 6:
            assert ledger["workflow"]["effective"]["parent_version"] == "1.0.0" and pages.calls == []
    assert (ledger["cycle"], ledger["stage"], ledger["parent_version"]) == (2, 1, "2.0.0")
    assert ledger["workflow"] == supervisor.pin_workflow(effective)
    assert ledger["cycle_versions"] == {"1": "1.0.0", "2": "2.0.0"}
    assert ledger["completed_stages"][:2] == historical
    assert [record["stage"] for record in ledger["completed_stages"]] == list(range(1, 7))
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == sha for path, sha in old_evidence)
    assert ledger["issue_scope"]["issues"][0]["number"] == 25 and len(pages.calls) == 1
    assert ledger["awaiting_goal"] and supervisor.workflow_stage_key(ledger) == "open_issue_triage"
    assert supervisor.previous_evidence(ledger, 5)["stage"] == 5  # v2 review carries v1 resolution.
    assert ledger["parent_migrations"][0]["from_cycle"] == 1
    message = supervisor.message_for(setup.target, ledger, {"action": "start_goal", "action_id": "new"}, instance.directory(setup.target))
    assert message.startswith("/goal Use the native skill for open_issue_triage")


@pytest.mark.parametrize("damage", ["missing_review", "wrong_pair", "uncommitted_review", "uncommitted_parent"])
def test_failed_migration_keeps_final_goal_receipt_and_history(cycle_setup, monkeypatch, damage):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 6
    candidate(setup)
    receipt = write_goal_evidence(setup, setup.ledger)
    setup.remote.snapshot()
    if damage == "missing_review":
        setup.target.pop("workflow_parent_migration")
    elif damage == "wrong_pair":
        setup.target["workflow_parent_migration"]["to_sha256"] = "f" * 64
    elif damage == "uncommitted_review":
        setup.remote.tree.pop("migration-review.md")
    else:
        setup.remote.tree.pop("workflow/next/mech-cycle.yaml")
    before = copy.deepcopy(setup.ledger)
    path = instance.directory(setup.target) / "completion.json"
    supervisor.atomic_json(path, receipt)
    with pytest.raises(supervisor.SupervisorError, match="migration|committed"):
        instance.advance(setup.target, setup.ledger, receipt, {"status": "merged"}, "native_completed")
    assert setup.ledger == before and supervisor.read_json(path) == receipt


def test_restart_after_release_preserves_inflight_legacy_goal_and_effective_hash(cycle_setup, monkeypatch):
    from kg_microbe_workflows import (
        LEGACY_PARENT_PATH,
        LEGACY_SCHEMA_PATH,
        PARENT_PATH,
        SCHEMA_PATH,
    )
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    old_parent, old_schema = setup.repo / "installed-parent.yaml", setup.repo / "installed-schema.yaml"
    old_parent.write_bytes(LEGACY_PARENT_PATH.read_bytes())
    old_schema.write_bytes(LEGACY_SCHEMA_PATH.read_bytes())
    setup.config.update(workflow_parent_path=str(old_parent), workflow_schema_path=str(old_schema))
    effective = supervisor.load_effective(setup.config, setup.target)
    setup.ledger["workflow"] = supervisor.pin_workflow(effective)
    setup.ledger["stage"] = 3
    setup.target["_workflow"] = effective
    instance.save(setup.target, setup.ledger)
    original = copy.deepcopy(setup.ledger)
    # The installed default release changes, while the assessed runtime remains v1.
    old_parent.write_bytes(PARENT_PATH.read_bytes())
    old_schema.write_bytes(SCHEMA_PATH.read_bytes())
    setup.config.pop("workflow_parent_path")
    setup.config.pop("workflow_schema_path")
    monkeypatch.setattr(supervisor, "ROOT", setup.runtime.parents[1])
    loaded = supervisor.validate_config(copy.deepcopy(setup.config), resolve_repositories=False)
    assert loaded["targets"][0]["_workflow"] == effective
    restored = supervisor.Supervisor(loaded, native=instance.native, notifier=instance.notifier, runner=setup.remote)
    restored.check_workflow(loaded["targets"][0], setup.ledger)
    assert setup.ledger == original


def test_stage_zero_remains_not_started_and_does_not_freeze_issues(cycle_setup):
    effective = candidate(cycle_setup)
    target = copy.deepcopy(cycle_setup.target)
    target.update(_workflow=effective, stages=effective["stages"], initial_stage=0)
    pages = IssuePages()
    ledger = supervisor.new_ledger(cycle_setup.config, target, runner=pages)
    assert ledger["stage"] == 0 and supervisor.workflow_stage_key(ledger) is None
    assert supervisor.last_stage(ledger) == 7 and "issue_scope" not in ledger and pages.calls == []


def test_frozen_issue_scope_survives_restart_and_new_arrivals(cycle_setup, monkeypatch):
    setup = cycle_setup
    effective = candidate(setup)
    setup.target.update(_workflow=effective, stages=effective["stages"])
    pages = IssuePages([page([node(25)])])
    ledger = supervisor.new_ledger(setup.config, setup.target, runner=pages)
    ledger.update(adopted_goal=copy.deepcopy(GOAL), baseline_head=HEAD, baseline_status="")
    instance = cycle_instance(setup, monkeypatch)
    with_issues(instance, setup.remote, pages)
    instance.save(setup.target, ledger)
    instance.check_workflow(setup.target, ledger)
    scope = copy.deepcopy(ledger["issue_scope"])
    pages.pages.append(page([node(25), node(26)]))
    instance.sweep(apply=False)
    restored = supervisor.read_json(instance.directory(setup.target) / "ledger.json")
    assert restored["issue_scope"] == scope and len(pages.calls) == 1
    assert [row["number"] for row in json.loads(scope["content"])["issues"]] == [25]


def test_direct_four_goal_to_v2_adoption_is_refused(cycle_setup):
    effective = candidate(cycle_setup)
    legacy = copy.deepcopy(cycle_setup.ledger)
    legacy["schema_version"] = 1
    with pytest.raises(supervisor.SupervisorError, match="first adopt.*six-goal"):
        supervisor.migrate_ledger(legacy, cycle_setup.target, effective)


def stage_one_receipt(setup, *, empty=False, blocked=False):
    from test_issue_triage_contract import materialize, triage_evidence

    from kg_microbe_workflows import evidence_directory
    effective = candidate(setup)
    ledger = copy.deepcopy(setup.ledger)
    data = triage_evidence(setup.repo, empty=empty)
    for issue in data["issue_triage"]["dispositions"]:
        if issue["status"] == "fixed":
            issue.update(pr_urls=[f"https://github.com/{setup.target['github_repository']}/pull/42"], commit_sha=FIX)
    if blocked:
        triage = data["issue_triage"]
        triage["dispositions"][0].update(status="blocked", prerequisite="Needs upstream decision")
        triage["carry_forward_group_ids"].append("mandatory")
        triage["budget"] = {"limit_seconds": 14400, "selected_group_ids": [], "work_intervals": [],
                            "unused_reason": "Required work blocked before optional budget"}
        data["outcome"] = "blocked"
    materialize(setup.repo, data)
    ledger.update(run_id=data["run_id"], stage=1, workflow=supervisor.pin_workflow(effective),
                  parent_version="2.0.0", cycle_versions={"1": "2.0.0"})
    artifact = next(item for item in data["artifacts"] if item["kind"] == "issue_inventory")
    content = (setup.repo / artifact["path"]).read_text()
    ledger["issue_scope"] = {"sha256": artifact["sha256"], "content": content,
                             "frozen_at": data["scope_frozen_at"], "issues": json.loads(content)["issues"]}
    path = setup.repo / evidence_directory(data["run_id"], 1, 1, 1) / "evidence.yaml"
    path.write_text(json.dumps(data))
    receipt = copy.deepcopy(setup.receipt)
    receipt.update(run_id=ledger["run_id"], workflow_sha256=ledger["workflow"]["sha256"],
                   issues=[] if empty else [{"number": 1, "disposition": "addressed", "fix_commit_sha": FIX}])
    receipt["goal_outputs"]["goal_evidence"] = {"path": str(path.relative_to(setup.repo)),
                                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return ledger, receipt, data


def test_stage_one_requires_exact_supervisor_scope_and_holds_critical_blockers(cycle_setup):
    ledger, receipt, data = stage_one_receipt(cycle_setup)
    assert supervisor.goal_output_data(receipt, ledger, cycle_setup.target) == data
    ledger["issue_scope"]["sha256"] = "f" * 64
    with pytest.raises(supervisor.SupervisorError, match="supervisor-frozen issue inventory"):
        supervisor.goal_output_data(receipt, ledger, cycle_setup.target)
    ledger, receipt, _ = stage_one_receipt(cycle_setup, blocked=True)
    with pytest.raises(supervisor.SupervisorError, match="critical/high issue prerequisites"):
        supervisor.goal_output_data(receipt, ledger, cycle_setup.target)


def test_critical_resolution_keeps_independent_historical_provenance(cycle_setup):
    ledger, receipt, _ = stage_one_receipt(cycle_setup)
    receipt["issues"] = []
    assert supervisor.goal_output_data(receipt, ledger, cycle_setup.target)["issue_triage"]["dispositions"][0]["status"] == "fixed"


def test_renumbered_stage_four_no_longer_requires_record_review_outputs(cycle_setup):
    effective = candidate(cycle_setup)
    ledger = copy.deepcopy(cycle_setup.ledger)
    ledger.update(stage=4, workflow=supervisor.pin_workflow(effective))
    assert supervisor.workflow_stage_key(ledger) == "protein_examples"
    assert "goal_evidence" not in supervisor.receipt_template(ledger, cycle_setup.target)["goal_outputs"]
    assert supervisor.goal_output_data(cycle_setup.receipt, ledger, cycle_setup.target) is None


def test_stage_seven_freezes_infrastructure_with_unchanged_policy(cycle_setup):
    effective = candidate(cycle_setup)
    target = copy.deepcopy(cycle_setup.target)
    target.update(_workflow=effective, stages=effective["stages"], initial_stage=7)
    pages = IssuePages()
    ledger = supervisor.new_ledger(cycle_setup.config, target, runner=pages)
    assert supervisor.workflow_stage_key(ledger) == "infrastructure"
    assert ledger["infra_scope"]["content"] == (cycle_setup.repo / "INFRA_TASKS.md").read_text()
    assert effective["infrastructure_policy"] == cycle_setup.ledger["workflow"]["effective"]["infrastructure_policy"]
    assert pages.calls == []
