"""Offline source archival contracts; historical code is never executed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.adhoc.edgemech_recovery_20261125.preserve_sources import (
    Bindings,
    preserve,
    python_blocks,
    regular_bytes,
    selected_call,
    sha,
)


def records() -> list[dict]:
    return [
        {
            "timestamp": "2026-11-26T01:00:00Z",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "synthetic-call",
                "input": "await tools.exec_command({cmd: 'original source'});",
            },
        },
        {
            "timestamp": "2026-11-26T01:00:01Z",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "CommandExecution",
                    "command": [
                        "bash",
                        "-lc",
                        "python - <<'PY'\nraise RuntimeError('never run')\nPY\n",
                    ],
                    "status": "failed",
                    "exit_code": 1,
                },
            },
        },
        {
            "timestamp": "2026-11-26T01:00:02Z",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "unrelated",
                "output": "not this result",
            },
        },
        {
            "timestamp": "2026-11-26T01:00:03Z",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "synthetic-call",
                "output": "actual failed result",
            },
        },
        {
            "timestamp": "2026-11-26T01:00:04Z",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "later-call",
                "input": "later source",
            },
        },
        {
            "timestamp": "2026-11-26T01:00:05Z",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "CommandExecution",
                    "command": ["true"],
                    "status": "completed",
                    "exit_code": 0,
                },
            },
        },
    ]


def selection(tmp_path: Path) -> dict:
    path = tmp_path / "rollout.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in records()))
    return {
        "cutoff": "2026-11-26T02:00:00Z",
        "owners": [
            {
                "rollout": str(path),
                "calls": [{"id": "synthetic-01", "line": 1, "purpose": "offline fixture"}],
            }
        ],
    }


def test_exact_sources_and_failed_native_receipt_retained_without_execution(tmp_path):
    spec = selection(tmp_path)
    result = preserve(spec, tmp_path / "private", tmp_path / "public")
    entry = result["entries"][0]
    assert entry["native_commands"] == [{"status": "failed", "exit_code": 1}]
    assert entry["result_records"] == 1
    code = tmp_path / "private/synthetic-01/command-01-python-01.py.txt"
    assert code.read_bytes() == b"raise RuntimeError('never run')\n"
    assert entry["files"][2]["private_original_sha256"] == sha(code.read_bytes())
    linkage = json.loads((tmp_path / "private/synthetic-01/linkage.json").read_text())
    assert linkage["results"][0]["record"]["payload"]["output"] == "actual failed result"
    assert len(linkage["commands"]) == 1


def test_private_and_public_source_hashes_are_distinct(tmp_path):
    spec = selection(tmp_path)
    path = Path(spec["owners"][0]["rollout"])
    rows = records()
    rows[0]["payload"]["input"] = "Path('/Users/example/private')"
    path.write_text("".join(json.dumps(x) + "\n" for x in rows))
    result = preserve(spec, tmp_path / "private", tmp_path / "public")
    entry = result["entries"][0]["files"][0]
    assert entry["private_original_sha256"] != entry["public"]["sha256"]
    assert "/Users/example" in (tmp_path / "private/synthetic-01/orchestrator.js.txt").read_text()
    assert (
        "/Users/example" not in (tmp_path / "public/synthetic-01/orchestrator.js.txt").read_text()
    )


def test_binding_redaction_is_stable_and_does_not_rewrite_digest_substrings():
    bindings = Bindings({"PRIVATE_PID": "12345"})
    text = "/Users/example x /Users/example %77 /dev/ttys999 00000000-0000-0000-0000-000000000001 12345 a12345b"
    first = bindings.transform(text)
    assert bindings.transform(text) == first
    for sensitive in [
        "/Users/example",
        "%77",
        "/dev/ttys999",
        "00000000-0000-0000-0000-000000000001",
    ]:
        assert sensitive not in first
    assert "PRIVATE_PID" in first and "a12345b" in first


def test_missing_result_refuses_without_inventing_success():
    rows = records()[:1]
    parsed = [(json.dumps(r).encode(), r) for r in rows]
    with pytest.raises(ValueError, match="exactly one"):
        selected_call(parsed, 1, "2026-11-26T02:00:00Z")


@pytest.mark.parametrize("bad", ["cutoff", "duplicate", "wrong-line"])
def test_invalid_selection_refuses_before_output_creation(tmp_path, bad):
    spec = selection(tmp_path)
    if bad == "cutoff":
        spec["cutoff"] = "2026-11-25T00:00:00Z"
    elif bad == "duplicate":
        spec["owners"][0]["calls"] *= 2
    else:
        spec["owners"][0]["calls"][0]["line"] = 2
    with pytest.raises(ValueError):
        preserve(spec, tmp_path / "private", tmp_path / "public")
    assert not (tmp_path / "private").exists()
    assert not (tmp_path / "public").exists()


def test_archive_does_not_replace_existing_originals(tmp_path):
    spec = selection(tmp_path)
    preserve(spec, tmp_path / "private", tmp_path / "public")
    original = (tmp_path / "private/MANIFEST.json").read_bytes()
    with pytest.raises(FileExistsError):
        preserve(spec, tmp_path / "private", tmp_path / "public")
    assert (tmp_path / "private/MANIFEST.json").read_bytes() == original


def test_output_symlink_and_private_public_overlap_refused(tmp_path):
    spec = selection(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        preserve(spec, link / "private", tmp_path / "public")
    assert list(outside.iterdir()) == []
    with pytest.raises(ValueError):
        preserve(spec, tmp_path / "same", tmp_path / "same/public")


def test_input_symlink_refused(tmp_path):
    actual = tmp_path / "actual"
    actual.write_text("original")
    link = tmp_path / "link"
    link.symlink_to(actual)
    with pytest.raises(ValueError):
        regular_bytes(link)


def test_heredoc_content_is_not_evaluated_and_unterminated_refuses():
    assert python_blocks("python3 - <<'CODE'\nprint('$(do-not-run)')\nCODE\n") == [
        "print('$(do-not-run)')\n"
    ]
    with pytest.raises(ValueError):
        python_blocks("python - <<'CODE'\nprint(1)\n")


def test_duplicate_results_and_bad_source_bounds_refused():
    rows = records()
    rows.append(rows[3])
    parsed = [(json.dumps(r).encode(), r) for r in rows]
    with pytest.raises(ValueError, match="exactly one"):
        selected_call(parsed, 1, "2026-11-26T02:00:00Z")
    for line in [0, -1, 100]:
        with pytest.raises(ValueError, match="outside rollout"):
            selected_call(parsed, line, "2026-11-26T02:00:00Z")


def test_uuid_attached_to_prose_is_parameterized():
    identity = "00000000-0000-0000-0000-000000000001"
    result = Bindings().transform("workerthread" + identity + "/checkpoint")
    assert identity not in result
    assert "workerthreadPRIVATE_UUID_" in result
