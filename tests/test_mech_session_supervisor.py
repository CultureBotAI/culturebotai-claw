"""Offline regression coverage for session identity, delivery, and closure gates."""
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "mech_session_supervisor", Path(__file__).parents[1] / "scripts/mech_session_supervisor.py")
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)

HEAD = "a" * 40
MERGE = "b" * 40
FIX = "c" * 40
GOAL = {"conversation_id": "conversation-one", "started_at": "2026-10-19T10:00:00+00:00", "start_step_index": 12}


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "TraitMech"
    skill = repo / ".claude/skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("Example canonical skill\n")
    runtime = tmp_path / "workspace/run"
    runtime.mkdir(parents=True)
    workflow = runtime / "instructions.md"
    workflow.write_text("Finish the current goal and write the closure receipt.\n")
    target = {"repository_key": "traitmech", "root": str(repo), "github_repository": "CultureBotAI/TraitMech",
              "native_session_id": "conversation-one", "pid": 1234, "tty": "/dev/ttys030",
              "process_identity": "1234 ttys030 Mon Oct 19 10:00:00 2026 agy",
              "workflow_prompt_path": str(workflow), "initial_stage": 1, "default_branch": "main",
              "initial_goal_identity": dict(GOAL),
              "stages": [{"stage": stage, "goal_text": f"Complete stage {stage}", "skill_paths": [str(skill)]}
                         for stage in range(1, 5)]}
    config = {"run_id": "run-one", "runtime_dir": str(runtime), "targets": [target],
              "input_lock_dir": str(tmp_path / "locks"), "native_reader_path": "/unused/native.py",
              "notifier_path": "/unused/notifier.py", "history_path": str(tmp_path / "history.jsonl")}
    ledger = supervisor.new_ledger(config, target)
    ledger.update(adopted_goal=copy.deepcopy(GOAL), baseline_status="", baseline_head=HEAD)
    observation = {"ready": True, "observed_at": supervisor.now(), "goal_identity": copy.deepcopy(GOAL),
                   "goal_state": "completed", "native": {"conversation_id": GOAL["conversation_id"],
                       "current_goal": {**GOAL, "state": "completed", "goal_text": "original goal"}},
                   "tab": {"window": 1, "tab": 1, "tty": target["tty"], "screen": "idle screen"}}
    artifact = repo / "review.txt"
    artifact.write_text("Review, coverage and test evidence for the fixed fixture.\n")
    evidence = {"artifact": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
    receipt = {"schema_version": 1, "run_id": config["run_id"], "repository_key": target["repository_key"],
               "stage": 1, "goal_identity": copy.deepcopy(GOAL), "goal_complete": True, "status": "completed",
               "coverage": dict(evidence), "validation": [{**evidence, "command": "pytest", "status": "passed", "head_sha": HEAD}],
               "review": {**evidence, "status": "complete", "head_sha": HEAD, "remaining_findings": 0},
               "issues": [{"number": 23, "disposition": "addressed", "fix_commit_sha": FIX}],
               "pr": {"number": 42, "head_sha": HEAD, "branch": "curation/current", "base": "main"},
               "cleanup": {"remote_branch_deleted": True, "local_branch_deleted": True, "checkout_ready": True}}
    return SimpleNamespace(repo=repo, runtime=runtime, target=target, config=config,
                           ledger=ledger, observation=observation, receipt=receipt)


class GitHubFixture:
    """Every command is enumerated; unexpected mutation commands fail the test."""
    def __init__(self):
        self.calls = []
        self.dirty = ""
        self.branch = "main"
        self.head = HEAD
        self.remote_code = 2
        self.local_code = 1
        self.ancestor_code = 0
        self.open_prs = []
        self.rules = []
        self.branch_state = {"protected": True}
        self.issue = {"state": "closed"}
        self.checks = [{"name": "tests", "state": "SUCCESS", "bucket": "pass"}]
        self.commits = [[{"sha": HEAD}, {"sha": FIX}]]
        self.pr = {"merged": True, "merged_at": "2026-10-19T12:00:00Z", "merge_commit_sha": MERGE,
                   "base": {"ref": "main", "repo": {"full_name": "CultureBotAI/TraitMech"}},
                   "head": {"ref": "curation/current", "sha": HEAD, "repo": {"full_name": "CultureBotAI/TraitMech"}}}

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        code = 0
        if args[0] == "git":
            command = args[3:]
            if command == ["remote", "get-url", "origin"]:
                out = "https://github.com/CultureBotAI/TraitMech.git\n"
            elif command[:1] == ["status"]:
                out = self.dirty
            elif command[:1] == ["symbolic-ref"]:
                out = self.branch
            elif command == ["rev-parse", "HEAD"]:
                out = self.head
            elif command[:1] == ["ls-remote"]:
                out, code = "", self.remote_code
            elif command[:1] == ["show-ref"]:
                out, code = "", self.local_code
            elif command[:1] == ["merge-base"]:
                out, code = "", self.ancestor_code
            else:
                raise AssertionError(args)
        elif args[:3] == ["gh", "pr", "checks"]:
            out = json.dumps(self.checks)
        elif args[:3] == ["gh", "pr", "list"]:
            assert "--head" not in args, "feature PRs must not be excluded from a no-change inventory"
            out = json.dumps(self.open_prs)
        elif args[:2] == ["gh", "api"]:
            endpoint = args[-1]
            if endpoint.endswith("/pulls/42"):
                out = json.dumps(self.pr)
            elif "/commits?" in endpoint:
                out = json.dumps(self.commits)
            elif endpoint.endswith("/issues/23"):
                out = json.dumps(self.issue)
            elif "/rules/branches/" in endpoint:
                out = json.dumps(self.rules)
            elif "/branches/" in endpoint:
                out = json.dumps(self.branch_state)
            else:
                raise AssertionError(args)
        else:
            raise AssertionError(args)
        return SimpleNamespace(stdout=out, stderr="", returncode=code)


def test_goal_identity_survives_amended_text(setup):
    native = setup.observation["native"]
    before = supervisor.goal_identity(native)
    native["current_goal"]["goal_text"] += " appended guidance"
    assert supervisor.goal_identity(native) == before == GOAL


def test_default_helpers_are_committed_siblings_and_overrides_remain_supported(setup, monkeypatch):
    monkeypatch.setattr(supervisor, "ROOT", setup.runtime.parents[1])
    config = copy.deepcopy(setup.config)
    del config["native_reader_path"]
    del config["notifier_path"]
    validated = supervisor.validate_config(config, resolve_repositories=False)
    assert validated["native_reader_path"] == str(supervisor.ROOT / "scripts/mech_session_native.py")
    assert validated["notifier_path"] == str(supervisor.ROOT / "scripts/mech_session_terminal.py")
    explicit = supervisor.validate_config(copy.deepcopy(setup.config), resolve_repositories=False)
    assert explicit["native_reader_path"] == setup.config["native_reader_path"]
    assert explicit["notifier_path"] == setup.config["notifier_path"]


@pytest.mark.parametrize("screen", [
    "border\n>\nborder\n  ● [22:33:51] git push running\nGemini high\n" + "\n" * 20,
    "border\n>\nborder\nGemini · 1 task(s) · /tasks\n" + "\n" * 15,
    "▸ queued text (alt+m to send immediately)\nborder\n>\nborder\nGemini\n",
    "border\n>\nborder\nPress up to edit queued messages Gemini\n",
    "border\n>\nborder\nGemini · background tasks: 2\n",
])
def test_background_and_queued_states_block_even_with_trailing_blank_rows(screen):
    assert supervisor.terminal_busy_reason(screen)


def test_empty_normal_footer_is_not_busy():
    assert supervisor.terminal_busy_reason("border\n>\nborder\n? for shortcuts Gemini high\n\n") is None


@pytest.mark.parametrize("reason", ["native execution is busy", "nonempty composer", "approval menu", "queued task"])
def test_unready_sessions_never_receive_transition(setup, reason):
    setup.observation.update(ready=False, readiness_reason=reason)
    assert "action" not in supervisor.decide(setup.ledger, setup.observation)


def test_active_idle_goal_gets_assessment_not_next_goal(setup):
    setup.observation["goal_state"] = "active"
    assert supervisor.decide(setup.ledger, setup.observation)["action"] == "assess_and_finalize"


@pytest.mark.parametrize("state", ["reserved", "sent", "uncertain", "accepted"])
def test_reserved_and_uncertain_actions_never_repeat_on_restart(setup, state):
    decision = supervisor.decide(setup.ledger, setup.observation)
    setup.ledger["actions"][decision["action_id"]] = {"kind": "finalize", "stage": 1, "state": state}
    restored = json.loads(json.dumps(setup.ledger))
    assert "action" not in supervisor.decide(restored, setup.observation)


def test_old_completion_or_user_started_goal_cannot_advance(setup):
    setup.ledger.update(awaiting_goal=True, stage=2)
    setup.observation["goal_identity"]["start_step_index"] += 1
    assert "action" not in supervisor.decide(setup.ledger, setup.observation)


def test_active_native_goal_requires_explicit_audited_override(setup):
    setup.observation["goal_state"] = "active"
    with pytest.raises(supervisor.SupervisorError, match="not completed"):
        supervisor.completion_authority(setup.target, setup.ledger, setup.observation)
    setup.target["allow_receipt_completion_override"] = True
    with pytest.raises(supervisor.SupervisorError, match="not completed"):
        supervisor.completion_authority(setup.target, setup.ledger, setup.observation)
    setup.ledger["actions"]["x"] = {"state": "accepted", "stage": 1, "goal_identity": dict(GOAL)}
    assert supervisor.completion_authority(setup.target, setup.ledger, setup.observation) == "verified_receipt_override"


def test_cancelled_goal_is_not_automatically_resumed(setup):
    setup.observation["goal_state"] = "cancelled"
    assert "action" not in supervisor.decide(setup.ledger, setup.observation)


def test_pipeline_stops_after_fourth_stage(setup):
    setup.ledger["stage"] = 5
    assert supervisor.decide(setup.ledger, setup.observation) == {"phase": "pipeline_complete"}


def test_matching_receipt_and_independent_remote_proof_pass(setup):
    assert not supervisor.validate_receipt(setup.receipt, setup.ledger, setup.target, setup.runtime)
    proof = supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, GitHubFixture())
    assert proof["head_sha"] == HEAD and proof["merge_commit_sha"] == MERGE


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(run_id="other"),
    lambda r: r.update(stage=2),
    lambda r: r["goal_identity"].update(start_step_index=13),
    lambda r: r["review"].update(head_sha="d" * 40),
    lambda r: r["review"].update(remaining_findings=1),
    lambda r: r["validation"][0].update(status="failed"),
    lambda r: r["issues"][0].update(disposition="deferred"),
    lambda r: r["coverage"].update(sha256="0" * 64),
    lambda r: r["coverage"].update(artifact="/outside/secret"),
    lambda r: r["cleanup"].update(local_branch_deleted=False),
])
def test_receipt_scope_review_validation_and_artifacts_are_required(setup, mutation):
    mutation(setup.receipt)
    assert supervisor.validate_receipt(setup.receipt, setup.ledger, setup.target, setup.runtime)


@pytest.mark.parametrize("attribute,value,error", [
    ("dirty", " M data/record.yaml\n", "not clean"),
    ("branch", "unrelated-work", "default branch"),
    ("remote_code", 0, "remote branch"),
    ("remote_code", 128, "remote branch"),
    ("local_code", 0, "local branch"),
    ("local_code", 128, "local branch"),
    ("ancestor_code", 1, "does not contain"),
    ("ancestor_code", 128, "does not contain"),
    ("checks", [], "CI"),
    ("checks", [{"bucket": "pending"}], "CI"),
    ("issue", {"state": "open"}, "not closed"),
    ("commits", [[{"sha": HEAD}]], "not closed"),
])
def test_remote_proof_fails_closed(setup, attribute, value, error):
    remote = GitHubFixture()
    setattr(remote, attribute, value)
    with pytest.raises(supervisor.SupervisorError, match=error):
        supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, remote)


@pytest.mark.parametrize("mutation", [
    lambda pr: pr.update(merged=False),
    lambda pr: pr["head"].update(sha="d" * 40),
    lambda pr: pr["base"].update(ref="other"),
    lambda pr: pr["head"]["repo"].update(full_name="Other/TraitMech"),
])
def test_open_queued_or_wrong_identity_pr_cannot_advance(setup, mutation):
    remote = GitHubFixture()
    mutation(remote.pr)
    with pytest.raises(supervisor.SupervisorError, match="not actually merged"):
        supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, remote)


def no_change_receipt(setup):
    receipt = copy.deepcopy(setup.receipt)
    receipt.update(status="no_changes", pr=None, issues=[],
                   no_changes={"head_sha": HEAD, "explanation": "Audited scope already satisfied",
                               "no_goal_owned_changes": True, "no_open_goal_pr": True})
    return receipt


def test_no_change_requires_clean_unchanged_baseline_and_repo_wide_pr_inventory(setup):
    receipt = no_change_receipt(setup)
    assert not supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime)
    remote = GitHubFixture()
    assert supervisor.verify_remote_receipt(receipt, setup.ledger, setup.target, remote)["status"] == "no_changes"
    remote.open_prs = [{"number": 81}]
    with pytest.raises(supervisor.SupervisorError, match="open PR"):
        supervisor.verify_remote_receipt(receipt, setup.ledger, setup.target, remote)
    remote.open_prs = []
    setup.ledger["baseline_status"] = "?? data/new-goal-record.yaml\n"
    with pytest.raises(supervisor.SupervisorError, match="initially uncommitted"):
        supervisor.verify_remote_receipt(receipt, setup.ledger, setup.target, remote)


def make_instance(setup, monkeypatch, send):
    notifier = SimpleNamespace(jxa=send)
    instance = supervisor.Supervisor(setup.config, native=SimpleNamespace(), notifier=notifier, runner=GitHubFixture())
    monkeypatch.setattr(instance, "observe", lambda target, **kwargs: copy.deepcopy(setup.observation))
    return instance


def test_dispatch_reserves_durable_intent_before_input_and_timeout_is_not_retried(setup, monkeypatch):
    def timeout(*args):
        saved = json.loads((setup.runtime / "traitmech/ledger.json").read_text())
        assert next(iter(saved["actions"].values()))["state"] == "reserved"
        raise TimeoutError("delivery acknowledgement lost")

    instance = make_instance(setup, monkeypatch, timeout)
    decision = supervisor.decide(setup.ledger, setup.observation)
    result = instance.dispatch(setup.target, setup.ledger, decision)
    assert result["state"] == "uncertain"
    restored = json.loads((setup.runtime / "traitmech/ledger.json").read_text())
    assert "action" not in supervisor.decide(restored, setup.observation)


def test_dispatch_rechecks_changed_goal_and_does_not_type(setup, monkeypatch):
    decision = supervisor.decide(setup.ledger, setup.observation)
    setup.observation["goal_identity"]["start_step_index"] += 1
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    assert instance.dispatch(setup.target, setup.ledger, decision)["state"] == "not-sent"
    assert not setup.ledger["actions"]


def test_shared_input_lock_prevents_concurrent_terminal_writer(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    decision = supervisor.decide(setup.ledger, setup.observation)
    lock = Path(setup.config["input_lock_dir"]) / "ttys030.lock"
    with supervisor.file_lock(lock):
        with pytest.raises(BlockingIOError):
            instance.dispatch(setup.target, setup.ledger, decision)


def test_native_history_marker_reconciles_uncertain_without_duplicate(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    action = {"state": "uncertain", "stage": 1, "kind": "finalize", "marker": "MECH-WORKFLOW-test",
              "reserved_epoch_ms": 100, "native_session_id": setup.target["native_session_id"]}
    setup.ledger["actions"]["test"] = action
    Path(setup.config["history_path"]).write_text(json.dumps({"workspace": setup.target["root"],
        "conversationId": setup.target["native_session_id"],
        "timestamp": 101, "display": "[MECH-WORKFLOW-test] instruction"}) + "\n")
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert action["state"] == "accepted"
    assert "action" not in supervisor.decide(setup.ledger, setup.observation)


def test_observe_mode_never_sends_and_archived_receipt_does_not_block_new_stage(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("observe must not type"))
    instance.save(setup.target, setup.ledger)
    directory = instance.directory(setup.target)
    supervisor.atomic_json(directory / "completion.json", setup.receipt)
    dashboard = instance.sweep(apply=False)
    assert dashboard["sessions"][0]["stage"] == 2
    saved = json.loads((directory / "ledger.json").read_text())
    assert saved["awaiting_goal"] and not saved["actions"]
    # Adopted stage 2 will overwrite completion.json eventually. Until then the
    # exact previously verified receipt is harmless, not a stale-proof blocker.
    saved.update(awaiting_goal=False)
    saved["adopted_goal"]["start_step_index"] = 20
    instance.save(setup.target, saved)
    setup.observation["goal_identity"]["start_step_index"] = 20
    setup.observation["native"]["current_goal"]["start_step_index"] = 20
    assert instance.sweep(apply=False)["sessions"][0]["phase"] == "ready_to_dispatch"


def test_new_goal_marker_adoption_preserves_pre_goal_clean_baseline(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    setup.ledger.update(stage=2, awaiting_goal=True)
    setup.ledger["actions"]["next"] = {"kind": "start_goal", "stage": 2, "state": "sent",
        "marker": "MECH-WORKFLOW-next", "reserved_epoch_ms": 1,
        "native_session_id": setup.target["native_session_id"]}
    setup.observation["goal_identity"]["start_step_index"] = 40
    setup.observation["native"]["current_goal"].update(start_step_index=40, goal_text="next MECH-WORKFLOW-next")
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert not setup.ledger["awaiting_goal"]
    assert setup.ledger["adopted_goal"]["start_step_index"] == 40
    assert setup.ledger["baseline_head"] == HEAD and setup.ledger["baseline_status"] == ""


def test_config_refuses_duplicate_targets_and_unverified_skill_locations(setup, monkeypatch):
    monkeypatch.setattr(supervisor, "ROOT", setup.runtime.parents[1])
    assert supervisor.validate_config(setup.config, resolve_repositories=False)
    invalid = copy.deepcopy(setup.config)
    invalid["targets"].append(copy.deepcopy(invalid["targets"][0]))
    with pytest.raises(supervisor.SupervisorError, match="duplicate"):
        supervisor.validate_config(invalid, resolve_repositories=False)
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    setup.target["stages"][0]["skill_paths"] = ["/global/SKILL.md"]
    assert instance.skill_errors(setup.target, 1)


@pytest.mark.parametrize("conversation", [None, "different-conversation"])
def test_other_conversation_history_cannot_accept_a_delivery(setup, monkeypatch, conversation):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    action = {"state": "uncertain", "stage": 1, "kind": "finalize", "marker": "MECH-WORKFLOW-test",
              "reserved_epoch_ms": 100, "native_session_id": setup.target["native_session_id"]}
    setup.ledger["actions"]["test"] = action
    Path(setup.config["history_path"]).write_text(json.dumps({"workspace": setup.target["root"],
        "conversationId": conversation, "timestamp": 101, "display": "[MECH-WORKFLOW-test] instruction"}) + "\n")
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert action["state"] == "uncertain"


def test_no_required_ci_must_be_proved_by_live_branch_and_rules(setup):
    remote = GitHubFixture()
    remote.checks = []
    remote.branch_state = {"protected": False}
    assert supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, remote)["checks"] == []
    remote.rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "test"}]}}]
    with pytest.raises(supervisor.SupervisorError, match="absence of requirements"):
        supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, remote)


def test_declared_ci_policy_still_applies_without_branch_protection(setup):
    remote = GitHubFixture()
    remote.checks = []
    remote.branch_state = {"protected": False}
    setup.target["required_checks"] = ["tests"]
    with pytest.raises(supervisor.SupervisorError, match="declared CI"):
        supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, remote)


def test_stalled_instruction_repairs_are_progress_bound_deduplicated_and_capped(setup, monkeypatch):
    monkeypatch.setattr(supervisor.time, "time", lambda: 1000)
    setup.observation["native"]["last_step"] = {"index": 99}
    setup.ledger["actions"]["initial"] = {"kind": "finalize", "stage": 1, "state": "accepted",
                                         "reserved_epoch_ms": 1, "native_step_index": 80}
    repair = supervisor.decide(setup.ledger, setup.observation)
    assert repair["action"] == "repair_closure"
    setup.ledger["actions"][repair["action_id"]] = {"kind": "repair_closure", "stage": 1,
        "state": "accepted", "reserved_epoch_ms": 2, "native_step_index": 99}
    assert "action" not in supervisor.decide(setup.ledger, setup.observation)
    # New executed work permits a bounded follow-up; the same state does not.
    setup.observation["native"]["last_step"]["index"] = 101
    assert supervisor.decide(setup.ledger, setup.observation)["action"] == "repair_closure"
    for number in (1, 2):
        setup.ledger["actions"][f"repair-{number}"] = {"kind": "repair_closure", "stage": 1,
            "state": "accepted", "reserved_epoch_ms": number + 2, "native_step_index": 99}
    decision = supervisor.decide(setup.ledger, setup.observation)
    assert decision["phase"] == "requires_intervention" and "action" not in decision


def test_busy_or_uncertain_stall_never_triggers_repair(setup):
    setup.ledger["actions"]["initial"] = {"kind": "finalize", "stage": 1, "state": "uncertain",
        "reserved_epoch_ms": 1, "native_step_index": 80}
    setup.observation["native"]["last_step"] = {"index": 99}
    assert "action" not in supervisor.repair_decision(setup.ledger, setup.observation, "invalid receipt")
    setup.ledger["actions"]["initial"]["state"] = "accepted"
    setup.observation["ready"] = False
    assert "action" not in supervisor.repair_decision(setup.ledger, setup.observation, "invalid receipt")


def test_runtime_symlinks_cannot_redirect_receipts_or_output(setup, monkeypatch, tmp_path):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    instance.save(setup.target, setup.ledger)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(setup.receipt))
    (instance.directory(setup.target) / "completion.json").symlink_to(outside)
    dashboard = instance.sweep(apply=False)
    assert dashboard["sessions"][0]["phase"] == "closure_blocked"
    assert "regular file" in dashboard["sessions"][0]["reason"]
    outside_dir = tmp_path / "outside-directory"
    outside_dir.mkdir()
    (instance.directory(setup.target) / "receipts").symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(supervisor.SupervisorError, match="escapes"):
        instance.write(instance.directory(setup.target) / "receipts/unsafe.json", {})
    assert not (outside_dir / "unsafe.json").exists()


def test_repair_dispatch_uses_same_reason_and_receipt_hash_then_refuses_changed_receipt(setup, monkeypatch):
    monkeypatch.setattr(supervisor.time, "time", lambda: 1000)
    setup.observation["native"]["last_step"] = {"index": 99}
    setup.ledger["actions"]["initial"] = {"kind": "finalize", "stage": 1, "state": "accepted",
                                         "reserved_epoch_ms": 1, "native_step_index": 80}
    sent = []
    instance = make_instance(setup, monkeypatch, lambda source, value: sent.append(value["message"]) or "sent")
    instance.save(setup.target, setup.ledger)
    path = instance.directory(setup.target) / "completion.json"
    path.write_text('{"incomplete": true}')
    receipt_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    decision = supervisor.repair_decision(setup.ledger, setup.observation, "missing validation", receipt_hash)
    assert instance.dispatch(setup.target, setup.ledger, decision)["state"] == "sent"
    assert "missing validation" in sent[0]
    path.write_text('{"corrected": true}')
    assert instance.dispatch(setup.target, setup.ledger, decision)["state"] == "not-sent"
    assert len(sent) == 1


def test_first_adoption_refuses_goal_that_changed_since_assessment(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    setup.ledger["adopted_goal"] = None
    setup.observation["goal_identity"]["start_step_index"] += 1
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert setup.ledger["adopted_goal"] is None
    assert "reassessment" in setup.observation["error"]


@pytest.mark.parametrize("applicability", ["blocked", "prerequisite_blocked", "representation_gap", "adapter_needed", "unknown"])
def test_file_presence_does_not_waive_skill_prerequisites(setup, monkeypatch, applicability):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    setup.target["stages"][0]["applicability"] = applicability
    assert instance.skill_errors(setup.target, 1)


def test_progress_is_identity_bound_and_never_completion_authority(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    instance.save(setup.target, setup.ledger)
    progress = {"run_id": setup.ledger["run_id"], "repository_key": "traitmech", "stage": 1,
                "goal_identity": dict(GOAL), "phase": "PR merged"}
    supervisor.atomic_json(instance.directory(setup.target) / "progress.json", progress)
    assert instance.progress(setup.target, setup.ledger)["authority"] == "informational_only"
    assert supervisor.decide(setup.ledger, setup.observation)["action"] == "finalize"
    progress["goal_identity"]["start_step_index"] += 1
    supervisor.atomic_json(instance.directory(setup.target) / "progress.json", progress)
    assert instance.progress(setup.target, setup.ledger)["authority"] == "ignored"


def test_fresh_matching_blocked_progress_suppresses_automatic_repairs(setup):
    setup.observation["agent_progress"] = {"authority": "informational_only", "stage": 1,
        "current": True, "phase": "blocked", "summary": "native writer prerequisite unavailable"}
    decision = supervisor.repair_decision(setup.ledger, setup.observation, "receipt missing")
    assert decision["phase"] == "requires_intervention"
    assert "writer prerequisite" in decision["reason"] and "action" not in decision


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("matching_cwd", [True, False])
def test_actual_delivery_javascript_handles_macos_line_endings_and_stale_windows(setup, separator, matching_cwd):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute the actual JXA-compatible delivery code offline")
    expected = {"pid": setup.target["pid"], "window": 1, "tab": 1, "tty": setup.target["tty"],
                "identity": setup.target["process_identity"], "cwd": setup.target["root"],
                "screen": "verified idle screen", "message": "one authorized workflow instruction"}
    cwd = expected["cwd"] if matching_cwd else "/different/repository"
    fixture = {"expected": expected, "cwd_output": separator.join(["p1234", "fcwd", "n" + cwd])}
    harness = r'''
const fixture = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const sent = [];
const tab = {tty: () => fixture.expected.tty, contents: () => fixture.expected.screen};
const terminal = {
    windows: () => [{id: () => {throw new Error("Can't get object.");}},
                   {id: () => 1, tabs: () => [tab]}],
    doScript: (message, options) => {if (options.in !== tab) throw new Error('wrong tab'); sent.push(message);}
};
const system = {doShellScript: command => {
    if (command.includes('/usr/sbin/lsof')) return fixture.cwd_output;
    if (command.includes('pgid=,tpgid=')) return '1234 1234';
    if (command.includes('/bin/ps -p')) return fixture.expected.identity;
    throw new Error('unexpected shell command');
}};
function Application(name) {if (name !== 'Terminal') throw new Error('unexpected application'); return terminal;}
Application.currentApplication = () => system;
'''
    harness += supervisor.SEND_JS
    harness += "\nconst outcome = run([JSON.stringify(fixture.expected)]); process.stdout.write(JSON.stringify({outcome,sent}));\n"
    result = subprocess.run([node, "-e", harness], input=json.dumps(fixture), text=True,
                            capture_output=True, check=True, timeout=10)
    actual = json.loads(result.stdout)
    assert actual == ({"outcome": "sent", "sent": [expected["message"]]} if matching_cwd
                      else {"outcome": "identity-changed", "sent": []})
