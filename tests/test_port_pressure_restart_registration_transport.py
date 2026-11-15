"""Production restart checks with owned synthetic process and controller evidence."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    'restart_registration_fixture', Path(__file__).with_name('test_mech_port_pressure_native_transport.py'))
fixture_module = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(fixture_module)
Evidence = fixture_module.Evidence
guard = fixture_module.guard


def test_production_preflight_binds_exact_registration_and_current_consumer(tmp_path):
    evidence = Evidence(tmp_path)
    observed = evidence.transport.preflight(evidence.target)
    assert observed['idle'] and observed['verified_identity']
    live = evidence.transport.identity_before
    assert live['executable_sha256'] == hashlib.sha256(evidence.executable.read_bytes()).hexdigest()
    assert live['model'] == 'gemini-3-pro' and live['effort'] == 'high'
    assert live['argv'] == [str(evidence.executable), '--conversation=' + fixture_module.CID,
                            '--model=gemini-3-pro', '--effort=high']
    plan = evidence.transport.binding_plan
    assert plan['expected']['effective'][0]['pid'] == evidence.target['pid']
    assert plan['expected']['generation'].startswith('baseline:')
    assert evidence.inputs == []


def test_changed_executable_after_preflight_is_refused_before_quit(tmp_path):
    evidence = Evidence(tmp_path)
    evidence.transport.preflight(evidence.target)
    with evidence.transport.transaction_lease():
        evidence.executable.write_text('#!/bin/sh\nexit 98\n')
        with pytest.raises(guard.GuardError, match='executable bytes changed'):
            evidence.transport.quit(evidence.target)
    assert evidence.inputs == []


def test_changed_executable_after_quit_is_refused_before_resume(tmp_path):
    evidence = Evidence(tmp_path)
    evidence.on_input = lambda message: evidence.exited() if message == '/quit' else None
    evidence.transport.preflight(evidence.target)
    with evidence.transport.transaction_lease():
        evidence.transport.quit(evidence.target)
        returned = evidence.transport.wait_exit(evidence.target, 1)
        assert evidence.inputs == ['/quit'] and evidence.target['pid'] not in evidence.records
        evidence.executable.write_text('#!/bin/sh\nexit 98\n')
        with pytest.raises(guard.GuardError, match='executable bytes changed'):
            evidence.transport.resume(evidence.target, returned)
    assert evidence.inputs == ['/quit']


@pytest.mark.parametrize('before,after', [
    ('--model=gemini-3-pro', '--model=gemini-3-pro-max'), ('--effort=high', '--effort=highest'),
])
def test_wrong_cli_selector_is_not_justified_by_unchanged_footer(tmp_path, before, after):
    evidence = Evidence(tmp_path)
    original = evidence.supervisor.runner
    def runner(args, **kwargs):
        result = original(args, **kwargs)
        if args[:2] == ['/bin/ps', '-ww']:
            result.stdout = result.stdout.replace(before, after)
        return result
    evidence.supervisor.runner = runner
    assert evidence.screen == fixture_module.IDLE
    assert evidence.transport.observe(evidence.target)['idle']
    with pytest.raises(guard.GuardError, match='CLI model/effort|model or effort changed'):
        evidence.transport.preflight(evidence.target)
    assert evidence.inputs == []


def test_changed_retained_registration_evidence_refuses_before_quit(tmp_path):
    evidence = Evidence(tmp_path)
    evidence.transport.preflight(evidence.target)
    path = Path(evidence.target['port_pressure_identity']['evidence']['path'])
    with evidence.transport.transaction_lease():
        path.write_bytes(path.read_bytes() + b'\n')
        with pytest.raises(guard.GuardError, match='evidence digest changed'):
            evidence.transport.quit(evidence.target)
    assert evidence.inputs == []


def test_missing_resident_baseline_acknowledgment_prevents_quit(tmp_path):
    evidence = Evidence(tmp_path)
    controller = json.loads(evidence.controller.read_text())
    status_path = Path(controller['services']['approvals']['status_file'])
    status = json.loads(status_path.read_text())
    del status['binding_reload']
    status_path.write_text(json.dumps(status))
    with pytest.raises(guard.bindings.BindingError, match='acknowledgment missing'):
        evidence.transport.preflight(evidence.target)
    assert evidence.inputs == [] and evidence.transport.binding_plan is None


def test_missing_controller_reload_capability_prevents_quit(tmp_path):
    evidence = Evidence(tmp_path)
    controller = json.loads(evidence.controller.read_text())
    del controller['services']['approvals']['binding_reload']
    evidence.controller.write_text(json.dumps(controller))
    with pytest.raises(guard.bindings.BindingError, match='reload capability unavailable'):
        evidence.transport.preflight(evidence.target)
    assert evidence.inputs == [] and evidence.transport.binding_plan is None


def test_transport_rejects_boundary_only_without_boundary_even_if_called_directly(tmp_path):
    evidence = Evidence(tmp_path)
    evidence.supervisor.config['port_pressure']['restart_policy'] = 'goal_boundary_only'
    assert evidence.transport.observe(evidence.target)['idle']
    with pytest.raises(guard.GuardError, match='goal-boundary-only restart requires a verified boundary'):
        evidence.transport.preflight(evidence.target)
    assert evidence.inputs == [] and evidence.transport.binding_plan is None


def test_transport_accepts_exact_completed_boundary_without_sending_input(tmp_path):
    evidence = Evidence(tmp_path)
    evidence.supervisor.config['port_pressure']['restart_policy'] = 'goal_boundary_only'
    evidence.transport.boundary = {
        'goal_identity': evidence.target['initial_goal_identity'],
        'completion_authority': 'native_completed',
    }
    result = evidence.transport.preflight(evidence.target)
    assert result['idle'] and evidence.transport.binding_plan is not None
    assert evidence.inputs == []
