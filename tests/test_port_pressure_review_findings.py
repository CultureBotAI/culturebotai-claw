"""Actual-adapter regressions for independent findings #918 and #919."""
import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from test_mech_port_pressure_native_transport import (
    IDLE,
    OTHER_CID,
    START,
    SURVEY,
    Evidence,
    guard,
    supervisor_module,
    terminal,
)


def paired_evidence(tmp_path):
    evidence = Evidence(tmp_path)
    peer_root = tmp_path / 'peer-repository'
    peer_root.mkdir()
    evidence.add_process(190, 1, 'bash', tty='/dev/ttys002', cwd=peer_root,
                         started=START - timedelta(minutes=1))
    evidence.add_process(200, 190, 'agy', tty='/dev/ttys002', cwd=peer_root, cid=OTHER_CID)
    peer = {**copy.deepcopy(evidence.target), 'repository_key': 'culturemech', 'pid': 200,
            'tty': '/dev/ttys002', 'root': str(peer_root), 'github_repository': 'CultureBotAI/CultureMech',
            'native_session_id': OTHER_CID, 'process_identity': evidence.identity(200)}
    peer['initial_goal_identity']['conversation_id'] = OTHER_CID
    evidence.supervisor.config['targets'].append(peer)
    cache_path = Path(evidence.supervisor.config['conversation_cache_path'])
    cache = supervisor_module.read_json(cache_path)
    cache[str(peer_root)] = OTHER_CID
    supervisor_module.atomic_json(cache_path, cache)
    evidence.supervisor.write(evidence.supervisor.directory(peer) / 'status.json', {
        'run_id': evidence.supervisor.config['run_id'], 'repository_key': 'culturemech',
        'goal_identity': peer['initial_goal_identity']})
    peer_native = {**copy.deepcopy(evidence.native), 'conversation_id': OTHER_CID}
    original_inspect = evidence.supervisor.native.inspect
    evidence.supervisor.native.inspect = lambda root, cid: copy.deepcopy(peer_native) if cid == OTHER_CID else original_inspect(root, cid)
    original_jxa = evidence.notifier.jxa
    def jxa(source, payload):
        if source == terminal.SNAPSHOT_JS and payload == [peer['tty']]:
            return json.dumps({'tabs': [{'window': 8, 'tab': 1, 'tty': peer['tty'], 'screen': IDLE}]})
        return original_jxa(source, payload)
    evidence.notifier.jxa = jxa
    original_runner = evidence.supervisor.runner
    def runner(args, **kwargs):
        if args == ['git', '-C', str(peer_root), 'remote', 'get-url', 'origin']:
            return evidence.response('https://github.com/CultureBotAI/CultureMech.git\n')
        return original_runner(args, **kwargs)
    evidence.supervisor.runner = runner
    evidence.socket_rows[100] = [(f'127.0.0.1:{54000 + index}', 'LISTEN') for index in range(1300)]
    evidence.socket_rows[200] = [(f'127.0.0.1:{56000 + index}', 'LISTEN') for index in range(1200)]
    return evidence


def block(evidence, kind):
    if kind == 'prompt':
        evidence.screen = SURVEY
    elif kind == 'busy':
        evidence.screen = 'Running git push\n'
        evidence.native['native_execution_state'] = 'busy'
        evidence.native['active_tools'] = [{'step_index': 10, 'status': 'running',
                                            'tool_name': 'run_command', 'toolSummary': 'git push',
                                            'created_at': (START + timedelta(hours=1)).isoformat()}]
    else:
        evidence.screen = 'Running background task pr\n'
        evidence.add_process(300, 100, 'pr', started=START + timedelta(hours=1))


@pytest.mark.parametrize('kind', ['prompt', 'busy', 'task'])
def test_known_blocked_footerless_session_does_not_latch_or_hide_eligible_peer(tmp_path, kind):
    evidence = paired_evidence(tmp_path)
    block(evidence, kind)
    row = evidence.transport.observe(evidence.target)
    assert row['verified_identity'] and not row['idle'] and 'error' not in row
    assert 'model_evidence' not in row
    if kind != 'prompt':
        assert row['blocked_tasks'] and row['busy']
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    first = instance.tick(apply=False)
    assert first['phase'] == 'candidate' and first['candidate']['pid'] == 200
    assert not instance.disable_path.exists() and not instance.state_path.exists()
    # Clearing the ordinary blocker makes its exact model proof mandatory again.
    evidence.screen = IDLE
    evidence.native['native_execution_state'] = 'idle_candidate'
    evidence.native['active_tools'] = []
    evidence.records.pop(300, None)
    second = instance.tick(apply=False)
    assert second['phase'] == 'candidate' and second['candidate']['pid'] == 100
    assert second['candidate']['model_evidence']['model_label'] == 'Gemini 3 Pro'
    assert evidence.inputs == []


@pytest.mark.parametrize('kind', ['prompt', 'busy', 'task'])
def test_blocked_session_id_mismatch_still_latches_before_any_peer_input(tmp_path, kind):
    evidence = paired_evidence(tmp_path)
    block(evidence, kind)
    evidence.log_paths[100][0].write_text(f'conversation_id="{OTHER_CID}"\n')
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    report = instance.tick(apply=True)
    assert report['phase'] == 'disabled' and 'conversation' in report['disable_reason']
    assert instance.disable_path.exists() and evidence.inputs == []


def test_blocked_footerless_session_does_not_waive_unknown_listener_measurement(tmp_path):
    evidence = paired_evidence(tmp_path)
    block(evidence, 'prompt')
    original = evidence.supervisor.runner
    def runner(args, **kwargs):
        if args[0] == '/usr/sbin/lsof' and '-p' in args and args[args.index('-p') + 1] == '100' and '-sTCP:LISTEN' in args:
            return evidence.response(returncode=1)
        return original(args, **kwargs)
    evidence.supervisor.runner = runner
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    report = instance.tick(apply=True)
    assert report['phase'] == 'disabled' and 'measurement is unknown' in report['disable_reason']
    assert evidence.inputs == []


def test_cleared_blocker_with_wrong_idle_model_remains_a_fatal_proof_failure(tmp_path):
    evidence = paired_evidence(tmp_path)
    block(evidence, 'prompt')
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    assert instance.tick(apply=False)['phase'] == 'candidate'
    evidence.screen = IDLE.replace('Gemini 3 Pro', 'Gemini 3 Pro Max')
    report = instance.tick(apply=False)
    assert report['phase'] == 'disabled' and 'model and effort' in report['disable_reason']
    with pytest.raises(guard.GuardError, match='no longer verified idle'):
        evidence.transport.quit(evidence.target)
    assert evidence.inputs == []


@pytest.mark.parametrize('identity_problem', ['absent', 'nonmatching'])
def test_canary_excludes_other_idle_targets_without_requiring_restart_model(tmp_path, identity_problem):
    evidence = paired_evidence(tmp_path)
    evidence.supervisor.config['port_pressure']['restart_repository_keys'] = ['culturemech']
    if identity_problem == 'absent':
        evidence.target.pop('port_pressure_identity')
    else:
        evidence.target['port_pressure_identity']['model_label'] = 'Gemini 3 Pro Max'
    row = evidence.transport.observe(evidence.target)
    assert row['verified_identity'] and row['idle'] and 'error' not in row
    assert 'model_evidence' not in row
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    report = instance.tick(apply=False)
    assert report['phase'] == 'candidate' and report['candidate']['pid'] == 200
    assert not instance.disable_path.exists() and not instance.state_path.exists()
    with pytest.raises(guard.GuardError, match='model'):
        evidence.transport.quit(evidence.target)
    assert evidence.inputs == []
    # The same target becomes subject to exact model proof when allowlisted.
    evidence.supervisor.config['port_pressure']['restart_repository_keys'].append('traitmech')
    updated = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    rejected = updated.tick(apply=False)
    assert rejected['phase'] == 'disabled' and 'model' in rejected['disable_reason']
    assert evidence.inputs == []


@pytest.mark.parametrize('exclusion', ['canary', 'dispatched'])
def test_excluded_target_id_mismatch_still_latches(tmp_path, exclusion):
    evidence = paired_evidence(tmp_path)
    if exclusion == 'canary':
        evidence.supervisor.config['port_pressure']['restart_repository_keys'] = ['culturemech']
    evidence.target.pop('port_pressure_identity')
    evidence.log_paths[100][0].write_text(f'conversation_id="{OTHER_CID}"\n')
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    report = instance.tick(apply=True, excluded_repository_keys=('traitmech',) if exclusion == 'dispatched' else ())
    assert report['phase'] == 'disabled' and 'conversation' in report['disable_reason']
    assert instance.disable_path.exists() and evidence.inputs == []


@pytest.mark.parametrize('exclusion', ['canary', 'dispatched'])
def test_excluded_target_unknown_measurement_still_latches(tmp_path, exclusion):
    evidence = paired_evidence(tmp_path)
    if exclusion == 'canary':
        evidence.supervisor.config['port_pressure']['restart_repository_keys'] = ['culturemech']
    evidence.target.pop('port_pressure_identity')
    original = evidence.supervisor.runner
    def runner(args, **kwargs):
        if args[0] == '/usr/sbin/lsof' and '-p' in args and args[args.index('-p') + 1] == '100' and '-sTCP:LISTEN' in args:
            return evidence.response(returncode=1)
        return original(args, **kwargs)
    evidence.supervisor.runner = runner
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    report = instance.tick(apply=True, excluded_repository_keys=('traitmech',) if exclusion == 'dispatched' else ())
    assert report['phase'] == 'disabled' and 'measurement is unknown' in report['disable_reason']
    assert evidence.inputs == []


@pytest.mark.parametrize('identity_problem', ['absent', 'nonmatching', 'missing_footer'])
def test_recent_dispatch_exclusion_defers_model_proof_until_next_tick(tmp_path, identity_problem):
    evidence = paired_evidence(tmp_path)
    if identity_problem == 'absent':
        evidence.target.pop('port_pressure_identity')
    elif identity_problem == 'nonmatching':
        evidence.target['port_pressure_identity']['model_label'] = 'Gemini 3 Pro Max'
    else:
        evidence.screen = IDLE.replace('Gemini 3 Pro | high\n', '')
    instance = guard.PortPressureGuard(evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now)
    # Native goal/UI acceptance lags: still idle, but the supervisor just sent
    # this target a goal and explicitly excludes it for this tick.
    report = instance.tick(apply=False, excluded_repository_keys=('traitmech',))
    assert report['phase'] == 'candidate' and report['candidate']['pid'] == 200
    assert not instance.disable_path.exists() and not instance.state_path.exists()
    observation = evidence.transport.observe(evidence.target)
    assert observation['observation']['native']['native_execution_state'] == 'idle_candidate'
    assert 'error' not in observation
    if identity_problem != 'missing_footer':
        assert observation['idle']
    next_tick = instance.tick(apply=False)
    assert next_tick['phase'] == 'disabled' and 'model' in next_tick['disable_reason']
    assert evidence.inputs == []


@pytest.mark.parametrize('wrong_model', [False, True])
def test_resumed_model_is_proved_even_when_observer_excludes_target(tmp_path, wrong_model):
    evidence = Evidence(tmp_path)
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.supervisor.config['port_pressure']['restart_repository_keys'] = []
    if wrong_model:
        evidence.screen = IDLE.replace('Gemini 3 Pro', 'Gemini 3 Pro Max')
        with pytest.raises(guard.GuardError, match='model and effort'):
            evidence.transport.wait_resumed(evidence.target, 45)
    else:
        result = evidence.transport.wait_resumed(evidence.target, 45)
        assert result['pid'] == 200 and result['listeners'] == 2
    assert evidence.inputs == []


SIGNIN = 'Sign in with your organization\n'
MIXED = SIGNIN + SURVEY


@pytest.mark.parametrize('frames,reads,sleeps,message', [
    ([MIXED], 1, [], 'human prompt during resume'),
    ([SURVEY], 1, [], 'human prompt during resume'),
    ([SIGNIN, SIGNIN], 2, [1.0], 'sign-in evidence remains after fresh reread; current runtime is unverified'),
    ([SIGNIN, SURVEY], 2, [1.0], 'human prompt during resume'),
    ([SIGNIN, MIXED], 2, [1.0], 'human prompt during resume'),
])
def test_resume_prompt_diagnostic_reports_only_the_reads_that_happened(tmp_path, frames, reads, sleeps, message):
    evidence = Evidence(tmp_path)
    evidence.transport.preflight(evidence.target)
    evidence.exited()
    evidence.resumed()
    evidence.screen = frames[0]
    seen, waited = [], []
    original = evidence.transport.snapshot
    def snapshot(target):
        seen.append(evidence.screen)
        return original(target)
    def sleep(seconds):
        waited.append(seconds)
        evidence.sleep(seconds)
        evidence.screen = frames[min(len(waited), len(frames) - 1)]
    evidence.transport.snapshot = snapshot
    evidence.transport.sleep = sleep
    with pytest.raises(guard.GuardError) as error:
        evidence.transport.wait_resumed(evidence.target, 45)
    assert str(error.value) == message
    assert len(seen) == reads and waited == sleeps and evidence.inputs == []
