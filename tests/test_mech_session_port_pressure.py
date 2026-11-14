"""Offline restart transaction tests; no live Terminal, processes or network."""
import copy
import hashlib
import importlib.util
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "mech_session_port_pressure", Path(__file__).parents[1] / "scripts/mech_session_port_pressure.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

CID = "11111111-2222-3333-4444-555555555555"
NOW = 10_000.0


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def read_json(path):
    return json.loads(path.read_text())


@contextmanager
def file_lock(path):
    yield


def target(tmp_path, pid=42, key="traitmech"):
    root = tmp_path / key
    root.mkdir(exist_ok=True)
    return {"repository_key": key, "pid": pid, "tty": f"/dev/ttys{pid:03d}",
            "root": str(root), "process_identity": f"{pid} ttys{pid:03d} old-start agy",
            "native_session_id": CID,
            "port_pressure_identity": {"model": "gemini-3-pro", "effort": "high",
                                       "model_label": "Gemini 3 Pro", "effort_label": "high",
                                       "agy_executable": "/not/executed/agy"}}


class SupervisorFixture:
    def __init__(self, tmp_path, *, mode="restart", targets=None, **policy):
        self.runtime = tmp_path / "workspace/runtime"
        self.runtime.mkdir(parents=True)
        self.config = {"run_id": "test-run", "runtime_dir": str(self.runtime),
                       "input_lock_dir": str(tmp_path / "locks"),
                       "port_pressure": {"mode": mode, **policy},
                       "targets": targets or [target(tmp_path)]}
        self._port_pressure_helpers = {"file_lock": file_lock, "read_json": read_json,
                                       "atomic_json": atomic_json, "send_js": "guarded-send"}
        self.writes = []
        self.native_cache = {row["repository_key"]: ("cached", {}) for row in self.config["targets"]}
        self.stop = False

    def stopping(self):
        return self.stop

    def write(self, path, data):
        self.writes.append(path)
        atomic_json(path, data)

    def directory(self, row):
        return self.runtime / row["repository_key"]


def reload_fixture(supervisor, paths, row, module, clock):
    root = supervisor.runtime.parent
    control = root / "control"
    control.mkdir(exist_ok=True)
    Path(supervisor.config["input_lock_dir"]).mkdir(exist_ok=True)
    monitor_source = root / "monitor-source.py"
    monitor_source.write_text("# synthetic existing monitor\n")
    controller = root / "controller.json"
    status = root / "approval-status.json"
    targets = paths[0]
    adapter = Path(module.__file__).resolve()
    config = {"version": 1, "state_dir": str(control), "services": {"approvals": {
        "kind": "approval", "argv": ["/synthetic/python", str(monitor_source)], "cwd": str(root),
        "status_file": str(status), "session_targets_file": str(targets),
        "binding_reload": {"version": 1, "journal": str(control / "binding-reload.json"),
                           "adapter": str(adapter), "input_lock_dir": supervisor.config["input_lock_dir"]},
        "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (adapter, monitor_source, targets)}}}}
    atomic_json(controller, config)
    supervisor.config["port_pressure"]["controller_config_path"] = str(controller)
    atomic_json(Path(supervisor.config["_config_path"]), supervisor.config)
    def identity_reader(pid):
        return {"pid": pid, "started": "synthetic monitor start"}

    def verifier(service, consumer):
        pass  # only external OS operations are injected
    resident = module.ResidentBindings(controller, targets, monitor_source, clock=clock,
                                       identity_reader=identity_reader, consumer_verifier=verifier,
                                       input_lock_dir=supervisor.config["input_lock_dir"])
    recovery = SimpleNamespace(targets={})
    def publish():
        resident.refresh(recovery)
        atomic_json(status, {"pid": os.getpid(), "binding_reload": resident.acknowledgment()})
    publish()
    def prepare(controller_path, binding_paths, target, *, now, input_lock_dir=None):
        return module.prepare_rebind(controller_path, binding_paths, target, now=now,
                                     identity_reader=identity_reader, consumer_verifier=verifier,
                                       input_lock_dir=supervisor.config["input_lock_dir"])
    wrapped = SimpleNamespace(prepare_rebind=prepare, rebind_lease=module.rebind_lease,
                              check_before=module.check_before, install_rebind=module.install_rebind,
                              await_rebind=module.await_rebind)
    return wrapped, publish, resident, recovery, controller


class TransportFixture:
    """Enumerated transaction operations; no method can submit a goal."""
    def __init__(self, supervisor, *, fail=None, measured=None):
        self.s = supervisor
        self.fail = fail
        self.measured = measured
        self.calls = []
        self.inputs = []

    def step(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise guard.GuardError(f"{name} failed")

    def collect(self):
        self.step("collect")
        rows = []
        counts = {}
        for index, row in enumerate(self.s.config["targets"]):
            counts[str(row["pid"])] = 2000 + index
            rows.append({"repository_key": row["repository_key"], "pid": row["pid"],
                         "verified_identity": True, "idle": True, "busy": False, "prompt": False,
                         "blocked_tasks": [], "conversation_ids": dict.fromkeys(("index", "supervisor", "log"), CID)})
        measured = {"known": True, "host_listeners": sum(counts.values()),
                    "ephemeral_low": 49152, "ephemeral_high": 65535,
                    "per_pid": counts, "agy_pids": [int(pid) for pid in counts]}
        return self.measured if self.measured is not None else measured, rows

    def preflight(self, row):
        self.step("preflight")

    @contextmanager
    def transaction_lease(self):
        yield

    def quit(self, row):
        self.step("quit")
        self.inputs.append("/quit")

    def wait_exit(self, row, timeout):
        self.step("wait_exit")
        return {"printed_id": row["native_session_id"], "old_pid_exited": True}

    def resume(self, row, returned):
        self.step("resume")
        assert returned["printed_id"] == row["native_session_id"] and returned["old_pid_exited"]
        self.inputs.append("agy --conversation=" + row["native_session_id"])

    def wait_resumed(self, row, timeout):
        self.step("wait_resumed")
        return {"pid": row["pid"] + 1000, "tty": row["tty"], "process_identity": "new identity",
                "started": "new start", "listeners": 2}

    def rebind(self, row, new):
        self.step("rebind")
        row.update(pid=new["pid"], tty=new["tty"], process_identity=new["process_identity"])


@pytest.mark.parametrize("mode,apply,phase", [("off", True, "off"), ("report", True, "candidate"),
                                             ("report", False, "candidate"), ("restart", False, "candidate")])
def test_off_and_report_never_send_input_or_restart(tmp_path, mode, apply, phase):
    supervisor = SupervisorFixture(tmp_path, mode=mode)
    transport = TransportFixture(supervisor)
    result = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW).tick(apply=apply)
    assert result["phase"] == phase
    assert transport.inputs == []
    assert set(transport.calls) <= {"collect"}
    assert not (supervisor.runtime / "port-pressure-state.json").exists()


def test_at_most_one_quit_and_explicit_resume_per_tick_without_goal_text(tmp_path):
    rows = [target(tmp_path, 42, "traitmech"), target(tmp_path, 43, "culturemech")]
    supervisor = SupervisorFixture(tmp_path, targets=rows)
    transport = TransportFixture(supervisor)
    result = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW).tick(apply=True)
    assert result["phase"] == "restarted" and result["old_pid"] == 43
    assert transport.inputs == ["/quit", "agy --conversation=" + CID]
    assert transport.calls == ["collect", "preflight", "quit", "wait_exit", "resume", "wait_resumed", "rebind"]
    state = read_json(supervisor.runtime / "port-pressure-state.json")
    assert "inflight" not in state and len(state["restart_history"]) == 1
    assert state["restart_history"][0]["new_pid"] == 1043


def test_id_mismatch_sends_no_quit_and_disables_guard(tmp_path):
    supervisor = SupervisorFixture(tmp_path)
    transport = TransportFixture(supervisor)
    original = transport.collect

    def mismatched():
        measured, rows = original()
        rows[0]["conversation_ids"]["log"] = "different"
        return measured, rows

    transport.collect = mismatched
    result = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW).tick(apply=True)
    assert result["phase"] == "disabled" and "mismatch" in result["alert"]
    assert transport.inputs == []
    assert read_json(supervisor.runtime / "port-pressure-state.json")["disabled"] is True


@pytest.mark.parametrize("failure", ["preflight", "quit", "wait_exit", "resume", "wait_resumed", "rebind"])
def test_first_transaction_failure_latches_and_new_guard_never_retries(tmp_path, failure):
    supervisor = SupervisorFixture(tmp_path)
    transport = TransportFixture(supervisor, fail=failure)
    first = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW).tick(apply=True)
    before_inputs = list(transport.inputs)
    before_state = read_json(supervisor.runtime / "port-pressure-state.json")
    transport.fail = None
    second = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW + 1).tick(apply=True)
    assert first["phase"] == second["phase"] == "disabled"
    assert transport.inputs == before_inputs
    assert read_json(supervisor.runtime / "port-pressure-state.json")["failure"] == before_state["failure"]


def test_persisted_inflight_stops_before_observation_or_input(tmp_path):
    supervisor = SupervisorFixture(tmp_path)
    atomic_json(supervisor.runtime / "port-pressure-state.json", {"inflight": {"pid": 42}})
    transport = TransportFixture(supervisor)
    result = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW).tick(apply=True)
    assert result["phase"] == "disabled" and "unfinished" in result["alert"]
    assert transport.calls == transport.inputs == []


def test_cooldown_and_hourly_cap_survive_new_guard_objects(tmp_path):
    rows = [target(tmp_path, 42, "traitmech"), target(tmp_path, 43, "culturemech"),
            target(tmp_path, 44, "habitatmech")]
    supervisor = SupervisorFixture(tmp_path, targets=rows)
    transport = TransportFixture(supervisor)
    results = [guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW).tick(apply=True)
               for _ in range(3)]
    assert [row["phase"] for row in results] == ["restarted", "restarted", "limited"]
    assert [row["old_pid"] for row in results[:2]] == [44, 43]
    assert len(transport.inputs) == 4
    later = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW + 3600).tick(apply=True)
    assert later["phase"] == "restarted" and len(transport.inputs) == 6


@pytest.mark.parametrize("reason", ["queued human question", "background task became busy"])
def test_native_quit_rechecks_preflight_after_selection_before_any_input(tmp_path, reason):
    supervisor = SupervisorFixture(tmp_path)
    fixture = TransportFixture(supervisor)
    supervisor.notifier = SimpleNamespace(jxa=lambda *_: pytest.fail("input must not be sent"))
    native = guard.NativeTransport(supervisor, clock=lambda: NOW)
    native.collect = fixture.collect
    calls = []

    def preflight(row):
        calls.append(row["pid"])
        if len(calls) > 1:
            raise guard.GuardError(reason)
        return {"idle": True}

    native.preflight = preflight
    native.transaction_lease = fixture.transaction_lease
    result = guard.PortPressureGuard(supervisor, transport=native, clock=lambda: NOW).tick(apply=True)
    assert result["phase"] == "disabled" and reason in result["alert"]
    assert calls == [42, 42]


@pytest.mark.parametrize("raw", ["{broken json", "[]", '"not an object"'])
def test_corrupt_state_is_durably_disabled_and_alerted_before_input(tmp_path, raw):
    supervisor = SupervisorFixture(tmp_path)
    state_path = supervisor.runtime / "port-pressure-state.json"
    state_path.write_text(raw)
    transport = TransportFixture(supervisor)
    result = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW).tick(apply=True)
    assert result["phase"] == "disabled" and result["alert"]
    assert transport.inputs == []
    assert state_path.read_text() == raw
    latch_path = supervisor.runtime / "port-pressure-disabled.json"
    first_latch = latch_path.read_bytes()
    later = guard.PortPressureGuard(supervisor, transport=transport, clock=lambda: NOW + 1).tick(apply=True)
    assert later["phase"] == "disabled" and transport.inputs == []
    assert latch_path.read_bytes() == first_latch and state_path.read_text() == raw


def test_log_conversation_requires_one_pid_owned_identity():
    assert guard.log_conversation(f'conversation_id="{CID}"\nconversationId: {CID}') == CID
    with pytest.raises(guard.GuardError, match="missing or ambiguous"):
        guard.log_conversation("no identity")
    with pytest.raises(guard.GuardError, match="missing or ambiguous"):
        guard.log_conversation(f'conversation_id={CID}\nconversation_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')


def test_model_and_effort_are_proven_by_current_footer(tmp_path):
    identity = target(tmp_path)["port_pressure_identity"]
    assert guard.model_evidence("Gemini 3 Pro | high", identity)["effort"] == "high"
    with pytest.raises(guard.GuardError, match="footer"):
        guard.model_evidence("Gemini 3 Pro | high\n" + "old history\n" * 12, identity)


@pytest.mark.parametrize("screen", ["Gemini 3 Pro Max | high", "Gemini 3 Pro | highest"])
def test_model_and_effort_substring_collisions_do_not_prove_same_runtime(tmp_path, screen):
    identity = target(tmp_path)["port_pressure_identity"]
    with pytest.raises(guard.GuardError, match="footer"):
        guard.model_evidence(screen, identity)


@pytest.mark.parametrize("label,effort,footer", [
    ("Gemini 3.1 Pro", "High", "  ? for shortcuts                 Gemini 3.1 Pro (High)"),
    ("Gemini 4 Argon", "high", "  ? for shortcuts                 Gemini 4 Argon · high"),
])
def test_model_evidence_accepts_observed_native_footer_shapes(tmp_path, label, effort, footer):
    identity = {**target(tmp_path)["port_pressure_identity"], "model_label": label, "effort_label": effort}
    assert guard.model_evidence("────────────\n>\n────────────\n" + footer, identity)["model_label"] == label
    with pytest.raises(guard.GuardError, match="footer"):
        guard.model_evidence(footer.replace(label, label + " Max"), identity)


def test_historical_model_fields_above_composer_cannot_prove_current_footer(tmp_path):
    identity = target(tmp_path)["port_pressure_identity"]
    screen = "Gemini 3 Pro | high\n────────────\n>\n────────────\nGemini 4 Pro | low"
    with pytest.raises(guard.GuardError, match="footer"):
        guard.model_evidence(screen, identity)


def test_fresh_shutdown_output_cannot_reuse_historical_printed_id():
    before = "earlier agy --conversation=" + CID + "\n" + "composer-boundary\n" * 8
    assert guard.fresh_output(before, before + "new shell output\n") == "new shell output\n"
    with pytest.raises(guard.GuardError, match="boundary"):
        guard.fresh_output(before, "cropped historical agy --conversation=" + CID)


def prepare_bindings(tmp_path):
    supervisor = SupervisorFixture(tmp_path)
    row = supervisor.config["targets"][0]
    root = Path(row["root"])
    unchanged = {"pid": 99, "tty": "/dev/ttys099", "root": str(root / "unrelated"),
                 "process_identity": "unrelated process", "native_session_id": "other", "recovery_identity": "unrelated-stable"}
    monitor = tmp_path / "monitor.json"
    approval = tmp_path / "approval.json"
    config = tmp_path / "supervisor.json"
    atomic_json(monitor, [{"pid": row["pid"], "tty": row["tty"], "cwd": row["root"],
                           "identity": row["process_identity"], "started": "old start",
                           "native_session_id": CID, "recovery_identity": "stable-old"}, unchanged])
    atomic_json(approval, {"targets": [copy.deepcopy(row), unchanged], "other_setting": "retained"})
    supervisor.config.update(_config_path=str(config))
    supervisor.config["port_pressure"]["binding_files"] = [
        {"role": "monitor", "path": str(monitor)}, {"role": "approval", "path": str(approval)}]
    atomic_json(config, supervisor.config)
    atomic_json(supervisor.directory(row) / "status.json", {
        "run_id": "test-run", "repository_key": row["repository_key"],
        "goal_identity": {"conversation_id": CID}, "untouched": "preserved"})
    new = {"pid": 1042, "tty": row["tty"], "process_identity": "1042 new-start agy",
           "started": "new start", "listeners": 2}
    return supervisor, row, new, (monitor, approval, config), unchanged


def test_binding_plan_and_rebind_update_only_exact_old_identity(tmp_path):
    supervisor, row, new, paths, unchanged = prepare_bindings(tmp_path)
    plan = guard.binding_plan(supervisor, row, read_json)
    assert {role for item in plan for role in item["roles"]} == {"monitor", "approval", "supervisor"}
    adapter, publish, _resident, _recovery, controller = reload_fixture(
        supervisor, paths, row, guard.bindings, lambda: NOW)
    plan = adapter.prepare_rebind(str(controller), [str(path) for path in paths], row, now=lambda: NOW)
    with adapter.rebind_lease(plan):
        guard.apply_bindings(supervisor, row, new, plan, supervisor._port_pressure_helpers,
                             sleep=lambda _: publish(), binding_adapter=adapter)
    monitor, approval, config = [read_json(path) for path in paths]
    assert monitor[0]["pid"] == approval["targets"][0]["pid"] == config["targets"][0]["pid"] == 1042
    assert monitor[0]["identity"] == new["process_identity"] and monitor[0]["started"] == "new start"
    assert monitor[1] == approval["targets"][1] == unchanged
    assert approval["other_setting"] == "retained"
    assert row["pid"] == 1042 and "traitmech" not in supervisor.native_cache
    status = read_json(supervisor.directory(row) / "status.json")
    assert status["untouched"] == "preserved"
    assert status["port_pressure_restart"]["old_pid"] == 42
    assert status["port_pressure_restart"]["new_pid"] == 1042
    assert read_json(supervisor.runtime.parent / "control/binding-reload.json")["state"] == "complete"


@pytest.mark.parametrize("field,value", [("tty", "/dev/ttys100"), ("cwd", "/wrong"),
                                        ("identity", "PID reused with different start")])
def test_binding_preflight_rejects_mismatched_tty_cwd_or_process_start(tmp_path, field, value):
    supervisor, row, _new, paths, _unchanged = prepare_bindings(tmp_path)
    data = read_json(paths[0])
    data[0][field] = value
    atomic_json(paths[0], data)
    with pytest.raises(guard.GuardError, match="identity disagreement"):
        guard.binding_plan(supervisor, row, read_json)


def test_binding_change_after_preflight_stops_before_any_replacement(tmp_path):
    supervisor, row, new, paths, _unchanged = prepare_bindings(tmp_path)
    adapter, _publish, _resident, _recovery, controller = reload_fixture(
        supervisor, paths, row, guard.bindings, lambda: NOW)
    plan = adapter.prepare_rebind(str(controller), [str(path) for path in paths], row, now=lambda: NOW)
    data = read_json(paths[1])
    data["external_change"] = True
    atomic_json(paths[1], data)
    before = [path.read_bytes() for path in paths]
    with pytest.raises(guard.bindings.BindingError, match="CAS drift"):
        with adapter.rebind_lease(plan):
            guard.apply_bindings(supervisor, row, new, plan, supervisor._port_pressure_helpers)
    assert [path.read_bytes() for path in paths] == before and row["pid"] == 42


def test_binding_files_are_accepted_as_transport_settings_not_policy_typos(tmp_path):
    supervisor, _row, _new, _paths, _unchanged = prepare_bindings(tmp_path)
    instance = guard.PortPressureGuard(supervisor, transport=TransportFixture(supervisor), clock=lambda: NOW)
    assert instance.config["mode"] == "restart"


def test_native_resume_uses_exact_id_same_model_and_effort_without_goal(tmp_path):
    supervisor = SupervisorFixture(tmp_path)
    captured = []
    supervisor.notifier = SimpleNamespace(jxa=lambda _source, value: captured.append(value) or "sent")
    def runner(args, **kwargs):
        if args == ["/bin/ps", "-p", "42", "-o", "pid="]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if args == ["/usr/bin/env", "LC_ALL=C", "/bin/ps", "-ax", "-o", "pid=,ppid=,tty=,lstart=,comm="]:
            return SimpleNamespace(returncode=0, stdout="41 1 ttys042 Thu Jan 1 00:00:00 1970 zsh\n", stderr="")
        if args == ["/bin/ps", "-ax", "-o", "pid=,tty=,lstart=,comm="]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(args)

    supervisor.runner = runner
    native = guard.NativeTransport(supervisor, clock=lambda: NOW)
    row = supervisor.config["targets"][0]
    with pytest.raises(guard.GuardError, match="registration evidence"):
        native.resume(row, {"tab": {"tty": row["tty"], "window": 1, "tab": 1},
                            "shell": {"pid": 41, "identity": "shell start"}})
    assert captured == []



@pytest.mark.parametrize("listener_count", [1, 2, 3])
def test_native_resumed_listener_count_must_be_exactly_two(tmp_path, listener_count):
    supervisor = SupervisorFixture(tmp_path)
    row = supervisor.config["targets"][0]
    supervisor.notifier = SimpleNamespace(
        live_process=lambda _pid: {"pid": 1042, "tty": row["tty"], "identity": "1042 new start", "started": "Thu Jan 1 00:00:00 1970"},
        composer_reason=lambda _screen: None)
    native = guard.NativeTransport(supervisor, clock=lambda: NOW)
    tab = {"window": 1, "tab": 1, "tty": row["tty"], "screen": "Gemini 3 Pro | high"}
    native.before_quit = {"model_evidence": guard.model_evidence(tab["screen"], row["port_pressure_identity"]),
                          "observation": {"tab": tab}}
    native.snapshot = lambda _row: tab
    started = datetime(1970, 1, 1).astimezone().timestamp()
    native.processes = lambda: [{"pid": 1042, "tty": row["tty"], "comm": "agy", "started_epoch": started}]
    native.observe = lambda _row: {"idle": True, "verified_identity": True, "observation": {"tab": tab}}
    text = "p1042\ncagy\n" + "".join(
        f"f{fd}\ntIPv4\nn127.0.0.1:{50000 + fd}\nTST=LISTEN\n" for fd in range(4, 4 + listener_count))
    native.verify_restart_identity = lambda *_args: {}  # identity is tested through the production fixture
    native.sockets = lambda *_args, **_kwargs: {"stdout": text, "stderr": "", "returncode": 0}
    if listener_count == 2:
        result = native.wait_resumed(row, 45)
        assert result["pid"] == 1042 and result["listeners"] == 2
    else:
        with pytest.raises(guard.GuardError, match="exactly 2"):
            native.wait_resumed(row, 45)


def exit_transport(tmp_path, *, printed_id=CID, historical_only=False, old_reused=False):
    supervisor = SupervisorFixture(tmp_path)
    row = supervisor.config["targets"][0]
    old_screen = ("historical agy --conversation=" + CID + "\n") + "idle composer boundary\n" * 4
    current = old_screen + ("" if historical_only else "To resume: agy --conversation=" + printed_id + "\n") + "$ "
    supervisor.notifier = SimpleNamespace(foreground=lambda *_: True,
                                         process_cwd=lambda _pid: Path(row["root"]))
    calls = []

    def run(args, **_kwargs):
        calls.append(args)
        assert args[0] == "/bin/ps" and args[1] == "-p"
        if args[2] == "42":
            return SimpleNamespace(returncode=0 if old_reused else 1,
                                   stdout="42 changed-start agy" if old_reused else "", stderr="")
        assert args[2] == "41"
        return SimpleNamespace(returncode=0, stdout="41 shell start bash", stderr="")

    supervisor.runner = run
    native = guard.NativeTransport(supervisor, clock=lambda: NOW)
    native.before_quit = {"observation": {"tab": {"window": 1, "tab": 1, "tty": row["tty"], "screen": old_screen}}}
    native.snapshot = lambda _target: {"window": 1, "tab": 1, "tty": row["tty"], "screen": current}
    native.processes = lambda: [{"pid": 41, "tty": row["tty"], "comm": "bash"}]
    return native, row, calls


def test_native_exit_requires_old_pid_gone_fresh_exact_id_and_returned_shell(tmp_path):
    native, row, calls = exit_transport(tmp_path)
    result = native.wait_exit(row, 30)
    assert result["shell"]["pid"] == 41 and result["tab"]["tty"] == row["tty"]
    assert [call[2] for call in calls] == ["42", "41"]


@pytest.mark.parametrize("changes,reason", [
    ({"printed_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}, "resume ID"),
    ({"historical_only": True}, "resume ID"),
    ({"old_reused": True}, "PID reused"),
])
def test_native_exit_refuses_mismatch_historical_id_or_reused_process(tmp_path, changes, reason):
    native, row, _calls = exit_transport(tmp_path, **changes)
    with pytest.raises(guard.GuardError, match=reason):
        native.wait_exit(row, 30)


def test_native_exit_refuses_another_live_agy_on_same_tty(tmp_path):
    native, row, _calls = exit_transport(tmp_path)
    native.processes = lambda: [{"pid": 500, "tty": row["tty"], "comm": "agy"}]
    with pytest.raises(guard.GuardError, match="live agy remains"):
        native.wait_exit(row, 30)


def test_native_resume_rereads_signin_once_without_process_or_input_actions(tmp_path):
    supervisor = SupervisorFixture(tmp_path)
    native = guard.NativeTransport(supervisor, clock=lambda: NOW)
    tab = {"window": 1, "tab": 1, "tty": "/dev/ttys042", "screen": "Sign in with your organization"}
    native.before_quit = {"observation": {"tab": tab}}
    reads = []
    native.snapshot = lambda _row: reads.append(tab) or tab
    native.sleep = lambda _: None
    native.processes = lambda: pytest.fail("sign-in menu must stop processing")
    with pytest.raises(guard.GuardError, match="after fresh reread"):
        native.wait_resumed(supervisor.config["targets"][0], 45)
    assert len(reads) == 2


def test_unknown_canary_target_fails_before_any_observation(tmp_path):
    supervisor = SupervisorFixture(tmp_path, restart_repository_keys=['not_configured'])
    transport = TransportFixture(supervisor)
    with pytest.raises(guard.GuardError, match='unconfigured target'):
        guard.PortPressureGuard(supervisor, transport=transport)
    assert transport.calls == [] and transport.inputs == []


def test_exact_native_server_identity_line_accepts_one_id_and_rejects_lookalikes():
    line = f"I1110 00:07:00.123456 123 server.go:3329] GetConversationDetail: found conversation {CID} (active=false)"
    assert guard.log_conversation(line + "\n" + line) == CID
    for invalid in ("quoted: " + line, line.replace("server.go", "tool.go"),
                    line.replace("active=false", "active=unknown"), line[:-4],
                    line.replace(CID, CID[:-1])):
        with pytest.raises(guard.GuardError, match="missing or ambiguous"):
            guard.log_conversation(invalid)
    with pytest.raises(guard.GuardError, match="ambiguous"):
        guard.log_conversation(line + "\n" + line.replace(CID, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
