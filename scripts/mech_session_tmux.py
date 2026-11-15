#!/usr/bin/env python3
"""Observe explicitly pinned local tmux sessions without sending input.

Inputs: an inspected binding or private registry. Output: private JSON, with
screen hashes/states rather than screen contents. No import-time discovery,
registry mutation, session creation, workflow adoption, or native-store writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "\t".join(("#{pid}", "#{session_name}", "#{session_id}", "#{window_id}",
                    "#{pane_id}", "#{pane_pid}", "#{pane_tty}", "#{pane_dead}"))
MAX_METADATA = 1024 * 1024
MAX_SCREEN = 256 * 1024
MAX_REGISTRY = 1024 * 1024
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")


class ObservationError(ValueError):
    """A binding could not be proved; callers must retain the hold."""


def require(condition, message):
    if not condition:
        raise ObservationError(message)


def absolute(value, label):
    require(isinstance(value, str) and value and "\x00" not in value, f"invalid {label}")
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts, f"absolute {label} required")
    return path


def positive(value, label):
    require(type(value) is int and value > 0, f"invalid {label}")
    return value


def run_read(args):
    """The adapter constructs every argv; there is no shell or write command."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("read command unavailable or timed out") from exc
    require(result.returncode == 0, "read command failed")
    require(len(result.stdout) <= 4 * 1024 * 1024, "read output exceeds bound")
    return result.stdout


def process_record(raw):
    parts = raw.strip().split(None, 8)
    require(len(parts) == 9 and parts[0].isdigit() and parts[1].isdigit(),
            "unreadable process identity")
    return {"pid": int(parts[0]), "ppid": int(parts[1]), "tty": "/dev/" + parts[2],
            "started": " ".join(parts[3:8]), "comm": parts[8]}


def process(pid, runner):
    positive(pid, "PID")
    return process_record(runner(["/bin/ps", "-p", str(pid), "-o",
                                  "pid=,ppid=,tty=,lstart=,comm="]))


def socket_identity(path):
    path = absolute(path, "socket")
    require(not path.is_symlink(), "symlinked socket refused")
    try:
        item = path.stat()
    except OSError as exc:
        raise ObservationError("socket unavailable") from exc
    require(stat.S_ISSOCK(item.st_mode), "not a Unix socket")
    require(item.st_uid == os.getuid(), "socket belongs to another user")
    return {"device": item.st_dev, "inode": item.st_ino}


def validate_binding(binding):
    require(isinstance(binding, dict) and binding.get("transport") == "tmux",
            "explicit tmux transport required")
    require(isinstance(binding.get("key"), str) and IDENTIFIER.fullmatch(binding["key"]),
            "invalid binding key")
    absolute(binding.get("root"), "repository root")
    tmux = binding.get("tmux", {})
    require(isinstance(tmux, dict), "invalid tmux endpoint")
    executable = absolute(tmux.get("executable"), "tmux executable")
    require(executable.name == "tmux", "tmux executable required")
    absolute(tmux.get("socket"), "socket")
    require(isinstance(tmux.get("socket_identity"), dict), "invalid socket identity")
    for field in ("device", "inode"):
        require(type(tmux.get("socket_identity", {}).get(field)) is int
                and tmux["socket_identity"][field] >= 0, "invalid socket identity")
    pane = binding.get("pane", {})
    require(isinstance(pane, dict) and isinstance(pane.get("session"), str)
            and IDENTIFIER.fullmatch(pane["session"]), "invalid exact session")
    for field, pattern in (("session_id", r"\$\d+"), ("window_id", r"@\d+"),
                           ("pane_id", r"%\d+")):
        require(isinstance(pane.get(field), str) and re.fullmatch(pattern, pane[field]),
                "invalid " + field)
    positive(pane.get("pid"), "pane PID")
    require(isinstance(pane.get("tty"), str) and re.fullmatch(r"/dev/ttys\d+", pane["tty"]),
            "macOS pane TTY required")
    for key in ("server_process", "pane_process", "native_process"):
        value = binding.get(key, {})
        require(isinstance(value, dict), "invalid " + key)
        positive(value.get("pid"), key + " PID")
        require(type(value.get("ppid")) is int and value["ppid"] >= 0
                and all(isinstance(value.get(k), str) and value[k]
                        for k in ("started", "comm", "tty")), "incomplete " + key)
    require(binding["pane_process"]["pid"] == pane["pid"], "pane process differs")
    require(binding["native_process"]["tty"] == pane["tty"], "native/pane TTY differs")
    require(Path(binding["native_process"]["comm"]).name in {"codex", "agy"},
            "unrecognized native executable")
    native = binding.get("native")
    if native is not None:
        require(isinstance(native, dict) and native.get("mode") in {"embedded", "managed"},
                "invalid native mode")
        require(Path(binding["native_process"]["comm"]).name == "codex", "Codex native metadata required")
        require(isinstance(native.get("thread_id"), str) and UUID.fullmatch(native["thread_id"]),
                "invalid native thread")
        if native.get("rollout_path") is not None:
            path = absolute(native["rollout_path"], "rollout path")
            require(path.name.startswith("rollout-") and path.name.endswith(native["thread_id"] + ".jsonl"),
                    "rollout filename differs from thread")
        require(native["mode"] == "managed" or native.get("rollout_path"),
                "embedded thread requires rollout path")
    # An optional viewer is informational only: it cannot prove or veto a pane.
    return binding


def tmux_argv(binding, *args):
    return [binding["tmux"]["executable"], "-N", "-S", binding["tmux"]["socket"], *args]


def endpoint(binding, runner):
    # A pane linked into another session can acquire that viewer's default
    # display-message context. Verify membership in the exact owned session.
    raw = runner(tmux_argv(binding, "list-panes", "-s", "-t",
                           "=" + binding["pane"]["session"], "-F", FORMAT))
    matches = []
    for line in raw.splitlines():
        fields = line.split("\t")
        require(len(fields) == 8 and fields[0].isdigit() and fields[5].isdigit(),
                "unreadable tmux endpoint")
        if fields[4] == binding["pane"]["pane_id"]:
            matches.append(fields)
    require(len(matches) == 1, "pane missing or ambiguous in owned session")
    fields = matches[0]
    require(fields[7] == "0", "pane is dead")
    return {"server_pid": int(fields[0]), "session": fields[1], "session_id": fields[2],
            "window_id": fields[3], "pane_id": fields[4], "pid": int(fields[5]), "tty": fields[6]}


def cwd(pid, runner):
    paths = [line[1:] for line in runner(["/usr/sbin/lsof", "-a", "-p", str(pid),
                                        "-d", "cwd", "-Fn"]).splitlines() if line.startswith("n")]
    require(len(paths) == 1, "native cwd unavailable or ambiguous")
    return paths[0]


def descendant(native_pid, pane_pid, runner):
    raw = runner(["/bin/ps", "-ax", "-o", "pid=,ppid="])
    parents = {}
    for line in raw.splitlines():
        parts = line.split()
        require(len(parts) == 2 and all(p.isdigit() for p in parts), "unreadable process ancestry")
        require(int(parts[0]) not in parents, "duplicate process ancestry")
        parents[int(parts[0])] = int(parts[1])
    seen = set()
    while native_pid not in seen:
        if native_pid == pane_pid:
            return True
        seen.add(native_pid)
        native_pid = parents.get(native_pid, 0)
    return False


def verify_transport(binding, runner, stat_socket=socket_identity):
    require(stat_socket(binding["tmux"]["socket"]) == binding["tmux"]["socket_identity"],
            "socket replaced")
    found = endpoint(binding, runner)
    require(found == {**binding["pane"], "server_pid": binding["server_process"]["pid"]},
            "tmux endpoint changed")
    for field in ("server_process", "pane_process", "native_process"):
        require(process(binding[field]["pid"], runner) == binding[field], field + " changed")
    require(descendant(binding["native_process"]["pid"], binding["pane"]["pid"], runner),
            "native process is not in the pinned pane")
    require(cwd(binding["native_process"]["pid"], runner) == binding["root"], "native cwd changed")


def read_header(path):
    # Opening a FIFO read-only blocks before fstat; NONBLOCK is required even
    # though only regular files pass the descriptor check below.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "native metadata is not regular")
        raw = stream.readline(MAX_METADATA + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) <= MAX_METADATA and raw.endswith(b"\n"), "unbounded native metadata")
    require((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino), "native file changed")
    record = json.loads(raw)
    require(isinstance(record, dict) and record.get("type") == "session_meta"
            and isinstance(record.get("payload"), dict), "invalid native metadata")
    return record["payload"]


def read_registry(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "registry is not a regular file")
        require(before.st_size <= MAX_REGISTRY, "registry exceeds bound")
        raw = stream.read(MAX_REGISTRY + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) <= MAX_REGISTRY, "registry exceeds bound")
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "registry changed during read")
    return json.loads(raw)


def native_identity(binding, runner, header_reader=read_header):
    native = binding.get("native")
    if native is None:
        return {"state": "unknown", "reason": "native binding not supplied"}
    if native["mode"] == "managed":
        return {"state": "unknown", "reason": "shared daemon ownership needs separate native proof",
                "expected_thread_id": native["thread_id"]}
    try:
        opened = runner(["/usr/sbin/lsof", "-a", "-p", str(binding["native_process"]["pid"]), "-Fn"])
        paths = sorted({line[1:] for line in opened.splitlines() if line.startswith("n")
                        and Path(line[1:]).name.startswith("rollout-") and line.endswith(".jsonl")})
        require(native["rollout_path"] in paths and len(paths) <= 16, "rollout not owned by native process")
        primary = []
        for path in paths:
            meta = header_reader(path)
            if meta.get("source") in ("cli", "vscode") and meta.get("thread_source") in (None, "user"):
                primary.append((path, meta))
        require(len(primary) == 1 and primary[0][0] == native["rollout_path"], "ambiguous primary thread")
        meta = primary[0][1]
        require(meta.get("id") == native["thread_id"] and meta.get("cwd") == binding["root"],
                "native metadata identity differs")
        return {"state": "verified", "thread_id": native["thread_id"], "proof": "native-owned primary rollout metadata"}
    except (ObservationError, OSError, ValueError, TypeError):
        return {"state": "unknown", "reason": "native ownership or metadata unproved"}


def screen_state(screen):
    """Describe visible state only; an empty composer never proves task completion."""
    lines = screen.replace("\r", "").splitlines()
    tail = "\n".join(lines[-16:])
    for phrase, state in (("conversation is open in another app", "thread_locked"),
                          ("Trust this folder", "trust_prompt"), ("Sign in", "sign_in"),
                          ("Update available", "update_prompt"), ("request_user_input", "question"),
                          ("Queued follow-up", "question"), ("needs your approval", "approval")):
        if phrase.casefold() in tail.casefold():
            return state
    for state in ("Goal paused", "Goal stalled", "Goal hit usage limits", "Goal achieved", "Pursuing goal"):
        if state in tail:
            return state
    if "esc to interrupt" in tail or re.search(r"Working \(|background terminal.*running", tail, re.I):
        return "working_visible"
    if re.search(r"(?:Do you want to|Would you like to|Allow command|Run this command\?|^\s*Questions?\b)", tail, re.I | re.M):
        return "prompt_or_question"
    candidates = [index for index, line in enumerate(lines) if re.match(r"^\s*[›»](?:\s|$)", line)]
    if candidates:
        index = candidates[-1]
        if len(lines) - index > 9:
            return "unknown"
        content = re.sub(r"^\s*[›»]\s*", "", lines[index]).strip()
        remainder = [line.strip() for line in lines[index + 1:] if line.strip()]
        if content in {"", "Ask Codex to do anything"} and remainder and re.match(r"(?:GPT-|gpt-)", remainder[0]):
            return "empty_composer_visible"
        return "draft_or_unknown"
    return "unknown"


def observe_binding(binding, runner=run_read, stat_socket=socket_identity, header_reader=read_header):
    validate_binding(binding)
    result = {"key": binding["key"], "transport": "tmux", "binding": "unknown",
              "state": "unknown", "native": {"state": "unknown"}, "no_input": True}
    try:
        verify_transport(binding, runner, stat_socket)
        native_before = native_identity(binding, runner, header_reader)
        screen = runner(tmux_argv(binding, "capture-pane", "-p", "-t", binding["pane"]["pane_id"]))
        require(len(screen.encode()) <= MAX_SCREEN, "screen exceeds bound")
        native = native_identity(binding, runner, header_reader)
        if native != native_before:
            native = {"state": "unknown", "reason": "native identity changed during capture"}
        verify_transport(binding, runner, stat_socket)
        result.update(binding="live", state=screen_state(screen), native=native,
                      screen_sha256=hashlib.sha256(screen.encode()).hexdigest(),
                      screen_characters=len(screen))
    except (ObservationError, OSError, ValueError) as exc:
        result.update(binding="stale_or_unverified", reason=str(exc))
    return result


def inspect_binding(key, executable, socket, session, pane_id, native_pid, root, native=None,
                    runner=run_read, stat_socket=socket_identity):
    """Emit a candidate pin for review, without adopting it into any registry."""
    require(isinstance(key, str) and IDENTIFIER.fullmatch(key), "invalid key")
    require(isinstance(session, str) and IDENTIFIER.fullmatch(session), "invalid session")
    require(isinstance(pane_id, str) and re.fullmatch(r"%\d+", pane_id), "invalid pane")
    require(absolute(executable, "tmux executable").name == "tmux", "tmux executable required")
    absolute(socket, "socket")
    absolute(root, "repository root")
    positive(native_pid, "native PID")
    binding = {"key": key, "transport": "tmux", "root": root,
               "tmux": {"executable": executable, "socket": socket, "socket_identity": stat_socket(socket)},
               "pane": {"session": session, "pane_id": pane_id}}
    found = endpoint(binding, runner)
    require(found["session"] == session, "pane belongs to another session")
    binding["pane"] = {k: v for k, v in found.items() if k != "server_pid"}
    binding["server_process"] = process(found["server_pid"], runner)
    binding["pane_process"] = process(found["pid"], runner)
    binding["native_process"] = process(native_pid, runner)
    if native is not None:
        binding["native"] = native
    validate_binding(binding)
    verify_transport(binding, runner, stat_socket)
    return binding


def observe_registry(data, runner=run_read):
    require(isinstance(data, dict) and type(data.get("schema_version")) is int and data.get("schema_version") == 1
            and data.get("role") == "observer_only", "invalid observation registry")
    targets = data.get("targets")
    require(isinstance(targets, list) and 1 <= len(targets) <= 64, "invalid target count")
    keys, endpoints = set(), set()
    for target in targets:
        validate_binding(target)
        endpoint_key = (target["tmux"]["socket"], target["pane"]["pane_id"])
        require(target["key"] not in keys and endpoint_key not in endpoints, "duplicate binding")
        keys.add(target["key"])
        endpoints.add(endpoint_key)
    rows = [observe_binding(target, runner) for target in targets]
    return {"schema_version": 1, "role": "observer_only", "observed_at": datetime.now(timezone.utc).isoformat(),
            "targets": rows, "no_input": True, "no_registry_or_workflow_writes": True,
            "counts": {"configured": len(rows), "live_transport_bindings": sum(row["binding"] == "live" for row in rows),
                       "verified_native_identities": sum(row["native"]["state"] == "verified" for row in rows)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="print a candidate pin; never adopt it")
    for option in ("key", "tmux", "socket", "session", "pane", "root"):
        inspect.add_argument("--" + option, required=True)
    inspect.add_argument("--pid", type=int, required=True)
    inspect.add_argument("--thread")
    inspect.add_argument("--rollout")
    inspect.add_argument("--native-mode", choices=("embedded", "managed"))
    observe = commands.add_parser("observe", help="print a private read-only snapshot")
    observe.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            require(bool(args.thread) == bool(args.native_mode), "thread and native mode must be supplied together")
            require(not args.rollout or args.thread, "rollout requires thread")
            native = {"thread_id": args.thread, "mode": args.native_mode} if args.thread else None
            if args.rollout:
                native["rollout_path"] = args.rollout
            data = inspect_binding(args.key, args.tmux, args.socket, args.session, args.pane,
                                   args.pid, args.root, native)
            result = {"candidate_only": True, "binding": data, "observation": observe_binding(data)}
            ok = result["observation"]["binding"] == "live"
        else:
            result = observe_registry(read_registry(args.registry))
            ok = result["counts"]["configured"] == result["counts"]["live_transport_bindings"]
        print(json.dumps(result, indent=2))
        return 0 if ok else 1
    except (ObservationError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "no_input": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
