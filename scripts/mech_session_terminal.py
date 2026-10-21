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
    if re.search(r"↑/↓\s*Navigate|(?:Accept|Allow|Run)[^\n]*\?", tail, re.I):
        return "approval-menu"
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
