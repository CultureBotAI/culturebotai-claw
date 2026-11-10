"""Real filesystem tests; no Terminal, native session or provider calls."""
import hashlib
import json
import os

import pytest

from kg_microbe_workflows import instructions as instructions


@pytest.fixture
def context():
    return {"action_id": "a" * 24, "kind": "finalize", "run_id": "run-one",
            "repository_key": "traitmech", "cycle": 3, "stage": 4,
            "native_session_id": "conversation-one", "reservation_goal_identity": {"start_step_index": 12},
            "workflow_sha256": "b" * 64, "instruction_sha256": "c" * 64}


def test_full_task_is_immutable_but_wire_is_bounded(tmp_path, context):
    session = tmp_path / "traitmech"
    body = "Full objective and closure policy. " * 150
    delivery = instructions.prepare_instruction(session, context, body)
    artifact = delivery["instruction_artifact"]
    path = session / "instructions" / (context["action_id"] + ".json")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
    assert json.loads(raw)["instruction"] == body
    for key, value in context.items():
        assert json.loads(raw)[key] == value
    assert len(delivery["message"].encode()) <= instructions.MAX_WIRE_BYTES
    assert body not in delivery["message"]
    assert json.dumps(str(path)) in delivery["message"]
    assert artifact["sha256"] in delivery["message"]
    assert instructions.prepare_instruction(session, context, body) == delivery
    with pytest.raises(instructions.InstructionError, match="different bytes"):
        instructions.prepare_instruction(session, context, body + " changed")
    assert path.read_bytes() == raw
    assert list(path.parent.iterdir()) == [path]


def test_goal_prefix_only_on_actual_wire_goal(tmp_path, context):
    context["kind"] = "start_goal"
    d = instructions.prepare_instruction(tmp_path / "goal", context, "/goal Full objective")
    assert d["message"].startswith("/goal [MECH-WORKFLOW-")
    value = json.loads(open(d["instruction_artifact"]["path"]).read())
    assert value["instruction"] == "/goal Full objective"
    assert "do not replay" in value["execution_note"]


@pytest.mark.parametrize("invalid", ["escape", "body_control", "path_control", "wire_too_long", "body_too_long"])
def test_preparation_refuses_before_artifact_creation(tmp_path, context, invalid):
    session = tmp_path / "session"
    body = "objective"
    if invalid == "escape":
        context["action_id"] = "../outside"
    elif invalid == "body_control":
        body = "objective\x1b[27u"
    elif invalid == "path_control":
        session = tmp_path / "session\nother"
    elif invalid == "wire_too_long":
        session = tmp_path / ("a" * 250)
    else:
        body = "x" * instructions.MAX_INSTRUCTION_BYTES
    with pytest.raises(instructions.InstructionError):
        instructions.prepare_instruction(session, context, body)
    assert not session.exists()


@pytest.mark.parametrize("component", ["session", "instructions", "file"])
def test_symlinks_are_never_followed(tmp_path, context, component):
    session = tmp_path / "session"
    outside = tmp_path / "outside"
    outside.mkdir()
    if component == "session":
        session.symlink_to(outside, target_is_directory=True)
    else:
        session.mkdir()
        directory = session / "instructions"
        if component == "instructions":
            directory.symlink_to(outside, target_is_directory=True)
        else:
            directory.mkdir()
            (directory / (context["action_id"] + ".json")).symlink_to(outside / "untouched")
    with pytest.raises((instructions.InstructionError, OSError)):
        instructions.prepare_instruction(session, context, "objective")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("change", ["changed", "missing", "symlink", "fifo", "escape"])
def test_preinput_recheck_refuses_changed_or_unsafe_artifact(tmp_path, context, change):
    session = tmp_path / "session"
    d = instructions.prepare_instruction(session, context, "objective")
    a = d["instruction_artifact"]
    path = session / "instructions" / (context["action_id"] + ".json")
    if change == "changed":
        path.write_text("different")
    else:
        path.unlink()
        if change == "symlink":
            path.symlink_to(tmp_path / "missing")
        elif change == "fifo":
            os.mkfifo(path)
        elif change == "escape":
            a["path"] = str(tmp_path / path.name)
    with pytest.raises((instructions.InstructionError, OSError)):
        instructions.verify_instruction(session, a)


def test_atomic_publication_never_overwrites_a_racing_destination(tmp_path, context, monkeypatch):
    original = instructions.os.link
    def race(source, destination, **kwargs):
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     mode=0o600, dir_fd=kwargs["dst_dir_fd"])
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"concurrent bytes")
        return original(source, destination, **kwargs)
    monkeypatch.setattr(instructions.os, "link", race)
    session = tmp_path / "session"
    with pytest.raises(instructions.InstructionError, match="different bytes"):
        instructions.prepare_instruction(session, context, "objective")
    files = list((session / "instructions").iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"concurrent bytes"


def test_multiline_unicode_objective_preserved_and_fixed_metadata_cannot_be_overridden(tmp_path, context):
    context.update(schema_version="untrusted", delivery_format="other")
    body = "Full objective: α → β\n\tKeep the second line and its tab."
    result = instructions.prepare_instruction(tmp_path / "session", context, body)
    raw = json.loads(open(result["instruction_artifact"]["path"]).read())
    assert raw["instruction"] == body
    assert raw["schema_version"] == "1.0.0"
    assert raw["delivery_format"] == instructions.FORMAT
    assert "\n" not in result["message"] and "\t" not in result["message"]


@pytest.mark.parametrize("predecessor", [None, {"start_step_index": 12}])
def test_start_goal_artifact_explicitly_labels_predecessor_not_receipt_identity(tmp_path, context, predecessor):
    context.update(kind="start_goal", reservation_goal_identity=predecessor)
    result = instructions.prepare_instruction(tmp_path / "session", context, "/goal Full objective")
    artifact = json.loads(open(result["instruction_artifact"]["path"]).read())
    assert artifact["reservation_goal_identity"] == predecessor
    assert "goal_identity" not in artifact
    note = artifact["execution_note"]
    assert "pre-dispatch/predecessor identity" in note and "possibly null" in note
    assert "not the newly adopted goal identity" in note
    assert "current status.json receipt_template" in note
    assert "do not copy this predecessor identity into a new-goal receipt" in note
