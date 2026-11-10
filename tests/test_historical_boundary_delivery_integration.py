"""Both historical-boundary authority and exact native delivery are necessary."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_historical_goal_reconciliation import exact_start_input
from test_stage3_historical_reconciliation import (  # noqa: F401 -- offline fixtures
    apply,
    cycle_setup,
    ledger,
    npm,
    release_record,
    setup,
    supervisor,
)


def pending_start(state, *, held=False, previously_accepted=False):
    if held:
        apply(state)
    else:
        release_record(state)
        apply(state)
    current = ledger(state)
    action = {
        "kind": "start_goal", "stage": 4, "cycle": 4, "state": "uncertain",
        "marker": "synthetic-boundary-delivery", "native_session_id": state.current["conversation_id"],
        "reserved_epoch_ms": 0, "goal_identity": copy.deepcopy(current["adopted_goal"]),
        "native_step_index": current["adopted_goal"]["start_step_index"],
        "message": "/goal perform the complete reviewed next objective [synthetic-boundary-delivery]",
    }
    if previously_accepted:
        action.update(state="accepted", accepted_at="2026-10-25T01:00:01Z", acceptance="native_workspace_history_marker")
    current["actions"]["next-stage"] = action
    identity = {**state.current, "start_step_index": 17000, "started_at": "2026-11-01T01:00:00Z"}
    observation = exact_start_input(state, action, identity)
    assert supervisor.native_delivery_proof(action, state.target, observation) is not None
    return current, action, observation


@pytest.mark.parametrize("invalid", ["held", "malformed", "same_external", "earlier_step", "earlier_time"])
def test_exact_delivery_cannot_cross_unreleased_or_invalid_historical_boundary(npm, invalid):  # noqa: F811 -- imported fixture
    current, action, observation = pending_start(npm, held=invalid == "held")
    if invalid == "malformed":
        current["historical_goal_boundary"]["released_by"] = "0" * 64
    elif invalid in {"same_external", "earlier_step", "earlier_time"}:
        identity = copy.deepcopy(observation["goal_identity"])
        if invalid == "same_external":
            identity = copy.deepcopy(npm.current)
        elif invalid == "earlier_step":
            identity["start_step_index"] = npm.current["start_step_index"] - 1
        else:
            identity["started_at"] = "2026-10-28T01:00:00Z"
        observation = exact_start_input(npm, action, identity)
    # Exact delivery genuinely passes for every negative fixture. Only the
    # separately reviewed historical boundary can reject these observations.
    assert supervisor.native_delivery_proof(action, npm.target, observation) is not None
    before = copy.deepcopy(current)
    npm.instance.reconcile(npm.target, current, observation)
    assert current == before


@pytest.mark.parametrize("invalid", ["marker_only", "partial", "queued", "not_declaration", "foreign_workspace", "duplicate"])
def test_released_boundary_cannot_replace_exact_native_delivery(npm, invalid):  # noqa: F811 -- imported fixture
    current, action, observation = pending_start(npm)
    native = observation["native"]
    entry = native["user_input_evidence"]["inputs"][0]
    if invalid == "marker_only":
        native.pop("user_input_evidence")
    elif invalid == "partial":
        partial = action["message"][:-12]
        entry.update(text_sha256=supervisor.hashlib.sha256(partial.encode()).hexdigest(), text_length=len(partial))
    elif invalid == "queued":
        entry["status_number"] = 11
    elif invalid == "not_declaration":
        entry["native_goal_declaration"] = False
    elif invalid == "foreign_workspace":
        native["root"] = "/example/other-repository"
    else:
        native["user_input_evidence"]["inputs"].append(copy.deepcopy(entry))
    # Exact goal text and a history display still cannot repair native proof.
    Path(npm.config["history_path"]).write_text(json.dumps({
        "workspace": npm.target["root"], "conversationId": npm.current["conversation_id"],
        "timestamp": 1, "display": action["message"]}) + "\n")
    before = copy.deepcopy(current)
    npm.instance.reconcile(npm.target, current, observation)
    assert current == before


@pytest.mark.parametrize("previously_accepted", [False, True])
def test_released_boundary_and_exact_new_declaration_adopt_once_without_history_rewrite(npm, previously_accepted):  # noqa: F811 -- imported fixture
    current, action, observation = pending_start(npm, previously_accepted=previously_accepted)
    previous_actions = copy.deepcopy({key: value for key, value in current["actions"].items() if key != "next-stage"})
    previous_closures = copy.deepcopy(current["completed_stages"])
    previous_workflow = copy.deepcopy(current["workflow"])
    npm.instance.reconcile(npm.target, current, observation)
    assert current["adopted_goal"] == observation["goal_identity"]
    assert not current["awaiting_goal"] and "historical_goal_boundary" not in current
    assert action["state"] == "accepted" and action["delivery_proof"]["native_step_index"] == 17000
    if previously_accepted:
        assert action["accepted_at"] == "2026-10-25T01:00:01Z"
        assert action["acceptance"] == "native_workspace_history_marker"
    else:
        assert action["acceptance"] == "native_exact_user_input"
    assert {key: value for key, value in current["actions"].items() if key != "next-stage"} == previous_actions
    assert current["completed_stages"] == previous_closures and current["workflow"] == previous_workflow
    assert (current["cycle"], current["stage"]) == (4, 4)
    after = copy.deepcopy(current)
    npm.instance.reconcile(npm.target, current, observation)
    assert current == after
