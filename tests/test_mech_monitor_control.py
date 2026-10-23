"""Lifecycle tests use disposable Python children, never the live Mech monitors."""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "mech_monitor_control", Path(__file__).resolve().parents[1] / "scripts/mech_monitor_control.py"
)
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)

FAKE_MONITOR = '''\
import json, os, signal, sys, time
from pathlib import Path
status, stop, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
if mode == "exit":
    raise SystemExit(2)
running = True
def terminate(*args):
    global running
    if mode != "ignore":
        running = False
signal.signal(signal.SIGTERM, terminate)
while running and (mode == "ignore" or not stop.exists()):
    if mode != "silent":
        payload = {"pid": os.getpid(), "updated": time.time(), "running": True,
                   "active_sessions": 0, "readable_sessions": 0}
        temp = status.with_suffix(".tmp")
        temp.write_text(json.dumps(payload))
        temp.replace(status)
    time.sleep(0.02)
if mode != "silent":
    status.write_text(json.dumps({"pid": os.getpid(), "updated": time.time(), "running": False}))
'''


@pytest.fixture
def environment(tmp_path):
    root = tmp_path.resolve()
    source = root / "fake_monitor.py"
    source.write_text(FAKE_MONITOR)
    services = {}
    for name, kind in (("approvals", "approval"), ("supervisor", "supervisor")):
        directory = root / name
        directory.mkdir()
        targets = directory / "targets.json"
        targets.write_text("[]")
        services[name] = {
            "kind": kind,
            "argv": [str(Path(sys.executable).resolve()), str(source), str(directory / "status.json"),
                     str(directory / "STOP"), "normal"],
            "cwd": str(root), "stop_file": str(directory / "STOP"),
            "status_file": str(directory / "status.json"), "log_file": str(directory / "monitor.log"),
            "session_targets_file": str(targets),
            "source_sha256": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
        }
    manifest = {"version": 1, "state_dir": str(root / "state"), "services": services}
    config = root / "config.json"
    config.write_text(json.dumps(manifest))
    controllers = []

    def make(timeout=4, bindings=True):
        controller = control.Controller(control.load_manifest(config), timeout)
        if bindings:
            controller.bindings = lambda name, table: {
                "configured": 1, "live": 1, "stale": 0, "state": "bound-sessions-live"
            }
        controllers.append(controller)
        return controller

    yield {"root": root, "manifest": manifest, "config": config, "make": make, "source": source}
    # Cleanup only the Popen handles created by this fixture, never process-name
    # searches or real monitor state. Ignore-mode children deliberately need kill.
    for controller in controllers:
        for child in controller.children.values():
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=1)


def save_config(environment):
    environment["config"].write_text(json.dumps(environment["manifest"]))


def test_start_stop_restart_and_preserve_data(environment):
    controller = environment["make"]()
    sentinel = environment["root"] / "ledger.json"
    sentinel.write_text('{"completed_goals": 42}')
    stop = Path(environment["manifest"]["services"]["approvals"]["stop_file"])
    stop.write_text("previous stop")
    started = controller.run("start", ["approvals", "supervisor"])
    assert started["ok"], started
    pids = {row["service"]: row["pid"] for row in started["services"]}
    assert all(row["state"] == "running" for row in started["services"])
    assert started["services"][0]["monitoring"] == "no-live-sessions"
    assert not stop.exists()
    repeated = controller.run("start", ["approvals", "supervisor"])
    assert repeated["ok"]
    assert {row["service"]: row["pid"] for row in repeated["services"]} == pids
    restarted = controller.run("restart", ["approvals"])
    assert restarted["ok"], restarted
    assert restarted["services"][0]["pid"] != pids["approvals"]
    assert control.process_at(pids["supervisor"]) is not None
    stopped = controller.run("stop", ["approvals", "supervisor"])
    assert stopped["ok"], stopped
    assert all(row["state"] == "stopped" for row in stopped["services"])
    assert stop.exists()
    assert sentinel.read_text() == '{"completed_goals": 42}'
    assert controller.run("stop", ["approvals", "supervisor"])["ok"]
    events = [json.loads(line) for line in controller.events_path.read_text().splitlines()]
    assert any(item["event"] == "already-running" for item in events)
    assert all(item["event"] != "sigkill" for item in events)


def test_recover_and_stop_unregistered_exact_legacy_process(environment):
    launcher = environment["make"]()
    assert launcher.run("start", ["approvals"])["ok"]
    pid = next(iter(launcher.children))
    launcher.registry_path.unlink()  # Simulate a lost registry, not lost process.
    recovered = environment["make"]()
    result = recovered.run("start", ["approvals"])
    assert result["ok"] and result["services"][0]["pid"] == pid
    assert recovered.registry["services"]["approvals"]["source"] == "existing"
    assert recovered.run("stop", ["approvals"])["ok"]
    assert control.process_at(pid) is None


def test_start_failure_rolls_back_only_new_children(environment):
    controller = environment["make"](timeout=1)
    assert controller.run("start", ["approvals"])["ok"]
    approval_pid = controller.registry["services"]["approvals"]["pid"]
    controller.manifest["services"]["supervisor"]["argv"][-1] = "silent"
    result = controller.run("start", ["approvals", "supervisor"])
    assert not result["ok"]
    assert "heartbeat timed out" in result["errors"][0]
    assert control.process_at(approval_pid) is not None
    assert not Path(controller.manifest["services"]["approvals"]["stop_file"]).exists()
    supervisor_stop = Path(controller.manifest["services"]["supervisor"]["stop_file"])
    assert supervisor_stop.exists()
    supervisor_pid = controller.registry["services"]["supervisor"]["pid"]
    controller.children[supervisor_pid].wait(timeout=2)
    assert control.process_at(supervisor_pid) is None


def test_stop_timeout_does_not_force_kill(environment, monkeypatch):
    environment["manifest"]["services"]["approvals"]["argv"][-1] = "ignore"
    save_config(environment)
    controller = environment["make"](timeout=0.4)
    assert controller.run("start", ["approvals"])["ok"]
    seen = []
    original = os.kill

    def record(pid, sig):
        seen.append(sig)
        return original(pid, sig)

    monkeypatch.setattr(control.os, "kill", record)
    result = controller.run("stop", ["approvals"])
    assert not result["ok"]
    assert "no force kill" in result["errors"][0]
    assert seen == [signal.SIGTERM]
    assert result["services"][0]["state"] == "running"
    assert result["services"][0]["stop_requested"] is True


def test_stale_bindings_preflight_all_before_any_stop_clear(environment):
    controller = environment["make"](bindings=False)
    for spec in controller.manifest["services"].values():
        Path(spec["stop_file"]).write_text("preserve")
    result = controller.run("start", ["approvals", "supervisor"])
    assert not result["ok"]
    assert "no-live-bound-sessions" in result["errors"][0]
    assert not controller.children
    assert all(Path(spec["stop_file"]).read_text() == "preserve"
               for spec in controller.manifest["services"].values())


def test_invalid_second_binding_preflight_leaves_first_untouched(environment):
    controller = environment["make"]()
    controller.bindings = lambda name, table: {"state": "bound-sessions-live" if name == "approvals" else "stale-session-bindings"}
    stop = Path(controller.manifest["services"]["approvals"]["stop_file"])
    stop.write_text("preserve")
    result = controller.run("start", ["approvals", "supervisor"])
    assert not result["ok"] and not controller.children
    assert stop.read_text() == "preserve"


def test_source_drift_blocks_start_but_not_stop(environment):
    controller = environment["make"]()
    assert controller.run("start", ["approvals"])["ok"]
    environment["source"].write_text(FAKE_MONITOR + "\n# changed\n")
    assert not controller.run("start", ["approvals"])["ok"]
    assert controller.run("stop", ["approvals"])["ok"]


def test_stale_heartbeat_not_reported_as_working(environment):
    controller = environment["make"]()
    spec = controller.manifest["services"]["approvals"]
    proc = {"pid": 4321, "started": "Wed Oct 21 09:00:00 2026", "command": "fake"}
    status = Path(spec["status_file"])
    for payload in (
        {"pid": 4321, "updated": time.time() - 1000, "running": True},
        {"pid": 2222, "updated": time.time(), "running": True},
        {"pid": 4321, "updated": time.time(), "running": False},
    ):
        status.write_text(json.dumps(payload))
        assert not controller.heartbeat("approvals", proc)["fresh"]
    status.write_text(json.dumps({"pid": 4321, "updated_at": control.timestamp(), "running": True}))
    assert controller.heartbeat("approvals", proc)["fresh"]
    assert not controller.heartbeat("approvals", None)["fresh"]


def test_reused_pid_cannot_be_signaled_or_replaced(environment, monkeypatch):
    controller = environment["make"]()
    controller.state_dir.mkdir()
    old = {"pid": 777, "started": "old", "command": "owned", "signature": "hash"}
    control.atomic_json(controller.registry_path, {"version": 1, "services": {"approvals": old}})
    monkeypatch.setattr(control, "process_table", lambda: {777: {"pid": 777, "started": "new", "command": "unrelated"}})
    killed = []
    monkeypatch.setattr(control.os, "kill", lambda *args: killed.append(args))
    for action in ("stop", "start", "restart"):
        result = controller.run(action, ["approvals"])
        assert not result["ok"] and "reused" in result["errors"][0]
    assert not killed and not controller.children
    assert not Path(controller.manifest["services"]["approvals"]["stop_file"]).exists()


def test_duplicate_exact_matches_fail_closed(environment, monkeypatch):
    controller = environment["make"]()
    command = " ".join(controller.manifest["services"]["approvals"]["argv"])
    monkeypatch.setattr(control, "process_table", lambda: {
        pid: {"pid": pid, "started": "same", "command": command} for pid in (100, 200)
    })
    killed = []
    monkeypatch.setattr(control.os, "kill", lambda *args: killed.append(args))
    result = controller.run("stop", ["approvals"])
    assert not result["ok"] and "ambiguous" in result["errors"][0]
    assert not killed


def test_process_changes_between_preflight_and_signal(environment, monkeypatch):
    controller = environment["make"]()
    proc = {"pid": 1234, "started": "original", "command": "configured"}
    monkeypatch.setattr(controller, "identify", lambda name: {**proc, "started": "changed"})
    killed = []
    monkeypatch.setattr(control.os, "kill", lambda *args: killed.append(args))
    with pytest.raises(control.ControlError, match="changed before signal"):
        controller.verified_signal("approvals", proc)
    assert not killed


def test_exact_command_wrong_cwd_is_not_owned(environment, monkeypatch):
    controller = environment["make"]()
    command = " ".join(controller.manifest["services"]["approvals"]["argv"])
    proc = {"pid": 1234, "started": "original", "command": command}
    controller.registry = {"services": {}}
    monkeypatch.setattr(control, "exact_argv", lambda *args: True)
    monkeypatch.setattr(control, "process_cwd", lambda pid: "/unrelated")
    monkeypatch.setattr(control, "process_at", lambda pid: proc)
    with pytest.raises(control.ControlError, match="working directory"):
        controller.identify("approvals", {1234: proc})


def test_live_binding_requires_pid_start_tty_and_cwd(environment, monkeypatch):
    controller = environment["make"](bindings=False)
    spec = controller.manifest["services"]["approvals"]
    target_file = Path(spec["session_targets_file"])
    started = "Wed Oct 21 09:00:00 2026"
    identity = f"1234 ttys004 {started} agy"
    target = {"pid": 1234, "tty": "/dev/ttys004", "started": started, "identity": identity, "cwd": "/repo"}
    target_file.write_text(json.dumps([target]))
    table = {1234: {"pid": 1234, "started": started, "command": "agy"}}
    monkeypatch.setattr(control, "process_cwd", lambda pid: "/repo")
    monkeypatch.setattr(control, "_ps", lambda args: identity)
    assert controller.bindings("approvals", table)["live"] == 1
    table[1234]["started"] = "Wed Oct 21 09:01:00 2026"
    assert controller.bindings("approvals", table)["live"] == 0
    table[1234]["started"] = started
    monkeypatch.setattr(control, "_ps", lambda args: identity.replace("ttys004", "ttys005"))
    assert controller.bindings("approvals", table)["live"] == 0
    monkeypatch.setattr(control, "_ps", lambda args: identity)
    monkeypatch.setattr(control, "process_cwd", lambda pid: "/other")
    assert controller.bindings("approvals", table)["live"] == 0
    assert controller.bindings("approvals", {})["state"] == "no-live-bound-sessions"


def test_lifecycle_lock_prevents_concurrent_mutation(environment):
    controller = environment["make"]()
    controller.state_dir.mkdir()
    with open(controller.state_dir / "lifecycle.lock", "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(control.ControlError, match="Another monitoring"):
            controller.run("stop", ["approvals"])
    assert not Path(controller.manifest["services"]["approvals"]["stop_file"]).exists()


@pytest.mark.parametrize("field", ["stop_file", "status_file", "log_file"])
def test_symlink_lifecycle_files_refused(environment, field):
    spec = environment["manifest"]["services"]["approvals"]
    path = Path(spec[field])
    destination = environment["root"] / "unrelated"
    destination.write_text("preserve")
    path.symlink_to(destination)
    with pytest.raises(control.ControlError, match="Symlink"):
        control.load_manifest(environment["config"])
    assert destination.read_text() == "preserve"


def test_symlink_parent_and_hardlink_state_refused(environment):
    linked = environment["root"] / "linked"
    linked.symlink_to(environment["root"] / "approvals", target_is_directory=True)
    with pytest.raises(control.ControlError, match="Symlink"):
        control.safe_path(linked / "file.json")
    source = environment["root"] / "original"
    source.write_text("preserve")
    other = environment["root"] / "hardlink"
    os.link(source, other)
    with pytest.raises(control.ControlError, match="Hard-linked"):
        control.safe_path(other)


def test_status_json_cli_and_bounded_timeout(environment, capsys):
    assert control.main(["status", "--config", str(environment["config"]), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] and all(row["state"] == "stopped" for row in payload["services"])
    assert all(row["bindings"]["state"] == "no-live-bound-sessions" for row in payload["services"])
    with pytest.raises(SystemExit) as error:
        control.main(["stop", "--timeout", "61"])
    assert error.value.code == 2


def test_pidfile_is_not_used(environment):
    controller = environment["make"]()
    controller.state_dir.mkdir()
    (controller.state_dir / "supervisor.pid").write_text(str(os.getpid()))
    result = controller.run("stop", ["approvals", "supervisor"])
    assert result["ok"] and all(row["pid"] is None for row in result["services"])


def test_parse_ps_ignores_zombies_and_keeps_exact_command():
    output = "  1 S Tue Oct 20 09:00:00 2026 /usr/bin/python3 /a/script.py --loop\n" \
             "  2 Z Tue Oct 20 09:00:00 2026 /usr/bin/python3 gone.py\n"
    assert control.parse_processes(output) == {
        1: {"pid": 1, "started": "Tue Oct 20 09:00:00 2026", "command": "/usr/bin/python3 /a/script.py --loop"}
    }


def test_spawn_failure_restores_stop_before_process_registration(environment, monkeypatch):
    controller = environment["make"]()
    spec = controller.manifest["services"]["approvals"]
    marker = Path(spec["stop_file"])
    marker.write_text("was stopped")
    original = subprocess.Popen

    def fail_spawn(argv, **kwargs):
        if argv == spec["argv"]:
            raise OSError("fixture spawn failed")
        return original(argv, **kwargs)

    monkeypatch.setattr(control.subprocess, "Popen", fail_spawn)
    result = controller.run("start", ["approvals"])
    assert not result["ok"] and "fixture spawn failed" in result["errors"][0]
    assert json.loads(marker.read_text())["source"] == "failed-start-rollback"
    assert not controller.children


def test_keyboard_interrupt_rolls_back_new_monitor(environment, monkeypatch):
    controller = environment["make"]()
    original = controller.heartbeat
    interrupted = False

    def interrupt_once(name, proc):
        nonlocal interrupted
        if proc and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()
        return original(name, proc)

    monkeypatch.setattr(controller, "heartbeat", interrupt_once)
    result = controller.run("start", ["approvals"])
    assert not result["ok"] and "Startup interrupted" in result["errors"][0]
    assert Path(controller.manifest["services"]["approvals"]["stop_file"]).exists()
    assert all(child.poll() is not None for child in controller.children.values())


def test_fresh_approval_status_never_hides_stale_bindings(environment, monkeypatch):
    controller = environment["make"]()
    assert controller.run("start", ["approvals"])["ok"]
    original = controller.heartbeat

    def heartbeat(name, proc):
        result = original(name, proc)
        result["data"].update(active_sessions=14, readable_sessions=14)
        return result

    monkeypatch.setattr(controller, "heartbeat", heartbeat)
    controller.bindings = lambda *args: {"configured": 14, "live": 0, "stale": 14, "state": "no-live-bound-sessions"}
    result = controller.run("status", ["approvals"])
    assert result["services"][0]["monitoring"] == "no-live-bound-sessions"


def test_agent_executable_cannot_be_a_monitor(environment):
    environment["manifest"]["services"]["approvals"]["argv"] = ["/usr/local/bin/agy"]
    save_config(environment)
    with pytest.raises(control.ControlError, match="agent session"):
        control.load_manifest(environment["config"])


def test_human_status_explains_stale_bindings(environment, capsys):
    assert control.main(["status", "--config", str(environment["config"])]) == 0
    assert "live bindings 0/0, stale 0" in capsys.readouterr().out


def test_duplicate_session_targets_refused(environment):
    controller = environment["make"](bindings=False)
    spec = controller.manifest["services"]["approvals"]
    target = {"pid": 1234, "tty": "/dev/ttys004"}
    Path(spec["session_targets_file"]).write_text(json.dumps([target, target]))
    with pytest.raises(control.ControlError, match="duplicate session"):
        controller.bindings("approvals", {})


@pytest.mark.parametrize("field,value", [("stop_file", "ledger.json"), ("log_file", "completion.json")])
def test_lifecycle_write_names_cannot_overwrite_workflow_records(environment, field, value):
    environment["manifest"]["services"]["approvals"][field] = str(environment["root"] / value)
    save_config(environment)
    with pytest.raises(control.ControlError, match="must be named STOP|must have a .log suffix"):
        control.load_manifest(environment["config"])


def test_lifecycle_write_cannot_overwrite_pinned_source(environment):
    spec = environment["manifest"]["services"]["approvals"]
    protected = Path(spec["log_file"])
    protected.write_text("pinned source")
    spec["source_sha256"][str(protected)] = hashlib.sha256(protected.read_bytes()).hexdigest()
    save_config(environment)
    with pytest.raises(control.ControlError, match="must not overwrite"):
        control.load_manifest(environment["config"])


@pytest.mark.parametrize("protected_kind", ["manifest", "session_targets"])
def test_controller_state_cannot_overwrite_its_inputs(environment, protected_kind):
    reserved = Path(environment["manifest"]["state_dir"]) / "events.jsonl"
    reserved.parent.mkdir(parents=True, exist_ok=True)
    config = environment["config"]
    if protected_kind == "manifest":
        reserved.write_text(json.dumps(environment["manifest"]))
        config = reserved
    else:
        reserved.write_text("[]")
        environment["manifest"]["services"]["approvals"]["session_targets_file"] = str(reserved)
        save_config(environment)
    before = reserved.read_bytes()
    with pytest.raises(control.ControlError, match="must not overwrite"):
        control.load_manifest(config)
    assert reserved.read_bytes() == before


@pytest.mark.parametrize("confirmation", [None, "zombie"])
def test_stop_confirms_exit_after_mixed_ps_snapshot(environment, monkeypatch, confirmation):
    controller = environment["make"]()
    expected = {"pid": 1234, "started": "Wed Oct 21 09:00:00 2026", "command": "/usr/bin/python3 monitor.py"}
    first = "1234 S Wed Oct 21 09:00:00 2026 [python3] <defunct>\n"
    second = "1234 Z Wed Oct 21 09:00:00 2026 [python3] <defunct>\n" if confirmation == "zombie" else ""
    snapshots = iter([first, second])
    monkeypatch.setattr(control, "_ps", lambda args: next(snapshots))
    signals = []
    monkeypatch.setattr(control.os, "kill", lambda *args: signals.append(args))
    assert controller.stopped("approvals", expected) is True
    assert not signals


@pytest.mark.parametrize("changed", [{"command": "unrelated"}, {"started": "new process start"}])
def test_stop_still_refuses_persistent_or_reused_identity(environment, monkeypatch, changed):
    controller = environment["make"]()
    expected = {"pid": 1234, "started": "original", "command": "owned"}
    monkeypatch.setattr(control, "process_at", lambda pid: {**expected, **changed})
    signals = []
    monkeypatch.setattr(control.os, "kill", lambda *args: signals.append(args))
    with pytest.raises(control.ControlError, match="identity changed while waiting"):
        controller.stopped("approvals", expected)
    assert not signals


@pytest.mark.parametrize("failure", ["empty-argv", "missing-argv", "missing-cwd", "denied-argv", "denied-cwd"])
@pytest.mark.parametrize("confirmation", ["gone", "zombie", "present", "reused"])
def test_exit_between_ps_and_linux_proc_verification(environment, monkeypatch, failure, confirmation):
    controller = environment["make"]()
    spec = controller.manifest["services"]["approvals"]
    expected = {"pid": 1234, "started": "Wed Oct 21 09:00:00 2026", "command": " ".join(spec["argv"])}
    controller.registry = {"services": {}}
    original_read = Path.read_bytes
    monkeypatch.setattr(control.sys, "platform", "linux")

    def read_cmdline(path):
        if str(path) != "/proc/1234/cmdline":
            return original_read(path)
        if failure == "empty-argv":
            return b""  # Zombie cmdline after ps observed the running process.
        if failure == "missing-argv":
            raise FileNotFoundError("fixture process exited before cmdline read")
        if failure == "denied-argv":
            raise PermissionError("fixture cmdline unreadable")
        return b"\0".join(os.fsencode(arg) for arg in spec["argv"]) + b"\0"

    monkeypatch.setattr(Path, "read_bytes", read_cmdline)

    def read_cwd(path):
        assert path == "/proc/1234/cwd"
        if failure == "denied-cwd":
            raise PermissionError("fixture cwd unreadable")
        raise FileNotFoundError("fixture process exited before cwd read")

    monkeypatch.setattr(control.os, "readlink", read_cwd)
    second = {
        "gone": "", "zombie": "1234 Z Wed Oct 21 09:00:00 2026 [python3] <defunct>\n",
        "present": f"1234 S {expected['started']} {expected['command']}\n",
        "reused": "1234 S Wed Oct 21 09:00:01 2026 unrelated\n",
    }[confirmation]
    monkeypatch.setattr(control, "_ps", lambda args: second)
    signals = []
    monkeypatch.setattr(control.os, "kill", lambda *args: signals.append(args))
    if confirmation in ("gone", "zombie"):
        assert controller.identify("approvals", {1234: expected}) is None
    else:
        with pytest.raises(control.ControlError, match="different arguments|Cannot verify"):
            controller.identify("approvals", {1234: expected})
    assert not signals
