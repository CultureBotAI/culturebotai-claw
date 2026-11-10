#!/usr/bin/env python3
"""Read-only macOS Terminal adapter for the Mech session supervisor.

Importing this module performs no discovery, messaging, or approval handling.
The supervisor supplies its own guarded send script to ``jxa`` only in apply
mode. These readers intentionally reject unfamiliar process and composer shapes.
"""
import json
import re
import subprocess
from pathlib import Path

TAIL_CHARS = 64000

# Canonical blocked-state vocabulary shared across Terminal/agy/Codex input
# guards (#677, #725): rejects sign-in, trust, update, approval, and queued
# human question / request_user_input states before any paste or submit.
BLOCKED_PROMPT_RE = re.compile(
    r"Sign in with|authentication required|Log in to continue|Select (?:a )?login|not signed in|"
    r"Trust this folder|Do you trust|trust the (?:files|contents)|"
    r"Update available|Skip until next version|Update now|"
    r"approval request|Allow command|Requesting permission|Do you want to|"
    r"Allow sandbox bypass|Confirm the command is safe|Would you like to|"
    r"Allow access to this file\?|Run this command\?|Accept changes\?|"
    r"ctrl\+k\s+approve|needs approval for|↑/↓\s*Navigate|"
    r"Queued follow-up|⇧← to answer|request_user_input|"
    r"^\s*(?:Question|Questions|QUESTION)\b|Type your answer|to submit answer|"
    r"to navigate questions|Select Model|Select Reasoning|"
    r"How['’]s the CLI experience|^\s*\[0\]\s+Skip\b|^\s*\?\s+(?:Which|.*question)|"
    r"^\s*(?:Select|Choose) (?:an? option|one of the following)|"
    r"^\s*[›❯>]?\s*\d+[.)]\s+(?:Yes|No|Allow|Deny|Approve|Reject|Cancel)\b",
    re.I | re.M,
)

QUEUED_QUESTION_RE = re.compile(
    r"Queued follow-up|⇧← to answer|request_user_input|"
    r"^\s*(?:Question|Questions|QUESTION)\b|Type your answer|to submit answer|"
    r"to navigate questions",
    re.I | re.M,
)

SNAPSHOT_JS = r'''
function run(argv) {
    const TAIL_CHARS = 64000;
    function currentTail(tab) {
        let raw = '';
        try {
            if (typeof tab.history === 'function') raw = String(tab.history() || '');
        } catch (error) { raw = ''; }
        if (!raw) raw = String(tab.contents() || '');
        return raw.length > TAIL_CHARS ? raw.slice(-TAIL_CHARS) : raw;
    }
    const allowed = JSON.parse(argv[0]);
    const terminal = Application('Terminal');
    const tabs = [], warnings = [];
    for (const win of terminal.windows()) {
        let wid = null;
        try {
            wid = win.id();
            const children = win.tabs();
            for (let index = 0; index < children.length; index++) {
                try {
                    const tab = children[index], tty = tab.tty();
                    if (allowed.includes(tty))
                        tabs.push({window: wid, tab: index + 1, tty,
                                   screen: currentTail(tab)});
                } catch (error) { warnings.push(String(error)); }
            }
        } catch (error) { warnings.push(String(error)); }
    }
    return JSON.stringify({tabs, warnings});
}
'''


def command(args, timeout=10):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} exited {result.returncode}: {result.stderr.strip()[:300]}"
        )
    return result.stdout


def jxa(source, value):
    return command(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", source, json.dumps(value)],
        timeout=20,
    ).strip()


def process_record(line):
    parts = line.strip().split(None, 7)
    if (len(parts) != 8 or parts[7] != "agy" or not parts[0].isdigit()
            or int(parts[0]) <= 0 or not re.fullmatch(r"ttys\d+", parts[1])):
        return None
    return {
        "pid": int(parts[0]),
        "tty": "/dev/" + parts[1],
        "identity": line.strip(),
        "started": " ".join(parts[2:7]),
    }


def checked_pid(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError("PID must be a positive integer")
    return str(pid)


def live_process(pid):
    return process_record(command([
        "/bin/ps", "-p", checked_pid(pid), "-o", "pid=,tty=,lstart=,comm=",
    ]).strip())


def process_cwd(pid):
    result = command([
        "/usr/sbin/lsof", "-a", "-p", checked_pid(pid), "-d", "cwd", "-Fn",
    ])
    paths = [line[1:] for line in result.splitlines() if line.startswith("n")]
    if len(paths) != 1:
        raise RuntimeError("current working directory unavailable or ambiguous")
    return Path(paths[0]).resolve()


def foreground(pid, tty):
    if not re.fullmatch(r"/dev/ttys\d+", tty):
        return False
    groups = command([
        "/bin/ps", "-p", checked_pid(pid), "-o", "pgid=,tpgid=",
    ]).split()
    return len(groups) == 2 and groups[0].isdigit() and groups[0] == groups[1]


def composer_reason(screen):
    """Accept only an empty, familiar composer; busy checks live in supervisor."""
    lines = [line.rstrip() for line in screen.replace("\r", "").splitlines()]
    # This documented startup announcement needs no response. Accept its one
    # known two-line shape without broadening generic prompt/menu recognition
    # and without sending Escape (or any other input) to dismiss it.
    announcement_lines: set[int] = set()
    for i in range(len(lines) - 1, 0, -1):
        if (lines[i].strip(" │┃").lower() == "esc to dismiss"
                and re.fullmatch(r"Meet Gemini 4 Argon[^?\n]{0,300}", lines[i - 1].strip(" │┃"))):
            announcement_lines.update((i - 1, i))
    lines = [line for index, line in enumerate(lines) if index not in announcement_lines]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return "empty-screen"
    candidates = [i for i, line in enumerate(lines) if line.strip() == ">"]
    if not candidates:
        return "no-empty-composer"
    index = candidates[-1]
    tail = "\n".join(lines[index:])
    if index < 1 or len(lines) - index > 9:
        return "composer-too-far-from-footer"
    border = r"[─━═\-┌┐└┘│┃╭╮╰╯ ]+"
    if (not re.fullmatch(border, lines[index - 1]) or index + 1 >= len(lines)
            or not re.fullmatch(border, lines[index + 1])):
        return "missing-composer-borders"
    prompt = active_prompt_reason(tail)
    if prompt is not None:
        return prompt
    if not re.search(r"Gemini\s+\S", tail):
        return "unrecognized-footer"
    for line in lines[index + 1:]:
        text = line.strip()
        if not text or re.fullmatch(border, text):
            continue
        if ("Gemini " in text
                or re.fullmatch(r"● \[\d{2}:\d{2}:\d{2}\] .+ running", text)
                or re.search(
                    r"(?:\?\s+for\s+(?:shortcuts|help)|tab\s+to\s+accept|"
                    r"shift\+tab|ctrl\+\w|background task|/tasks)", text, re.I
                )):
            continue
        return "unrecognized-composer-tail"
    return None


def active_prompt_reason(text):
    """Return a blocked-state reason when an active prompt or queued question is visible (#677)."""
    if QUEUED_QUESTION_RE.search(text):
        return "queued-question"
    if re.search(
        r"Sign in with|authentication required|Log in to continue|Select (?:a )?login|not signed in",
        text,
        re.I,
    ):
        return "sign-in-prompt"
    if re.search(r"Trust this folder|Do you trust|trust the (?:files|contents)", text, re.I):
        return "trust-prompt"
    if re.search(r"Update available|Skip until next version|Update now", text, re.I):
        return "update-prompt"
    if BLOCKED_PROMPT_RE.search(text):
        return "approval-menu"
    return None


def _active_composer_window(screen):
    lines = [line.rstrip() for line in (screen or "").replace("\r", "").splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def verify_paste_ready(screen):
    """Verify a fresh screen has an idle empty composer and no active prompt/question (#677)."""
    lines = _active_composer_window(screen)
    if not lines:
        return "empty-screen"
    window = "\n".join(lines[-16:])
    prompt = active_prompt_reason(window)
    if prompt is not None:
        return prompt
    border = r"[─━═\-┌┐└┘│┃╭╮╰╯ ]+"
    candidates = [
        i for i, line in enumerate(lines)
        if line.strip() in {">", "›"} and len(lines) - i <= 9
    ]
    if not candidates:
        return "no-empty-composer"
    index = candidates[-1]
    if index < 1 or index + 1 >= len(lines):
        return "missing-composer-borders"
    if not re.fullmatch(border, lines[index - 1]) or not re.fullmatch(border, lines[index + 1]):
        return "missing-composer-borders"
    return None


def composer_draft_reason(screen, expected_draft):
    """Verify the current bottom composer holds ``expected_draft`` with no active prompt (#677).

    Historical viewport text above the active composer borders or a paste-evidence
    file on disk is never sufficient proof that the current composer still holds
    the intended draft.
    """
    expected = "\n".join(
        line.rstrip() for line in (expected_draft or "").replace("\r", "").splitlines()
    ).strip()
    if not expected:
        return "empty-expected-draft"
    lines = _active_composer_window(screen)
    if not lines:
        return "empty-screen"
    window = "\n".join(lines[-16:])
    prompt = active_prompt_reason(window)
    if prompt is not None:
        return prompt
    border = r"[─━═\-┌┐└┘│┃╭╮╰╯ ]+"
    border_indices = [i for i, line in enumerate(lines) if re.fullmatch(border, line) and line.strip()]
    if len(border_indices) < 2:
        return "missing-composer-borders"
    top_border, bottom_border = border_indices[-2], border_indices[-1]
    if bottom_border <= top_border + 1 or len(lines) - bottom_border > 9:
        return "composer-too-far-from-footer"
    tail = "\n".join(lines[bottom_border:])
    prompt_after = active_prompt_reason(tail)
    if prompt_after is not None:
        return prompt_after
    raw_composer = lines[top_border + 1 : bottom_border]
    normalized_lines = []
    for idx, line in enumerate(raw_composer):
        stripped = line.strip()
        if idx == 0:
            if stripped in {">", "›"}:
                continue
            for prefix in ("> ", "› ", ">", "›"):
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix) :].strip()
                    break
            else:
                return "no-composer-prompt-prefix"
        normalized_lines.append(stripped)
    current_draft = "\n".join(normalized_lines).strip()
    if current_draft != expected:
        return "composer-draft-mismatch"
    return None


def guarded_paste_and_submit(
    *,
    read_screen,
    send_paste,
    send_submit,
    draft,
    paste_evidence_path=None,
):
    """Canonical two-phase terminal input guard (#677).

    Reads a fresh screen immediately before paste and a second fresh screen
    immediately before submit. Fails closed without sending Enter if a queued
    human question (`⇧← to answer`, `Queued follow-up`, `QUESTION`,
    `request_user_input`) or any other blocked state arrives between paste and
    submit, or if the current bottom composer does not hold ``draft``.
    """
    pre_paste_screen = read_screen()
    paste_reason = verify_paste_ready(pre_paste_screen)
    if paste_reason is not None:
        return {
            "status": "blocked-before-paste",
            "reason": paste_reason,
            "pasted": False,
            "submitted": False,
        }
    send_paste(draft)
    if paste_evidence_path is not None:
        Path(paste_evidence_path).write_text(draft, encoding="utf-8")
    pre_submit_screen = read_screen()
    submit_reason = composer_draft_reason(pre_submit_screen, draft)
    if submit_reason is not None:
        return {
            "status": "blocked-before-submit",
            "reason": submit_reason,
            "pasted": True,
            "submitted": False,
        }
    send_submit()
    return {
        "status": "submitted",
        "reason": None,
        "pasted": True,
        "submitted": True,
    }

