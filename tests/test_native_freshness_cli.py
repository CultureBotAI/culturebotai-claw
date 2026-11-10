"""Native 1.1 uses the actual shared offline Git gate; no provider/API calls."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from test_goal_freshness import REPOSITORY, git, isolated_git  # noqa: F401
from test_goal_freshness import repo as _repo
from test_native_freshness import case as _case
from test_native_freshness import reference

from kg_microbe_workflows import freshness_cli as cli
from kg_microbe_workflows import native_freshness as native
from kg_microbe_workflows.freshness import FreshnessError

repo = _repo
case = _case


@pytest.fixture
def native_request(repo, case, monkeypatch):
    monkeypatch.setattr(cli, "repository_identity", lambda key: REPOSITORY)
    monkeypatch.setattr(native, "repository_identity", lambda key: REPOSITORY)
    contract = yaml.safe_load(case["contract"].read_text())
    contract.update(repository_key="fixturemech", github_repository=REPOSITORY)
    repo.publish("CLOSURE.md", case["instruction"].read_text())
    repo.publish("native-execution.yaml", yaml.safe_dump(contract))
    git(repo.checkout, "fetch", "origin")
    git(repo.checkout, "merge", "--ff-only", "origin/main")
    effective = native.load_execution(
        repo.checkout / "native-execution.yaml", root=repo.checkout, repository_key="fixturemech"
    )
    effective_ref = reference(case["evidence"] / "shared-effective.json", effective)
    initial = json.loads(
        Path(case["adoption"]["boundary"]["predecessor"]["reference"]["path"]).read_text()
    )
    initial.update(repository_key="fixturemech", repository_root=str(repo.checkout))
    initial_ref = reference(case["evidence"] / "shared-initial.json", initial)
    adoption = copy.deepcopy(case["adoption"])
    adoption.update(
        repository_key="fixturemech",
        github_repository=REPOSITORY,
        repository_root=str(repo.checkout),
    )
    adoption["boundary"]["workflow_sha256"] = native.execution_sha256(effective)
    adoption["boundary"]["predecessor"]["reference"] = initial_ref
    request = copy.deepcopy(case["request"])
    request.update(
        repository_key="fixturemech",
        repository_root=str(repo.checkout),
        effective_workflow=effective_ref,
        workflow_sha256=native.execution_sha256(effective),
        adoption=reference(case["evidence"] / "shared-adoption.json", adoption),
    )
    return request


def test_native_shared_batch_persists_fetched_head_before_inventory(repo, native_request):
    wanted = repo.publish("INFRA_TASKS.md", "New independently merged backlog\n")
    result = cli.run_batch([native_request], apply=True)
    assert result["status"] == "verified", result
    row = result["results"][0]
    artifact = cli.read_artifact(row["artifact"])
    assert row["head"] == repo.head() == artifact["head"] == wanted
    assert artifact["schema_version"] == "1.1.0"
    assert artifact["execution_context"] == native_request["execution_context"]
    assert artifact["effective_workflow"] == native_request["effective_workflow"]
    assert next(file for file in artifact["files"] if file["path"] == "INFRA_TASKS.md")[
        "object_sha"
    ] == git(repo.writer, "rev-parse", "HEAD:INFRA_TASKS.md")
    assert cli.execute(native_request, apply=False)["artifact"] == row["artifact"]


@pytest.mark.parametrize("phase", ["pre_goal", "post_merge"])
def test_native_complete_frozen_instructions_prevent_fast_forward(repo, native_request, phase):
    request = copy.deepcopy(native_request)
    if phase == "post_merge":
        initial = cli.execute(request, apply=True)
        request.update(
            phase="post_merge",
            prior_inventory=initial["artifact"],
            pull_requests=[{"number": 42, "head_sha": "e" * 40, "merge_commit_sha": "0" * 40}],
        )
    before = repo.head()
    merged = repo.publish(
        "CLOSURE.md", "A new closure policy must not replace active instructions\n"
    )
    if phase == "post_merge":
        request["pull_requests"][0]["merge_commit_sha"] = merged
    remote = {
        "number": 42,
        "merged": True,
        "merged_at": "2026-01-01T01:00:00Z",
        "head": {"sha": "e" * 40},
        "merge_commit_sha": merged,
        "base": {"repo": {"full_name": REPOSITORY}, "ref": "main"},
    }
    result = cli.execute(request, apply=True, observe_pr=lambda *args: remote)
    assert result["status"] == "hold", result
    assert result["reason"] == "workflow_pin_change_requires_adoption"
    assert repo.head() == before


def test_native_post_merge_observes_actual_merge_and_newer_backlog(repo, native_request):
    initial = cli.execute(native_request, apply=True)
    original = Path(initial["artifact"]["path"]).read_bytes()
    merged = repo.publish("own-change.txt", "Merged task\n")
    latest = repo.publish("INFRA_TASKS.md", "Later independent backlog\n")
    request = copy.deepcopy(native_request)
    request.update(
        phase="post_merge",
        prior_inventory=initial["artifact"],
        pull_requests=[{"number": 42, "head_sha": "e" * 40, "merge_commit_sha": merged}],
    )
    remote = {
        "number": 42,
        "merged": True,
        "merged_at": "2026-01-01T01:00:00Z",
        "head": {"sha": "e" * 40},
        "merge_commit_sha": merged,
        "base": {"repo": {"full_name": REPOSITORY}, "ref": "main"},
    }
    result = cli.execute(request, apply=True, observe_pr=lambda *args: remote)
    artifact = cli.read_artifact(result["artifact"])
    assert result["head"] == repo.head() == latest
    assert artifact["merges"][0]["merge_commit_sha"] == merged
    assert artifact["execution_context"] == request["execution_context"]
    assert Path(initial["artifact"]["path"]).read_bytes() == original


def test_native_no_change_keeps_inventory_and_full_context(repo, native_request):
    initial = cli.execute(native_request, apply=True)
    original = Path(initial["artifact"]["path"]).read_bytes()
    request = copy.deepcopy(native_request)
    request.update(phase="no_change", prior_inventory=initial["artifact"])
    result = cli.execute(request, apply=True)
    artifact = cli.read_artifact(result["artifact"])
    assert artifact["kind"] == "verified_no_change_freshness"
    for key in ("execution_context", "effective_workflow", "adoption", "workflow_sha256"):
        assert artifact[key] == request[key]
    assert Path(initial["artifact"]["path"]).read_bytes() == original
    repo.publish("later.txt", "Late change after no-change boundary")
    with pytest.raises(FreshnessError, match="remote_moved"):
        cli.execute(request, apply=True)


def test_native_shared_batch_does_not_admit_supervisor_fields(native_request):
    request = copy.deepcopy(native_request)
    request["run_id"] = "synthetic"
    result = cli.run_batch([request], apply=True)
    assert result["status"] == "hold"
    assert result["results"][0]["reason"] == "request_unknown_or_missing_fields"
