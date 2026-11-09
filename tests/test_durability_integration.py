"""Claw #938: saved status, publication gates and pinned policy stay connected.

Offline integration fixtures contain no real session identities or repository
paths. Temporary directories here are disposable pytest inputs, not work state.
"""
from __future__ import annotations

import copy
import json
from datetime import timedelta

import pytest
import yaml
from test_mech_session_supervisor import HEAD, GitHubFixture, supervisor
from test_mech_session_supervisor import setup as setup  # noqa: F401 -- shared fixture
from test_progress_status import NOW, STAMP
from test_progress_status import bundle as bundle  # noqa: F401 -- shared fixture
from test_progress_status import status as status  # noqa: F401 -- shared fixture
from test_workflow_contract import profile as profile  # noqa: F401 -- shared fixture

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_progress import ProgressError
from kg_microbe_progress.durability import read_durability
from kg_microbe_workflows import (
    PARENT_PATH,
    WorkflowError,
    load_document,
    load_effective_workflow,
    session_durability,
    sha256,
    validate_parent,
)
from kg_microbe_workflows.commit_publication import PublicationError


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def observation(**changes):
    value = {
        "schema_version": "1.0.0", "observed_at": STAMP, "status": "healthy",
        "alert": False, "complete": True, "repository_count": 1,
        "unpushed_commits": 0, "at_risk_files": 0, "overdue_files": 0,
        "repositories": [{"root": "PRIVATE_PATH", "worktrees": ["PRIVATE_WORKTREE"]}],
        "commit_samples": [{"branch": "PRIVATE_BRANCH", "commit": "a" * 40}],
        "errors": ["PRIVATE_ERROR"], "temporary": {"paths": ["PRIVATE_STATE"]},
    }
    value.update(changes)
    return value


@pytest.fixture
def runtime(tmp_path):
    root = (tmp_path / "durability-runtime").resolve()
    fleet = load_fleet_manifest()
    key = fleet.keys[0]
    write(root / "config.json", {"run_id": "fixture-run", "targets": [
        {"repository_key": key, "github_repository": fleet.mechs[key].github}]})
    write(root / key / "status.json", {
        "run_id": "fixture-run", "repository_key": key,
        "session_durability": observation(),
    })
    return root, fleet, key


def update_observation(runtime, **changes):
    root, _, key = runtime
    write(root / key / "status.json", {
        "run_id": "fixture-run", "repository_key": key,
        "session_durability": observation(**changes),
    })


def test_saved_projection_contains_no_private_observation_fields(runtime):
    root, fleet, key = runtime
    row, = read_durability(root, fleet, NOW)
    assert row["repository_key"] == key
    assert "PRIVATE_" not in json.dumps(row)
    assert not {"repositories", "commit_samples", "temporary", "errors"} & row.keys()


@pytest.mark.parametrize("age,expected", [(900, "healthy"), (901, "stale"),
                                          (-60, "healthy"), (-61, "future_timestamp")])
def test_saved_observation_freshness_boundaries(runtime, age, expected):
    update_observation(runtime, observed_at=(NOW - timedelta(seconds=age)).isoformat())
    root, fleet, _ = runtime
    row, = read_durability(root, fleet, NOW)
    if expected == "healthy":
        assert row["status"] == "healthy" and row["alert"] is False
    else:
        assert (row["status"], row["reason"], row["alert"], row["complete"]) == (
            "unknown", expected, True, False)


@pytest.mark.parametrize("missing,reason", [("status", "not_observed"),
                                           ("observation", "not_collected")])
def test_missing_saved_observation_is_unknown_not_zero(runtime, missing, reason):
    root, fleet, key = runtime
    path = root / key / "status.json"
    if missing == "status":
        path.unlink()
    else:
        write(path, {"run_id": "fixture-run", "repository_key": key})
    row, = read_durability(root, fleet, NOW)
    assert row["status"] == "unknown" and row["alert"] is True
    assert row["reason"] == reason
    assert row["unpushed_commits"] is row["at_risk_files"] is row["overdue_files"] is None


@pytest.mark.parametrize("field,value", [("run_id", "other-run"),
                                         ("repository_key", "other-repository")])
def test_saved_status_identity_must_match_runtime(runtime, field, value):
    root, fleet, key = runtime
    path = root / key / "status.json"
    data = json.loads(path.read_text())
    data[field] = value
    write(path, data)
    with pytest.raises(ProgressError, match="another run or repository"):
        read_durability(root, fleet, NOW)


@pytest.mark.parametrize("problem", ["github", "unknown", "duplicate", "symlink"])
def test_runtime_target_and_path_identity_fail_closed(runtime, tmp_path, problem):
    root, fleet, key = runtime
    path = root / "config.json"
    config = json.loads(path.read_text())
    if problem == "github":
        config["targets"][0]["github_repository"] = "unrelated/repository"
    elif problem == "unknown":
        config["targets"][0]["repository_key"] = "not-in-fleet"
    elif problem == "duplicate":
        config["targets"].append(copy.deepcopy(config["targets"][0]))
    else:
        directory = root / key
        directory.rename(tmp_path / "other-status")
        directory.symlink_to(tmp_path / "other-status", target_is_directory=True)
    write(path, config)
    with pytest.raises(ProgressError):
        read_durability(root, fleet, NOW)


@pytest.mark.parametrize("problem", ["symlink", "invalid_json", "invalid_counts"])
def test_progress_durability_read_failure_never_prints_success(
    status, bundle, runtime, tmp_path, capsys, problem,
):
    root, _, key = runtime
    path = root / key / "status.json"
    if problem == "symlink":
        other = tmp_path / "other.json"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
    elif problem == "invalid_json":
        path.write_text("{")
    else:
        update_observation(runtime, unpushed_commits=-1)
    bundle_path = tmp_path / "bundle.json"
    write(bundle_path, bundle)
    assert status.main(["--bundle", str(bundle_path), "--durability-runtime", str(root)], now=NOW) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Progress unavailable:")
    assert "PRIVATE_" not in captured.err


@pytest.mark.parametrize("counts", [
    {"unpushed_commits": 2}, {"at_risk_files": 3, "overdue_files": 1},
])
def test_progress_reports_saved_alerts_read_only_without_private_payload(
    status, bundle, runtime, tmp_path, capsys, monkeypatch, counts,
):
    root, _, key = runtime
    update_observation(runtime, status="alert", alert=True, **counts)
    bundle_path = tmp_path / "bundle.json"
    write(bundle_path, bundle)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*.json")}

    def forbidden(*args, **kwargs):
        pytest.fail("saved status must not invoke a subprocess or scan a host")

    monkeypatch.setattr(session_durability, "observe_mech", forbidden)
    monkeypatch.setattr(status.subprocess, "run", forbidden)
    assert status.main(["--bundle", str(bundle_path), "--durability-runtime", str(root)], now=NOW) == 3
    captured = capsys.readouterr()
    assert f"Local durability {key}: alert;" in captured.out
    assert f"unpushed commits={counts.get('unpushed_commits', 0)}" in captured.out
    assert f"at-risk files={counts.get('at_risk_files', 0)}" in captured.out
    assert "PRIVATE_" not in captured.out + captured.err
    assert captured.err == ""
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*.json")} == before


def test_default_progress_does_not_consult_optional_runtime(status, bundle, tmp_path, capsys, monkeypatch):
    import kg_microbe_progress.durability as durability

    def forbidden(*args, **kwargs):
        pytest.fail("legacy default must not discover or read local runtimes")

    monkeypatch.setattr(durability, "read_durability", forbidden)
    path = tmp_path / "bundle.json"
    write(path, bundle)
    assert status.main(["--bundle", str(path)], now=NOW) == 0
    assert capsys.readouterr().out == status.format_summary(bundle["snapshot"]) + "\n"


@pytest.mark.parametrize("mode", ["unknown", "stale", "future"])
def test_progress_saved_unknown_and_stale_state_alerts(status, bundle, runtime, tmp_path, capsys, mode):
    if mode == "unknown":
        update_observation(runtime, status="unknown", alert=True, complete=False,
                           unpushed_commits=None, at_risk_files=None, overdue_files=None)
    else:
        update_observation(runtime, observed_at=(NOW + timedelta(
            seconds=-901 if mode == "stale" else 61)).isoformat())
    root, _, key = runtime
    path = tmp_path / "bundle.json"
    write(path, bundle)
    assert status.main(["--bundle", str(path), "--durability-runtime", str(root)], now=NOW) == 3
    captured = capsys.readouterr()
    assert f"Local durability {key}: unknown" in captured.out
    assert ("unpushed commits=unknown" if mode == "unknown" else
            "(stale)" if mode == "stale" else "(future_timestamp)") in captured.out
    assert "PRIVATE_" not in captured.out + captured.err


@pytest.mark.parametrize("field", ["session_state_paths", "session_repository_roots"])
@pytest.mark.parametrize("paths", [["relative"], ["/owned", "/owned"], ["/${UNRESOLVED}/owned"], [1]])
def test_supervisor_requires_explicit_unique_owned_path_inventory(setup, monkeypatch, field, paths):
    monkeypatch.setattr(supervisor, "ROOT", setup.runtime.parents[1])
    setup.target[field] = paths
    with pytest.raises(supervisor.SupervisorError, match=field):
        supervisor.validate_config(setup.config, resolve_repositories=False)


def test_supervisor_omitted_inventory_is_not_replaced_by_empty_complete_inventory(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(supervisor, "durability_repository_roots", lambda target: [setup.repo])

    def observe(roots, *, session_state_paths):
        calls.append((roots, session_state_paths))
        return observation()

    monkeypatch.setattr(session_durability, "observe_mech", observe)
    instance = object.__new__(supervisor.Supervisor)
    instance.durability(setup.target)
    setup.target["session_state_paths"] = []
    instance.durability(setup.target)
    assert calls == [([setup.repo], None), ([setup.repo], [])]


def test_supervisor_observation_failure_is_unknown_and_sanitized(setup, monkeypatch):
    def unavailable(target):
        raise RuntimeError("PRIVATE_NATIVE_ID PRIVATE_PATH PRIVATE_REMOTE_ERROR")

    monkeypatch.setattr(supervisor, "durability_repository_roots", unavailable)
    result = object.__new__(supervisor.Supervisor).durability(setup.target)
    assert result["status"] == "unknown" and result["alert"] is True
    assert result["complete"] is False and result["unpushed_commits"] is None
    assert "PRIVATE_" not in json.dumps(result)
    assert session_durability.public_summary(result)["status"] == "unknown"


def test_supervisor_revalidates_every_distinct_owned_clone(setup, monkeypatch, tmp_path):
    from plugins.repository_settings import RepositoryTarget

    opened = []

    def open_target(target):
        opened.append((target.name, target.path, target.expected_repository))

    monkeypatch.setattr(RepositoryTarget, "open", open_target)
    extra = tmp_path / "separate-owned-clone"
    setup.target["session_repository_roots"] = [str(extra)]
    assert supervisor.durability_repository_roots(setup.target) == [setup.repo, extra]
    assert [item[1] for item in opened] == [setup.repo, extra]
    assert all(item[0] == "traitmech" and item[2] == "CultureBotAI/TraitMech" for item in opened)


def test_legacy_receipt_optional_new_policy_requires_deliverable_inventory(setup):
    assert supervisor.validate_receipt(setup.receipt, setup.ledger, setup.target, setup.runtime) == []
    setup.ledger["workflow"] = {"effective": {"session_state_policy": {
        "require_origin_publication_at_closure": True}}}
    assert any("deliverable_commits" in error for error in supervisor.validate_receipt(
        setup.receipt, setup.ledger, setup.target, setup.runtime))
    setup.receipt["deliverable_commits"] = [HEAD]
    assert supervisor.validate_receipt(setup.receipt, setup.ledger, setup.target, setup.runtime) == []


@pytest.mark.parametrize("commits", [[], ["b" * 40], [HEAD, HEAD], ["short"], HEAD])
def test_receipt_rejects_missing_reviewed_head_or_malformed_deliverables(setup, commits):
    setup.receipt["deliverable_commits"] = commits
    assert any("deliverable_commits" in error for error in supervisor.validate_receipt(
        setup.receipt, setup.ledger, setup.target, setup.runtime))


def test_no_change_receipt_cannot_hide_recorded_deliverables(setup):
    setup.receipt.update(status="no_changes", pr=None, issues=[], deliverable_commits=[HEAD],
                         no_changes={"head_sha": HEAD, "explanation": "No changes",
                                     "no_goal_owned_changes": True, "no_open_goal_pr": True})
    errors = supervisor.validate_receipt(setup.receipt, setup.ledger, setup.target, setup.runtime)
    assert errors == ["no-change closure cannot contain deliverable commits"]
    setup.receipt["deliverable_commits"] = []
    assert supervisor.validate_receipt(setup.receipt, setup.ledger, setup.target, setup.runtime) == []


def test_merged_pr_does_not_publish_an_extra_local_batch(setup, monkeypatch):
    setup.receipt["deliverable_commits"] = [HEAD, "d" * 40]
    monkeypatch.setattr(supervisor, "durability_repository_roots", lambda target: [setup.repo])
    with pytest.raises(PublicationError, match="origin branch inventory"):
        supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, GitHubFixture())
    setup.receipt["deliverable_commits"] = [HEAD]
    proof = supervisor.verify_remote_receipt(setup.receipt, setup.ledger, setup.target, GitHubFixture())
    assert proof["commit_publication"]["proofs"][HEAD]["method"] == "verified_merged_pr"


def test_parent_policy_is_copied_to_effective_workflow_and_legacy_absence_survives(profile, tmp_path):
    path, data = profile
    parent = load_document(PARENT_PATH.read_bytes())
    policy = parent["session_state_policy"]
    assert policy["work_root"] == ".temp"
    assert policy["require_origin_publication_at_closure"] is True
    effective = load_effective_workflow(PARENT_PATH, path)
    assert effective["session_state_policy"] == policy
    del parent["session_state_policy"]
    legacy = tmp_path / "retained-parent.yaml"
    legacy.write_text(yaml.safe_dump(parent, sort_keys=False))
    data["parent"]["sha256"] = sha256(legacy.read_bytes())
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert "session_state_policy" not in load_effective_workflow(legacy, path)


@pytest.mark.parametrize("field,value", [
    ("work_root", "/tmp"), ("separate_clone_root", "/tmp/clones"),
    ("prohibit_system_temp_state", False), ("push_committed_batches_same_day", False),
    ("require_origin_publication_at_closure", False), ("disposable_cache_allowed", False),
])
def test_declared_session_policy_cannot_be_weakened(field, value):
    parent = load_document(PARENT_PATH.read_bytes())
    parent["session_state_policy"][field] = value
    with pytest.raises(WorkflowError, match="session state"):
        validate_parent(parent)


def test_profile_cannot_override_parent_publication_policy(profile):
    path, data = profile
    data["session_state_policy"] = {"require_origin_publication_at_closure": False}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(WorkflowError):
        load_effective_workflow(PARENT_PATH, path)
