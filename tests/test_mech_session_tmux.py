"""Read-only tmux identity tests: no live processes, panes, or native stores."""
import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "mech_session_tmux", Path(os.environ.get("MECH_TMUX_OBSERVER_SOURCE",
                        Path(__file__).parents[1] / "scripts/mech_session_tmux.py"))
)
tmux = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tmux)

THREAD = "00000000-0000-0000-0000-000000000001"
ROLLOUT = f"/private/example/sessions/rollout-example-{THREAD}.jsonl"
ROOT = "/private/example/ExampleMech"
STARTED = "Mon Nov 2 10:00:00 2026"
SCREEN = "A completed response\n\n› Ask Codex to do anything\n\n  GPT-6 Example · folder\n  ? for shortcuts\n"


def record(pid, parent, tty, comm):
    return {"pid": pid, "ppid": parent, "tty": tty, "started": STARTED, "comm": comm}


def binding():
    return {
        "key": "examplemech", "transport": "tmux", "root": ROOT,
        "tmux": {"executable": "/usr/local/bin/tmux", "socket": "/private/example/mech-fleet",
                 "socket_identity": {"device": 1, "inode": 2}},
        "pane": {"session": "ExampleMech", "session_id": "$1", "window_id": "@2", "pane_id": "%3",
                 "pid": 102, "tty": "/dev/ttys005"},
        "server_process": record(100, 1, "/dev/??", "tmux"),
        "pane_process": record(102, 100, "/dev/ttys005", "/bin/bash"),
        "native_process": record(104, 102, "/dev/ttys005", "/example/bin/codex"),
        "native": {"mode": "embedded", "thread_id": THREAD, "rollout_path": ROLLOUT},
    }


class Reader:
    def __init__(self):
        self.calls = []
        self.capture = SCREEN
        self.rows = {item["pid"]: item for item in (
            binding()["server_process"], binding()["pane_process"], binding()["native_process"])}
        self.endpoint = "100\tExampleMech\t$1\t@2\t%3\t102\t/dev/ttys005\t0\n"
        self.parents = "100 1\n102 100\n104 102\n"
        self.root = ROOT
        self.opened = "p104\nn" + ROLLOUT + "\n"
        self.after_capture = None

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "/usr/local/bin/tmux":
            assert args[1:4] == ["-N", "-S", "/private/example/mech-fleet"]
            assert args[4] in {"list-panes", "capture-pane"}, "observer issued a mutation"
            if args[4] == "list-panes":
                assert args[5:] == ["-s", "-t", "=ExampleMech", "-F", tmux.FORMAT]
                return self.endpoint
            assert args[5:] == ["-p", "-t", "%3"]
            if self.after_capture:
                self.after_capture(self)
            return self.capture
        if args == ["/bin/ps", "-ax", "-o", "pid=,ppid="]:
            return self.parents
        if args[:2] == ["/bin/ps", "-p"]:
            item = self.rows[int(args[2])]
            assert args[3:] == ["-o", "pid=,ppid=,tty=,lstart=,comm="]
            return f'{item["pid"]} {item["ppid"]} {item["tty"].removeprefix("/dev/")} {item["started"]} {item["comm"]}\n'
        if args == ["/usr/sbin/lsof", "-a", "-p", "104", "-d", "cwd", "-Fn"]:
            return "p104\nn" + self.root + "\n"
        if args == ["/usr/sbin/lsof", "-a", "-p", "104", "-Fn"]:
            return self.opened
        raise AssertionError(f"Unexpected command {args!r}")


def socket(_path):
    return {"device": 1, "inode": 2}


def header(path):
    assert path == ROLLOUT
    return {"id": THREAD, "cwd": ROOT, "source": "cli"}


def observe(item=None, reader=None, stat_socket=socket, header_reader=header):
    return tmux.observe_binding(item or binding(), reader or Reader(), stat_socket, header_reader)


def test_detached_pane_verified_without_terminal_view_or_raw_screen():
    reader = Reader()
    result = observe(reader=reader)
    assert result["binding"] == "live"
    assert result["state"] == "empty_composer_visible"
    assert result["native"]["state"] == "verified"
    assert result["no_input"] is True
    assert "A completed response" not in json.dumps(result)
    assert not any("osascript" in arg for call in reader.calls for arg in call)
    assert len([call for call in reader.calls if "list-panes" in call]) == 2


def test_missing_viewer_does_not_veto_valid_native_pane():
    item = binding()
    item["viewer"] = {"window": 999999, "tty": "/dev/ttys999", "state": "closed"}
    assert observe(item)["binding"] == "live"


@pytest.mark.parametrize("field,value", [("session_id", "$4"),
                                         ("window_id", "@4"), ("pid", 999), ("tty", "/dev/ttys099")])
def test_exact_endpoint_mismatch_is_not_followed(field, value):
    item = binding()
    item["pane"][field] = value
    if field == "pid":
        item["pane_process"]["pid"] = value
    if field == "tty":
        item["native_process"]["tty"] = value
    reader = Reader()
    assert observe(item, reader)["binding"] == "stale_or_unverified"
    assert not any("capture-pane" in call for call in reader.calls)


@pytest.mark.parametrize("field", ["server_process", "pane_process", "native_process"])
def test_pid_reuse_with_new_start_is_stale(field):
    item = binding()
    item[field]["started"] = "Tue Nov 3 10:00:00 2026"
    assert observe(item)["binding"] == "stale_or_unverified"


def test_same_tty_unrelated_native_process_is_not_pane_ownership():
    reader = Reader()
    reader.parents = "100 1\n102 100\n104 1\n"
    assert observe(reader=reader)["reason"] == "native process is not in the pinned pane"


def test_native_cwd_not_tmux_server_or_viewer_cwd_is_authoritative():
    reader = Reader()
    reader.root = "/private/example/OtherMech"
    assert observe(reader=reader)["reason"] == "native cwd changed"


def test_dead_pane_is_not_live_even_when_native_pid_survives():
    reader = Reader()
    reader.endpoint = reader.endpoint.rstrip().rsplit("\t", 1)[0] + "\t1\n"
    assert observe(reader=reader)["reason"] == "pane is dead"


def test_linked_viewer_context_does_not_replace_owned_session_membership():
    reader = Reader()
    # display-message by pane alone would select a different linked session;
    # this fixture accepts only exact-session membership inventory instead.
    reader.endpoint += "100\tExampleMech\t$1\t@4\t%9\t109\t/dev/ttys009\t0\n"
    assert observe(reader=reader)["binding"] == "live"
    assert all("display-message" not in call for call in reader.calls)


def test_pane_still_existing_elsewhere_does_not_prove_owned_session_membership():
    reader = Reader()
    reader.endpoint = "100\tExampleMech\t$1\t@4\t%9\t109\t/dev/ttys009\t0\n"
    assert observe(reader=reader)["reason"] == "pane missing or ambiguous in owned session"


def test_replaced_socket_never_falls_back_to_default_server():
    reader = Reader()
    result = observe(reader=reader, stat_socket=lambda _path: {"device": 1, "inode": 9})
    assert result["reason"] == "socket replaced"
    assert reader.calls == []


@pytest.mark.parametrize("change", [
    lambda reader: setattr(reader, "endpoint", reader.endpoint.replace("$1", "$9")),
    lambda reader: reader.rows[104].update(started="Tue Nov 3 10:00:00 2026"),
    lambda reader: setattr(reader, "root", "/private/example/OtherMech"),
])
def test_identity_rechecked_after_capture(change):
    reader = Reader()
    reader.after_capture = change
    result = observe(reader=reader)
    assert result["binding"] == "stale_or_unverified"
    assert result["native"]["state"] == "unknown"
    assert "screen_sha256" not in result


def test_managed_thread_is_transport_live_but_not_false_native_fd_proof():
    item = binding()
    item["native"]["mode"] = "managed"
    reader = Reader()
    result = observe(item, reader)
    assert result["binding"] == "live"
    assert result["native"]["state"] == "unknown"
    assert result["native"]["expected_thread_id"] == THREAD
    assert not any(call[-1] == "-Fn" and "cwd" not in call for call in reader.calls)


@pytest.mark.parametrize("change", [
    {"id": "00000000-0000-0000-0000-000000000099"}, {"cwd": "/wrong"},
    {"thread_source": {"subagent": "spawn"}}, {"source": "unknown"},
])
def test_foreign_native_metadata_remains_unknown(change):
    result = observe(header_reader=lambda path: {**header(path), **change})
    assert result["binding"] == "live"
    assert result["native"]["state"] == "unknown"


@pytest.mark.parametrize("starts_expected", [True, False])
def test_native_thread_switch_during_capture_never_becomes_verified(starts_expected):
    reader = Reader()
    state = {"expected": starts_expected}
    reader.after_capture = lambda _reader: state.update(expected=not starts_expected)

    def changing_header(path):
        value = header(path)
        if not state["expected"]:
            value["id"] = "00000000-0000-0000-0000-000000000099"
        return value

    result = observe(reader=reader, header_reader=changing_header)
    assert result["binding"] == "live"
    assert result["native"] == {"state": "unknown", "reason": "native identity changed during capture"}


def test_resumed_desktop_origin_primary_thread_requires_same_owned_metadata():
    result = observe(header_reader=lambda path: {**header(path), "source": "vscode"})
    assert result["native"]["state"] == "verified"


def test_second_primary_log_is_ambiguous_even_when_expected_log_is_open():
    reader = Reader()
    other = "/private/example/rollout-other.jsonl"
    reader.opened += "n" + other + "\n"
    result = observe(reader=reader, header_reader=lambda _path: header(ROLLOUT))
    assert result["native"]["state"] == "unknown"


@pytest.mark.parametrize("screen,expected", [
    (SCREEN, "empty_composer_visible"),
    (SCREEN.replace("Ask Codex to do anything", "unsubmitted user draft"), "draft_or_unknown"),
    (SCREEN.replace("\n\n  GPT", "\ncontinuation draft\n  GPT"), "draft_or_unknown"),
    (SCREEN + "Goal stalled\n", "Goal stalled"),
    (SCREEN + "Goal achieved\n", "Goal achieved"),
    (SCREEN + "Pursuing goal\n", "Pursuing goal"),
    (SCREEN + "Working (5s • esc to interrupt)\n", "working_visible"),
    (SCREEN + "1 background terminal running\n", "working_visible"),
    (SCREEN + "QUESTION: choose a scope\n", "prompt_or_question"),
    (SCREEN + "request_user_input\n", "question"),
    (SCREEN + "Do you want to run this?\n", "prompt_or_question"),
    ("This conversation is open in another app", "thread_locked"),
    ("", "unknown"),
])
def test_screen_states_do_not_authorize_completion_or_dispatch(screen, expected):
    assert tmux.screen_state(screen) == expected


@pytest.mark.parametrize("mutate", [
    lambda item: item["pane"].update(pane_id="%3; send-keys"),
    lambda item: item["tmux"].update(socket="relative"),
    lambda item: item["tmux"].update(socket_identity=[]),
    lambda item: item["native_process"].update(pid=True),
    lambda item: item["native"].update(thread_id="not-a-uuid"),
    lambda item: item["native"].update(rollout_path="/wrong/rollout-other.jsonl"),
    lambda item: item["tmux"].update(executable="/bin/sh"),
])
def test_malformed_binding_never_runs_commands(mutate):
    item = binding()
    mutate(item)
    reader = Reader()
    with pytest.raises(tmux.ObservationError):
        observe(item, reader)
    assert reader.calls == []


def test_inspect_emits_candidate_with_pinned_server_and_native_processes():
    reader = Reader()
    result = tmux.inspect_binding("examplemech", "/usr/local/bin/tmux", "/private/example/mech-fleet",
                                  "ExampleMech", "%3", 104, ROOT, binding()["native"], reader, socket)
    assert result == binding()


def test_registry_rejects_duplicate_endpoint_before_observation():
    other = copy.deepcopy(binding())
    other["key"] = "different-key"
    reader = Reader()
    with pytest.raises(tmux.ObservationError, match="duplicate"):
        tmux.observe_registry({"schema_version": 1, "role": "observer_only", "targets": [binding(), other]}, reader)
    assert reader.calls == []


def test_real_header_reader_refuses_symlink_and_retains_only_metadata(tmp_path):
    path = tmp_path / "metadata.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "payload": header(ROLLOUT)}) + "\nprivate later transcript\n")
    assert tmux.read_header(path) == header(ROLLOUT)
    link = tmp_path / "link.jsonl"
    link.symlink_to(path)
    with pytest.raises(OSError):
        tmux.read_header(link)


def test_bad_registry_cli_returns_nonzero_without_writing(tmp_path, capsys):
    path = tmp_path / "registry.json"
    path.write_text('{"schema_version": true, "role": "observer_only", "targets": []}')
    before = path.read_bytes()
    assert tmux.main(["observe", "--registry", str(path)]) == 1
    assert path.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["no_input"] is True


@pytest.mark.parametrize("reader", ["registry", "header"])
@pytest.mark.parametrize("kind", ["fifo", "symlink", "regular"])
def test_file_readers_reject_special_files_without_blocking(tmp_path, reader, kind):
    path = tmp_path / "input.json"
    value = {"type": "session_meta", "payload": header(ROLLOUT)} if reader == "header" else {"hello": "world"}
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "symlink":
        target = tmp_path / "real.json"
        target.write_text(json.dumps(value) + "\n")
        path.symlink_to(target)
    else:
        path.write_text(json.dumps(value) + "\n")
    # A fresh bounded process detects blocking at open(), before regular-file
    # validation; a thread timeout would leave a blocked reader behind.
    result = subprocess.run([sys.executable, __file__, reader, str(path)],
                            text=True, capture_output=True, timeout=2)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["accepted"] is (kind == "regular")


if __name__ == "__main__":
    reader = tmux.read_header if sys.argv[1] == "header" else tmux.read_registry
    try:
        reader(Path(sys.argv[2]))
        print(json.dumps({"accepted": True}))
    except (OSError, tmux.ObservationError):
        print(json.dumps({"accepted": False}))
