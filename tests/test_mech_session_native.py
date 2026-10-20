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
        "Example:\n\n    <!-- GOAL_COMPLETE -->",
        "    <!-- GOAL_COMPLETE -->",
        "\t<!-- GOAL_CANCELLED -->",
        "````markdown\n```\n<!-- GOAL_COMPLETE -->",
        "```markdown\n~~~\n<!-- GOAL_COMPLETE -->",
        "~~~markdown\n```\n<!-- GOAL_CANCELLED -->",
        "```markdown\n```not-a-closing-fence\n<!-- GOAL_COMPLETE -->",
    ],
)
def test_quoted_or_nonterminal_markers_do_not_finish_goal(text):
    assert native.terminal_marker(text) is None


def test_exact_marker_after_closed_code_fence_is_terminal():
    assert (
        native.terminal_marker("```\ncommand\n```\n\n<!-- GOAL_COMPLETE -->")
        == native.COMPLETE
    )


@pytest.mark.parametrize("fence", ["```", "````", "~~~"])
def test_matching_or_longer_fence_closes_before_real_marker(fence):
    assert native.terminal_marker(
        f"{fence}text\nexample\n{fence}{fence[0]}\n\n<!-- GOAL_CANCELLED -->\n\n"
    ) == native.CANCELLED


def encint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def bytefield(number, value):
    return encint((number << 3) | 2) + encint(len(value)) + value


def intfield(number, value):
    return encint(number << 3) + encint(value)


def goal_context(name=b"goal", command_type=1, model_text=None):
    """Observed SYSTEM slash command path, verified against installed descriptors."""
    info = (
        bytefield(1, name)
        + bytefield(2, native.GOAL_DECLARATION if model_text is None else model_text)
        + intfield(3, command_type)
    )
    return bytefield(3, bytefield(2, bytefield(27, bytefield(1, info))))


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
        + goal_context(),
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


@pytest.mark.parametrize(
    "quoted_context",
    [
        bytefield(3, bytefield(1, b'Explain "' + native.GOAL_DECLARATION + b'".')),
        bytefield(1, native.GOAL_DECLARATION),  # Deprecated public query.
        # An attached text block is context, but is not the native slash command.
        bytefield(3, bytefield(2, bytefield(11, bytefield(1, native.GOAL_DECLARATION)))),
        goal_context(name=b"explain"),
        goal_context(command_type=2),  # A skill with the same name is not SYSTEM.
        goal_context(model_text=b'Example: "' + native.GOAL_DECLARATION + b'".'),
    ],
)
def test_quoted_goal_declaration_does_not_replace_current_goal(
    tmp_path, monkeypatch, quoted_context
):
    monkeypatch.setattr(native, "ROOT", tmp_path)
    (tmp_path / "conversations").mkdir()
    with sqlite3.connect(tmp_path / "conversations" / "example.db") as db:
        db.executescript(
            "CREATE TABLE trajectory_meta (trajectory_id text,cascade_id text);"
            "CREATE TABLE steps (idx integer,step_type integer,status integer,step_payload blob);"
            "CREATE TABLE trajectory_metadata_blob (id text,data blob);"
        )
        db.execute("INSERT INTO trajectory_meta VALUES (?,?)", ("trajectory", "example"))
        db.execute(
            "INSERT INTO trajectory_metadata_blob VALUES (?,?)",
            ("main", bytefield(7, b"file:///example/TraitMech")),
        )
        db.executemany(
            "INSERT INTO steps VALUES (?,?,?,?)",
            [
                (10, 14, 3, bytefield(
                    19, bytefield(3, bytefield(1, b"review records")) + goal_context()
                )),
                (20, 14, 3, bytefield(
                    19, bytefield(3, bytefield(1, b"ordinary follow-up")) + quoted_context
                )),
            ],
        )
    row = native.inspect("/example/TraitMech", "example")
    assert row["current_goal"]["start_step_index"] == 10
    assert row["current_goal"]["goal_text"] == "review records"
    assert row["current_goal"]["state"] == "active"


@pytest.fixture
def snapshot_files(tmp_path, monkeypatch):
    source = tmp_path / "native.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE example (value text)")
        db.execute("INSERT INTO example VALUES ('synthetic private data')")
    snapshot_parent = tmp_path / "copies"
    snapshot_parent.mkdir()
    real_mkdtemp = native.tempfile.mkdtemp
    created = []

    def tracked_mkdtemp(suffix=None, prefix=None, dir=None):
        path = real_mkdtemp(suffix=suffix, prefix=prefix, dir=snapshot_parent)
        created.append(Path(path))
        return path

    monkeypatch.setattr(native.tempfile, "mkdtemp", tracked_mkdtemp)
    return source, created


def test_snapshot_retries_disappearing_wal_and_removes_every_copy(snapshot_files, monkeypatch):
    source, created = snapshot_files
    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"synthetic WAL removed by checkpoint")
    copy = native.shutil.copy2

    def checkpoint_during_copy(src, dst):
        result = copy(src, dst)
        if Path(src) == source:
            wal.unlink(missing_ok=True)
        return result

    monkeypatch.setattr(native.shutil, "copy2", checkpoint_during_copy)
    with native.snapshot(source) as (db, evidence):
        assert db.execute("SELECT value FROM example").fetchone()[0] == "synthetic private data"
        assert evidence["attempts"] == 2
        assert not created[0].exists()
    assert created and all(not path.exists() for path in created)


@pytest.mark.parametrize("failure", ["copy", "connect", "pragma", "reader"])
def test_snapshot_removes_private_copy_on_every_failure(snapshot_files, monkeypatch, failure):
    source, created = snapshot_files
    closed = []

    def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    class FailedConnection:
        execute = fail

        def close(self):
            closed.append(True)

    if failure == "copy":
        monkeypatch.setattr(native.shutil, "copy2", fail)
    elif failure == "connect":
        monkeypatch.setattr(native.sqlite3, "connect", fail)
    elif failure == "pragma":
        monkeypatch.setattr(native.sqlite3, "connect", lambda _: FailedConnection())
    with pytest.raises(RuntimeError, match="injected failure"):
        with native.snapshot(source):
            if failure == "reader":
                fail()
    assert created and all(not path.exists() for path in created)
    if failure == "pragma":
        assert closed
