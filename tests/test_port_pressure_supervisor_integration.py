"""Offline CLI/loop boundaries for the port-pressure maintenance lane."""
import copy
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "pressure_integration_supervisor", Path(__file__).parents[1] / "scripts/mech_session_supervisor.py")
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


@pytest.mark.parametrize("phase", ["restarted", "disabled", "unknown"])
def test_maintenance_tick_never_dispatches_workflow_text(tmp_path, monkeypatch, phase):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    instance = supervisor.Supervisor(
        {"runtime_dir": str(runtime), "run_id": "test", "targets": [{"repository_key": "traitmech"}],
         "port_pressure": {"mode": "restart"}}, native=SimpleNamespace(), notifier=SimpleNamespace())
    monkeypatch.setattr(instance, "port_pressure", lambda **kwargs: {"phase": phase})
    monkeypatch.setattr(instance, "observe", lambda *args, **kwargs: pytest.fail("ordinary workflow was visited"))
    result = instance.sweep(apply=True)
    assert result["sessions"] == [] and result["port_pressure"]["phase"] == phase
    assert not (runtime / "traitmech/ledger.json").exists()


@pytest.mark.parametrize("flag,expected", [
    ("--port-pressure-report", {"report_only": True, "apply": False}),
    ("--port-pressure-restart", {"report_only": False, "apply": True}),
])
def test_guard_only_cli_preserves_active_supervisor_heartbeat_and_workflow_lock(tmp_path, monkeypatch, flag, expected):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    heartbeat = runtime / "heartbeat.json"
    heartbeat.write_text('{"running":true,"pid":500}')
    config_path = tmp_path / "config.json"
    config = {"runtime_dir": str(runtime), "port_pressure": {"mode": "off"}}
    config_path.write_text(json.dumps(config))
    calls = []

    class GuardOnly:
        def __init__(self, config, **kwargs):
            self.runtime = Path(config["runtime_dir"])

        def stopping(self):
            return False

        def port_pressure(self, **kwargs):
            calls.append(kwargs)
            return {"phase": "off"}

        def sweep(self, **kwargs):
            pytest.fail("guard-only CLI must not dispatch ordinary workflow")

        def write(self, *args):
            pytest.fail("guard-only CLI must not overwrite heartbeat")

    monkeypatch.setattr(supervisor, "Supervisor", GuardOnly)
    monkeypatch.setattr(supervisor, "validate_config", lambda config: config)
    monkeypatch.setattr(supervisor, "file_lock", lambda *args: pytest.fail("workflow lock taken"))
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    assert supervisor.main(["--config", str(config_path), flag]) == 0
    assert calls == [expected]
    assert heartbeat.read_text() == '{"running":true,"pid":500}'


def test_off_setting_is_reread_without_restarting_supervisor(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config = {"runtime_dir": str(tmp_path), "_config_path": str(config_path),
              "port_pressure": {"mode": "restart"}}
    config_path.write_text(json.dumps({"port_pressure": {"mode": "off"}}))
    instance = supervisor.Supervisor(config, native=SimpleNamespace(), notifier=SimpleNamespace())
    monkeypatch.setattr(supervisor, "import_file", lambda *args: pytest.fail("off guard initialized transport"))
    assert instance.port_pressure(apply=True)["phase"] == "off"


def test_explicit_empty_guard_settings_default_to_report(tmp_path, monkeypatch):
    config = {"runtime_dir": str(tmp_path), "port_pressure": {}}
    instance = supervisor.Supervisor(config, native=SimpleNamespace(), notifier=SimpleNamespace())
    calls = []

    class ReportGuard:
        def __init__(self, parent):
            assert parent.config["port_pressure"]["mode"] == "report"

        def tick(self, **kwargs):
            calls.append(kwargs)
            return {"phase": "candidate"}

    monkeypatch.setattr(supervisor, "import_file", lambda *args: SimpleNamespace(PortPressureGuard=ReportGuard))
    assert instance.port_pressure()["phase"] == "candidate"
    assert calls == [{"apply": False}]


def test_report_and_workflow_apply_are_mutually_exclusive():
    with pytest.raises(SystemExit) as error:
        supervisor.main(["--config", "/not/read", "--port-pressure-report", "--apply"])
    assert error.value.code == 2


def test_report_unknown_exits_nonzero(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"runtime_dir": str(tmp_path)}))
    monkeypatch.setattr(supervisor, "validate_config", lambda value: copy.deepcopy(value))
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    monkeypatch.setattr(supervisor, "Supervisor", lambda config, **kwargs: SimpleNamespace(
        stopping=lambda: False, port_pressure=lambda **kwargs: {"phase": "disabled"}))
    assert supervisor.main(["--config", str(config_path), "--port-pressure-report"]) == 1


@pytest.mark.parametrize("loop", [False, True])
@pytest.mark.parametrize("phase", ["disabled", "unknown"])
def test_apply_failure_exits_nonzero_including_after_loop_stops(tmp_path, monkeypatch, loop, phase):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"runtime_dir": str(tmp_path)}))

    class FailedMaintenance:
        def __init__(self, config, **kwargs):
            self.runtime = Path(config["runtime_dir"])

        def sweep(self, **kwargs):
            if loop:
                (self.runtime / "STOP").write_text("stop fixture after one tick")
            return {"port_pressure": {"phase": phase, "alert": "failed check"}}

        def write(self, *args):
            pass

    monkeypatch.setattr(supervisor, "Supervisor", FailedMaintenance)
    monkeypatch.setattr(supervisor, "validate_config", lambda value: value)
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    monkeypatch.setattr(supervisor, "file_lock", lambda *args: nullcontext())
    times = iter([0, 100])
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(times))
    args = ["--config", str(config_path), "--apply"] + (["--loop"] if loop else [])
    assert supervisor.main(args) == 1
