"""Exercise the production adapter with synthetic native and operating-system evidence.

The actual supervisor observation, native transport and SEND_JS run here. Every
process/socket/native/Terminal dependency is injected; the JS guard runs in Node
with an Application stub, never against Terminal or a live session.
"""
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


supervisor_module = load("native_transport_supervisor", "scripts/mech_session_supervisor.py")
guard = load("native_transport_guard", "scripts/mech_session_port_pressure.py")
terminal = load("native_transport_terminal", "scripts/mech_session_terminal.py")
CID = "11111111-2222-3333-4444-555555555555"
OTHER_CID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
START = datetime(2026, 11, 4, 10, 0).astimezone()
IDLE = "Earlier completed work\n────────────────────\n>\n────────────────────\nGemini 3 Pro | high\n"


class Evidence:
    def __init__(self, tmp_path):
        tmp_path = tmp_path.resolve()
        self.root = tmp_path / "repository"
        self.root.mkdir()
        self.now = (START + timedelta(hours=2)).timestamp()
        self.calls = []
        self.inputs = []
        self.before_send = None
        self.publish_bindings = None
        self.on_input = None
        self.screen = IDLE
        self.tab = {"window": 7, "tab": 1, "tty": "/dev/ttys001"}
        self.records = {}
        self.cwd = {}
        self.foreground = {}
        self.log_paths = {}
        self.socket_rows = {}
        self.add_process(90, 1, "bash", started=START - timedelta(minutes=1))
        self.add_process(100, 90, "agy")
        self.socket_rows[100] = [("127.0.0.1:54000", "LISTEN"), ("127.0.0.1:54001", "LISTEN")]
        self.executable = tmp_path / "bin/agy"
        self.executable.parent.mkdir()
        self.executable.write_text("#!/bin/sh\nexit 99\n")
        self.executable.chmod(0o700)  # Inspected, never executed.
        self.target = {"repository_key": "traitmech", "github_repository": "CultureBotAI/TraitMech",
                       "pid": 100, "tty": "/dev/ttys001", "root": str(self.root),
                       "native_session_id": CID, "process_identity": self.identity(100),
                       "initial_goal_identity": {"conversation_id": CID, "started_at": START.isoformat(),
                                                 "start_step_index": 1},
                       "port_pressure_identity": {"model": "gemini-3-pro", "effort": "high",
                                                  "model_label": "Gemini 3 Pro", "effort_label": "high",
                                                  "agy_executable": str(self.executable)}}
        runtime = tmp_path / "workspace/runtime"
        runtime.mkdir(parents=True)
        self.config_path = tmp_path / "supervisor.json"
        self.monitor_path = tmp_path / "monitor-targets.json"
        self.approval_path = tmp_path / "approval-targets.json"
        cache = tmp_path / "last_conversations.json"
        supervisor_module.atomic_json(cache, {str(self.root): CID})
        self.native = {"conversation_id": CID, "native_execution_state": "idle_candidate",
                       "active_tools": [], "last_step": {"index": 9, "status": "done"},
                       "current_goal": {"started_at": START.isoformat(), "start_step_index": 1,
                                        "state": "completed", "goal_text": "synthetic completed goal"}}
        config = {"run_id": "synthetic-port-pressure", "runtime_dir": str(runtime),
                  "input_lock_dir": str(tmp_path / "locks"), "targets": [self.target],
                  "conversation_cache_path": str(cache), "conversation_dir": str(tmp_path / "dbs"),
                  "_config_path": str(self.config_path),
                  "port_pressure": {"mode": "restart", "binding_files": [
                      {"role": "monitor", "path": str(self.monitor_path)},
                      {"role": "approval", "path": str(self.approval_path)}]}}
        self.notifier = SimpleNamespace(
            SNAPSHOT_JS=terminal.SNAPSHOT_JS, jxa=self.jxa,
            live_process=lambda pid: terminal.process_record(self.identity(pid)) if pid in self.records else None,
            process_cwd=lambda pid: self.cwd[pid],
            foreground=lambda pid, tty: self.foreground.get(pid, False),
            composer_reason=terminal.composer_reason,
        )
        reader = SimpleNamespace(inspect=self.inspect)
        self.supervisor = supervisor_module.Supervisor(config, native=reader, notifier=self.notifier,
                                                       runner=self.run)
        self.transport = guard.NativeTransport(self.supervisor, clock=lambda: self.now, sleep=self.sleep)
        status = {"run_id": config["run_id"], "repository_key": "traitmech",
                  "goal_identity": self.target["initial_goal_identity"]}
        supervisor_module.atomic_json(self.supervisor.directory(self.target) / "status.json", status)
        supervisor_module.atomic_json(self.config_path, config)
        common = {"pid": 100, "tty": self.target["tty"], "cwd": str(self.root),
                  "identity": self.identity(100), "started": self.records[100]["started"],
                  "native_session_id": CID, "recovery_identity": "stable-before-restart", "unrelated_setting": "preserve"}
        supervisor_module.atomic_json(self.monitor_path, {"targets": [common], "policy": "preserve"})
        supervisor_module.atomic_json(self.approval_path, [common])
        registration = self.target["port_pressure_identity"]
        capture = {"schema_version": 1, "source_kind": "process_argv", "observed_at": START.isoformat(),
                   "pid": 100, "process_identity": self.identity(100), "native_session_id": CID,
                   "tty": self.target["tty"], "cwd": str(self.root), "agy_executable": str(self.executable),
                   "executable_sha256": hashlib.sha256(self.executable.read_bytes()).hexdigest(),
                   "argv": [str(self.executable), "--conversation=" + CID, "--model=gemini-3-pro", "--effort=high"],
                   "model_label": "Gemini 3 Pro", "effort_label": "high"}
        evidence_path = tmp_path / "registration-evidence.json"
        evidence_path.write_text(json.dumps(capture))
        registration.update(schema_version=1, repository_key="traitmech", native_session_id=CID,
                            tty=self.target["tty"], cwd=str(self.root),
                            executable_sha256=capture["executable_sha256"],
                            evidence={"path": str(evidence_path),
                                      "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest()})
        helper = load("reload_fixture_helper", "tests/test_mech_session_port_pressure.py")
        adapter, self.publish_bindings, self.resident, self.recovery, self.controller = helper.reload_fixture(
            self.supervisor, [self.monitor_path, self.approval_path, self.config_path], self.target,
            guard.bindings, lambda: self.now)
        self.transport.binding_adapter = adapter

    def add_process(self, pid, ppid, comm, *, tty="/dev/ttys001", cwd=None, cid=CID, started=START):
        self.records[pid] = {"pid": pid, "ppid": ppid, "tty": tty, "comm": comm,
                             "started": started.strftime("%a %b %d %H:%M:%S %Y")}
        self.cwd[pid] = Path(cwd) if cwd else self.root
        self.foreground[pid] = True
        if comm == "agy":
            path = self.root.parent / "log" / f"cli-{pid}.log"
            path.parent.mkdir(exist_ok=True)
            path.write_text(f'conversation_id="{cid}"\n')
            self.log_paths[pid] = [path]

    def identity(self, pid):
        row = self.records[pid]
        return f"{pid} {Path(row['tty']).name} {row['started']} {row['comm']}"

    def sleep(self, seconds):
        self.now += seconds
        if self.publish_bindings:
            self.publish_bindings()

    def inspect(self, root, cid):
        assert Path(root) == self.root and cid == CID
        return copy.deepcopy(self.native)

    @staticmethod
    def response(stdout="", returncode=0, stderr=""):
        return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)

    def lsof_text(self, pid, *, listen):
        rows = self.socket_rows.get(pid, [])
        output = f"p{pid}\nc{self.records[pid]['comm']}\n"
        for fd, (address, state) in enumerate(rows, 5):
            if not listen or state == "LISTEN":
                output += f"f{fd}u\ntIPv4\nn{address}\nTST={state}\n"
        return output

    def run(self, args, **kwargs):
        self.calls.append(tuple(args))
        if args[:3] == ["/usr/bin/env", "LC_ALL=C", "/bin/ps"]:
            return self.response("\n".join(
                f"{r['pid']} {r['ppid']} {Path(r['tty']).name} {r['started']} {r['comm']}"
                for r in self.records.values()) + "\n")
        if args[:2] == ["/bin/ps", "-ww"]:
            return self.response(str(self.executable) + " --conversation=" + CID + " --model=gemini-3-pro --effort=high\n")
        if args[:2] == ["/bin/ps", "-t"]:
            return self.response("".join(f"{p} {r['comm']}\n" for p, r in self.records.items()
                                         if Path(r["tty"]).name == args[2]))
        if args == ["/bin/ps", "-ax", "-o", "pid=,tty=,lstart=,comm="]:
            return self.response("".join(self.identity(pid) + "\n" for pid in self.records))
        if args[:2] == ["/bin/ps", "-p"]:
            pid = int(args[2])
            return self.response(self.identity(pid) + "\n") if pid in self.records else self.response(returncode=1)
        if args[0] == "git":
            assert args == ["git", "-C", str(self.root), "remote", "get-url", "origin"]
            return self.response("https://github.com/CultureBotAI/TraitMech.git\n")
        if args[0] == "/usr/sbin/sysctl":
            return self.response("49152\n65535\n")
        if args[0] == "/usr/sbin/lsof":
            pid = int(args[args.index("-p") + 1]) if "-p" in args else None
            if "txt" in args:
                return self.response(f"p{pid}\nn{self.executable}\n")
            if "-iTCP" in args:
                pids = [pid] if pid is not None else list(self.socket_rows)
                return self.response("".join(self.lsof_text(p, listen="-sTCP:LISTEN" in args) for p in pids))
            return self.response(f"p{pid}\n" + "".join(f"n{p}\n" for p in self.log_paths.get(pid, [])))
        raise AssertionError(f"Unexpected operation: {args}")

    def jxa(self, source, payload):
        if source == terminal.SNAPSHOT_JS:
            return json.dumps({"tabs": [{**self.tab, "screen": self.screen}]})
        assert source == supervisor_module.SEND_JS
        if self.before_send:
            self.before_send()
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node is required to execute the actual guarded SEND_JS offline")
        fixture = {"expected": payload, "screen": self.screen,
                   "identity": self.identity(payload["pid"]), "cwd": str(self.cwd[payload["pid"]]),
                   "foreground": self.foreground[payload["pid"]],
                   "process_inventory": "\n".join(self.identity(pid) for pid in self.records)}
        harness = r'''
        const fs = require('fs');
        const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
        const sent = [];
        const tab = {tty: () => '/dev/ttys001', history: () => fixture.screen, contents: () => fixture.screen};
        global.Application = name => {
          if (name !== 'Terminal') throw Error('Unexpected Application');
          return {windows: () => [{id: () => 7, tabs: () => [tab]}],
                  doScript: message => sent.push(message)};
        };
        global.Application.currentApplication = () => ({doShellScript: cmd => {
          if (cmd === '/bin/ps -ax -o pid=,tty=,lstart=,comm=') return fixture.process_inventory;
          if (cmd.includes('lstart=')) return fixture.identity;
          if (cmd.includes('lsof')) return 'p' + fixture.expected.pid + '\nn' + fixture.cwd;
          if (cmd.includes('pgid=')) return fixture.foreground ? '100 100' : '100 999';
          throw Error('Unexpected shell read: ' + cmd);
        }});
        '''
        program = harness + source + "\nprocess.stdout.write(JSON.stringify({result:run([JSON.stringify(fixture.expected)]),sent}));"
        result = subprocess.run([node, "-e", program], input=json.dumps(fixture), text=True,
                                capture_output=True, check=True)
        evidence = json.loads(result.stdout)
        self.inputs.extend(evidence["sent"])
        for message in evidence["sent"]:
            if self.on_input:
                self.on_input(message)
        return evidence["result"]

    def exited(self):
        self.records.pop(100)
        self.socket_rows.pop(100, None)
        self.screen = IDLE + f"\nResume with agy --conversation={CID}\nsynthetic-shell $ "

    def resumed(self, count=2):
        self.add_process(200, 90, "agy", started=START + timedelta(hours=2))
        self.socket_rows[200] = [(f"127.0.0.1:{55000 + i}", "LISTEN") for i in range(count)]
        self.screen = IDLE


@pytest.fixture
def evidence(tmp_path):
    return Evidence(tmp_path)


def test_collect_uses_real_parsers_and_all_three_identity_sources(evidence):
    evidence.add_process(300, 1, "other-service", tty="/dev/ttys003")
    evidence.socket_rows[300] = [("127.0.0.1:56000", "LISTEN")]
    measurement, rows = evidence.transport.collect()
    assert measurement["known"] and measurement["host_listeners"] == 3
    assert measurement["per_pid"] == {"100": 2}
    assert rows[0]["verified_identity"] and rows[0]["idle"] and not rows[0]["busy"]
    assert set(rows[0]["conversation_ids"].values()) == {CID}
    assert evidence.inputs == []


@pytest.mark.parametrize("collision", ["cwd", "conversation"])
def test_peer_collisions_block_the_production_observer(evidence, collision):
    evidence.add_process(101, 90, "agy", tty="/dev/ttys002",
                         cwd=evidence.root if collision == "cwd" else evidence.root.parent,
                         cid=OTHER_CID if collision == "cwd" else CID)
    row = evidence.transport.observe(evidence.target)
    assert not row["verified_identity"] and not row["idle"]
    assert "another agy" in row["error"]


@pytest.mark.parametrize("log", ["native startup without an ID", f"conversation_id={CID}\nconversation_id={OTHER_CID}"])
def test_pid_owned_log_must_identify_one_complete_conversation(evidence, log):
    evidence.log_paths[100][0].write_text(log)
    row = evidence.transport.observe(evidence.target)
    assert not row["verified_identity"] and not row["idle"]
    assert "log conversation ID missing or ambiguous" in row["error"]


def test_correct_historical_model_cannot_validate_a_different_current_footer(evidence):
    evidence.screen = IDLE + "\n" + IDLE.replace("Gemini 3 Pro | high", "Gemini 3 Pro Max | highest")
    row = evidence.transport.observe(evidence.target)
    assert not row["idle"] and "configured model and effort" in row["error"]


def test_closed_git_proxy_connection_and_older_active_tool_remain_excluded(evidence):
    evidence.add_process(110, 100, "git", started=START + timedelta(hours=1))
    evidence.socket_rows[110] = [("127.0.0.1:54050->127.0.0.1:54000", "CLOSED")]
    evidence.native["active_tools"] = [{"step_index": 7, "status": "running", "tool_name": "run_command",
                                         "toolSummary": "git push", "created_at": (START + timedelta(hours=1)).isoformat()}]
    row = evidence.transport.observe(evidence.target)
    assert row["verified_identity"] and row["busy"] and not row["idle"]
    child = next(t for t in row["blocked_tasks"] if t.get("pid") == 110)
    assert child["socket_state"] == "CLOSED" and child["age_seconds"] == 3600
    assert any(t.get("step_index") == 7 for t in row["blocked_tasks"])
    assert evidence.inputs == []


def test_question_arriving_after_preflight_is_refused_by_actual_send_js(evidence):
    evidence.before_send = lambda: setattr(evidence, "screen", IDLE + "\n⇧← to answer\nQUESTION: choose one\n")
    evidence.transport.preflight(evidence.target)
    with evidence.transport.transaction_lease():
        with pytest.raises(guard.GuardError, match="guarded /quit was not confirmed"):
            evidence.transport.quit(evidence.target)
    assert evidence.inputs == []


@pytest.mark.parametrize("failure", ["historical_resume_id", "nonforeground_shell", "wrong_shell_cwd"])
def test_verified_exit_requires_fresh_id_and_owned_foreground_shell(evidence, failure):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    if failure == "historical_resume_id":
        evidence.screen = f"Old agy --conversation={CID}\n" + IDLE + "\nsynthetic-shell $ "
    elif failure == "nonforeground_shell":
        evidence.foreground[90] = False
    else:
        evidence.cwd[90] = evidence.root.parent
    with pytest.raises(guard.GuardError, match="fresh printed|foreground shell|shell cwd"):
        evidence.transport.wait_exit(evidence.target, 1)
    assert evidence.inputs == []


@pytest.mark.parametrize("count", [1, 2, 3])
def test_resumed_runtime_requires_exactly_two_real_loopback_listeners(evidence, count):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed(count)
    if count == 2:
        new = evidence.transport.wait_resumed(evidence.target, 1)
        assert new["pid"] == 200 and new["listeners"] == 2
    else:
        with pytest.raises(guard.GuardError, match="listener count is not exactly 2"):
            evidence.transport.wait_resumed(evidence.target, 1)


@pytest.mark.parametrize("field,value", [("window", 8), ("tab", 2), ("tty", "/dev/ttys002")])
def test_resumed_runtime_rejects_original_terminal_binding_drift(evidence, field, value):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.tab[field] = value
    with pytest.raises(guard.GuardError, match="Terminal binding changed|Terminal target ambiguous"):
        evidence.transport.wait_resumed(evidence.target, 1)
    assert evidence.inputs == []


@pytest.mark.parametrize("field", ["pid", "tty", "started"])
def test_resumed_runtime_rejects_process_identity_drift_from_initial_table(evidence, field):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    original = evidence.notifier.live_process
    def changed_identity(pid):
        live = original(pid)
        values = {"pid": 201, "tty": "/dev/ttys002",
                  "started": (START + timedelta(hours=1, minutes=59)).strftime("%a %b %d %H:%M:%S %Y")}
        live[field] = values[field]
        live["identity"] = f"{live['pid']} {Path(live['tty']).name} {live['started']} agy"
        return live
    evidence.notifier.live_process = changed_identity
    with pytest.raises(guard.GuardError, match="resumed PID or TTY|process start observation"):
        evidence.transport.wait_resumed(evidence.target, 1)
    assert evidence.inputs == []


def test_resumed_runtime_rechecks_process_identity_after_listener_measurement(evidence):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    original = evidence.supervisor.runner
    def changed_after_listeners(args, **kwargs):
        result = original(args, **kwargs)
        if args[0] == "/usr/sbin/lsof" and "-sTCP:LISTEN" in args and "200" in args:
            evidence.records[200]["started"] = (START + timedelta(hours=2, seconds=1)).strftime("%a %b %d %H:%M:%S %Y")
        return result
    evidence.supervisor.runner = changed_after_listeners
    with pytest.raises(guard.GuardError, match="process changed after listener check"):
        evidence.transport.wait_resumed(evidence.target, 1)
    assert evidence.inputs == []


@pytest.mark.parametrize("change", ["window", "tab", "busy"])
def test_rebind_freshly_proves_original_terminal_binding_and_idle_state(evidence, change):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    resumed = evidence.transport.wait_resumed(evidence.target, 1)
    files = [evidence.monitor_path, evidence.approval_path, evidence.config_path]
    before = {path: path.read_bytes() for path in files}
    if change == "busy":
        evidence.native["active_tools"] = [{"step_index": 10, "status": "running", "tool_name": "run_command"}]
    else:
        evidence.tab[change] += 1
    with pytest.raises(guard.GuardError, match="changed before rebind"):
        evidence.transport.rebind(evidence.target, resumed)
    assert {path: path.read_bytes() for path in files} == before
    assert evidence.inputs == []


@pytest.mark.parametrize("collision", ["cwd", "conversation"])
def test_peer_appearing_after_verified_exit_blocks_explicit_resume(evidence, collision):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    returned = evidence.transport.wait_exit(evidence.target, 1)
    evidence.add_process(101, 90, "agy", tty="/dev/ttys002",
                         cwd=evidence.root if collision == "cwd" else evidence.root.parent,
                         cid=OTHER_CID if collision == "cwd" else CID)
    with pytest.raises(guard.GuardError, match="another agy claimed"):
        evidence.transport.resume(evidence.target, returned)
    assert evidence.inputs == []


def test_agy_appearing_at_final_js_boundary_blocks_explicit_resume(evidence):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    returned = evidence.transport.wait_exit(evidence.target, 1)
    evidence.before_send = lambda: evidence.add_process(
        101, 90, "agy", tty="/dev/ttys002", cwd=evidence.root.parent, cid=OTHER_CID)
    with pytest.raises(guard.GuardError, match="guarded explicit-ID resume was not confirmed"):
        evidence.transport.resume(evidence.target, returned)
    assert evidence.inputs == []


def test_production_transaction_quits_resumes_and_rebinds_all_three_files(evidence):
    evidence.socket_rows[100] = [(f"127.0.0.1:{54000 + i}", "LISTEN") for i in range(1001)]
    def react(message):
        if message == "/quit":
            evidence.exited()
        else:
            assert "--conversation=" + CID in message
            assert "--model=gemini-3-pro" in message and "--effort=high" in message
            assert "/goal" not in message and "--continue" not in message and "--last" not in message
            evidence.resumed()
    evidence.on_input = react
    report = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport,
                                     clock=lambda: evidence.now).tick(apply=True)
    assert report["phase"] == "restarted", report
    assert len(evidence.inputs) == 2 and evidence.inputs[0] == "/quit"
    for path in (evidence.monitor_path, evidence.approval_path, evidence.config_path):
        data = json.loads(path.read_text())
        row = data["targets"][0] if isinstance(data, dict) else data[0]
        assert row["pid"] == 200 and row["tty"] == "/dev/ttys001"
        assert row.get("identity", row.get("process_identity")) == evidence.identity(200)
        assert row["native_session_id"] == CID
    assert json.loads(evidence.monitor_path.read_text())["policy"] == "preserve"
    assert evidence.target["pid"] == 200
    status = json.loads((evidence.supervisor.directory(evidence.target) / "status.json").read_text())
    assert status["goal_identity"]["conversation_id"] == CID
    assert status["port_pressure_restart"]["old_pid"] == 100
    assert status["port_pressure_restart"]["new_pid"] == 200


ANNOUNCEMENT = 'Meet Gemini 4 Argon …\nesc to dismiss\n'
BOXED_ANNOUNCEMENT = '┌─────────────────────────────┐\n│ Meet Gemini 4 Argon …       │\n│ esc to dismiss              │\n└─────────────────────────────┘\n'
SURVEY = "How's the CLI experience so far?\n[0] Skip\n"


@pytest.mark.parametrize('announcement', [ANNOUNCEMENT, BOXED_ANNOUNCEMENT])
def test_resume_accepts_known_announcement_without_dismissing_or_confusing_model(evidence, announcement):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.screen = IDLE + announcement
    new = evidence.transport.wait_resumed(evidence.target, 2)
    assert new['listeners'] == 2 and new['pid'] == 200
    assert evidence.inputs == []
    assert evidence.transport.observe({**evidence.target, **new})['model_evidence']['model_label'] == 'Gemini 3 Pro'


def test_feedback_survey_blocks_resume_without_answer_or_second_read(evidence):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.screen = IDLE + SURVEY
    evidence.transport.sleep = lambda _: pytest.fail('feedback survey must hold immediately')
    with pytest.raises(guard.GuardError, match='human prompt'):
        evidence.transport.wait_resumed(evidence.target, 2)
    assert evidence.inputs == []


def test_transient_signin_is_reread_without_keys_then_accepts_fresh_idle_runtime(evidence):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.screen = 'Select login\nSign in with your organization\n'
    reads = []
    original = evidence.transport.snapshot
    def snapshot(target):
        reads.append(evidence.screen)
        return original(target)
    evidence.transport.snapshot = snapshot
    def redraw(seconds):
        evidence.sleep(seconds)
        evidence.screen = IDLE
    evidence.transport.sleep = redraw
    assert evidence.transport.wait_resumed(evidence.target, 2)['listeners'] == 2
    assert len(reads) == 2 and 'Sign in' in reads[0] and reads[1] == IDLE
    assert evidence.inputs == []


@pytest.mark.parametrize('second_frame', ['Sign in with your organization\n',
                                         'Sign in with your organization\n' + IDLE])
def test_retained_or_persistent_signin_remains_unverified_after_fresh_reread(evidence, second_frame):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.screen = 'Sign in with your organization\n'
    reads = []
    original = evidence.transport.snapshot
    def snapshot(target):
        reads.append(evidence.screen)
        return original(target)
    evidence.transport.snapshot = snapshot
    def redraw(seconds):
        evidence.sleep(seconds)
        evidence.screen = second_frame
    evidence.transport.sleep = redraw
    with pytest.raises(guard.GuardError, match='after fresh reread; current runtime is unverified'):
        evidence.transport.wait_resumed(evidence.target, 2)
    assert len(reads) == 2 and evidence.inputs == []


def test_new_same_conversation_completed_goal_cannot_pass_final_boundary_preflight(evidence):
    evidence.transport.boundary = {'goal_identity': dict(evidence.target['initial_goal_identity']),
                                   'completion_authority': 'native_completed'}
    evidence.native['current_goal']['start_step_index'] += 1
    with pytest.raises(guard.GuardError, match='goal identity changed'):
        evidence.transport.quit(evidence.target)
    assert evidence.inputs == []


@pytest.mark.parametrize('second', [SURVEY, 'Allow command?\n', 'Sign in with your organization\n' + SURVEY])
def test_startup_signin_grace_never_answers_changed_or_mixed_human_prompt(evidence, second):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.screen = 'Sign in with your organization\n'
    sleeps = []
    def change(seconds):
        sleeps.append(seconds)
        evidence.sleep(seconds)
        evidence.screen = second
    evidence.transport.sleep = change
    with pytest.raises(guard.GuardError):
        evidence.transport.wait_resumed(evidence.target, 45)
    assert sleeps == [1.0] and evidence.inputs == []


def test_mixed_signin_and_feedback_never_receives_startup_grace(evidence):
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.screen = 'Sign in with your organization\n' + SURVEY
    evidence.transport.sleep = lambda _: pytest.fail('mixed human prompt must hold immediately')
    with pytest.raises(guard.GuardError):
        evidence.transport.wait_resumed(evidence.target, 45)
    assert evidence.inputs == []


@pytest.mark.parametrize('survey', [SURVEY, SURVEY.replace("How's", 'How’s'), '[0] Skip\n'])
def test_feedback_survey_is_reported_as_prompt_and_never_idle(evidence, survey):
    evidence.screen = IDLE + survey
    row = evidence.transport.observe(evidence.target)
    assert row['prompt'] is True and row['idle'] is False
    assert evidence.inputs == []


@pytest.mark.parametrize("failure", ["wait_exit", "resume", "wait_resumed", "rebind"])
def test_failed_restart_keeps_exact_immutable_prequit_evidence(evidence, failure):
    evidence.socket_rows[100] = [(f"127.0.0.1:{54000 + i}", "LISTEN") for i in range(1001)]
    before = {str(path): path.read_bytes() for path in
              (evidence.monitor_path, evidence.approval_path, evidence.config_path, evidence.controller)}
    def fail(*_args):
        raise guard.GuardError("injected failure at " + failure)
    setattr(evidence.transport, failure, fail)
    def react(message):
        if message == "/quit":
            # The evidence must already exist when the external send happens.
            prepared = list((evidence.supervisor.runtime / "port-pressure-attempts").glob("*/prepared.json"))
            assert len(prepared) == 1
            assert json.loads(prepared[0].read_text())["identity"]["pid"] == 100
            evidence.exited()
        else:
            evidence.resumed()
    evidence.on_input = react
    report = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport,
                                     clock=lambda: evidence.now).tick(apply=True)
    assert report["phase"] == "disabled" and failure in report["disable_reason"]
    attempts = list((evidence.supervisor.runtime / "port-pressure-attempts").iterdir())
    assert len(attempts) == 1
    directory = attempts[0]
    prepared = json.loads((directory / "prepared.json").read_text())
    for path, raw in before.items():
        retained = directory / prepared["bindings"][path]["file"]
        assert retained.read_bytes() == raw
        assert hashlib.sha256(raw).hexdigest() == prepared["bindings"][path]["sha256"]
    assert (directory / "quit-confirmed.json").exists()
    assert (directory / "failed.json").exists() and not (directory / "finished.json").exists()
    assert {path: Path(path).read_bytes() for path in before} == before
    state = json.loads((evidence.supervisor.runtime / "port-pressure-state.json").read_text())
    assert state["inflight"]["pid"] == 100
    inputs = list(evidence.inputs)
    guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport,
                            clock=lambda: evidence.now).tick(apply=True)
    assert evidence.inputs == inputs and len(list(directory.parent.iterdir())) == 1
