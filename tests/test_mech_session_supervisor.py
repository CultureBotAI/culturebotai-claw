"""Offline regression coverage for session identity, delivery, and closure gates."""
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
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


def test_goal_messages_register_every_pr_without_granting_completion(setup):
    decision = {"action": "finalize", "action_id": "example"}
    message = supervisor.message_for(setup.target, setup.ledger, decision, setup.runtime / "traitmech")
    assert "including follow-up PRs" in message
    assert "-m kg_microbe_progress.prs register" in message
    assert "--number NUMBER" in message
    assert "does not complete a goal" in message


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


def test_legacy_four_stage_pipeline_requires_migration_instead_of_completion(setup):
    setup.ledger["stage"] = 5
    assert supervisor.decide(setup.ledger, setup.observation)["phase"] == "requires_migration"


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
    monkeypatch.setattr(instance, "native_inputs", lambda target, after: [])
    return instance


def confirm_native_input(instance, action, *, index=None):
    payload = action.get("transport_message", action.get("message"))
    item = {"step_index": index if index is not None else (action.get("native_step_index") or 0) + 1,
            "timestamp_ms": action["reserved_epoch_ms"] + 1,
            "created_at": "2026-10-25T20:00:00+00:00", "text": supervisor.normalized_input(payload),
            "goal_declaration": payload.startswith("/goal ")}
    instance.native_inputs = lambda target, after: [item]
    return item


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


def test_history_only_records_submission_without_acceptance_or_duplicate(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("must not type"))
    action = {"state": "uncertain", "stage": 1, "kind": "finalize", "marker": "MECH-WORKFLOW-test",
              "message": "[MECH-WORKFLOW-test] instruction", "reserved_epoch_ms": 100,
              "native_session_id": setup.target["native_session_id"]}
    setup.ledger["actions"]["test"] = action
    Path(setup.config["history_path"]).write_text(json.dumps({"workspace": setup.target["root"],
        "conversationId": setup.target["native_session_id"],
        "timestamp": 101, "display": "[MECH-WORKFLOW-test] instruction"}) + "\n")
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert action["state"] == "uncertain"
    assert action["submission_evidence"]["timestamp"] == 101
    assert "accepted_at" not in action
    assert "action" not in supervisor.decide(setup.ledger, setup.observation)


@pytest.mark.parametrize("start_goal", [False, True])
def test_dispatch_persists_full_immutable_instruction_before_short_transport(setup, monkeypatch, start_goal):
    if start_goal:
        setup.ledger.update(stage=2, awaiting_goal=True)
    def send(source, value):
        saved = supervisor.read_json(setup.runtime / "traitmech/ledger.json")
        action = next(iter(saved["actions"].values()))
        artifact = action["instruction_artifact"]
        path = Path(artifact["path"])
        assert path.is_absolute() and path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
        assert supervisor.read_json(path)["instruction"] == supervisor.normalized_input(action["message"])
        assert action["state"] == "reserved"
        assert value["message"] == action["transport_message"]
        assert value["message"].startswith("/goal ") is start_goal
        assert len(value["message"]) < len(action["message"]) / 2
        assert "\n" not in value["message"]
        return "sent"
    instance = make_instance(setup, monkeypatch, send)
    decision = supervisor.decide(setup.ledger, setup.observation)
    action = instance.dispatch(setup.target, setup.ledger, decision)
    assert action["state"] == "sent"
    before = Path(action["instruction_artifact"]["path"]).read_bytes()
    assert instance.action_transport(setup.target, action["id"], action["kind"], action["message"])[0] == action["transport_message"]
    with pytest.raises(supervisor.SupervisorError, match="immutable"):
        instance.action_transport(setup.target, action["id"], action["kind"], action["message"] + " altered")
    assert Path(action["instruction_artifact"]["path"]).read_bytes() == before


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("damage", [None, "truncated", "quoted", "old_step", "old_time", "wrong_goal_kind", "wrong_conversation"])
def test_acceptance_requires_exact_new_native_input(setup, monkeypatch, legacy, damage):
    instance = make_instance(setup, monkeypatch, lambda *_: "sent")
    action = instance.dispatch(setup.target, setup.ledger, supervisor.decide(setup.ledger, setup.observation))
    action["native_step_index"] = 40
    if legacy:
        del action["transport_message"]
    item = confirm_native_input(instance, action, index=41)
    if damage == "truncated":
        item["text"] = item["text"][:-5]
    elif damage == "quoted":
        item["text"] = "Quoted instruction: " + item["text"]
    elif damage == "old_step":
        item["step_index"] = 40
    elif damage == "old_time":
        item["timestamp_ms"] = action["reserved_epoch_ms"] - 1
    elif damage == "wrong_goal_kind":
        item["goal_declaration"] = True
    elif damage == "wrong_conversation":
        action["native_session_id"] = "another-conversation"
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert action["state"] == ("accepted" if damage is None else "sent")
    if damage is None:
        assert action["native_consumption"]["verified"]
        assert action["native_consumption"]["step_index"] == 41
        accepted = copy.deepcopy(action)
        item["step_index"] = 99
        Path(setup.config["history_path"]).write_text(json.dumps({"workspace": setup.target["root"],
            "conversationId": setup.target["native_session_id"], "timestamp": action["reserved_epoch_ms"] + 1,
            "display": action.get("transport_message", action["message"])}) + "\n")
        instance.reconcile(setup.target, setup.ledger, setup.observation)
        assert action["accepted_at"] == accepted["accepted_at"]
        assert action["acceptance"] == "native_user_input_exact"
        assert action["native_consumption"] == accepted["native_consumption"]


def test_historical_acceptance_is_preserved_but_not_reported_as_native_consumption(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: "sent")
    action = instance.dispatch(setup.target, setup.ledger, supervisor.decide(setup.ledger, setup.observation))
    action.update(state="accepted", accepted_at="original", acceptance="native_workspace_history_marker")
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert action["state"] == "accepted" and action["accepted_at"] == "original"
    assert action["native_consumption"]["verified"] is False
    confirm_native_input(instance, action)
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert action["native_consumption"]["verified"] is True
    assert action["accepted_at"] == "original"


@pytest.mark.parametrize("damage", [None, "conversation", "workspace"])
def test_native_input_reader_checks_snapshot_identity_and_completed_user_steps(setup, monkeypatch, damage):
    native = supervisor.import_file(Path(supervisor.__file__).with_name("mech_session_native.py"), "test_native_inputs")
    directory = setup.runtime / "native"
    directory.mkdir()
    setup.config["conversation_dir"] = str(directory)
    def vint(value):
        result = bytearray()
        while value > 127:
            result.append((value & 127) | 128)
            value >>= 7
        return bytes(result) + bytes([value])
    def field(number, value):
        return vint(number << 3 | 2) + vint(len(value)) + value
    payload = field(5, field(1, b"\x08\x65")) + field(19, field(1, b"exact instruction"))
    cid = setup.target["native_session_id"]
    path = directory / f"{cid}.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE trajectory_meta (id text, cid text); "
            "CREATE TABLE trajectory_metadata_blob (id text, data blob); "
            "CREATE TABLE steps (idx integer, step_type integer, status integer, step_payload blob);")
        connection.execute("INSERT INTO trajectory_meta VALUES (?,?)", ("main", "other" if damage == "conversation" else cid))
        uri = Path("/different/repository").as_uri() if damage == "workspace" else setup.repo.as_uri()
        connection.execute("INSERT INTO trajectory_metadata_blob VALUES (?,?)", ("main", field(7, uri.encode())))
        connection.executemany("INSERT INTO steps VALUES (?,?,?,?)", [
            (40, 14, 3, payload), (41, 14, 3, payload), (42, 15, 3, payload), (43, 14, 11, payload)])
    instance = supervisor.Supervisor(setup.config, native=native, notifier=SimpleNamespace())
    before = path.read_bytes()
    if damage:
        with pytest.raises(supervisor.SupervisorError, match=damage):
            instance.native_inputs(setup.target, 40)
    else:
        rows = instance.native_inputs(setup.target, 40)
        assert [(r["step_index"], r["text"], r["timestamp_ms"], r["goal_declaration"]) for r in rows] == [
            (41, "exact instruction", 101000, False)]
    assert path.read_bytes() == before
    assert not Path(str(path) + "-wal").exists()


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
        "message": "/goal next MECH-WORKFLOW-next",
        "native_session_id": setup.target["native_session_id"]}
    setup.observation["goal_identity"]["start_step_index"] = 40
    setup.observation["native"]["current_goal"].update(start_step_index=40, goal_text="next MECH-WORKFLOW-next")
    confirm_native_input(instance, setup.ledger["actions"]["next"], index=40)
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert not setup.ledger["awaiting_goal"]
    assert setup.ledger["adopted_goal"]["start_step_index"] == 40
    assert setup.ledger["baseline_head"] == HEAD and setup.ledger["baseline_status"] == ""


@pytest.mark.parametrize("damage", ["no_native_input", "truncated", "wrong_step", "not_goal"])
def test_goal_marker_alone_cannot_adopt_a_different_native_goal(setup, monkeypatch, damage):
    instance = make_instance(setup, monkeypatch, lambda *_: "sent")
    setup.ledger.update(stage=2, awaiting_goal=True)
    action = instance.dispatch(setup.target, setup.ledger, supervisor.decide(setup.ledger, setup.observation))
    setup.observation["goal_identity"]["start_step_index"] = 40
    setup.observation["native"]["current_goal"].update(start_step_index=40,
        goal_text=supervisor.normalized_input(action["transport_message"]))
    if damage != "no_native_input":
        item = confirm_native_input(instance, action, index=40)
        if damage == "truncated":
            item["text"] = item["text"][:-1]
        elif damage == "wrong_step":
            item["step_index"] = 41
        else:
            item["goal_declaration"] = False
    instance.reconcile(setup.target, setup.ledger, setup.observation)
    assert setup.ledger["awaiting_goal"]
    assert setup.ledger["adopted_goal"] == GOAL


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
    action = next(a for a in setup.ledger["actions"].values() if a.get("transport_message") == sent[0])
    assert "missing validation" in supervisor.read_json(Path(action["instruction_artifact"]["path"]))["instruction"]
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


@pytest.mark.parametrize("receipt_error", [False, True])
def test_cancelled_goal_blocks_repairs_after_accepted_instruction(setup, receipt_error):
    setup.observation.update(goal_state="cancelled")
    setup.observation["native"]["last_step"] = {"index": 99}
    setup.ledger["actions"]["initial"] = {"kind": "assess_and_finalize", "stage": 1, "state": "accepted",
        "reserved_epoch_ms": 1, "native_step_index": 80}
    decision = (supervisor.repair_decision(setup.ledger, setup.observation, "invalid receipt")
                if receipt_error else supervisor.decide(setup.ledger, setup.observation))
    assert decision["phase"] == "blocked" and "action" not in decision
    assert "cancelled" in decision["reason"]


def test_definitively_unsent_repair_retries_without_waiting_for_acceptance(setup, monkeypatch):
    monkeypatch.setattr(supervisor.time, "time", lambda: 1000)
    setup.observation["native"]["last_step"] = {"index": 99}
    setup.ledger["actions"]["initial"] = {"kind": "finalize", "stage": 1, "state": "accepted",
        "reserved_epoch_ms": 1, "native_step_index": 80}
    outcomes = iter(["screen-changed", "sent"])
    instance = make_instance(setup, monkeypatch, lambda *_: next(outcomes))
    first = supervisor.decide(setup.ledger, setup.observation)
    assert instance.dispatch(setup.target, setup.ledger, first)["state"] == "not-sent"
    # The UI rejected input definitively. No new native work or acceptance can
    # occur because of this attempt, so the same repair must remain retryable.
    retry = supervisor.decide(setup.ledger, setup.observation)
    assert retry["action"] == "repair_closure" and retry["action_id"] == first["action_id"]
    assert instance.dispatch(setup.target, setup.ledger, retry)["state"] == "sent"


def test_definitively_unsent_repairs_do_not_exhaust_delivery_allowance(setup, monkeypatch):
    monkeypatch.setattr(supervisor.time, "time", lambda: 1000)
    setup.observation["native"]["last_step"] = {"index": 99}
    setup.ledger["actions"]["initial"] = {"kind": "finalize", "stage": 1, "state": "accepted",
        "reserved_epoch_ms": 1, "native_step_index": 80}
    for index in range(3):
        setup.ledger["actions"][f"unsent-{index}"] = {"kind": "repair_closure", "stage": 1, "state": "not-sent",
            "reserved_epoch_ms": index + 2, "native_step_index": 99}
    assert supervisor.decide(setup.ledger, setup.observation)["action"] == "repair_closure"


@pytest.mark.parametrize("failure_point", ["archive", "baseline"])
def test_closure_preparation_failure_does_not_persist_partial_transition(setup, monkeypatch, failure_point):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("observe must not type"))
    instance.save(setup.target, setup.ledger)
    directory = instance.directory(setup.target)
    supervisor.atomic_json(directory / "completion.json", setup.receipt)
    if failure_point == "archive":
        original = instance.write

        def fail_archive(path, value):
            if "receipts" in path.parts:
                raise OSError("archive temporarily unavailable")
            return original(path, value)

        monkeypatch.setattr(instance, "write", fail_archive)
    else:
        original = instance.baseline

        def fail_baseline(target, ledger):
            if "baseline_head" not in ledger:
                raise OSError("baseline temporarily unavailable")
            return original(target, ledger)

        monkeypatch.setattr(instance, "baseline", fail_baseline)
    instance.sweep(apply=False)
    saved = supervisor.read_json(directory / "ledger.json")
    assert saved["stage"] == 1 and saved["completed_stages"] == []
    assert saved["baseline_head"] == HEAD and saved["baseline_status"] == ""
    monkeypatch.setattr(instance, "write" if failure_point == "archive" else "baseline", original)
    assert instance.sweep(apply=False)["sessions"][0]["stage"] == 2
    saved = supervisor.read_json(directory / "ledger.json")
    assert len(saved["completed_stages"]) == 1 and saved["awaiting_goal"]


def test_stop_file_blocks_direct_dispatch(setup, monkeypatch):
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("STOP must prevent transport"))
    (setup.runtime / "STOP").touch()
    decision = supervisor.decide(setup.ledger, setup.observation)
    assert instance.dispatch(setup.target, setup.ledger, decision)["state"] == "not-sent"
    assert not setup.ledger["actions"]


@pytest.mark.parametrize("stop_point", ["observation", "reservation"])
def test_signal_stop_during_dispatch_prevents_transport(setup, monkeypatch, stop_point):
    stopped = False
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("signal must prevent transport"))
    instance.stop_requested = lambda: stopped
    if stop_point == "observation":
        def observe(*args, **kwargs):
            nonlocal stopped
            stopped = True
            return copy.deepcopy(setup.observation)
        monkeypatch.setattr(instance, "observe", observe)
    else:
        original = instance.save

        def save(target, ledger):
            nonlocal stopped
            original(target, ledger)
            stopped = True

        monkeypatch.setattr(instance, "save", save)
    decision = supervisor.decide(setup.ledger, setup.observation)
    result = instance.dispatch(setup.target, setup.ledger, decision)
    assert result["state"] == "not-sent"
    assert all(action["state"] == "not-sent" for action in setup.ledger["actions"].values())


def test_stop_requested_mid_sweep_prevents_visiting_later_targets(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = make_instance(setup, monkeypatch, lambda *_: pytest.fail("no real transport"))
    other = {**setup.target, "repository_key": "othermech"}
    setup.config["targets"].append(other)
    observed = []

    def observe(target, **kwargs):
        observed.append(target["repository_key"])
        return copy.deepcopy(setup.observation)

    def dispatch(*args):
        (setup.runtime / "STOP").touch()
        return {"state": "not-sent"}

    monkeypatch.setattr(instance, "observe", observe)
    monkeypatch.setattr(instance, "dispatch", dispatch)
    dashboard = instance.sweep(apply=True)
    assert observed == ["traitmech"]
    assert [row["repository"] for row in dashboard["sessions"]] == ["traitmech"]


def test_main_passes_signal_cancellation_to_supervisor(setup, monkeypatch):
    handlers = {}
    monkeypatch.setattr(supervisor.signal, "signal", lambda number, handler: handlers.setdefault(number, handler))
    monkeypatch.setattr(supervisor, "validate_config", lambda config: config)
    config_path = setup.runtime / "config.json"
    supervisor.atomic_json(config_path, setup.config)

    class SignalProbe:
        def __init__(self, config, *, stop_requested):
            self.runtime = Path(config["runtime_dir"])
            self.stop_requested = stop_requested

        def sweep(self, *, apply):
            assert not self.stop_requested()
            handlers[supervisor.signal.SIGTERM](supervisor.signal.SIGTERM, None)
            assert self.stop_requested()
            return {}

        def write(self, *args):
            pass

    monkeypatch.setattr(supervisor, "Supervisor", SignalProbe)
    assert supervisor.main(["--config", str(config_path), "--apply", "--loop", "--interval", "5"]) == 0


def test_fifo_artifact_is_rejected_promptly_in_fresh_process(setup):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO regression requires Unix")
    fifo = setup.repo / "coverage.pipe"
    os.mkfifo(fifo)
    probe = """
import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("reviewed_supervisor",sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.artifact_errors(
    {"artifact":sys.argv[2],"sha256":"a"*64},[Path(sys.argv[3])],"coverage")))
"""
    try:
        result = subprocess.run([sys.executable, "-c", probe, str(Path(supervisor.__file__).resolve()),
                                 str(fifo), str(setup.repo)], capture_output=True, text=True,
                                check=True, timeout=3)
    except subprocess.TimeoutExpired:
        pytest.fail("FIFO evidence blocked the supervisor waiting for a writer")
    assert "regular file" in json.loads(result.stdout)[0]


class CycleGitHubFixture(GitHubFixture):
    """Final-head trees are independent snapshots, so dirty/new reports fail."""
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.tree = {}

    @staticmethod
    def blob(raw):
        return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

    def snapshot(self):
        self.tree = {str(path.relative_to(self.root)): self.blob(path.read_bytes())
                     for path in self.root.rglob("*") if path.is_file()}

    def __call__(self, args, **kwargs):
        if args[0] == "git" and args[3] in {"rev-parse", "hash-object"}:
            if args[3] == "rev-parse" and ":" in args[-1]:
                assert args[-1].split(":", 1)[0] == HEAD
                self.calls.append(args)
                return SimpleNamespace(stdout=self.tree.get(args[-1].split(":", 1)[1], ""), stderr="", returncode=0)
            if args[3] == "hash-object":
                self.calls.append(args)
                return SimpleNamespace(stdout=self.blob((self.root / args[-1]).read_bytes()), stderr="", returncode=0)
        return super().__call__(args, **kwargs)


@pytest.fixture
def cycle_setup(setup):
    from kg_microbe_workflows import PARENT_PATH, SCHEMA_PATH, STAGE_KEYS
    parent = __import__("yaml").safe_load(PARENT_PATH.read_text())
    profile = {"schema_version": "1.0.0", "profile_id": "traitmech-workflow", "profile_version": "1.0.0",
               "repository_key": "traitmech", "github_repository": "CultureBotAI/TraitMech",
               "parent": {"id": parent["id"], "version": parent["version"],
                          "sha256": hashlib.sha256(PARENT_PATH.read_bytes()).hexdigest(),
                          "schema_sha256": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
                          "repository": "CultureBotAI/culturebotai-claw", "revision": HEAD},
               "adaptation_skill": ".claude/skills/example/SKILL.md",
               "stages": [{"stage": stage, "key": key, "goal_text": f"Use the canonical skill for stage {stage}",
                           "skill_paths": [".claude/skills/example/SKILL.md"], "applicability": "enabled"}
                          for stage, key in enumerate(STAGE_KEYS, 1)]}
    path = setup.repo / "workflow/mech-workflow.yaml"
    path.parent.mkdir()
    path.write_text(json.dumps(profile))
    setup.target.update(workflow_profile_path=str(path), workflow_next_profile_path=str(path))
    effective = supervisor.load_effective(setup.config, setup.target)
    setup.target.update(_workflow=effective, stages=effective["stages"])
    ledger = supervisor.new_ledger(setup.config, setup.target)
    ledger.update(adopted_goal=copy.deepcopy(GOAL), baseline_status="", baseline_head=HEAD)
    setup.ledger = ledger
    infra = setup.repo / "INFRA_TASKS.md"
    infra.write_text('# Infrastructure tasks\n\n<!-- mech-infra-tasks:start -->\n```yaml\nschema_version: "1.0.0"\ntasks: []\n```\n<!-- mech-infra-tasks:end -->\n')
    setup.receipt.update(schema_version=2, cycle=1, workflow_sha256=ledger["workflow"]["sha256"],
                         goal_outputs={"infra_tasks": {"path": "INFRA_TASKS.md", "sha256": hashlib.sha256(infra.read_bytes()).hexdigest()}})
    setup.remote = CycleGitHubFixture(setup.repo)
    setup.remote.snapshot()
    return setup


def write_goal_evidence(setup, ledger, *, findings=None, groups=None, infra_tasks=None):
    from kg_microbe_workflows import REQUIRED_OUTPUTS, evidence_directory
    stage, cycle = ledger["stage"], ledger["cycle"]
    if stage == 6 and not ledger.get("infra_scope"):
        ledger["infra_scope"] = supervisor.freeze_infrastructure(setup.target)
    receipt = copy.deepcopy(setup.receipt)
    receipt.update(stage=stage, cycle=cycle, goal_identity=copy.deepcopy(ledger["adopted_goal"]),
                   workflow_sha256=ledger["workflow"]["sha256"])
    required_outputs = supervisor.stage_profile(setup.target, stage, ledger).get("required_outputs") or []
    if stage < 4 and not required_outputs:
        return receipt
    directory = evidence_directory(ledger["run_id"], cycle, stage, 1)
    artifacts = []
    for kind in sorted(set(REQUIRED_OUTPUTS.get(stage, [])) | set(required_outputs)):
        path = setup.repo / directory / (kind + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((setup.repo / "INFRA_TASKS.md").read_text() if kind == "infra_snapshot"
                        else f"{kind} evidence for cycle {cycle} stage {stage}\n")
        artifacts.append({"path": str(path.relative_to(setup.repo)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "kind": kind})
    data = {"schema_version": "1.0.0", "repository_key": "traitmech", "github_repository": "CultureBotAI/TraitMech",
            "run_id": ledger["run_id"], "cycle": cycle, "stage": stage, "revision": 1,
            "outcome": "completed" if findings or groups or infra_tasks else "no_findings",
            "summary": "Bounded review evidence", "source_revision": HEAD, "artifacts": artifacts,
            "findings": findings or [], "groups": groups or [], "infra_tasks": infra_tasks or [],
            "carry_forward_ids": [item["finding_id"] for item in findings or [] if item["status"] != "resolved"]}
    previous = supervisor.previous_evidence(ledger, stage)
    if previous:
        data["previous_evidence"] = copy.deepcopy(previous["goal_evidence"])
    if stage >= 5:
        data["scope_frozen_at"] = ledger["infra_scope"]["frozen_at"] if stage == 6 else "2026-10-19T12:00:00Z"
    path = setup.repo / directory / "evidence.yaml"
    path.write_text(json.dumps(data))
    receipt["goal_outputs"]["goal_evidence"] = {"path": str(path.relative_to(setup.repo)),
                                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return receipt


def cycle_instance(setup, monkeypatch, send=lambda *_: "sent"):
    instance = make_instance(setup, monkeypatch, send)
    instance.runner = setup.remote
    return instance


def test_two_full_six_goal_cycles_keep_all_identity_and_closure_history(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    ledger = setup.ledger
    instance.save(setup.target, ledger)
    starts = []
    for expected_cycle in (1, 2):
        for expected_stage in range(1, 7):
            assert (ledger["cycle"], ledger["stage"]) == (expected_cycle, expected_stage)
            receipt = write_goal_evidence(setup, ledger)
            setup.remote.snapshot()
            supervisor.atomic_json(instance.directory(setup.target) / "completion.json", receipt)
            dashboard = instance.sweep(apply=False)
            assert dashboard["sessions"][0]["phase"] == "ready_to_dispatch"
            ledger = supervisor.read_json(instance.directory(setup.target) / "ledger.json")
            assert len(ledger["completed_stages"]) == (expected_cycle - 1) * 6 + expected_stage
            assert ledger["awaiting_goal"]
            decision = supervisor.decide(ledger, setup.observation)
            starts.append(decision["action_id"])
            action = instance.dispatch(setup.target, ledger, decision)
            assert action["state"] == "sent"
            setup.observation["goal_identity"]["start_step_index"] += 10
            setup.observation["native"]["current_goal"].update(
                start_step_index=setup.observation["goal_identity"]["start_step_index"],
                goal_text=supervisor.normalized_input(action["transport_message"]))
            confirm_native_input(instance, action, index=setup.observation["goal_identity"]["start_step_index"])
            instance.reconcile(setup.target, ledger, setup.observation)
            assert not ledger["awaiting_goal"]
            instance.save(setup.target, ledger)
    assert (ledger["cycle"], ledger["stage"]) == (3, 1)
    assert len(set(starts)) == 12
    assert len(list((instance.directory(setup.target) / "receipts").glob("cycle-*/stage-*.json"))) == 12
    index = supervisor.read_json(instance.directory(setup.target) / "verified-evidence-index.json")
    assert len(index["entries"]) == 6
    assert supervisor.previous_evidence(ledger, 4)["stage"] == 5


def test_old_cycle_actions_cannot_authorize_acceptance_repair_or_completion(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    ledger = setup.ledger
    before = supervisor.action_id(ledger, "finalize")
    ledger["cycle"] = 2
    ledger["actions"][before] = {"kind": "finalize", "stage": 1, "cycle": 1, "state": "accepted",
                                  "goal_identity": copy.deepcopy(GOAL), "marker": "old-marker",
                                  "reserved_epoch_ms": 0, "native_step_index": 1,
                                  "native_session_id": setup.target["native_session_id"]}
    setup.observation.update(goal_state="active")
    setup.target["allow_receipt_completion_override"] = True
    assert supervisor.action_id(ledger, "finalize") != before
    assert supervisor.decide(ledger, setup.observation)["action"] == "assess_and_finalize"
    with pytest.raises(supervisor.SupervisorError, match="not completed"):
        supervisor.completion_authority(setup.target, ledger, setup.observation)
    assert "action" not in supervisor.repair_decision(ledger, setup.observation, "missing proof")
    ledger.update(awaiting_goal=True)
    ledger["actions"][before].update(kind="start_goal", state="uncertain")
    setup.observation["goal_identity"]["start_step_index"] += 1
    setup.observation["native"]["current_goal"]["goal_text"] = "old-marker"
    instance.reconcile(setup.target, ledger, setup.observation)
    assert ledger["awaiting_goal"] and ledger["actions"][before]["state"] == "uncertain"


def test_old_cycle_receipt_and_progress_are_rejected(cycle_setup, monkeypatch):
    setup = cycle_setup
    setup.ledger["cycle"] = 2
    assert "receipt cycle mismatch" in supervisor.validate_receipt(setup.receipt, setup.ledger, setup.target, setup.runtime)
    instance = cycle_instance(setup, monkeypatch)
    progress = {key: setup.receipt[key] for key in ("run_id", "repository_key", "cycle", "stage", "goal_identity")}
    progress.update(phase="completed", updated_at=supervisor.now())
    supervisor.atomic_json(instance.directory(setup.target) / "progress.json", progress)
    assert instance.progress(setup.target, setup.ledger)["authority"] == "ignored"


def test_stage4_requires_real_versioned_review_outputs_but_may_leave_domain_findings(cycle_setup):
    setup = cycle_setup
    setup.ledger["stage"] = 4
    receipt = write_goal_evidence(setup, setup.ledger, findings=[{"finding_id": "trait-001", "status": "open", "summary": "A related trait defect"}])
    assert supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime) == []
    with pytest.raises(supervisor.SupervisorError, match="not versioned"):
        supervisor.verify_remote_receipt(receipt, setup.ledger, setup.target, setup.remote)
    setup.remote.snapshot()
    assert supervisor.verify_remote_receipt(receipt, setup.ledger, setup.target, setup.remote)["status"] == "merged"
    receipt["goal_outputs"].pop("goal_evidence")
    assert any("goal evidence" in error for error in supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime))


def test_stage5_requires_exact_frozen_review_and_real_closed_issue_fixes(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 4
    reviewed = write_goal_evidence(setup, setup.ledger, findings=[{"finding_id": "trait-001", "status": "open", "summary": "A related trait defect"}])
    ledger = instance.advance(setup.target, setup.ledger, reviewed, {"status": "merged"}, "native_completed")
    receipt = write_goal_evidence(setup, ledger)
    errors = supervisor.validate_receipt(receipt, ledger, setup.target, setup.runtime)
    assert any("disappeared" in error or "scope" in error for error in errors)
    from kg_microbe_workflows import evidence_directory
    artifact = evidence_directory(ledger["run_id"], 1, 5, 1) + "/validation.md"
    group = {"group_id": "related-traits", "summary": "Related trait defects", "finding_ids": ["trait-001"], "issue_url": "https://github.com/CultureBotAI/TraitMech/issues/23",
             "status": "resolved", "resolution_evidence": [artifact]}
    finding = {"finding_id": "trait-001", "status": "resolved", "summary": "Resolved trait defect", "carried_from": "trait-001",
               "group_id": group["group_id"], "issue_url": group["issue_url"]}
    receipt = write_goal_evidence(setup, ledger, findings=[finding], groups=[group])
    assert supervisor.validate_receipt(receipt, ledger, setup.target, setup.runtime) == []
    setup.remote.snapshot()
    assert supervisor.verify_remote_receipt(receipt, ledger, setup.target, setup.remote)["status"] == "merged"
    receipt["issues"] = []
    assert any("matching independently verified" in error for error in supervisor.validate_receipt(receipt, ledger, setup.target, setup.runtime))


def test_stage6_requires_frozen_infrastructure_plan_and_blocks_uncommitted_next_profile(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 6
    receipt = write_goal_evidence(setup, setup.ledger)
    assert supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime) == []
    setup.remote.snapshot()
    path = Path(setup.target["workflow_profile_path"])
    candidate = json.loads(path.read_text())
    candidate["stages"][0]["goal_text"] = "Evolved next-cycle objective"
    path.write_text(json.dumps(candidate))
    # A queued edit is not active-policy drift, and never changes this cycle.
    instance.check_workflow(setup.target, setup.ledger)
    assert supervisor.stage_profile(setup.target, 1, setup.ledger)["goal_text"] != candidate["stages"][0]["goal_text"]
    with pytest.raises(supervisor.SupervisorError, match="not committed"):
        instance.advance(setup.target, setup.ledger, receipt, {"status": "merged"}, "native_completed")
    assert setup.ledger["cycle"] == 1 and setup.ledger["completed_stages"] == []
    setup.remote.snapshot()
    advanced = instance.advance(setup.target, setup.ledger, receipt, {"status": "merged"}, "native_completed")
    assert advanced["cycle"] == 2 and supervisor.stage_profile(setup.target, 1, advanced)["goal_text"] == candidate["stages"][0]["goal_text"]
    assert setup.ledger["workflow"] != advanced["workflow"]


def test_migration_preserves_native_goal_and_old_receipts_but_handoff_is_not_completion(cycle_setup, monkeypatch):
    setup = cycle_setup
    legacy_target = {key: value for key, value in setup.target.items() if key != "_workflow"}
    legacy = supervisor.new_ledger(setup.config, legacy_target)
    legacy.update(adopted_goal=copy.deepcopy(GOAL), stage=4,
                  actions={"original": {"kind": "finalize", "state": "uncertain", "stage": 4,
                                    "marker": "original-marker", "reserved_epoch_ms": 1,
                                    "native_session_id": setup.target["native_session_id"]}},
                  completed_stages=[{"stage": 1, "receipt_sha256": "a" * 64}])
    review = setup.repo / "migration-review.md"
    review.write_text("Independent migration review preserves native identity and history.\n")
    setup.target["workflow_migration"] = {"ledger_sha256": supervisor.digest(legacy), "goal_identity": dict(GOAL),
        "reviewed_by": "offline-reviewer", "reason": "Adopt the authorized six-stage workflow",
        "review": {"artifact": str(review), "sha256": hashlib.sha256(review.read_bytes()).hexdigest()}}
    migrated = supervisor.migrate_ledger(legacy, setup.target, setup.target["_workflow"])
    assert migrated["adopted_goal"] == legacy["adopted_goal"] and migrated["stage"] == 4
    assert migrated["actions"]["original"]["state"] == "uncertain"
    assert migrated["completed_stages"][0]["receipt_sha256"] == "a" * 64
    decision = supervisor.decide(migrated, setup.observation)
    assert decision["action"] == "policy_update"
    instance = cycle_instance(setup, monkeypatch)
    instance.check_workflow(setup.target, migrated)
    action = instance.dispatch(setup.target, migrated, decision)
    Path(setup.config["history_path"]).write_text(json.dumps({"workspace": setup.target["root"],
        "conversationId": setup.target["native_session_id"], "timestamp": action["reserved_epoch_ms"] + 1,
        "display": action["transport_message"]}) + "\n")
    instance.reconcile(setup.target, migrated, setup.observation)
    assert migrated["policy_notification_required"]
    confirm_native_input(instance, action)
    instance.reconcile(setup.target, migrated, setup.observation)
    assert not migrated["policy_notification_required"]
    setup.observation["goal_state"] = "active"
    setup.target["allow_receipt_completion_override"] = True
    with pytest.raises(supervisor.SupervisorError, match="not completed"):
        supervisor.completion_authority(setup.target, migrated, setup.observation)
    invalid = copy.deepcopy(legacy)
    invalid["adopted_goal"]["start_step_index"] += 1
    with pytest.raises(supervisor.SupervisorError, match="exact reviewed"):
        supervisor.migrate_ledger(invalid, setup.target, setup.target["_workflow"])


def test_cycle_pin_and_core_source_drift_fail_closed(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    instance.check_workflow(setup.target, setup.ledger)
    path = instance.directory(setup.target) / "effective-workflow.json"
    snapshot = supervisor.read_json(path)
    snapshot["effective"]["stages"][0]["goal_text"] = "tampered runtime instructions"
    supervisor.atomic_json(path, snapshot)
    with pytest.raises(supervisor.SupervisorError, match="snapshot changed"):
        instance.check_workflow(setup.target, setup.ledger)
    path.unlink()
    core = setup.repo / "core.yaml"
    core.write_text("original core")
    setup.ledger["workflow"]["effective"]["sources"] = [{"path": str(core), "sha256": hashlib.sha256(core.read_bytes()).hexdigest(), "kind": "schema"}]
    setup.ledger["workflow"]["sha256"] = supervisor.digest(setup.ledger["workflow"]["effective"])
    core.write_text("unreviewed changed core")
    with pytest.raises(supervisor.SupervisorError, match="hash mismatch"):
        instance.check_workflow(setup.target, setup.ledger)


def test_semantically_equal_rewritten_review_manifest_cannot_replace_verified_source(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 4
    reviewed = write_goal_evidence(setup, setup.ledger)
    ledger = instance.advance(setup.target, setup.ledger, reviewed, {"status": "merged"}, "native_completed")
    receipt = write_goal_evidence(setup, ledger)
    manifest = setup.repo / receipt["goal_outputs"]["goal_evidence"]["path"]
    data = json.loads(manifest.read_text())
    original = setup.repo / data["previous_evidence"]["path"]
    alternate = original.parent / "rewritten-evidence.yaml"
    alternate.write_text(json.dumps(json.loads(original.read_text()), indent=2))
    data["previous_evidence"] = {"path": str(alternate.relative_to(setup.repo)), "sha256": hashlib.sha256(alternate.read_bytes()).hexdigest()}
    manifest.write_text(json.dumps(data))
    receipt["goal_outputs"]["goal_evidence"]["sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert supervisor.validate_receipt(receipt, ledger, setup.target, setup.runtime), "Rewritten evidence must not replace the verified manifest"


def test_stage6_cannot_replace_frozen_notebook_with_later_empty_scope(cycle_setup):
    setup = cycle_setup
    setup.ledger["stage"] = 6
    notebook = setup.repo / "INFRA_TASKS.md"
    notebook.write_text(notebook.read_text().replace("tasks: []", 'tasks:\n- task_id: upgrade-a\n  summary: Upgrade required validator\n  status: note'))
    setup.ledger["infra_scope"] = supervisor.freeze_infrastructure(setup.target)
    notebook.write_text(notebook.read_text().split("<!-- mech-infra-tasks:start -->")[0] +
                        '<!-- mech-infra-tasks:start -->\n```yaml\nschema_version: "1.0.0"\ntasks: []\n```\n<!-- mech-infra-tasks:end -->\n')
    setup.receipt["goal_outputs"]["infra_tasks"]["sha256"] = hashlib.sha256(notebook.read_bytes()).hexdigest()
    receipt = write_goal_evidence(setup, setup.ledger)
    assert any("supervisor-frozen" in error for error in supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime))


def test_stage6_freeze_is_prepared_before_transition_and_survives_restart(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 4
    reviewed = write_goal_evidence(setup, setup.ledger)
    stage5 = instance.advance(setup.target, setup.ledger, reviewed, {"status": "merged"}, "native_completed")
    resolution = write_goal_evidence(setup, stage5)
    advanced = instance.advance(setup.target, stage5, resolution, {"status": "merged"}, "native_completed")
    scope = advanced["infra_scope"]
    assert scope["sha256"] == hashlib.sha256((setup.repo / "INFRA_TASKS.md").read_bytes()).hexdigest()
    instance.save(setup.target, advanced)
    restored = supervisor.read_json(instance.directory(setup.target) / "ledger.json")
    assert restored["infra_scope"] == scope
    assert supervisor.read_json(instance.directory(setup.target) / "cycles/cycle-000001/infra-scope.json") == scope


def test_only_exact_migrated_current_stage_accepts_old_receipt(cycle_setup):
    setup = cycle_setup
    setup.ledger["legacy_receipt_stage"] = 1
    receipt = copy.deepcopy(setup.receipt)
    receipt["schema_version"] = 1
    for key in ("cycle", "workflow_sha256", "goal_outputs"):
        receipt.pop(key)
    assert supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime) == []
    setup.ledger["cycle"] = 2
    assert supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime)
    setup.ledger.update(cycle=1, stage=4, legacy_receipt_stage=4)
    receipt["stage"] = 4
    assert any("goal evidence" in error for error in supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime))


def test_cancelled_migrated_goal_never_receives_policy_handoff(cycle_setup):
    cycle_setup.ledger["policy_notification_required"] = True
    cycle_setup.observation["goal_state"] = "cancelled"
    assert supervisor.decide(cycle_setup.ledger, cycle_setup.observation)["phase"] == "blocked"


def test_restart_uses_pinned_cycle_while_next_profile_is_being_edited(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    instance.save(setup.target, setup.ledger)
    instance.check_workflow(setup.target, setup.ledger)
    Path(setup.target["workflow_profile_path"]).write_text("unfinished: [")
    monkeypatch.setattr(supervisor, "ROOT", setup.runtime.parents[1])
    loaded = supervisor.validate_config(copy.deepcopy(setup.config), resolve_repositories=False)
    assert loaded["targets"][0]["_workflow"] == setup.ledger["workflow"]["effective"]
    restored = supervisor.Supervisor(loaded, native=SimpleNamespace(), notifier=SimpleNamespace(), runner=setup.remote)
    restored.check_workflow(loaded["targets"][0], setup.ledger)
    setup.ledger["stage"] = 6
    receipt = write_goal_evidence(setup, setup.ledger)
    with pytest.raises(ValueError, match="invalid workflow YAML"):
        restored.advance(setup.target, setup.ledger, receipt, {"status": "merged"}, "native_completed")
    assert setup.ledger["cycle"] == 1


def test_nonregular_runtime_input_cannot_block_the_fleet(cycle_setup):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO regression requires Unix")
    fifo = cycle_setup.runtime / "runtime-input.json"
    os.mkfifo(fifo)
    probe = '''
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("supervisor",sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    module.read_json(Path(sys.argv[2]))
except module.SupervisorError as error:
    print(str(error))
'''
    try:
        result = subprocess.run([sys.executable, "-c", probe, str(Path(supervisor.__file__).resolve()), str(fifo)],
                                capture_output=True, text=True, check=True, timeout=3)
    except subprocess.TimeoutExpired:
        pytest.fail("runtime FIFO blocked the fleet")
    assert "regular file" in result.stdout


def test_migrated_pending_next_goal_is_reconciled_without_new_identifier_resend(cycle_setup, monkeypatch):
    setup = cycle_setup
    ledger = setup.ledger
    ledger.update(stage=2, awaiting_goal=True)
    ledger["actions"]["old-v1-identifier"] = {"kind": "start_goal", "stage": 2, "cycle": 1,
        "state": "uncertain", "marker": "MECH-WORKFLOW-old-v1-identifier", "reserved_epoch_ms": 1,
        "message": "/goal already started MECH-WORKFLOW-old-v1-identifier",
        "native_session_id": setup.target["native_session_id"]}
    assert supervisor.decide(ledger, setup.observation)["phase"] == "awaiting_native_acceptance"
    setup.observation["goal_identity"]["start_step_index"] += 1
    setup.observation["native"]["current_goal"].update(
        start_step_index=setup.observation["goal_identity"]["start_step_index"],
        goal_text="already started MECH-WORKFLOW-old-v1-identifier")
    instance = cycle_instance(setup, monkeypatch)
    confirm_native_input(instance, ledger["actions"]["old-v1-identifier"],
                         index=setup.observation["goal_identity"]["start_step_index"])
    instance.reconcile(setup.target, ledger, setup.observation)
    assert not ledger["awaiting_goal"]
    assert ledger["actions"]["old-v1-identifier"]["state"] == "accepted"


def test_cycle_activation_rechecks_candidate_github_repository(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 6
    receipt = write_goal_evidence(setup, setup.ledger)
    path = Path(setup.target["workflow_profile_path"])
    candidate = json.loads(path.read_text())
    candidate["github_repository"] = "DifferentOwner/DifferentMech"
    path.write_text(json.dumps(candidate))
    setup.remote.snapshot()
    with pytest.raises(supervisor.SupervisorError, match="repository identity"):
        instance.advance(setup.target, setup.ledger, receipt, {"status": "merged"}, "native_completed")
    assert setup.ledger["cycle"] == 1 and setup.ledger["completed_stages"] == []


def test_no_change_resolution_still_checks_deferred_issue_is_real_and_open(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 4
    reviewed = write_goal_evidence(setup, setup.ledger,
        findings=[{"finding_id": "trait-001", "status": "open", "summary": "Needs additional evidence"}])
    ledger = instance.advance(setup.target, setup.ledger, reviewed, {"status": "merged"}, "native_completed")
    group = {"group_id": "related-traits", "summary": "Related evidence gaps", "finding_ids": ["trait-001"],
             "issue_url": "https://github.com/CultureBotAI/TraitMech/issues/23", "status": "deferred",
             "disposition": "Await primary evidence"}
    finding = {"finding_id": "trait-001", "summary": "Needs additional evidence", "status": "deferred",
               "disposition": group["disposition"], "group_id": group["group_id"], "issue_url": group["issue_url"],
               "carried_from": "trait-001"}
    receipt = write_goal_evidence(setup, ledger, findings=[finding], groups=[group])
    receipt.update(status="no_changes", pr=None, issues=[], no_changes={"head_sha": HEAD,
        "explanation": "The exact evidence was already committed", "no_goal_owned_changes": True, "no_open_goal_pr": True})
    setup.remote.snapshot()
    assert supervisor.validate_receipt(receipt, ledger, setup.target, setup.runtime) == []
    setup.remote.issue = {"state": "closed"}
    with pytest.raises(supervisor.SupervisorError, match="must remain open"):
        supervisor.verify_remote_receipt(receipt, ledger, setup.target, setup.remote)
    setup.remote.issue = {"state": "open", "pull_request": {}}
    with pytest.raises(supervisor.SupervisorError, match="must remain open"):
        supervisor.verify_remote_receipt(receipt, ledger, setup.target, setup.remote)
    setup.remote.issue = {"state": "open"}
    assert supervisor.verify_remote_receipt(receipt, ledger, setup.target, setup.remote)["status"] == "no_changes"
    assert any("/issues/23" in args[-1] for args in setup.remote.calls)


def test_previous_review_payload_cannot_be_overwritten_before_resolution(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 4
    reviewed = write_goal_evidence(setup, setup.ledger)
    ledger = instance.advance(setup.target, setup.ledger, reviewed, {"status": "merged"}, "native_completed")
    receipt = write_goal_evidence(setup, ledger)
    old = ledger["completed_stages"][-1]["goal_evidence_snapshot"]["artifacts"][0]
    (setup.repo / old["path"]).write_text("Overwritten immutable report\n")
    setup.remote.snapshot()
    assert any("archived workflow evidence" in error for error in supervisor.validate_receipt(receipt, ledger, setup.target, setup.runtime))
    with pytest.raises(supervisor.SupervisorError, match="archived workflow evidence"):
        supervisor.verify_remote_receipt(receipt, ledger, setup.target, setup.remote)


def test_later_cycle_closure_retains_prior_infrastructure_payloads_in_git(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 6
    closed = write_goal_evidence(setup, setup.ledger)
    setup.remote.snapshot()
    ledger = instance.advance(setup.target, setup.ledger, closed, {"status": "merged"}, "native_completed")
    receipt = write_goal_evidence(setup, ledger)
    old = ledger["completed_stages"][-1]["goal_evidence_snapshot"]["artifacts"][0]
    assert old["path"] in setup.remote.tree
    setup.remote.tree.pop(old["path"])
    with pytest.raises(supervisor.SupervisorError, match="not versioned"):
        supervisor.verify_remote_receipt(receipt, ledger, setup.target, setup.remote)


def test_parent_strengthened_early_stage_outputs_are_required(cycle_setup):
    setup = cycle_setup
    effective = setup.ledger["workflow"]["effective"]
    effective["stages"][0]["required_outputs"] = ["validation"]
    setup.ledger["workflow"]["sha256"] = supervisor.digest(effective)
    receipt = copy.deepcopy(setup.receipt)
    receipt["workflow_sha256"] = setup.ledger["workflow"]["sha256"]
    assert "goal_evidence" in supervisor.receipt_template(setup.ledger, setup.target)["goal_outputs"]
    assert any("goal evidence" in error for error in supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime))
    receipt = write_goal_evidence(setup, setup.ledger)
    assert supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime) == []
    path = setup.repo / receipt["goal_outputs"]["goal_evidence"]["path"]
    data = json.loads(path.read_text())
    data["artifacts"] = []
    path.write_text(json.dumps(data))
    receipt["goal_outputs"]["goal_evidence"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert any("required" in error for error in supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime))


def test_local_candidate_cannot_relabel_canonical_parent_provenance(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 6
    receipt = write_goal_evidence(setup, setup.ledger)
    path = Path(setup.target["workflow_profile_path"])
    profile = json.loads(path.read_text())
    profile["parent"]["revision"] = "d" * 40
    path.write_text(json.dumps(profile))
    setup.remote.snapshot()
    with pytest.raises(supervisor.SupervisorError, match="parent provenance"):
        instance.advance(setup.target, setup.ledger, receipt, {"status": "merged"}, "native_completed")
    assert setup.ledger["cycle"] == 1


@pytest.mark.parametrize("damage", ["untracked", "overwritten"])
def test_early_stage_preserves_superseded_ancestors_of_archived_infrastructure(cycle_setup, monkeypatch, damage):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    setup.ledger["stage"] = 6
    receipt = write_goal_evidence(setup, setup.ledger)
    first_ref = copy.deepcopy(receipt["goal_outputs"]["goal_evidence"])
    first = json.loads((setup.repo / first_ref["path"]).read_text())
    second = copy.deepcopy(first)
    second.update(revision=2, supersedes_evidence=first_ref)
    for artifact in second["artifacts"]:
        original = setup.repo / artifact["path"]
        artifact["path"] = artifact["path"].replace("revision-0001/", "revision-0002/")
        destination = setup.repo / artifact["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(original.read_bytes())
    second_path = setup.repo / first_ref["path"].replace("revision-0001/", "revision-0002/")
    second_path.write_text(json.dumps(second))
    receipt["goal_outputs"]["goal_evidence"] = {"path": str(second_path.relative_to(setup.repo)),
                                                "sha256": hashlib.sha256(second_path.read_bytes()).hexdigest()}
    assert supervisor.validate_receipt(receipt, setup.ledger, setup.target, setup.runtime) == []
    setup.remote.snapshot()
    ledger = instance.advance(setup.target, setup.ledger, receipt, {"status": "merged"}, "native_completed")
    early = write_goal_evidence(setup, ledger)
    assert "goal_evidence" not in early["goal_outputs"]
    ancestor = first["artifacts"][0]["path"]
    if damage == "untracked":
        setup.remote.tree.pop(ancestor)
    else:
        (setup.repo / ancestor).write_text("Overwritten superseded infrastructure report\n")
        setup.remote.snapshot()
    with pytest.raises(supervisor.SupervisorError, match="not versioned|archived workflow evidence"):
        supervisor.verify_remote_receipt(early, ledger, setup.target, setup.remote)


def test_compacting_conversation_counts_as_busy():
    screen = (
        "Earlier output\n"
        "✻ Compacting conversation... (esc to interrupt · 19s)\n"
        "────────────────────────\n>\n────────────────────────\n"
        "  ? for shortcuts                                         Gemini 3.1 Pro (High)\n"
    )
    assert supervisor.terminal_busy_reason(screen) == "busy, background, or queued terminal state"
    quiet_compaction = screen.replace("(esc to interrupt · 19s)", "(19s)")
    assert supervisor.terminal_busy_reason(quiet_compaction) == "busy, background, or queued terminal state"


@pytest.mark.parametrize("screen", [
    # ttys020 (communitymech): duplicate > below footer and missing top border
    "────────────────────────────────────────\n>\n────────────────────────────────────────\n? for shortcuts                                            Gemini 4 Argon · high\n>\n────────────────────────────────────────\nesc to cancel                                              Gemini 4 Argon · high\n",
    # ttys021 / ttys025 (culturemech / mediaingredientmech): missing bottom border (blank line after >)
    "────────────────────────────────────────\n>\n\n? for shortcuts                                            Gemini 4 Argon · high\n\n",
    # ttys022 (dufmech): overwritten top border and blank line after >
    "──────wrote completion.json.                                               ─────\n>\n\nesc to cancel                                              Gemini 4 Argon · high\n\n\n? for shortcuts\n",
    # ttys024 / ttys027 (habitatmech / pathwaymech): duplicate > line and missing bottom border
    "────────────────────────────────────────\n>\n>\n? for shortcuts                                            Gemini 4 Argon · high\nesc to cancel                                              Gemini 4 Argon · high\n",
    # ttys026 (naturalproductmech): missing top border (blank line before >)
    "⣟  Generating...\n\n>\n────────────────────────────────────────\nesc to cancel                                              Gemini 4 Argon · high\n? for shortcuts\n",
    # Missing top border with earlier submitted user prompt and assistant output in scrollback
    "────────────────────────────────────────\n> /goal earlier submitted prompt\n● Explored 3 files\n⣟  Generating...\n\n>\n────────────────────────────────────────\nesc to cancel                                              Gemini 4 Argon · high\n? for shortcuts\n",
    # Leftover esc to cancel on its own line in footer
    "────────────────────────\n>\n────────────────────────\n  esc to cancel\n  ? for shortcuts                                         Gemini 3.1 Pro (High)\n",
    # ttys020 (communitymech): response text spliced onto composer > line with old > in scrollback (composer-too-far-from-footer)
    ">\nEarlier output\n" + "\n".join(f"line {i}" for i in range(15)) + "\n────────────────────────────────────────────────────────────────────────────────\nNothing to commit, working tree clean); wrote completion receipt.   > 2052` merged at `2026-10-22T01:02:13Z`\n────────────────────────────────────────────────────────────────────────────────\n  ? for shortcuts                                         Gemini 3.1 Pro (High)\n",
    # Response text spliced onto composer > line without any prior > in scrollback (no-empty-composer)
    "Earlier output\n────────────────────────────────────────────────────────────────────────────────\nNothing to commit, working tree clean); wrote completion receipt.   > 2052` merged at `2026-10-22T01:02:13Z`\n────────────────────────────────────────────────────────────────────────────────\n  ? for shortcuts                                         Gemini 3.1 Pro (High)\n",
    # Response text spliced onto composer > line with stale > within 9 lines of bottom above top border
    ">\nEarlier output\n────────────────────────────────────────────────────────────────────────────────\nNothing to commit, working tree clean); wrote completion receipt.   > 2052` merged at `2026-10-22T01:02:13Z`\n────────────────────────────────────────────────────────────────────────────────\n  ? for shortcuts                                         Gemini 3.1 Pro (High)\n",
])
def test_confirmed_display_corruption_accepts_distorted_idle_composers(screen):
    assert supervisor.confirmed_display_corruption(screen) is True


@pytest.mark.parametrize("screen", [
    # Healthy idle composer
    "Earlier output\n────────────────────────\n>\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # Single-line unsent user draft (ttys017 AntibioticMech)
    "────────────────────────────────────────\n> /goal review all records and add uniprot protein examples espcially for gene\n    or protein elements of causal graphs. make a claude skill for this\n────────────────────────────────────────\n                                                           Gemini 4 Argon · high\n",
    # Single-line unsent user draft with old > in scrollback (composer-too-far-from-footer)
    ">\n" + "\n".join(f"line {i}" for i in range(15)) + "\n────────────────────────────────────────\n> /goal continue unfinished stage\n────────────────────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # Multi-line unsent draft with trailing empty >
    "────────────────────────\n> first draft line\n>\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # 5+ line multi-line unsent draft ending with a trailing empty > (first draft line > 4 lines above >)
    "────────────────────────\n> first draft line\n  second line\n  third line\n  fourth line\n  fifth line\n>\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # 5+ line multi-line unsent draft with a blank line before trailing empty >
    "────────────────────────\n> first draft line\n  second line\n  third line\n  fourth line\n  fifth line\n\n>\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # Long multi-line unsent draft whose final continuation line contains " > " above bottom border
    "────────────────────────\n> first draft line\n  second line\n  third line\n  fourth line\n  fifth line\n  sixth line with > token\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # Continuation text below >
    "────────────────────────\n>\nunsubmitted second line\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # Approval / feedback menu
    "────────────────────────\n>\n────────────────────────\nHow's the CLI experience so far?\n1. Good\n2. Fine\n  Gemini 3.1 Pro (High)\n",
    # Native inline bash approval prompt above a missing-border composer
    " ┃ self needs approval for Bash\n ┃ ────────────────────────────────────────\n ┃ ● Bash(git status)\n ┃ ctrl+k approve · alt+j manage\n────────────────────────────────────────\n>\n\n  ? for shortcuts  Gemini 4 Argon · high\n",
    # Native inline bash approval prompt where ctrl+k row is blanked and header is > 4 lines above >
    " ┃ self needs approval for Bash\n ┃ ────────────────────────────────────────\n ┃ ● Bash(git status\n ┃   --short\n ┃   --branch)\n ┃\n────────────────────────────────────────\n>\n\n  ? for shortcuts  Gemini 4 Argon · high\n",
    # Multi-line native inline approval header above composer without ┃ on bottom rows
    "  self needs approval for Bash\n  ● Bash(git diff\n    --stat\n    origin/main\n    HEAD)\n────────────────────────────────────────\n>\n\n  ? for shortcuts  Gemini 4 Argon · high\n",
    # Spliced composer line mentioning Gemini on the prompt line itself but missing Gemini footer below
    "────────────────────────\nChecked Gemini 3.1 Pro output   > trailing text\n────────────────────────\n  ? for shortcuts\n",
    # Busy / compacting state
    "✻ Compacting conversation...\n>\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # Busy background task state on a spliced composer line
    "● 1 background task running\n────────────────────────\nNothing to commit   > 2052\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
    # Non-border text around >
    "not a border\n>\nnot a border\n  ? for shortcuts  Gemini 3.1 Pro (High)\n",
])
def test_confirmed_display_corruption_rejects_healthy_drafts_menus_and_busy(screen):
    assert supervisor.confirmed_display_corruption(screen) is False


def test_observe_redraws_confirmed_corruption_only_when_allowed(setup, monkeypatch):
    distorted = "  Committed d843d7b.\n>\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n"
    healthy = "  Committed d843d7b.\n────────────────────────\n>\n────────────────────────\n  ? for shortcuts  Gemini 3.1 Pro (High)\n"
    cache_path = setup.runtime / "conversations.json"
    cache_path.write_text(json.dumps({str(setup.repo.resolve()): setup.target["native_session_id"]}))
    setup.config["conversation_cache_path"] = str(cache_path)
    setup.config["conversation_dir"] = str(setup.runtime / "conversations")
    calls = []

    def fake_jxa(source, payload):
        calls.append((source, payload))
        if source == notifier.SNAPSHOT_JS:
            return json.dumps({"tabs": [{"window": 1, "tab": 1, "tty": setup.target["tty"], "screen": distorted}], "warnings": []})
        if source == supervisor.REDRAW_JS:
            return json.dumps({"status": "redrawn", "rows": 22, "restoredRows": 22, "screen": healthy})
        raise AssertionError("unexpected JXA call")

    notifier = SimpleNamespace(
        SNAPSHOT_JS="snapshot",
        live_process=lambda pid: {"pid": pid, "tty": setup.target["tty"], "identity": setup.target["process_identity"]},
        process_cwd=lambda pid: setup.repo.resolve(),
        foreground=lambda pid, tty: True,
        jxa=fake_jxa,
        composer_reason=supervisor.import_file(Path(__file__).parents[1] / "scripts/mech_session_terminal.py", "t").composer_reason,
    )
    native = SimpleNamespace(inspect=lambda root, sid: {
        "conversation_id": sid,
        "native_execution_state": "idle_candidate",
        "current_goal": {**GOAL, "state": "completed", "goal_text": "goal"},
    })
    gh = GitHubFixture()
    def runner(args, **kw):
        if args[0] == "/bin/ps":
            return SimpleNamespace(stdout=f"{setup.target['pid']} agy\n", stderr="", returncode=0)
        return gh(args, **kw)

    instance = supervisor.Supervisor(setup.config, native=native, notifier=notifier, runner=runner)
    obs_readonly = instance.observe(setup.target, fresh=True, allow_redraw=False)
    assert obs_readonly["ready"] is False
    assert obs_readonly["readiness_reason"] == "missing-composer-borders"
    assert len(calls) == 1

    obs_redraw = instance.observe(setup.target, fresh=True, allow_redraw=True)
    assert obs_redraw["ready"] is True
    assert obs_redraw["readiness_reason"] is None
    assert obs_redraw["redraw"] == {"status": "redrawn", "rows": 22, "restored_rows": 22}
    assert len(calls) == 3


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed to execute JXA scripts offline")
def test_send_js_and_redraw_js_use_history_tail_and_restore_rows(setup):
    harness = r'''
    let sent = [];
    let currentRows = 22;
    let historyText = "X".repeat(70000) + "\nexpected tail";
    let refreshedText = "X".repeat(70000) + "\nrefreshed tail";
    let didBump = false;
    global.delay = () => {};
    const tabObj = {
        tty: () => "/dev/ttys030",
        contents: () => "stale scrolled viewport",
        history: () => (didBump ? refreshedText : historyText),
        numberOfRows: () => currentRows,
    };
    Object.defineProperty(tabObj, "numberOfRows", {
        get: () => () => currentRows,
        set: (val) => {
            if (val === 23) didBump = true;
            currentRows = val;
        },
    });
    global.Application = name => {
        if (name === "Terminal") {
            return {
                windows: () => [{id: () => 1, tabs: () => [tabObj]}],
                doScript: (msg) => { sent.push(msg); },
            };
        }
        return {
            includeStandardAdditions: false,
            doShellScript: (cmd) => {
                if (cmd.includes("lstart=")) return "1234 ttys030 Mon Oct 19 10:00:00 2026 agy";
                if (cmd.includes("lsof")) return "p1234\nn/repo/TraitMech";
                if (cmd.includes("pgid=")) return "1234 1234";
                throw Error("unexpected cmd: " + cmd);
            },
        };
    };
    global.Application.currentApplication = () => global.Application("System");
    '''
    payload = {
        "window": 1, "tab": 1, "tty": "/dev/ttys030", "pid": 1234,
        "identity": "1234 ttys030 Mon Oct 19 10:00:00 2026 agy",
        "cwd": "/repo/TraitMech",
        "screen": ("X" * 64000)[-64000 + len("\nexpected tail"):] + "\nexpected tail",
        "message": "hello world",
    }
    send_prog = harness + supervisor.SEND_JS + f"\nconst out = run([JSON.stringify({json.dumps(payload)})]); process.stdout.write(JSON.stringify({{out, sent}}));"
    res = json.loads(subprocess.run(["node", "-e", send_prog], text=True, capture_output=True, check=True).stdout)
    assert res["out"] == "sent" and res["sent"] == ["hello world"]

    mismatch_payload = {**payload, "screen": "stale scrolled viewport"}
    mismatch_prog = harness + supervisor.SEND_JS + f"\nconst out = run([JSON.stringify({json.dumps(mismatch_payload)})]); process.stdout.write(JSON.stringify({{out, sent}}));"
    res_mismatch = json.loads(subprocess.run(["node", "-e", mismatch_prog], text=True, capture_output=True, check=True).stdout)
    assert res_mismatch["out"] == "screen-changed" and res_mismatch["sent"] == []

    redraw_prog = harness + supervisor.REDRAW_JS + f"\nconst out = JSON.parse(run([JSON.stringify({json.dumps(payload)})])); process.stdout.write(JSON.stringify({{out, currentRows}}));"
    res_redraw = json.loads(subprocess.run(["node", "-e", redraw_prog], text=True, capture_output=True, check=True).stdout)
    assert res_redraw["out"]["status"] == "redrawn"
    assert res_redraw["out"]["rows"] == 22
    assert res_redraw["out"]["restoredRows"] == 22
    assert res_redraw["currentRows"] == 22
    assert res_redraw["out"]["screen"].endswith("\nrefreshed tail")



HIST_HEAD = "d" * 40
HIST_FIX = "e" * 40
HIST_MERGE = "f" * 40
CURRENT_BASE = "1" * 40


class HistoricalGitHubFixture(CycleGitHubFixture):
    """Prior squash merge is inherited; its original fix commit need not be."""
    def __init__(self, root):
        super().__init__(root)
        self.pr["base"]["sha"] = CURRENT_BASE
        self.historical_pr = copy.deepcopy(self.pr)
        self.historical_pr.update(merge_commit_sha=HIST_MERGE)
        self.historical_pr["head"].update(sha=HIST_HEAD, ref="curation/previous")
        self.historical_commits = [[{"sha": HIST_FIX}, {"sha": HIST_HEAD}]]
        self.historical_issue = {"state": "closed"}
        self.historical_ancestry = {}

    def __call__(self, args, **kwargs):
        endpoint = args[-1]
        if args[:2] == ["gh", "api"]:
            if endpoint.endswith("/pulls/41"):
                self.calls.append(args)
                return SimpleNamespace(stdout=json.dumps(self.historical_pr), stderr="", returncode=0)
            if endpoint.endswith("/pulls/41/commits?per_page=100"):
                self.calls.append(args)
                return SimpleNamespace(stdout=json.dumps(self.historical_commits), stderr="", returncode=0)
            if endpoint.endswith("/issues/23"):
                self.calls.append(args)
                return SimpleNamespace(stdout=json.dumps(self.historical_issue), stderr="", returncode=0)
            if endpoint.endswith("/issues/24"):
                self.calls.append(args)
                return SimpleNamespace(stdout=json.dumps(self.issue), stderr="", returncode=0)
        if args[:1] == ["git"] and args[3:5] == ["merge-base", "--is-ancestor"]:
            if args[-2] == HIST_FIX:
                return SimpleNamespace(stdout="", stderr="", returncode=1)
            if args[-2] == HIST_MERGE:
                self.calls.append(args)
                return SimpleNamespace(stdout="", stderr="", returncode=self.historical_ancestry.get(args[-1], 0))
        return super().__call__(args, **kwargs)


@pytest.fixture
def historical_setup(cycle_setup, monkeypatch):
    setup = cycle_setup
    instance = cycle_instance(setup, monkeypatch)
    finding = {"finding_id": "trait-001", "status": "resolved", "summary": "Previously fixed trait defect",
               "carried_from": "trait-001", "group_id": "related-traits",
               "issue_url": "https://github.com/CultureBotAI/TraitMech/issues/23"}
    setup.ledger["stage"] = 4
    reviewed = write_goal_evidence(setup, setup.ledger, findings=[finding])
    old_ledger = instance.advance(setup.target, setup.ledger, reviewed, {"status": "merged"}, "native_completed")
    from kg_microbe_workflows import evidence_directory
    def group(cycle):
        return {"group_id": "related-traits", "summary": "Previously fixed defect", "finding_ids": ["trait-001"],
                "issue_url": finding["issue_url"], "status": "resolved",
                "resolution_evidence": [evidence_directory(old_ledger["run_id"], cycle, 5, 1) + "/validation.md"]}
    prior = write_goal_evidence(setup, old_ledger, findings=[finding], groups=[group(1)])
    prior["pr"].update(number=41, head_sha=HIST_HEAD, branch="curation/previous")
    prior["issues"][0]["fix_commit_sha"] = HIST_FIX
    old_record = {"cycle": 1, "stage": 5, "receipt_sha256": supervisor.digest(prior),
                  "verification": {"status": "merged", "pr_number": 41, "head_sha": HIST_HEAD,
                                   "merge_commit_sha": HIST_MERGE, "merged_at": "2026-10-19T12:00:00Z"},
                  "goal_evidence": copy.deepcopy(prior["goal_outputs"]["goal_evidence"]),
                  "goal_evidence_snapshot": supervisor.goal_output_data(prior, old_ledger, setup.target)}
    old_ledger["completed_stages"].append(old_record)
    old_ledger.update(cycle=2, stage=4)
    reviewed = write_goal_evidence(setup, old_ledger, findings=[finding])
    setup.ledger = instance.advance(setup.target, old_ledger, reviewed, {"status": "merged"}, "native_completed")
    receipt = write_goal_evidence(setup, setup.ledger, findings=[finding], groups=[group(2)])
    receipt["issues"] = [
        {"number": 23, "disposition": "addressed", "fix_commit_sha": HIST_FIX,
         "historical_resolution": {"github_repository": setup.target["github_repository"], "pr_number": 41,
                                   "base": "main", "head_sha": HIST_HEAD, "merge_commit_sha": HIST_MERGE,
                                   "receipt_sha256": old_record["receipt_sha256"]}},
        {"number": 24, "disposition": "addressed", "fix_commit_sha": FIX},
    ]
    setup.receipt = receipt
    setup.remote = HistoricalGitHubFixture(setup.repo)
    setup.remote.snapshot()
    setup.historical_record = next(record for record in setup.ledger["completed_stages"]
                                   if record.get("receipt_sha256") == old_record["receipt_sha256"])
    return setup


def test_historical_squash_resolution_and_current_fix_both_verify(historical_setup):
    s = historical_setup
    assert supervisor.validate_receipt(s.receipt, s.ledger, s.target, s.runtime) == []
    proof = supervisor.verify_remote_receipt(s.receipt, s.ledger, s.target, s.remote)
    assert proof["pr_number"] == 42
    assert [item["number"] for item in proof["historical_issue_resolutions"]] == [23]
    ancestry = [args[-2:] for args in s.remote.calls if args[:1] == ["git"] and args[3] == "merge-base"]
    assert [HIST_MERGE, HEAD] in ancestry and [HIST_MERGE, CURRENT_BASE] in ancestry and [HIST_MERGE, "HEAD"] in ancestry
    assert not any(pair[0] == HIST_FIX for pair in ancestry), "squashed original fixes are not merge ancestors"


@pytest.mark.parametrize("field,value", [
    ("pr_number", 42), ("pr_number", True), ("github_repository", "Other/Repo"),
    ("github_repository", None), ("base", "release"), ("head_sha", "d" * 39),
    ("merge_commit_sha", "0" * 40), ("receipt_sha256", "0" * 64),
])
def test_historical_resolution_requires_exact_prior_ledger_identity(historical_setup, field, value):
    s = historical_setup
    s.receipt["issues"][0]["historical_resolution"][field] = value
    assert supervisor.validate_receipt(s.receipt, s.ledger, s.target, s.runtime)


@pytest.mark.parametrize("mutation", [
    lambda s: s.ledger["completed_stages"].remove(s.historical_record),
    lambda s: s.ledger["completed_stages"].append(copy.deepcopy(s.historical_record)),
    lambda s: s.historical_record["verification"].update(status="no_changes"),
    lambda s: s.historical_record.update(cycle=2, stage=6),
])
def test_unverified_ambiguous_or_future_receipt_cannot_authorize_historical_fix(historical_setup, mutation):
    s = historical_setup
    mutation(s)
    assert supervisor.validate_receipt(s.receipt, s.ledger, s.target, s.runtime)


def test_historical_scope_must_already_be_resolved_in_frozen_review(historical_setup):
    s = historical_setup
    previous = supervisor.previous_evidence(s.ledger, 5)
    previous["goal_evidence_snapshot"]["findings"][0]["status"] = "open"
    # Even if metadata still claims the old issue is fixed, a reopened finding
    # requires a current fix; it cannot inherit the prior resolution.
    with pytest.raises(supervisor.SupervisorError, match="same already-resolved"):
        supervisor.verify_historical_finding_scope(s.receipt["issues"][0],
            s.historical_record["goal_evidence_snapshot"]["groups"][0], s.receipt, s.ledger, s.target,
            previous["goal_evidence_snapshot"])


def test_historical_scope_cannot_be_replaced_with_unrelated_finding(historical_setup):
    s = historical_setup
    item = copy.deepcopy(s.historical_record["goal_evidence_snapshot"]["groups"][0])
    item["finding_ids"] = ["new-unrelated-finding"]
    with pytest.raises(supervisor.SupervisorError, match="same already-resolved"):
        supervisor.verify_historical_finding_scope(s.receipt["issues"][0], item, s.receipt, s.ledger, s.target,
                                                  supervisor.previous_evidence(s.ledger, 5)["goal_evidence_snapshot"])


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r.historical_issue.update(state="open"), "not closed"),
    (lambda r: r.historical_issue.update(pull_request={}), "not closed"),
    (lambda r: r.historical_pr.update(merged=False), "historical resolution PR"),
    (lambda r: r.historical_pr.update(merge_commit_sha="0" * 40), "historical resolution PR"),
    (lambda r: r.historical_pr["head"].update(sha="0" * 40), "historical resolution PR"),
    (lambda r: r.historical_pr["head"]["repo"].update(full_name="Other/Repo"), "historical resolution PR"),
    (lambda r: r.historical_pr["base"].update(ref="release"), "historical resolution PR"),
    (lambda r: r.historical_pr["base"]["repo"].update(full_name="Other/Repo"), "historical resolution PR"),
    (lambda r: setattr(r, "historical_commits", [[{"sha": HIST_HEAD}]]), "fix is not in"),
    (lambda r: setattr(r, "historical_commits", {"error": "unavailable"}), "membership unavailable"),
    (lambda r: r.pr["base"].pop("sha"), "base commit unavailable"),
    (lambda r: r.historical_ancestry.update({HEAD: 1}), "not in current reviewed"),
    (lambda r: r.historical_ancestry.update({CURRENT_BASE: 1}), "not in current reviewed"),
    (lambda r: r.historical_ancestry.update({"HEAD": 1}), "not in current reviewed"),
])
def test_historical_remote_checks_fail_closed(historical_setup, mutation, match):
    s = historical_setup
    mutation(s.remote)
    with pytest.raises(supervisor.SupervisorError, match=match):
        supervisor.verify_remote_receipt(s.receipt, s.ledger, s.target, s.remote)


def test_current_issue_does_not_inherit_historical_exception(historical_setup):
    s = historical_setup
    s.receipt["issues"][1]["fix_commit_sha"] = HIST_FIX
    with pytest.raises(supervisor.SupervisorError, match="fix in this PR"):
        supervisor.verify_remote_receipt(s.receipt, s.ledger, s.target, s.remote)


def test_historical_entry_cannot_be_implicit(historical_setup):
    s = historical_setup
    del s.receipt["issues"][0]["historical_resolution"]
    with pytest.raises(supervisor.SupervisorError, match="fix in this PR"):
        supervisor.verify_remote_receipt(s.receipt, s.ledger, s.target, s.remote)


def test_current_ci_remains_required_with_historical_resolutions(historical_setup):
    s = historical_setup
    s.remote.checks[0]["bucket"] = "fail"
    with pytest.raises(supervisor.SupervisorError, match="CI evidence"):
        supervisor.verify_remote_receipt(s.receipt, s.ledger, s.target, s.remote)


@pytest.mark.parametrize("key,value", [("number", 999), ("fix_commit_sha", FIX), ("extra", "ignored")])
def test_historical_descriptor_cannot_override_verified_proof_fields(historical_setup, key, value):
    s = historical_setup
    s.receipt["issues"][0]["historical_resolution"][key] = value
    assert supervisor.validate_receipt(s.receipt, s.ledger, s.target, s.runtime)
    with pytest.raises(supervisor.SupervisorError, match="exact distinct prior-PR descriptor"):
        supervisor.verify_remote_receipt(s.receipt, s.ledger, s.target, s.remote)


@pytest.mark.parametrize("stage", [1, 4, 6])
def test_historical_resolution_cannot_change_other_stage_contracts(historical_setup, stage):
    s = historical_setup
    s.ledger["stage"] = stage
    s.receipt["stage"] = stage
    with pytest.raises(supervisor.SupervisorError, match="stage-5 receipt"):
        supervisor.historical_resolution_record(s.receipt["issues"][0], s.receipt, s.ledger, s.target)
