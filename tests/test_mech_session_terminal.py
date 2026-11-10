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
        IDENTITY.replace("agy", "node"),
        IDENTITY.replace("agy", "/opt/codex/bin/codex"),
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
    function tab(tty, screen, broken = false, history = null) {
        return {
            tty: () => tty,
            history: () => {
                if (broken) throw Error("unreadable");
                return history;
            },
            contents: () => {
                if (broken) throw Error("unreadable");
                return screen;
            },
        };
    }
    global.Application = name => {
        if (name !== "Terminal") throw Error("wrong app");
        return {
            doScript: () => { writes++; throw Error("snapshot must never type"); },
            windows: () => [{id: () => 7, tabs: () => [
                tab("/dev/ttys001", "other"),
                tab("/dev/ttys002", "scrolled viewport", false, "X".repeat(70000) + "\nlive bottom tail"),
                tab("/dev/ttys003", "broken", true),
                tab("/dev/ttys004", "fallback contents", false, ""),
            ]}],
        };
    };
    '''
    program = harness + terminal.SNAPSHOT_JS + r'''
    const result = JSON.parse(run([JSON.stringify(["/dev/ttys002", "/dev/ttys003", "/dev/ttys004"])]));
    process.stdout.write(JSON.stringify({result, writes}));
    '''
    result = subprocess.run(["node", "-e", program], text=True, capture_output=True, check=True)
    parsed = json.loads(result.stdout)
    assert parsed["writes"] == 0
    assert len(parsed["result"]["tabs"]) == 2
    tab2 = parsed["result"]["tabs"][0]
    assert tab2["window"] == 7 and tab2["tab"] == 2 and tab2["tty"] == "/dev/ttys002"
    assert len(tab2["screen"]) == terminal.TAIL_CHARS
    assert tab2["screen"].endswith("\nlive bottom tail")
    assert "scrolled viewport" not in tab2["screen"]
    assert parsed["result"]["tabs"][1] == {
        "window": 7, "tab": 4, "tty": "/dev/ttys004", "screen": "fallback contents"
    }
    assert len(parsed["result"]["warnings"]) == 1


def test_known_announcement_cannot_substitute_for_runtime_model_footer():
    announcement = 'Meet Gemini 4 Argon …\nesc to dismiss\n'
    assert terminal.composer_reason(EMPTY + announcement) is None
    assert terminal.composer_reason(EMPTY.replace('? for shortcuts Gemini model\n', '') + announcement) is not None
    assert terminal.composer_reason(EMPTY + 'Unrecognized announcement\nesc to dismiss\n') is not None


@pytest.mark.parametrize(
    ("indicator", "expected_reason"),
    [
        ("⇧← to answer", "queued-question"),
        ("Queued follow-up (1)", "queued-question"),
        ("QUESTION: Which target branch should be used?", "queued-question"),
        ("request_user_input waiting for response", "queued-question"),
        ("Sign in with Google to continue", "sign-in-prompt"),
        ("Trust this folder and its contents?", "trust-prompt"),
        ("Update available — Skip until next version", "update-prompt"),
        ("Allow command in terminal?", "approval-menu"),
    ],
)
def test_queued_questions_and_blocked_prompts_rejected_by_canonical_guard(
    indicator, expected_reason
):
    screen = EMPTY + indicator + "\n"
    assert terminal.composer_reason(screen) == expected_reason
    assert terminal.verify_paste_ready(screen) == expected_reason
    draft_screen = EMPTY.replace("\n>\n", "\n> Review shard 04\n") + indicator + "\n"
    assert terminal.composer_draft_reason(draft_screen, "Review shard 04") == expected_reason


def test_guarded_paste_and_submit_succeeds_on_valid_idle_then_current_draft(tmp_path):
    draft = "Review shard 04 and write structured receipt"
    screens = iter(
        [
            EMPTY,
            EMPTY.replace("\n>\n", f"\n> {draft}\n"),
        ]
    )
    pasted = []
    submitted = []
    evidence = tmp_path / "paste-evidence.txt"

    result = terminal.guarded_paste_and_submit(
        read_screen=lambda: next(screens),
        send_paste=pasted.append,
        send_submit=lambda: submitted.append("Enter"),
        draft=draft,
        paste_evidence_path=evidence,
    )

    assert result == {
        "status": "submitted",
        "reason": None,
        "pasted": True,
        "submitted": True,
    }
    assert pasted == [draft]
    assert submitted == ["Enter"]
    assert evidence.read_text(encoding="utf-8") == draft


@pytest.mark.parametrize(
    "question_banner",
    [
        "Queued follow-up · ⇧← to answer",
        "QUESTION\nType your answer · Enter to submit answer",
        "request_user_input: waiting for human selection",
    ],
)
def test_guarded_paste_and_submit_blocks_when_question_arrives_after_paste(
    tmp_path, question_banner
):
    draft = "Review shard 04 and write structured receipt"
    # Even though the draft remains visible in the composer AND the paste-evidence
    # file was written, a question arriving between paste and submit must abort
    # before sending Enter (#677).
    screens = iter(
        [
            EMPTY,
            EMPTY.replace("\n>\n", f"\n> {draft}\n") + question_banner + "\n",
        ]
    )
    pasted = []
    submitted = []
    evidence = tmp_path / "paste-evidence.txt"

    result = terminal.guarded_paste_and_submit(
        read_screen=lambda: next(screens),
        send_paste=pasted.append,
        send_submit=lambda: submitted.append("Enter"),
        draft=draft,
        paste_evidence_path=evidence,
    )

    assert result == {
        "status": "blocked-before-submit",
        "reason": "queued-question",
        "pasted": True,
        "submitted": False,
    }
    assert pasted == [draft]
    assert submitted == []
    assert evidence.is_file()


def test_guarded_paste_and_submit_rejects_historical_text_when_current_composer_is_empty(
    tmp_path,
):
    draft = "Review shard 04 and write structured receipt"
    # Historical text above the current empty composer plus a paste-evidence file
    # on disk must not pass the pre-submit check (#677).
    screens = iter(
        [
            EMPTY,
            f"Earlier output: {draft}\n" + EMPTY,
        ]
    )
    pasted = []
    submitted = []
    evidence = tmp_path / "paste-evidence.txt"

    result = terminal.guarded_paste_and_submit(
        read_screen=lambda: next(screens),
        send_paste=pasted.append,
        send_submit=lambda: submitted.append("Enter"),
        draft=draft,
        paste_evidence_path=evidence,
    )

    assert result["status"] == "blocked-before-submit"
    assert result["submitted"] is False
    assert pasted == [draft]
    assert submitted == []


def test_guarded_paste_and_submit_refuses_symlink_evidence_and_failed_paste(tmp_path):
    """#1136: symlinked paste_evidence_path and failed send_paste abort before submit."""
    draft = "Review shard 04 and write structured receipt"
    target_file = tmp_path / "real.txt"
    target_file.write_text("original", encoding="utf-8")
    symlink_evidence = tmp_path / "symlink.txt"
    symlink_evidence.symlink_to(target_file)

    symlink_result = terminal.guarded_paste_and_submit(
        read_screen=lambda: EMPTY,
        send_paste=lambda _: True,
        send_submit=lambda: None,
        draft=draft,
        paste_evidence_path=symlink_evidence,
    )
    assert symlink_result == {
        "status": "blocked-before-paste",
        "reason": "symlink-paste-evidence-path",
        "pasted": False,
        "submitted": False,
    }
    assert target_file.read_text(encoding="utf-8") == "original"

    failed_paste = terminal.guarded_paste_and_submit(
        read_screen=lambda: EMPTY,
        send_paste=lambda _: False,
        send_submit=lambda: None,
        draft=draft,
        paste_evidence_path=tmp_path / "evidence.txt",
    )
    assert failed_paste == {
        "status": "paste-failed",
        "reason": "paste-transport-failed",
        "pasted": False,
        "submitted": False,
    }
    assert not (tmp_path / "evidence.txt").exists()

