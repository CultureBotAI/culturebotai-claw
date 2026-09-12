"""Fault injections for authoritative baselines and recoverable remote writes."""
import base64
import copy
import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

import kg_microbe_merge_queue as queue

REPO = "CultureBotAI/example"
WORKFLOW_PATH = ".github/workflows/ci.yml"
WORKFLOW = """on:
  pull_request:
  merge_group:
    types: [checks_requested]
jobs:
  qc:
    runs-on: ubuntu-latest
    steps:
      - run: echo checked
"""


@pytest.fixture
def transaction(monkeypatch, tmp_path):
    policy = {"example": {WORKFLOW_PATH: ["qc"]}}
    live = {
        "repository": {"id": 1, "full_name": REPO, "private": False, "archived": False,
                       "default_branch": "main", "permissions": {"admin": True},
                       "allow_auto_merge": False, "allow_squash_merge": True},
        "owner_type": "Organization", "main_sha": "a" * 40,
        "rulesets": [], "effective_rules": [], "classic_protection": None,
        "workflows": {WORKFLOW_PATH: {
            "sha": "b" * 40, "content": base64.b64encode(WORKFLOW.encode()).decode()
        }},
    }
    monkeypatch.setattr(queue, "identities", lambda: {"example": REPO})
    monkeypatch.setattr(queue, "load_policy", lambda: policy)
    monkeypatch.setattr(queue, "snapshot", lambda *args: copy.deepcopy(live))
    monkeypatch.setattr(queue, "context_evidence", lambda *args: {"verified": "live run"})
    return live, tmp_path / "receipt.json"


class API:
    def __init__(self, live, receipt, fault=None):
        self.live, self.receipt, self.fault = live, receipt, fault
        self.calls = []

    def request(self, endpoint, method="GET", body=None):
        # Every write must have an independently readable intent before dispatch.
        journal = json.loads(self.receipt.read_text())["repositories"][0]
        intent = journal["attempts"][-1]
        assert intent == {"method": method, "endpoint": endpoint, "body": body, "status": "pending"}
        self.calls.append(method)
        if method in ("POST", "PUT"):
            response = dict(body, id=42, source_type="Repository", source=REPO)
            self.live["rulesets"] = [response]
            self.live["effective_rules"] = [dict(rule, ruleset_id=42) for rule in body["rules"]]
        elif method == "PATCH":
            self.live["repository"].update(body)
            response = self.live["repository"]
        else:
            raise AssertionError((endpoint, method))
        if self.fault:
            return self.fault(method, response)
        return response


@pytest.mark.parametrize("alter", [
    lambda before: before["repository"].update(allow_auto_merge=True),
    lambda before: before["rulesets"].append({"id": 999, "name": "fabricated baseline"}),
    lambda before: before["workflows"][WORKFLOW_PATH].update(sha="c" * 40),
    lambda before: before.pop("repository"),
])
def test_forged_baseline_stops_before_any_write(transaction, alter):
    live, receipt = transaction
    api = API(live, receipt)
    saved = queue.plan(api)
    alter(saved["repositories"][0]["before"])
    with pytest.raises(queue.QueueError, match="baseline"):
        queue.apply(api, saved, receipt)
    assert api.calls == []
    assert not receipt.exists()


def test_receipt_uses_live_baseline_and_evidence_after_unrelated_main_advance(transaction):
    live, receipt = transaction
    api = API(live, receipt)
    saved = queue.plan(api)
    # Main SHA and raw workflow content are deliberately outside the stable fingerprint.
    saved["repositories"][0]["before"]["main_sha"] = "forged"
    saved["repositories"][0]["before"]["workflows"][WORKFLOW_PATH]["content"] = "forged"
    saved["repositories"][0]["evidence"] = {"forged": "untrusted run"}
    live["main_sha"] = "c" * 40
    expected_before = copy.deepcopy(live)
    result = queue.apply(api, saved, receipt)
    assert result["plan"]["repositories"][0]["before"] == expected_before
    assert result["plan"]["repositories"][0]["evidence"] == {"verified": "live run"}
    assert saved["repositories"][0]["before"]["main_sha"] == "forged"
    assert json.loads(receipt.read_text()) == result


@pytest.mark.parametrize("fault", ["serialization", "write", "flush", "fsync", "replace"])
def test_atomic_writer_keeps_complete_previous_receipt(tmp_path, monkeypatch, fault):
    receipt = tmp_path / "receipt.json"
    before = {"complete": "baseline"}
    queue.write_json(receipt, before, exclusive=True)
    value = {"new": "state"}
    if fault == "serialization":
        value["new"] = object()
        expected = TypeError
    else:
        def fail(*args):
            raise OSError(28, "simulated persistence failure")
        if fault in ("write", "flush"):
            original_fdopen = queue.os.fdopen
            @contextmanager
            def faulty_stream(*args, **kwargs):
                with original_fdopen(*args, **kwargs) as stream:
                    wrapped = Mock(wraps=stream)
                    getattr(wrapped, fault).side_effect = fail
                    yield wrapped
            monkeypatch.setattr(queue.os, "fdopen", faulty_stream)
        else:
            monkeypatch.setattr(queue.os, fault, fail)
        expected = OSError
    with pytest.raises(expected):
        queue.write_json(receipt, value)
    assert json.loads(receipt.read_text()) == before
    assert list(tmp_path.iterdir()) == [receipt]


def test_initial_receipt_is_exclusive_and_complete(tmp_path):
    receipt = tmp_path / "receipt.json"
    queue.write_json(receipt, {"first": True}, exclusive=True)
    with pytest.raises(FileExistsError):
        queue.write_json(receipt, {"second": True}, exclusive=True)
    assert json.loads(receipt.read_text()) == {"first": True}
    assert list(tmp_path.iterdir()) == [receipt]


def test_failed_pending_journal_prevents_remote_dispatch(transaction, monkeypatch):
    live, receipt = transaction
    api = API(live, receipt)
    saved = queue.plan(api)
    def fail(*args):
        raise OSError(28, "cannot persist intent")
    monkeypatch.setattr(queue.os, "replace", fail)
    with pytest.raises(queue.QueueError, match="last durable receipt"):
        queue.apply(api, saved, receipt)
    assert api.calls == []
    written = json.loads(receipt.read_text())
    assert written["repositories"][0]["attempts"] == []
    assert written["plan"]["repositories"][0]["before"]["rulesets"] == []


def test_failed_post_write_persistence_retains_pending_intent_and_stops(transaction, monkeypatch):
    live, receipt = transaction
    api = API(live, receipt)
    saved = queue.plan(api)
    original_replace = queue.os.replace
    def fail_after_remote_write(*args):
        if api.calls:
            raise OSError(28, "disk full after committed POST")
        return original_replace(*args)
    monkeypatch.setattr(queue.os, "replace", fail_after_remote_write)
    with pytest.raises(queue.QueueError, match="last durable receipt"):
        queue.apply(api, saved, receipt)
    assert api.calls == ["POST"]
    assert live["rulesets"][0]["id"] == 42
    written = json.loads(receipt.read_text())
    row = written["repositories"][0]
    assert row["attempts"][0]["status"] == "pending"
    assert row["actions"] == []
    assert written["plan"]["repositories"][0]["before"]["rulesets"] == []


@pytest.mark.parametrize("response", [None, {}, {"id": True}, {"id": "42"}, {"id": 0}])
def test_malformed_ruleset_response_preserves_unknown_outcome(transaction, response):
    live, receipt = transaction
    api = API(live, receipt, lambda method, valid: response)
    with pytest.raises(queue.QueueError, match="outcome unknown"):
        queue.apply(api, queue.plan(api), receipt)
    assert api.calls == ["POST"]
    assert live["rulesets"][0]["id"] == 42
    row = json.loads(receipt.read_text())["repositories"][0]
    assert row["status"] == "failed"
    assert row["attempts"][0]["status"] == "unknown"
    assert row["actions"] == []


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("failure", [queue.QueueError("lost response"), OSError("transport failure"),
                                    json.JSONDecodeError("invalid response", "", 0)])
def test_committed_write_with_lost_response_is_unknown(transaction, method, failure):
    live, receipt = transaction
    def fault(actual_method, response):
        if actual_method == method:
            raise failure
        return response
    api = API(live, receipt, fault)
    with pytest.raises(queue.QueueError, match="outcome unknown"):
        queue.apply(api, queue.plan(api), receipt)
    assert api.calls == (["POST"] if method == "POST" else ["POST", "PATCH"])
    row = json.loads(receipt.read_text())["repositories"][0]
    assert row["status"] == "failed"
    assert row["attempts"][-1]["status"] == "unknown"
    assert row["attempts"][-1]["method"] == method
    assert len(row["actions"]) == (0 if method == "POST" else 1)


def test_malformed_auto_merge_response_is_unknown(transaction):
    live, receipt = transaction
    api = API(live, receipt, lambda method, valid: {} if method == "PATCH" else valid)
    with pytest.raises(queue.QueueError, match="outcome unknown"):
        queue.apply(api, queue.plan(api), receipt)
    assert live["repository"]["allow_auto_merge"] is True
    row = json.loads(receipt.read_text())["repositories"][0]
    assert row["attempts"][-1]["status"] == "unknown"
    assert row["actions"] == [{"method": "POST", "ruleset_id": 42}]


def test_interrupted_remote_write_leaves_durable_pending_intent(transaction):
    live, receipt = transaction
    def interrupt_after_commit(method, response):
        raise KeyboardInterrupt
    api = API(live, receipt, interrupt_after_commit)
    with pytest.raises(KeyboardInterrupt):
        queue.apply(api, queue.plan(api), receipt)
    assert api.calls == ["POST"]
    assert live["rulesets"][0]["id"] == 42
    row = json.loads(receipt.read_text())["repositories"][0]
    assert row["attempts"][0]["status"] == "pending"
    assert row["actions"] == []


def test_ruleset_update_response_must_match_requested_id(transaction):
    live, receipt = transaction
    previous = queue.desired_ruleset({WORKFLOW_PATH: ["qc"]})
    previous["rules"][-1]["parameters"]["check_response_timeout_minutes"] = 60
    live["rulesets"] = [dict(previous, id=42, source_type="Repository", source=REPO)]
    live["effective_rules"] = [dict(rule, ruleset_id=42) for rule in previous["rules"]]
    api = API(live, receipt, lambda method, valid: dict(valid, id=999))
    with pytest.raises(queue.QueueError, match="outcome unknown"):
        queue.apply(api, queue.plan(api), receipt)
    assert api.calls == ["PUT"]
    row = json.loads(receipt.read_text())["repositories"][0]
    assert row["attempts"][0]["endpoint"].endswith("/rulesets/42")
    assert row["attempts"][0]["status"] == "unknown"
    assert row["actions"] == []


def test_uncertain_first_repository_leaves_later_repository_unattempted(transaction, monkeypatch):
    live, receipt = transaction
    other = copy.deepcopy(live)
    other_repo = "CultureBotAI/other"
    other["repository"].update(id=2, full_name=other_repo)
    states = {REPO: live, other_repo: other}
    monkeypatch.setattr(queue, "identities", lambda: {"example": REPO, "other": other_repo})
    monkeypatch.setattr(queue, "load_policy", lambda: {
        key: {WORKFLOW_PATH: ["qc"]} for key in ("example", "other")
    })
    monkeypatch.setattr(queue, "snapshot", lambda api, repo, workflows: copy.deepcopy(states[repo]))
    def lose_response(method, response):
        raise queue.QueueError("response lost after committed mutation")
    api = API(live, receipt, lose_response)
    with pytest.raises(queue.QueueError, match="outcome unknown"):
        queue.apply(api, queue.plan(api), receipt)
    assert api.calls == ["POST"]
    rows = json.loads(receipt.read_text())["repositories"]
    assert rows[0]["status"] == "failed"
    assert rows[1]["status"] == "not updated"
    assert rows[1]["attempts"] == []
    assert other["rulesets"] == []


def test_success_and_repeat_apply_keep_confirmed_journal_and_no_duplicate_writes(transaction):
    live, receipt = transaction
    api = API(live, receipt)
    result = queue.apply(api, queue.plan(api), receipt)
    row = result["repositories"][0]
    assert row["status"] == "updated"
    assert [attempt["status"] for attempt in row["attempts"]] == ["confirmed", "confirmed"]
    assert api.calls == ["POST", "PATCH"]
    second_receipt = receipt.with_name("second.json")
    api.receipt = second_receipt
    result = queue.apply(api, queue.plan(api), second_receipt)
    assert result["repositories"][0]["status"] == "unchanged"
    assert result["repositories"][0]["attempts"] == []
    assert api.calls == ["POST", "PATCH"]
