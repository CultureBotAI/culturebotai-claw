"""Distinctive regressions for progress provenance, counting and publication."""
from __future__ import annotations

import copy
import json

import pytest

import kg_microbe_progress as progress
from kg_microbe_fleet import load_fleet_manifest

NOW = "2026-10-20T08:00:00+00:00"
SEEN = "2026-10-20T07:00:00+00:00"
KEY = "culturemech"
GITHUB = load_fleet_manifest().mechs[KEY].github


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def runtime(tmp_path, *, name="run-one", stage=1, cycle=1):
    root = tmp_path / name
    config = {"run_id": name, "targets": [{"repository_key": KEY, "github_repository": GITHUB}]}
    ledger = {
        "schema_version": 2, "run_id": name, "repository_key": KEY,
        "cycle": cycle, "stage": stage, "created_at": "2026-10-20T01:00:00+00:00",
        "last_observed_at": SEEN, "completed_stages": [], "phase": "waiting",
        "blocked_reason": "busy/background/queued",
        "adopted_goal": {"conversation_id": "PRIVATE_CONVERSATION_ID"},
        "actions": {"a": {"message": "/Users/PRIVATE_PERSON/PASSWORD DO NOT PUBLISH"}},
    }
    write(root / "config.json", config)
    save_ledger(root, ledger)
    return root, ledger


def save_ledger(root, ledger):
    write(root / KEY / "ledger.json", ledger)


def add_closure(root, ledger, *, stage=1, cycle=1, pr=None, legacy=False):
    identity = {"conversation_id": "PRIVATE_ID", "start_step_index": stage, "started_at": SEEN}
    receipt = {
        "run_id": ledger["run_id"], "repository_key": KEY, "stage": stage,
        "goal_identity": identity, "goal_complete": True,
        "status": "no_changes" if pr is None else "completed",
        "pr": None if pr is None else {"number": pr, "head_sha": "a" * 40},
    }
    if not legacy:
        receipt["cycle"] = cycle
    verification = {"verified_at": SEEN, "status": "no_changes"}
    if pr is not None:
        verification.update(status="merged", pr_number=pr, head_sha="a" * 40,
                            merge_commit_sha="b" * 40, merged_at="2026-10-20T06:00:00Z")
    record = {
        "stage": stage, "cycle": cycle, "goal_identity": identity,
        "receipt_sha256": progress.digest(receipt), "verification": verification,
    }
    ledger["completed_stages"].append(record)
    directory = root / KEY / "receipts"
    if not legacy:
        directory /= f"cycle-{cycle:06d}"
    path = directory / f"stage-{stage}-{record['receipt_sha256'][:12]}.json"
    write(path, receipt)
    save_ledger(root, ledger)
    return path


def collect(root, history=None, **kwargs):
    return progress.collect_progress([root], history, generated_at=NOW, **kwargs)


def repo(snapshot):
    return next(row for row in snapshot["repositories"] if row["key"] == KEY)


def pr_observation(ledger, *, number=7, state="open", at=SEEN, head="a", **kwargs):
    result = {
        "repository_key": KEY, "run_id": ledger["run_id"], "cycle": 1, "stage": 1,
        "number": number, "state": state, "head_sha": head * 40, "observed_at": at,
    }
    if state == "merged":
        result.update(merge_commit_sha="b" * 40, merged_at="2026-10-20T06:00:00Z")
    result.update(kwargs)
    return result


def test_adopted_stage_four_does_not_invent_earlier_completed_goals(tmp_path):
    root, _ = runtime(tmp_path, stage=4)
    history, snapshot = collect(root)
    assert snapshot["totals"]["completed_goals"] == 0
    assert [stage["state"] for stage in repo(snapshot)["stages"]] == [
        "unverified", "unverified", "unverified", "current", "pending", "pending",
    ]
    assert snapshot["tracking"]["earlier_history"] == "unknown"
    assert len(snapshot["repositories"]) == len(load_fleet_manifest().keys)
    assert history["closures"] == []


def test_six_distinct_verified_stages_needed_for_completed_cycle(tmp_path):
    root, ledger = runtime(tmp_path, stage=1, cycle=2)
    for stage in range(1, 6):
        add_closure(root, ledger, stage=stage)
    history, snapshot = collect(root)
    assert snapshot["totals"]["completed_cycles"] == 0
    add_closure(root, ledger, stage=6)
    history, snapshot = collect(root, history)
    assert snapshot["totals"]["completed_cycles"] == 1
    assert snapshot["totals"]["completed_goals"] == 6
    assert snapshot["totals"]["no_change_goals"] == 6
    assert snapshot["totals"]["unique_prs"] == 0


def test_same_pr_across_goals_counts_once_and_commits_are_not_prs(tmp_path):
    root, ledger = runtime(tmp_path, stage=3)
    add_closure(root, ledger, stage=1, pr=42, legacy=True)
    add_closure(root, ledger, stage=2, pr=42)
    history, snapshot = collect(root)
    assert snapshot["totals"]["completed_goals"] == 2
    assert snapshot["totals"]["unique_prs"] == 1
    assert snapshot["totals"]["merged_prs"] == 1
    assert len(history["associations"]) == 2
    assert len(history["pr_events"]) == 1
    assert collect(root, history) == (history, snapshot)


def test_multiple_pr_rounds_per_goal_and_state_transitions(tmp_path):
    root, ledger = runtime(tmp_path)
    observations = [pr_observation(ledger), pr_observation(ledger, number=8)]
    history, snapshot = collect(root, verified_pr_observations=observations)
    assert snapshot["totals"]["unique_prs"] == 2
    assert snapshot["totals"]["open_prs"] == 2
    assert snapshot["totals"]["completed_goals"] == 0
    # An additional head commit changes PR state history, not PR round count.
    history, snapshot = collect(root, history, verified_pr_observations=[
        pr_observation(ledger, at="2026-10-20T07:10:00Z", head="c"),
    ])
    assert snapshot["totals"]["unique_prs"] == 2
    assert len(history["pr_events"]) == 3
    for state, minute in (("closed", "20"), ("open", "30"), ("merged", "40")):
        history, snapshot = collect(root, history, verified_pr_observations=[
            pr_observation(ledger, state=state, at=f"2026-10-20T07:{minute}:00Z", head="c"),
        ])
    assert snapshot["totals"]["merged_prs"] == 1
    assert snapshot["totals"]["open_prs"] == 1
    assert snapshot["totals"]["completed_goals"] == 0
    with pytest.raises(progress.ProgressError, match="regressed"):
        collect(root, history, verified_pr_observations=[
            pr_observation(ledger, state="open", at="2026-10-20T07:50:00Z", head="c"),
        ])


def test_restart_retains_old_runs_but_new_run_is_current(tmp_path):
    first, first_ledger = runtime(tmp_path, stage=2)
    add_closure(first, first_ledger)
    history, _ = collect(first)
    second, second_ledger = runtime(tmp_path, name="run-two")
    second_ledger["created_at"] = "2026-10-20T06:00:00Z"
    save_ledger(second, second_ledger)
    history, snapshot = collect(second, history)
    assert len(history["cursors"]) == 2
    assert repo(snapshot)["current"]["run_key"] == progress.run_key("run-two")
    assert snapshot["totals"]["completed_goals"] == 1
    # Similar timestamps and stage numbers in different runs are distinct goals.
    second_ledger["stage"] = 2
    add_closure(second, second_ledger)
    _, snapshot = collect(second, history)
    assert snapshot["totals"]["completed_goals"] == 2


@pytest.mark.parametrize("change", ["remove", "hash", "archive", "identity", "duplicate"])
def test_verified_closures_cannot_disappear_or_change(tmp_path, change):
    root, ledger = runtime(tmp_path, stage=2)
    path = add_closure(root, ledger, pr=12)
    history, _ = collect(root)
    if change == "remove":
        ledger["completed_stages"] = []
    elif change == "hash":
        path.write_text(path.read_text().replace('"completed"', '"tampered"'))
    elif change == "archive":
        path.unlink()
    elif change == "identity":
        ledger["completed_stages"][0]["goal_identity"]["start_step_index"] = 999
    else:
        ledger["completed_stages"].append(copy.deepcopy(ledger["completed_stages"][0]))
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError):
        collect(root, history)


@pytest.mark.parametrize("field,value", [
    ("stage", 1), ("cycle", 0), ("last_observed_at", "2026-10-19T07:00:00Z"),
    ("created_at", "2026-10-19T01:00:00Z"),
])
def test_run_cursor_regression_fails(tmp_path, field, value):
    root, ledger = runtime(tmp_path, stage=2)
    history, _ = collect(root)
    ledger[field] = value
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError):
        collect(root, history)


def test_only_explicit_closure_authority_counts_current_receipt_never_counts(tmp_path):
    root, ledger = runtime(tmp_path)
    write(root / KEY / "completion.json", {"status": "completed", "pr": {"number": 900}})
    write(root / KEY / "progress.json", {"summary": "Completed 8 rounds and PR #222."})
    _, snapshot = collect(root)
    assert snapshot["totals"]["unique_prs"] == 0
    assert snapshot["totals"]["completed_goals"] == 0
    assert ledger["completed_stages"] == []


def test_public_allowlist_excludes_paths_agent_text_and_native_identity(tmp_path):
    root, ledger = runtime(tmp_path, stage=2)
    ledger["blocked_reason"] = "/Users/PRIVATE_PERSON/my_secret_code"
    ledger["phase"] = "PRIVATE_PHASE"
    add_closure(root, ledger, pr=12)
    history, snapshot = collect(root)
    raw = json.dumps([history, snapshot])
    assert "PRIVATE" not in raw
    assert "/Users/" not in raw
    assert "conversation" not in raw
    assert "PASSWORD" not in raw
    assert repo(snapshot)["current"]["phase"] == "unknown"


def test_history_append_extension_and_bundle_integrity(tmp_path):
    root, ledger = runtime(tmp_path, stage=2)
    add_closure(root, ledger, pr=12)
    history, snapshot = collect(root)
    progress.validate_bundle(history, snapshot)
    altered = copy.deepcopy(history)
    altered["closures"] = []
    with pytest.raises(progress.ProgressError, match="append-only"):
        progress.validate_extension(history, altered)
    forged = copy.deepcopy(snapshot)
    repo(forged)["pull_requests"][0]["url"] = "https://example.org/private"
    with pytest.raises(progress.ProgressError, match="differs"):
        progress.validate_bundle(history, forged)
    forged = copy.deepcopy(snapshot)
    repo(forged)["current"]["phase"] = "ready_to_dispatch"
    with pytest.raises(progress.ProgressError, match="differs"):
        progress.validate_bundle(history, forged)


@pytest.mark.parametrize("corruption", ["remove_prs", "remove_associations", "wrong_merge"])
def test_issue_634_closure_requires_pr_proof_and_explicit_goal_association(tmp_path, corruption):
    root, ledger = runtime(tmp_path, stage=2)
    add_closure(root, ledger, pr=12)
    history, _ = collect(root)
    damaged = copy.deepcopy(history)
    if corruption == "remove_prs":
        damaged["pr_events"] = []
        damaged["associations"] = []
    elif corruption == "remove_associations":
        damaged["associations"] = []
    else:
        damaged["closures"][0]["merge_commit_sha"] = "c" * 40
    with pytest.raises(progress.ProgressError):
        progress.snapshot_from_history(damaged, generated_at=NOW)


def test_issue_634_observed_pr_always_requires_an_explicit_goal_association(tmp_path):
    root, ledger = runtime(tmp_path)
    history, _ = collect(root, verified_pr_observations=[pr_observation(ledger)])
    history["associations"] = []
    with pytest.raises(progress.ProgressError, match="explicit goal association"):
        progress.validate_history(history)


def test_schema_is_closed_and_linkml_backed(tmp_path):
    root, _ = runtime(tmp_path)
    history, snapshot = collect(root)
    history["raw_terminal"] = "must never publish"
    with pytest.raises(progress.ProgressError, match="Additional properties"):
        progress.validate_history(history)
    snapshot["tracking"]["counts_are_lower_bounds"] = "yes"
    with pytest.raises(progress.ProgressError):
        progress.validate_snapshot(snapshot)
    assert progress.SCHEMA_PATH.is_file()
    assert "ProgressSnapshot" in progress.json_schema()["$defs"]


def test_new_pr_association_requires_known_goal_and_opaque_refresh_requires_existing(tmp_path):
    root, ledger = runtime(tmp_path)
    observation = pr_observation(ledger, stage=2)
    with pytest.raises(progress.ProgressError, match="observed goal"):
        collect(root, verified_pr_observations=[observation])
    observation = pr_observation(ledger)
    history, _ = collect(root, verified_pr_observations=[observation])
    observation["run_key"] = progress.run_key(observation.pop("run_id"))
    observation["stage_number"] = observation.pop("stage")
    assert collect(root, history, verified_pr_observations=[observation])[0] == history
    observation["number"] = 1000
    with pytest.raises(progress.ProgressError, match="only refresh"):
        collect(root, history, verified_pr_observations=[observation])


def test_source_future_timestamp_fails_and_snapshot_time_does_not_hide_staleness(tmp_path):
    root, ledger = runtime(tmp_path)
    _, snapshot = collect(root)
    assert snapshot["generated_at"] == NOW
    assert repo(snapshot)["last_observed_at"] == SEEN
    ledger["last_observed_at"] = "2026-10-21T00:00:00Z"
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError, match="future"):
        collect(root)


def test_normal_generation_timestamp_is_taken_after_runtime_reads(tmp_path, monkeypatch):
    root, _ = runtime(tmp_path)
    original = progress.read_json
    calls = []

    def read(path):
        calls.append(path.name)
        return original(path)

    class Clock:
        @staticmethod
        def fromisoformat(value):
            from datetime import datetime
            return datetime.fromisoformat(value)

        @staticmethod
        def now(tz):
            assert "ledger.json" in calls
            return Clock.fromisoformat(NOW)

    monkeypatch.setattr(progress, "read_json", read)
    monkeypatch.setattr(progress, "datetime", Clock)
    _, snapshot = progress.collect_progress([root])
    assert snapshot["generated_at"] == NOW


def test_read_and_atomic_output_preserve_last_good_input(tmp_path):
    path = tmp_path / "artifact.json"
    progress.atomic_write_json(path, {"good": 1})
    assert progress.read_json(path) == {"good": 1}
    path.write_text('{"duplicate": 1, "duplicate": 2}')
    with pytest.raises(progress.ProgressError):
        progress.read_json(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(progress.ProgressError):
        progress.read_json(link)
    with pytest.raises(progress.ProgressError):
        progress.atomic_write_json(link, {"new": 1})
    assert "duplicate" in path.read_text()


def test_missing_target_and_foreign_github_identity_are_not_silent_partial_fleet(tmp_path):
    root, ledger = runtime(tmp_path)
    history, _ = collect(root)
    config = progress.read_json(root / "config.json")
    config["targets"][0]["github_repository"] = "someone/else"
    write(root / "config.json", config)
    with pytest.raises(progress.ProgressError, match="identity differs"):
        collect(root, history)
    config["targets"] = []
    write(root / "config.json", config)
    with pytest.raises(progress.ProgressError, match="no targets"):
        collect(root, history)
    assert ledger["stage"] == 1
