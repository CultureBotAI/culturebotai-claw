"""PR association reporting never grants goal completion authority."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe_progress import prs

HEAD = "a" * 40
MERGE = "b" * 40
WORKFLOW = "c" * 64
STAMP = "2026-10-20T07:00:00+00:00"
GOAL = {"conversation_id": "private-native-id", "started_at": STAMP, "start_step_index": 2}


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value) + "\n")


@pytest.fixture
def session(tmp_path):
    runtime = tmp_path / "run"
    root = runtime / "traitmech"
    root.mkdir(parents=True)
    ledger = {
        "schema_version": 2, "repository_key": "traitmech", "run_id": "private-run-name",
        "cycle": 1, "stage": 1, "adopted_goal": copy.deepcopy(GOAL),
        "workflow": {"sha256": WORKFLOW}, "completed_stages": [], "awaiting_goal": False,
        "last_observed_at": STAMP,
    }
    write(root / "ledger.json", ledger)
    write(root / "status.json", prs._context(ledger))
    write(runtime / "config.json", {"run_id": ledger["run_id"], "targets": [
        {"repository_key": "traitmech", "github_repository": "CultureBotAI/TraitMech"}]})
    return SimpleNamespace(root=root, runtime=runtime, ledger=ledger)


def record(session, number=42):
    return {**prs._context(session.ledger), "schema_version": 1, "pr_number": number, "reported_at": STAMP}


def live(number=42, *, state="open", merged=False):
    return {
        "number": number, "base": {"repo": {"full_name": "CultureBotAI/TraitMech"}},
        "head": {"sha": HEAD}, "html_url": f"https://github.com/CultureBotAI/TraitMech/pull/{number}",
        "merged": merged, "state": state, "merged_at": STAMP if merged else None,
        # GitHub returns a speculative merge SHA for open PRs. Never expose it
        # as merged evidence.
        "merge_commit_sha": MERGE,
    }


def fake_gh(data, calls=None, returncode=0):
    def execute(args):
        if calls is not None:
            calls.append(args)
        return SimpleNamespace(returncode=returncode, stdout=json.dumps(data), stderr="private authentication detail")
    return execute


def test_registration_idempotent_and_multiple_rounds_preserve_prior_bytes(session):
    first = prs.register_pr(session.root, 42)
    original = (session.root / prs.REGISTRY_NAME).read_bytes()
    assert prs.register_pr(session.root, 42) == first
    assert (session.root / prs.REGISTRY_NAME).read_bytes() == original
    prs.register_pr(session.root, 43)
    assert (session.root / prs.REGISTRY_NAME).read_bytes().startswith(original)
    gathered = prs.gather_associations([session.runtime])
    assert [item["pr_number"] for item in gathered] == [42, 43]
    assert json.loads((session.root / "ledger.json").read_text()) == session.ledger


def test_completed_stage_association_survives_cycle_restart(session):
    prs.register_pr(session.root, 42)
    old = prs._context(session.ledger)
    session.ledger["completed_stages"] = [{key: old[key] for key in ("cycle", "stage", "goal_identity", "workflow_sha256")}]
    session.ledger.update(cycle=2, adopted_goal={**GOAL, "start_step_index": 99})
    write(session.root / "ledger.json", session.ledger)
    gathered = prs.gather_associations([session.runtime])
    assert len(gathered) == 1 and gathered[0]["cycle"] == 1


@pytest.mark.parametrize("field,value", [
    ("run_id", "other-run"), ("repository_key", "cmmmech"),
])
def test_registry_source_identity_mismatch_fails_closed(session, field, value):
    item = record(session)
    item[field] = value
    write(session.root / prs.REGISTRY_NAME, item)
    with pytest.raises(prs.AssociationError, match="containing ledger"):
        prs.gather_associations([session.runtime])


@pytest.mark.parametrize("field,value", [
    ("cycle", 2), ("stage", 2),
    ("workflow_sha256", "d" * 64), ("goal_identity", {**GOAL, "start_step_index": 99}),
])
def test_orphan_registry_association_is_excluded_and_counted(session, field, value):
    item = record(session)
    item[field] = value
    write(session.root / prs.REGISTRY_NAME, item)
    before = {p.name: p.read_bytes() for p in session.root.iterdir()}
    found = prs.collect_associations([session.runtime])
    assert found.records == prs.gather_associations([session.runtime]) == []
    assert found.excluded_counts == {(session.ledger["run_id"], "traitmech"): 1}
    assert {p.name: p.read_bytes() for p in session.root.iterdir()} == before
    # Registration retains its stronger contract and never silently rewrites
    # an existing registry containing a superseded goal identity.
    with pytest.raises(prs.OrphanAssociation, match="retained goal"):
        prs.register_pr(session.root, 43)


def test_valid_records_unchanged_beside_orphan_and_no_orphan_github_query(session):
    valid = record(session)
    orphan = record(session, 43)
    orphan["goal_identity"] = {**GOAL, "start_step_index": 99}
    (session.root / prs.REGISTRY_NAME).write_text(json.dumps(orphan) + "\n" + json.dumps(valid) + "\n")
    result = prs.collect_associations([session.runtime])
    assert result.records == [valid]
    assert result.excluded_counts == {(session.ledger["run_id"], "traitmech"): 1}
    calls = []
    prs.fetch_pr_observations(result.records, gh=fake_gh(live(), calls))
    assert calls == [["gh", "api", "repos/CultureBotAI/TraitMech/pulls/42"]]
    write(session.root / prs.REGISTRY_NAME, valid)
    result = prs.collect_associations([session.runtime])
    assert result.records == [valid]
    assert result.excluded_counts == {(session.ledger["run_id"], "traitmech"): 0}


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("pr_number", True), ("pr_number", 0),
    ("reported_at", "not-a-date"), ("stage", 7), ("cycle", "2"),
    ("workflow_sha256", "bad"), ("goal_identity", {**GOAL, "start_step_index": True}),
    ("summary", "private text"),
])
def test_malformed_orphan_still_raises(session, field, value):
    item = record(session)
    item["cycle"] = 99
    item[field] = value
    write(session.root / prs.REGISTRY_NAME, item)
    with pytest.raises(prs.AssociationError) as error:
        prs.collect_associations([session.runtime])
    assert not isinstance(error.value, prs.OrphanAssociation)


@pytest.mark.parametrize("orphan_first", [True, False])
def test_orphan_cannot_hide_conflicting_registry_identity(session, orphan_first):
    valid = record(session)
    orphan = {**valid, "goal_identity": {**GOAL, "start_step_index": 99}}
    records = [orphan, valid] if orphan_first else [valid, orphan]
    (session.root / prs.REGISTRY_NAME).write_text("".join(json.dumps(r) + "\n" for r in records))
    with pytest.raises(prs.AssociationError, match="conflicting"):
        prs.collect_associations([session.runtime])


def test_duplicate_runtime_cannot_inflate_exclusions(session):
    with pytest.raises(prs.AssociationError, match="duplicate registry"):
        prs.collect_associations([session.runtime, session.runtime])


@pytest.mark.parametrize("mutate", [
    lambda ledger: ledger.update(adopted_goal="malformed-not-an-object"),
    lambda ledger: ledger.update(adopted_goal={**GOAL, "start_step_index": True}),
    lambda ledger: ledger.update(adopted_goal=None),
    lambda ledger: ledger.update(completed_stages={}),
    lambda ledger: ledger.update(completed_stages=["malformed"]),
    lambda ledger: ledger.update(completed_stages=[{"cycle": 1, "stage": 1,
        "goal_identity": "malformed", "workflow_sha256": WORKFLOW}]),
    lambda ledger: ledger.update(completed_stages=[{"cycle": 1, "stage": 1,
        "goal_identity": GOAL, "workflow_sha256": None}]),
])
def test_malformed_retained_context_cannot_be_counted_as_orphan(session, mutate):
    write(session.root / prs.REGISTRY_NAME, record(session))
    mutate(session.ledger)
    write(session.root / "ledger.json", session.ledger)
    with pytest.raises(prs.AssociationError) as error:
        prs.collect_associations([session.runtime])
    assert not isinstance(error.value, prs.OrphanAssociation)


def test_legacy_closure_without_workflow_pin_does_not_invent_association_authority(session):
    valid = record(session)
    legacy = {"cycle": 1, "stage": 1, "goal_identity": {**GOAL, "start_step_index": 1}}
    session.ledger["completed_stages"] = [legacy]
    write(session.root / "ledger.json", session.ledger)
    write(session.root / prs.REGISTRY_NAME, valid)
    assert prs.collect_associations([session.runtime]).records == [valid]
    valid["goal_identity"] = legacy["goal_identity"]
    write(session.root / prs.REGISTRY_NAME, valid)
    found = prs.collect_associations([session.runtime])
    assert found.records == []
    assert found.excluded_counts == {(session.ledger["run_id"], "traitmech"): 1}


@pytest.mark.parametrize("stage,awaiting", [(0, False), (1, True)])
def test_unadopted_goal_does_not_create_retained_context(session, stage, awaiting):
    write(session.root / prs.REGISTRY_NAME, record(session))
    session.ledger.update(adopted_goal=None, stage=stage, awaiting_goal=awaiting)
    write(session.root / "ledger.json", session.ledger)
    result = prs.collect_associations([session.runtime])
    assert result.records == []
    assert result.excluded_counts == {(session.ledger["run_id"], "traitmech"): 1}


@pytest.mark.parametrize("number", [0, -1, True, "42"])
def test_registry_requires_integer_positive_number(session, number):
    with pytest.raises(prs.AssociationError, match="positive integer"):
        prs.register_pr(session.root, number)
    assert not (session.root / prs.REGISTRY_NAME).exists()


def test_registration_rejects_status_mismatch_and_unadopted_goal(session):
    status = prs._context(session.ledger)
    status["cycle"] = 2
    write(session.root / "status.json", status)
    with pytest.raises(prs.AssociationError, match="disagree"):
        prs.register_pr(session.root, 42)
    write(session.root / "status.json", prs._context(session.ledger))
    session.ledger["awaiting_goal"] = True
    write(session.root / "ledger.json", session.ledger)
    with pytest.raises(prs.AssociationError, match="not yet"):
        prs.register_pr(session.root, 42)


@pytest.mark.parametrize("which", ["ledger.json", "status.json", "pr-associations.jsonl", ".pr-associations.lock"])
def test_registration_refuses_symlink_inputs(session, which, tmp_path):
    path = session.root / which
    outside = tmp_path / "outside"
    if path.exists():
        path.rename(outside)
    else:
        outside.write_text("")
    path.symlink_to(outside)
    with pytest.raises((prs.AssociationError, OSError)):
        prs.register_pr(session.root, 42)


def test_registry_rejects_partial_jsonl_and_duplicate_json_keys(session):
    path = session.root / prs.REGISTRY_NAME
    path.write_text(json.dumps(record(session)))
    with pytest.raises(prs.AssociationError, match="incomplete"):
        prs.gather_associations([session.runtime])
    path.write_text('{"schema_version":1,"schema_version":1}\n')
    with pytest.raises(prs.AssociationError, match="duplicate"):
        prs.gather_associations([session.runtime])


def test_registry_rejects_unexpected_free_text(session):
    item = record(session)
    item["summary"] = "private text"
    write(session.root / prs.REGISTRY_NAME, item)
    with pytest.raises(prs.AssociationError, match="fields"):
        prs.gather_associations([session.runtime])


def test_atomic_registration_failure_preserves_prior_file(session, monkeypatch):
    prs.register_pr(session.root, 42)
    original = (session.root / prs.REGISTRY_NAME).read_bytes()
    def fail(*args):
        raise OSError("injected write failure")
    monkeypatch.setattr(prs.os, "replace", fail)
    with pytest.raises(OSError, match="injected"):
        prs.register_pr(session.root, 43)
    assert (session.root / prs.REGISTRY_NAME).read_bytes() == original
    assert sorted(path.name for path in session.root.glob(".pr-associations-*")) == []


def test_runtime_target_cannot_redirect_github(session):
    config = json.loads((session.runtime / "config.json").read_text())
    config["targets"][0]["github_repository"] = "Other/TraitMech"
    write(session.runtime / "config.json", config)
    with pytest.raises(prs.AssociationError, match="canonical GitHub"):
        prs.register_pr(session.root, 42)


def test_unadopted_assessment_has_no_pr_associations_and_cannot_register(session):
    session.ledger.update(stage=0, adopted_goal=None)
    write(session.root / "ledger.json", session.ledger)
    write(session.root / "status.json", prs._context(session.ledger))
    assert prs.gather_associations([session.runtime]) == []
    with pytest.raises(prs.AssociationError, match="workflow identity"):
        prs.register_pr(session.root, 42)


def test_only_exact_v2_completion_candidate_contributes_association(session):
    candidate = {**prs._context(session.ledger), "schema_version": 2, "pr": {"number": 42}}
    write(session.root / "completion.json", candidate)
    found = prs.gather_associations([session.runtime])
    assert found[0]["pr_number"] == 42
    assert "completed" not in found[0]
    candidate.pop("cycle")
    write(session.root / "completion.json", candidate)
    assert prs.gather_associations([session.runtime]) == []
    candidate["schema_version"] = 1
    write(session.root / "completion.json", candidate)
    assert prs.gather_associations([session.runtime]) == []


def test_github_facts_are_allowlisted_and_open_trial_merge_is_not_completion(session):
    source = record(session)
    calls = []
    facts = prs.fetch_pr_observations([source, source], gh=fake_gh(live(), calls))
    assert calls == [["gh", "api", "repos/CultureBotAI/TraitMech/pulls/42"]]
    assert len(facts) == 2 and facts[0]["state"] == "open"
    assert facts[0]["association_authority"] == "agent_reported"
    assert "goal_identity" not in facts[0] and "workflow_sha256" not in facts[0]
    assert "merge_commit_sha" not in facts[0]


def test_github_merged_facts_remain_separate_from_goal_completion(session):
    facts = prs.fetch_pr_observations([record(session)], gh=fake_gh(live(state="closed", merged=True)))
    assert facts[0]["state"] == "merged"
    assert facts[0]["merge_commit_sha"] == MERGE
    assert "goal_complete" not in facts[0]


def test_retained_public_binding_refresh_accepts_stage_number_without_private_run_id(session):
    source = {"repository_key": "traitmech", "run_key": "d" * 24, "cycle": 1, "stage_number": 1, "number": 42}
    facts = prs.fetch_pr_observations([source], gh=fake_gh(live()))
    assert facts[0]["run_key"] == source["run_key"]
    assert "run_id" not in facts[0]
    source["stage"] = 2
    with pytest.raises(prs.AssociationError, match="stage"):
        prs.fetch_pr_observations([source], gh=fake_gh(live()))


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(number=43),
    lambda p: p.update(number=True),
    lambda p: p["base"]["repo"].update(full_name="Other/TraitMech"),
    lambda p: p.update(html_url="https://evil.example/pull/42"),
    lambda p: p["head"].update(sha="not-a-sha"),
    lambda p: p.update(merged="true"),
    lambda p: p.update(state="unknown"),
    lambda p: p.update(merged=True, merged_at=STAMP, state="open"),
    lambda p: p.update(merged=True, merged_at=None, state="closed"),
    lambda p: p.update(merged=True, merged_at=STAMP, state="closed", merge_commit_sha=None),
    lambda p: p.update(merged_at=STAMP),
])
def test_github_mismatches_fail_closed(session, mutate):
    data = live()
    mutate(data)
    with pytest.raises(prs.AssociationError, match="GitHub"):
        prs.fetch_pr_observations([record(session)], gh=fake_gh(data))


def test_github_failure_never_publishes_private_stderr_or_guesses_closed(session):
    with pytest.raises(prs.AssociationError, match="GitHub PR query failed") as failure:
        prs.fetch_pr_observations([record(session)], gh=fake_gh({}, returncode=1))
    assert "private authentication" not in str(failure.value)


def test_fifo_is_rejected_without_blocking(session):
    os.mkfifo(session.root / prs.REGISTRY_NAME)
    with pytest.raises(prs.AssociationError, match="regular"):
        prs.gather_associations([session.runtime])
