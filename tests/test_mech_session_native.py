"""Goal reconstruction must not turn stale/quoted completions into transitions."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/mech_session_native.py"
spec = importlib.util.spec_from_file_location("mech_session_native", MODULE_PATH)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def goal(index=10, state="active"):
    return {
        "goal_text": "review records",
        "started_at": "2026-10-19T00:00:00Z",
        "start_step_index": index,
        "state": state,
    }


def event(index, state="completed"):
    return {"step_index": index, "event": state}


def test_completion_after_checkpoint_and_duplicate_snapshot():
    state = native.select_current_goal([goal(), goal()], 20, [], [event(21)])
    assert state["state"] == "completed"
    assert state["completion_event"]["step_index"] == 21


def test_active_checkpoint_wins_over_older_completed_marker():
    state = native.select_current_goal([goal()], 30, [], [event(21)])
    assert state["state"] == "active"
    assert "completion_event" not in state


def test_new_goal_does_not_inherit_old_completion():
    state = native.select_current_goal(
        [goal(state="completed")], 30, [goal(40)], [event(21)]
    )
    assert state["goal_id"] == "goal-40"
    assert state["state"] == "active"


def test_completed_snapshot_does_not_reopen_or_cancel_on_ordinary_later_reply():
    state = native.select_current_goal(
        [goal(state="completed")], 30, [], [event(21), event(45, "cancelled")]
    )
    assert state["state"] == "completed"
    assert state["completion_event"]["historical_marker"]


def test_conflicting_duplicate_snapshot_fails_closed():
    with pytest.raises(ValueError, match="conflicting duplicate"):
        native.select_current_goal([goal(), goal(state="completed")], 30, [], [])


@pytest.mark.parametrize(
    "text",
    [
        "Quote: <!-- GOAL_COMPLETE -->",
        "> <!-- GOAL_COMPLETE -->",
        "```\n<!-- GOAL_COMPLETE -->",
        "Example\n```\n<!-- GOAL_COMPLETE -->\n```",
        "<!-- GOAL_COMPLETE -->\nMore work remains",
    ],
)
def test_quoted_or_nonterminal_markers_do_not_finish_goal(text):
    assert native.terminal_marker(text) is None


def test_exact_marker_after_closed_code_fence_is_terminal():
    assert (
        native.terminal_marker("```\ncommand\n```\n\n<!-- GOAL_COMPLETE -->")
        == native.COMPLETE
    )


def encint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def bytefield(number, value):
    return encint((number << 3) | 2) + encint(len(value)) + value


def test_completed_goal_with_queued_last_step_stays_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "ROOT", tmp_path)
    (tmp_path / "conversations").mkdir()
    db = sqlite3.connect(tmp_path / "conversations" / "example.db")
    db.executescript(
        "CREATE TABLE trajectory_meta (trajectory_id text,cascade_id text,trajectory_type integer,source integer); CREATE TABLE steps (idx integer,step_type integer,status integer,step_payload blob); CREATE TABLE trajectory_metadata_blob (id text,data blob);"
    )
    db.execute(
        "INSERT INTO trajectory_meta VALUES (?,?,?,?)", ("trajectory", "example", 4, 17)
    )
    db.execute(
        "INSERT INTO trajectory_metadata_blob VALUES (?,?)",
        ("main", bytefield(7, b"file:///example/TraitMech")),
    )
    # Public user text is a different item from the native /goal instruction context.
    user = bytefield(
        19,
        bytefield(3, bytefield(1, b"review records"))
        + bytefield(3, bytefield(2, native.GOAL_DECLARATION)),
    )
    complete = bytefield(20, bytefield(1, b"Done.\n<!-- GOAL_COMPLETE -->"))
    db.executemany(
        "INSERT INTO steps VALUES (?,?,?,?)",
        [(0, 14, 3, user), (1, 15, 3, complete), (2, 15, 11, b"")],
    )
    db.commit()
    db.close()
    row = native.inspect("/example/TraitMech", "example")
    assert row["current_goal"]["state"] == "completed"
    assert row["native_execution_state"] == "busy"
    assert row["last_step"]["status"] == "queued"
    assert not (tmp_path / "conversations" / "example.db-wal").exists()
