"""A native continuation preserves old PR ownership without stage-completion credit."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from kg_microbe_progress import prs

STAMP = "2026-10-25T05:16:26.654834+00:00"


def goal(index):
    return {"conversation_id": "same-conversation", "start_step_index": index, "started_at": STAMP}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def bind(tmp_path, ledger, predecessor, successor, name="acceptance"):
    binding = {"schema_version": 1, **{key: ledger[key] for key in
               ("run_id", "repository_key", "cycle", "stage")},
               "workflow_sha256": ledger["workflow"]["sha256"],
               "predecessor": predecessor, "successor": successor}
    proof = {"binding": binding, "verified_at": STAMP, "instruction_sha256": "d" * 64,
             "native_acceptance": {**successor, "submitted_text_sha256": "d" * 64,
                                   "matching_declarations": 1},
             "history_acceptance": {"conversation_id": successor["conversation_id"],
                                    "submitted_text_sha256": "d" * 64, "matching_entries": 1}}
    path = tmp_path / f"{name}.json"
    dump(path, proof)
    return {**binding, "evidence": {"path": str(path),
                                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


@pytest.fixture
def session(tmp_path):
    runtime = tmp_path / "runtime"
    directory = runtime / "antibioticmech"
    ledger = {"schema_version": 2, "run_id": "continuation-test", "repository_key": "antibioticmech",
              "cycle": 2, "stage": 3, "adopted_goal": goal(2), "awaiting_goal": False,
              "workflow": {"sha256": "a" * 64}, "completed_stages": [], "actions": {}}
    old = {**prs._context(ledger), "goal_identity": goal(1), "schema_version": 1,
           "pr_number": 1266, "reported_at": STAMP}
    ledger["same_stage_continuations"] = [bind(tmp_path, ledger, goal(1), goal(2))]
    dump(directory / "ledger.json", ledger)
    dump(directory / "status.json", prs._context(ledger))
    dump(runtime / "config.json", {"run_id": ledger["run_id"], "targets": [
        {"repository_key": "antibioticmech", "github_repository": "CultureBotAI/AntibioticMech"}]})
    registry = directory / prs.REGISTRY_NAME
    registry.write_text(json.dumps(old) + "\n")
    return directory, ledger, old


def test_register_and_gather_preserve_predecessor_and_no_completion_credit(session):
    directory, ledger, old = session
    before = copy.deepcopy(ledger)
    prior_bytes = (directory / prs.REGISTRY_NAME).read_bytes()
    new = prs.register_pr(directory, 1268)
    assert new["goal_identity"] == goal(2)
    assert (directory / prs.REGISTRY_NAME).read_bytes().startswith(prior_bytes)
    assert prs.gather_associations([directory.parent]) == [old, new]
    assert json.loads((directory / "ledger.json").read_text()) == before
    assert ledger["completed_stages"] == []
    assert not (directory / "completion.json").exists()
    assert prs.register_pr(directory, 1268) == new  # exact current binding stays idempotent
    with pytest.raises(prs.AssociationError, match="already bound"):
        prs.register_pr(directory, 1266)  # never relabel the original checkpoint


def test_lineage_retained_after_real_stage_advance(session):
    directory, ledger, old = session
    ledger["completed_stages"].append({"cycle": 2, "stage": 3, "goal_identity": goal(2),
                                        "workflow_sha256": "a" * 64})
    ledger.update(stage=4, adopted_goal=goal(3))
    dump(directory / "ledger.json", ledger)
    dump(directory / "status.json", prs._context(ledger))
    assert prs.gather_associations([directory.parent]) == [old]
    assert len(ledger["completed_stages"]) == 1


def test_multi_hop_and_later_workflow_change(session, tmp_path):
    _, ledger, old = session
    ledger["same_stage_continuations"].append(bind(tmp_path, ledger, goal(2), goal(3), "next"))
    ledger["adopted_goal"] = goal(3)
    assert prs._validate_record(old, ledger) == old
    ledger["completed_stages"] = [{"cycle": 2, "stage": 3, "goal_identity": goal(3),
                                   "workflow_sha256": "a" * 64}]
    ledger.update(cycle=3, stage=1, adopted_goal=goal(4), workflow={"sha256": "b" * 64})
    assert prs._validate_record(old, ledger) == old


@pytest.mark.parametrize("case", ["self", "disconnected", "cycle", "fork", "merge", "wrong-stage",
                                 "wrong-cycle", "wrong-workflow", "wrong-run", "wrong-repo"])
def test_invalid_lineage_fails_closed(session, tmp_path, case):
    _, ledger, old = session
    links = ledger["same_stage_continuations"]
    if case == "self":
        links[:] = [bind(tmp_path, ledger, goal(1), goal(1))]
    elif case == "disconnected":
        links[:] = [bind(tmp_path, ledger, goal(1), goal(9))]
    elif case == "cycle":
        links[:] = [bind(tmp_path, ledger, goal(1), goal(9)),
                    bind(tmp_path, ledger, goal(9), goal(1), "other")]
    elif case == "fork":
        links.append(bind(tmp_path, ledger, goal(1), goal(9), "other"))
    elif case == "merge":
        links.append(bind(tmp_path, ledger, goal(9), goal(2), "other"))
    else:
        changed = copy.deepcopy(ledger)
        if case == "wrong-workflow":
            changed["workflow"]["sha256"] = "b" * 64
        else:
            field = {"wrong-stage": "stage", "wrong-cycle": "cycle",
                     "wrong-run": "run_id", "wrong-repo": "repository_key"}[case]
            changed[field] = 5 if field in {"stage", "cycle"} else "different"
        links[:] = [bind(tmp_path, changed, goal(1), goal(2))]
    with pytest.raises(prs.AssociationError):
        prs._validate_record(old, ledger)
    current = {**old, "goal_identity": ledger["adopted_goal"]}
    with pytest.raises(prs.AssociationError):
        prs._validate_record(current, ledger)  # malformed optional lineage is never ignored


@pytest.mark.parametrize("case", ["hash", "missing", "symlink", "binding", "native-identity",
                                 "native-count", "history-count", "bool-count", "text", "timestamp"])
def test_acceptance_evidence_must_be_exact_and_unique(session, tmp_path, case):
    _, ledger, old = session
    evidence = ledger["same_stage_continuations"][0]["evidence"]
    path = tmp_path / "acceptance.json"
    proof = json.loads(path.read_text())
    if case == "hash":
        evidence["sha256"] = "f" * 64
    elif case == "missing":
        path.unlink()
    elif case == "symlink":
        actual = tmp_path / "actual.json"
        path.rename(actual)
        path.symlink_to(actual)
    else:
        if case == "binding":
            proof["binding"]["predecessor"] = goal(9)
        elif case == "native-identity":
            proof["native_acceptance"]["start_step_index"] = 9
        elif case == "native-count":
            proof["native_acceptance"]["matching_declarations"] = 2
        elif case == "history-count":
            proof["history_acceptance"]["matching_entries"] = 0
        elif case == "bool-count":
            proof["history_acceptance"]["matching_entries"] = True
        elif case == "text":
            proof["native_acceptance"]["submitted_text_sha256"] = "e" * 64
        else:
            proof["verified_at"] = "not-a-time"
        dump(path, proof)
        evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(prs.AssociationError):
        prs._validate_record(old, ledger)


def test_legacy_current_completed_contexts_unchanged_without_lineage(session):
    _, ledger, old = session
    ledger.pop("same_stage_continuations")
    assert prs._validate_record({**old, "goal_identity": goal(2)}, ledger)
    with pytest.raises(prs.AssociationError, match="retained goal"):
        prs._validate_record(old, ledger)
    ledger["completed_stages"].append({"cycle": 2, "stage": 3, "goal_identity": goal(1),
                                        "workflow_sha256": "a" * 64})
    assert prs._validate_record(old, ledger) == old
