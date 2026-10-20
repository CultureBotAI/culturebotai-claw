"""Exercise the committed adapter without reading or writing live terminals."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "mech_session_terminal",
    Path(__file__).parents[1] / "scripts/mech_session_terminal.py",
)
terminal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(terminal)

IDENTITY = "1234 ttys030 Mon Oct 19 10:00:00 2026 agy"
EMPTY = "Earlier output\n──────────\n>\n──────────\n? for shortcuts Gemini model\n"


def test_process_identity_retains_start_time_and_rejects_other_processes():
    assert terminal.process_record("  " + IDENTITY + "\n") == {
        "pid": 1234, "tty": "/dev/ttys030", "identity": IDENTITY,
        "started": "Mon Oct 19 10:00:00 2026",
    }
    for line in (
        IDENTITY.replace("agy", "bash"),
        IDENTITY.replace("ttys030", "pts/1"),
        IDENTITY.replace("1234", "unknown"),
        IDENTITY.replace("1234", "0"),
        "1234 ttys030 agy",
    ):
        assert terminal.process_record(line) is None


@pytest.mark.parametrize("pid", ["1234", "-1", "1; echo bad", 0, -1, True, None])
def test_invalid_pid_never_reaches_subprocess(pid, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid PID reached subprocess")
    monkeypatch.setattr(terminal, "command", forbidden)
    with pytest.raises(ValueError, match="PID"):
        terminal.live_process(pid)
    with pytest.raises(ValueError, match="PID"):
        terminal.process_cwd(pid)


def test_cwd_ambiguity_fails_and_foreground_requires_matching_groups(monkeypatch, tmp_path):
    monkeypatch.setattr(terminal, "command", lambda *_a, **_k: f"p1234\nn{tmp_path}\n")
    assert terminal.process_cwd(1234) == tmp_path.resolve()
    monkeypatch.setattr(terminal, "command", lambda *_a, **_k: "n/one\nn/two\n")
    with pytest.raises(RuntimeError, match="ambiguous"):
        terminal.process_cwd(1234)
    for output, expected in (("42 42\n", True), ("42 43\n", False), ("-1 -1\n", False), ("42\n", False)):
        monkeypatch.setattr(terminal, "command", lambda *_a, value=output, **_k: value)
        assert terminal.foreground(1234, "/dev/ttys030") is expected


def test_composer_accepts_historic_prompt_and_trailing_blanks():
    assert terminal.composer_reason("Run this command?\n" + EMPTY + "\n" * 20) is None


@pytest.mark.parametrize("screen", [
    EMPTY.replace("\n>\n", "\n> unsubmitted draft\n"),
    EMPTY.replace("\n>\n", "\n>\nunsubmitted second line\n"),
    EMPTY + "unsubmitted continuation\n",
    EMPTY + "Allow access to this file?\n↑/↓ Navigate\n",
    EMPTY.replace("Gemini model", "unrecognized new UI"),
    EMPTY.replace("──────────", "not a border"),
    "",
])
def test_drafts_menus_and_unrecognized_composers_fail_closed(screen):
    assert terminal.composer_reason(screen) is not None


def test_jxa_passes_source_and_payload_as_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(terminal, "command", lambda args, **kw: calls.append((args, kw)) or "result\n")
    payload = {"path": "space ' quote $(literal)", "message": "line one\nline two"}
    assert terminal.jxa("function run(argv) {}", payload) == "result"
    args, options = calls[0]
    assert args[:5] == ["/usr/bin/osascript", "-l", "JavaScript", "-e", "function run(argv) {}"]
    assert json.loads(args[5]) == payload
    assert options == {"timeout": 20}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed to execute the JXA snapshot body offline")
def test_snapshot_js_filters_ttys_and_isolates_unreadable_tabs():
    harness = r'''
    let writes = 0;
    function tab(tty, screen, broken = false) {
        return {tty: () => tty, contents: () => {
            if (broken) throw Error("unreadable");
            return screen;
        }};
    }
    global.Application = name => {
        if (name !== "Terminal") throw Error("wrong app");
        return {
            doScript: () => { writes++; throw Error("snapshot must never type"); },
            windows: () => [{id: () => 7, tabs: () => [
                tab("/dev/ttys001", "other"),
                tab("/dev/ttys002", "selected"),
                tab("/dev/ttys003", "broken", true),
            ]}],
        };
    };
    '''
    program = harness + terminal.SNAPSHOT_JS + r'''
    const result = JSON.parse(run([JSON.stringify(["/dev/ttys002", "/dev/ttys003"])]));
    process.stdout.write(JSON.stringify({result, writes}));
    '''
    result = subprocess.run(["node", "-e", program], text=True, capture_output=True, check=True)
    parsed = json.loads(result.stdout)
    assert parsed["writes"] == 0
    assert parsed["result"]["tabs"] == [
        {"window": 7, "tab": 2, "tty": "/dev/ttys002", "screen": "selected"}
    ]
    assert len(parsed["result"]["warnings"]) == 1
