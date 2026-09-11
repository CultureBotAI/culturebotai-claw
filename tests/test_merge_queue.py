"""Queue adoption must fail closed before writes and retain partial evidence."""
import base64
import copy
import json
from pathlib import Path

import pytest

import kg_microbe_merge_queue as queue

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


def state(repo="CultureBotAI/example"):
    return {
        "repository": {"id": 1, "full_name": repo, "private": False, "archived": False,
                       "default_branch": "main", "permissions": {"admin": True},
                       "allow_auto_merge": False, "allow_squash_merge": True},
        "owner_type": "Organization", "main_sha": "a" * 40,
        "rulesets": [], "effective_rules": [], "classic_protection": None,
        "workflows": {".github/workflows/ci.yml": {
            "sha": "b" * 40, "content": base64.b64encode(WORKFLOW.encode()).decode()
        }},
    }


@pytest.fixture
def setup(monkeypatch):
    policy = {"example": {".github/workflows/ci.yml": ["qc"]}}
    monkeypatch.setattr(queue, "identities", lambda: {"example": "CultureBotAI/example"})
    monkeypatch.setattr(queue, "load_policy", lambda: policy)
    monkeypatch.setattr(queue, "context_evidence", lambda *args: {})
    live = state()
    monkeypatch.setattr(queue, "snapshot", lambda *args: copy.deepcopy(live))
    return live


class API:
    def __init__(self, live, fail_patch=False):
        self.live, self.calls, self.fail_patch = live, [], fail_patch

    def request(self, endpoint, method="GET", body=None):
        self.calls.append((endpoint, method, body))
        if method == "POST":
            managed = dict(body, id=42, source_type="Repository", source="CultureBotAI/example")
            self.live["rulesets"].append(managed)
            return managed
        if method == "PATCH":
            if self.fail_patch:
                raise queue.QueueError("test write failure")
            self.live["repository"].update(body)
            return self.live["repository"]
        raise AssertionError((endpoint, method, body))


def test_policy_covers_manifest_including_taxon_and_ships_with_wheel():
    assert set(queue.load_policy()) == set(queue.identities())
    assert "taxonmech" in queue.load_policy()
    # Packaging declarations are exercised by the existing wheel build suite.
    import tomllib
    metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert "policy.json" in metadata["tool"]["setuptools"]["package-data"]["kg_microbe_merge_queue"]


@pytest.mark.parametrize("mutation", [
    lambda text: text.replace("  merge_group:\n    types: [checks_requested]\n", ""),
    lambda text: text.replace("  pull_request:\n", ""),
    lambda text: text.replace("  pull_request:\n", "  pull_request:\n    paths: ['docs/**']\n"),
    lambda text: text.replace("  pull_request:\n", "  pull_request:\n    paths-ignore: ['docs/**']\n"),
    lambda text: text.replace("checks_requested", "destroyed"),
    lambda text: text + "concurrency:\n  group: queue\n  cancel-in-progress: true\n",
])
def test_incomplete_or_cancelling_workflow_is_rejected(mutation):
    assert queue.workflow_errors(mutation(WORKFLOW))


def test_unfiltered_and_main_only_triggers_accepted():
    assert not queue.workflow_errors(WORKFLOW)
    assert not queue.workflow_errors(WORKFLOW.replace(
        "  pull_request:\n", "  pull_request:\n    branches: [main]\n"
    ))


def test_claw_required_workflows_are_queue_ready():
    root = Path(__file__).parents[1]
    for path in queue.load_policy()["claw"]:
        assert queue.workflow_errors((root / path).read_text()) == [], path


def test_plan_is_read_only_and_apply_is_idempotent(setup, tmp_path):
    api = API(setup)
    saved = queue.plan(api)
    assert saved["repositories"][0]["status"] == "planned"
    assert api.calls == []
    receipt = queue.apply(api, saved, tmp_path / "first.json")
    assert receipt["repositories"][0]["status"] == "updated"
    assert [call[1] for call in api.calls] == ["POST", "PATCH"]
    assert api.calls[-1][2] == {"allow_auto_merge": True}
    assert setup["rulesets"][0]["bypass_actors"] == []
    second = queue.plan(api)
    assert second["repositories"][0]["status"] == "unchanged"
    api.calls.clear()
    queue.apply(api, second, tmp_path / "second.json")
    assert api.calls == []


@pytest.mark.parametrize("mutation", [
    lambda saved, live: live["repository"].update(allow_auto_merge=True),
    lambda saved, live: live["workflows"][".github/workflows/ci.yml"].update(sha="c" * 40),
    lambda saved, live: saved["repositories"][0].update(repository="CultureBotAI/other"),
    lambda saved, live: saved["repositories"][0]["desired"].update(bypass_actors=[{"actor_id": 1}]),
    lambda saved, live: saved["repositories"].append(copy.deepcopy(saved["repositories"][0])),
])
def test_changed_or_tampered_plan_never_writes(setup, tmp_path, mutation):
    api = API(setup)
    saved = queue.plan(api)
    mutation(saved, setup)
    with pytest.raises(queue.QueueError):
        queue.apply(api, saved, tmp_path / "receipt.json")
    assert api.calls == []


def test_unrelated_main_commit_does_not_invalidate_workflow_evidence(setup, tmp_path):
    api = API(setup)
    saved = queue.plan(api)
    setup["main_sha"] = "c" * 40
    queue.apply(api, saved, tmp_path / "receipt.json")


def test_unrelated_ruleset_is_preserved(setup, tmp_path):
    other = {"name": "Separate review policy", "id": 7, "enforcement": "active",
             "rules": [{"type": "required_signatures"}]}
    setup["rulesets"].append(copy.deepcopy(other))
    api = API(setup)
    queue.apply(api, queue.plan(api), tmp_path / "receipt.json")
    assert setup["rulesets"][0] == other


def test_partial_failure_retains_before_and_completed_write(setup, tmp_path):
    api = API(setup, fail_patch=True)
    receipt = tmp_path / "receipt.json"
    with pytest.raises(queue.QueueError, match="partial results saved"):
        queue.apply(api, queue.plan(api), receipt)
    written = json.loads(receipt.read_text())
    assert written["plan"]["repositories"][0]["before"]["rulesets"] == []
    assert written["repositories"][0]["actions"] == [{"method": "POST", "ruleset_id": 42}]
    assert written["repositories"][0]["status"] == "failed"


def test_existing_receipt_is_not_overwritten(setup, tmp_path):
    api = API(setup)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("keep me")
    with pytest.raises(FileExistsError):
        queue.apply(api, queue.plan(api), receipt)
    assert api.calls == []
    assert receipt.read_text() == "keep me"


@pytest.mark.parametrize("change", [
    {"private": True}, {"permissions": {"admin": False}}, {"allow_squash_merge": False},
    {"default_branch": "develop"}, {"archived": True},
])
def test_ineligible_repository_blocks_apply(setup, tmp_path, change):
    setup["repository"].update(change)
    api = API(setup)
    saved = queue.plan(api)
    assert saved["repositories"][0]["status"] == "blocked"
    with pytest.raises(queue.QueueError):
        queue.apply(api, saved, tmp_path / "receipt.json")
    assert api.calls == []


def test_foreign_queue_or_duplicate_managed_name_rejected():
    live = state()
    live["effective_rules"] = [{"type": "merge_queue", "ruleset_id": 99}]
    assert queue.readiness_errors(live, "CultureBotAI/example")
    live["rulesets"] = [{"name": queue.RULESET_NAME}] * 2
    with pytest.raises(queue.QueueError, match="duplicate"):
        queue.managed_ruleset(live, "CultureBotAI/example")


def test_table_lists_updated_first_and_not_updated_last():
    rows = [{"repository": "a", "status": "blocked"},
            {"repository": "b", "status": "updated"},
            {"repository": "c", "status": "not updated"}]
    text = queue.table(rows)
    assert text.index("| b |") < text.index("| a |") < text.index("| c |")


@pytest.mark.parametrize("names,conclusions,blob_sha", [
    (["qc"], ["success"], "b" * 40),
    (["renamed"], ["success"], "b" * 40),
    (["qc", "qc"], ["success", "success"], "b" * 40),
    (["qc"], ["skipped"], "b" * 40),
    (["qc"], ["success"], "c" * 40),
])
def test_context_evidence_requires_real_unique_passing_current_jobs(names, conclusions, blob_sha):
    class EvidenceAPI:
        def request(self, endpoint):
            if "/contents/" in endpoint:
                return {"sha": blob_sha}
            return {"workflow_runs": [{"id": 1, "head_sha": "a" * 40, "html_url": "https://example/run",
                                       "event": "pull_request", "conclusion": "success"}]}

        def pages(self, endpoint, field):
            return [{"name": name, "conclusion": conclusion}
                    for name, conclusion in zip(names, conclusions, strict=True)]

    if names == ["qc"] and conclusions == ["success"] and blob_sha == "b" * 40:
        assert queue.context_evidence(EvidenceAPI(), "CultureBotAI/example",
                                      {".github/workflows/ci.yml": ["qc"]}, state())
    else:
        with pytest.raises(queue.QueueError, match="no passing run"):
            queue.context_evidence(EvidenceAPI(), "CultureBotAI/example",
                                   {".github/workflows/ci.yml": ["qc"]}, state())


def test_classic_protection_and_pending_run_replacement_are_detected():
    live = state()
    live["classic_protection"] = {"required_status_checks": {"contexts": ["legacy"]}}
    assert queue.readiness_errors(live, "CultureBotAI/example")
    assert queue.workflow_errors(WORKFLOW + "concurrency: shared-static-group\n")
    assert queue.workflow_errors(WORKFLOW + "concurrency:\n  group: shared\n  cancel-in-progress: false\n")


@pytest.mark.parametrize("line", [
    "    if: github.event_name == 'pull_request'\n",
    "    continue-on-error: true\n",
])
def test_skippable_required_job_is_rejected(line):
    assert queue.workflow_errors(WORKFLOW.replace("  qc:\n", "  qc:\n" + line), ["qc"])


def test_candidate_checkout_override_is_rejected():
    workflow = WORKFLOW.replace("      - run: echo checked", """      - uses: actions/checkout@v4
        with:
          ref: main""")
    assert queue.workflow_errors(workflow, ["qc"])


@pytest.mark.parametrize("rule", [
    {"type": "required_status_checks", "parameters": {"required_status_checks": [
        {"context": "legacy", "integration_id": queue.ACTIONS_APP_ID}]}},
    {"type": "required_status_checks", "parameters": {"required_status_checks": [
        {"context": "qc", "integration_id": 99}]}},
    {"type": "workflows"}, {"type": "required_deployments"},
])
def test_foreign_requirements_cannot_silently_strand_queue(rule):
    live = state()
    live["effective_rules"] = [rule]
    assert queue.readiness_errors(live, "CultureBotAI/example", {".github/workflows/ci.yml": ["qc"]})
