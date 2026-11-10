"""Verified goal-boundary recycling is ordered before one new goal, offline (#802)."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_mech_session_supervisor import (
    GOAL,
    cycle_instance,
    supervisor,
    write_goal_evidence,
)
from test_mech_session_supervisor import cycle_setup as cycle_setup
from test_mech_session_supervisor import setup as setup


def assert_bounded_goal_instruction(instance, fixture, ledger, wire):
    actions = [action for action in ledger['actions'].values() if action['kind'] == 'start_goal']
    assert len(actions) == 1
    action = actions[0]
    assert action['state'] == 'uncertain'  # Sending the reference is not native acceptance.
    assert 'action' not in supervisor.decide(ledger, fixture.observation)
    assert wire == action['message'] and len(wire.encode('utf-8')) <= 512
    assert wire.startswith(f"/goal [MECH-WORKFLOW-{action['id']}] Read ")
    assert hashlib.sha256(wire.encode()).hexdigest() == action['message_sha256']
    reference = action['instruction_artifact']
    path = Path(reference['path'])
    assert path == instance.directory(fixture.target) / 'instructions' / (action['id'] + '.json')
    assert json.dumps(str(path)) in wire and reference['sha256'] in wire
    raw = path.read_bytes()
    assert len(raw) == reference['bytes']
    assert hashlib.sha256(raw).hexdigest() == reference['sha256']
    artifact = json.loads(raw)
    decision = {'action': 'start_goal', 'action_id': action['id']}
    expected = supervisor.message_for(fixture.target, ledger, decision, instance.directory(fixture.target))
    assert artifact['instruction'] == expected and expected not in wire
    for key in ('cycle', 'stage', 'run_id', 'repository_key'):
        assert artifact[key] == ledger[key]
    assert artifact['action_id'] == action['id'] and artifact['kind'] == 'start_goal'
    assert artifact['stage_key'] == supervisor.workflow_stage_key(ledger)
    assert artifact['native_session_id'] == fixture.target['native_session_id']
    assert artifact['reservation_goal_identity'] == ledger['adopted_goal']
    assert artifact['workflow_sha256'] == ledger['workflow']['sha256']
    workflow = instance.directory(fixture.target) / 'effective-workflow.json'
    assert artifact['instruction_sha256'] == hashlib.sha256(workflow.read_bytes()).hexdigest()
    return artifact


def prepare(cycle_setup, monkeypatch, *, phase='restarted', mode='restart', send=None):
    fixture = cycle_setup
    events = []
    def deliver(_source, payload):
        events.append(('goal', payload['pid'], payload['message']))
        return send() if send else 'sent'
    instance = cycle_instance(fixture, monkeypatch, send=deliver)
    fixture.config['port_pressure'] = {'mode': mode}
    def pressure(*, apply=False, boundary=None, **_kwargs):
        events.append(('pressure', apply, copy.deepcopy(boundary)))
        if boundary is None:
            return {'phase': 'candidate', 'candidate': {'repository_key': 'unrelated'}}
        assert boundary['goal_identity'] == GOAL
        result = {'phase': phase}
        if phase == 'restarted':
            old = fixture.target['pid']
            fixture.target.update(pid=5678, process_identity='5678 ttys030 resumed agy')
            result.update(old_pid=old, new_pid=5678, listeners=2)
        return result
    monkeypatch.setattr(instance, 'port_pressure', pressure)
    receipt = write_goal_evidence(fixture, fixture.ledger)
    fixture.remote.snapshot()
    instance.save(fixture.target, fixture.ledger)
    supervisor.atomic_json(instance.directory(fixture.target) / 'completion.json', receipt)
    return fixture, instance, events


def test_verified_completion_recycles_target_then_dispatches_one_new_goal(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    original_verify = supervisor.verify_remote_receipt
    def verify(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        events.append(('verified', result['status']))
        return result
    monkeypatch.setattr(supervisor, 'verify_remote_receipt', verify)
    dashboard = instance.sweep(apply=True)
    assert events[0] == ('pressure', False, None)  # Only observation, never fallback recycle.
    assert [event[0] for event in events] == ['pressure', 'verified', 'pressure', 'goal']
    boundary = events[2][2]
    assert boundary['next_stage_key'] == 'causal_graphs'
    assert boundary['pid'] == 1234 and events[3][1] == 5678
    ledger = supervisor.read_json(instance.directory(fixture.target) / 'ledger.json')
    assert ledger['port_pressure_boundary']['phase'] == 'restarted'
    assert ledger['port_pressure_boundary']['new_pid'] == 5678
    artifact = assert_bounded_goal_instruction(instance, fixture, ledger, events[3][2])
    assert artifact['stage'] == 2 and artifact['stage_key'] == 'causal_graphs'
    assert artifact['instruction'].startswith('/goal Use the canonical skill for stage 2')
    assert 'stage 2' in artifact['instruction']
    assert dashboard['port_pressure']['phase'] == 'restarted'


@pytest.mark.parametrize('phase', ['candidate', 'blocked', 'limited', 'disabled', 'unknown'])
def test_unsatisfied_boundary_persists_hold_without_dispatch(cycle_setup, monkeypatch, phase):
    fixture, instance, events = prepare(cycle_setup, monkeypatch, phase=phase)
    dashboard = instance.sweep(apply=True)
    assert not any(event[0] == 'goal' for event in events)
    marker = supervisor.read_json(instance.directory(fixture.target) / 'ledger.json')['port_pressure_boundary']
    assert marker['phase'] == phase
    assert dashboard['sessions'][0]['delivery'] == 'not-sent'
    assert sum(event[0] == 'pressure' and event[2] is not None for event in events) == 1


def test_report_candidate_holds_boundary_and_never_reserves_goal(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch, phase='candidate', mode='report')
    instance.sweep(apply=True)
    ledger = supervisor.read_json(instance.directory(fixture.target) / 'ledger.json')
    assert not ledger['actions'] and ledger['awaiting_goal']
    assert ledger['port_pressure_boundary']['phase'] == 'candidate'
    assert not any(event[0] == 'goal' for event in events)


def test_completed_recycle_is_not_repeated_after_unsent_goal_or_next_tick(cycle_setup, monkeypatch):
    outcomes = iter(['screen-changed', 'sent'])
    fixture, instance, events = prepare(cycle_setup, monkeypatch, send=lambda: next(outcomes))
    instance.sweep(apply=True)
    assert events[-1][0] == 'goal'
    first = supervisor.read_json(instance.directory(fixture.target) / 'ledger.json')
    assert first['port_pressure_boundary']['phase'] == 'restarted'
    instance.sweep(apply=True)
    assert sum(event[0] == 'pressure' and event[2] is not None for event in events) == 1
    assert sum(event[0] == 'goal' for event in events) == 2  # First send was definitively rejected.
    assert instance.config['targets'][0]['pid'] == 5678


def test_changed_same_conversation_goal_blocks_before_boundary_transaction(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    receipt = write_goal_evidence(fixture, fixture.ledger)
    ledger = instance.advance(fixture.target, fixture.ledger, receipt, {'status': 'merged'}, 'native_completed')
    decision = supervisor.decide(ledger, fixture.observation)
    fixture.observation['goal_identity'] = {**GOAL, 'start_step_index': GOAL['start_step_index'] + 1}
    result = instance.dispatch(fixture.target, ledger, decision)
    assert result['state'] == 'not-sent'
    assert events == []
    assert ledger['port_pressure_boundary']['phase'] == 'blocked'


def test_unverified_completion_cannot_trigger_recycle(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    fixture.ledger.update(stage=2, awaiting_goal=True, completed_stages=[{
        'goal_identity': GOAL, 'receipt_sha256': 'a' * 64,
        'verification': {'status': 'queued'}, 'completion_authority': 'native_completed'}])
    decision = supervisor.decide(fixture.ledger, fixture.observation)
    with pytest.raises(supervisor.SupervisorError, match='retained verified completion'):
        instance.dispatch(fixture.target, fixture.ledger, decision)
    assert events == []


def test_initial_adoption_is_not_a_goal_boundary(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    for stage in (0, 1):
        fixture.ledger.update(stage=stage, awaiting_goal=True, completed_stages=[])
        assert instance.goal_boundary(fixture.target, fixture.ledger,
                                      {'action': 'start_goal', 'action_id': 'initial'}) is None
    assert events == []


def test_next_cycle_boundary_uses_next_stage_key(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    stages = fixture.ledger['workflow']['effective']['stages']
    fixture.ledger['stage'] = next(stage['stage'] for stage in stages if stage['key'] == 'infrastructure')
    receipt = write_goal_evidence(fixture, fixture.ledger)
    fixture.remote.snapshot()
    next_cycle = instance.advance(fixture.target, fixture.ledger, receipt, {'status': 'merged'}, 'native_completed')
    context = instance.goal_boundary(fixture.target, next_cycle, supervisor.decide(next_cycle, fixture.observation))
    assert next_cycle['cycle'] == 2 and context['next_stage_key'] == stages[0]['key']
    assert context['goal_identity'] == GOAL and events == []


def test_one_recycle_per_tick_keeps_second_boundary_held(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    receipt = write_goal_evidence(fixture, fixture.ledger)
    ledger = instance.advance(fixture.target, fixture.ledger, receipt, {'status': 'merged'}, 'native_completed')
    instance._port_pressure_recycled = True
    result = instance.dispatch(fixture.target, ledger, supervisor.decide(ledger, fixture.observation))
    assert result['state'] == 'not-sent' and events == []
    assert ledger['port_pressure_boundary']['phase'] == 'limited'


def test_noncanary_next_goal_is_not_held_by_boundary_guard(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    fixture.config['port_pressure']['restart_repository_keys'] = []
    receipt = write_goal_evidence(fixture, fixture.ledger)
    ledger = instance.advance(fixture.target, fixture.ledger, receipt, {'status': 'merged'}, 'native_completed')
    result = instance.dispatch(fixture.target, ledger, supervisor.decide(ledger, fixture.observation))
    assert result['state'] == 'uncertain'  # Transport succeeded; native acceptance is still unproven.
    assert 'action' not in supervisor.decide(ledger, fixture.observation)
    assert [event[0] for event in events] == ['goal']
    assert 'port_pressure_boundary' not in ledger


def test_missing_next_goal_skill_blocks_before_recycle(cycle_setup, monkeypatch):
    fixture, instance, events = prepare(cycle_setup, monkeypatch)
    receipt = write_goal_evidence(fixture, fixture.ledger)
    ledger = instance.advance(fixture.target, fixture.ledger, receipt, {'status': 'merged'}, 'native_completed')
    (fixture.repo / '.claude/skills/example/SKILL.md').unlink()
    result = instance.dispatch(fixture.target, ledger, supervisor.decide(ledger, fixture.observation))
    assert result['state'] == 'not-sent' and events == []
    assert ledger['port_pressure_boundary']['phase'] == 'blocked'


@pytest.mark.parametrize('boundary_phase', ['healthy', 'blocked'])
def test_unrelated_host_warning_fallback_survives_boundary_and_excludes_dispatch_attempt(cycle_setup, monkeypatch, boundary_phase):
    fixture, instance, events = prepare(cycle_setup, monkeypatch, phase=boundary_phase)
    fallback_calls = []
    original = instance.port_pressure
    def pressure(*, apply=False, boundary=None, excluded_repository_keys=(), **kwargs):
        if boundary is None and apply:
            fallback_calls.append(excluded_repository_keys)
            return {'phase': 'restarted', 'old_pid': 9000, 'new_pid': 9001, 'listeners': 2}
        return original(apply=apply, boundary=boundary, **kwargs)
    monkeypatch.setattr(instance, 'port_pressure', pressure)
    dashboard = instance.sweep(apply=True)
    assert fallback_calls == [('traitmech',)]
    assert dashboard['port_pressure']['phase'] == 'restarted'
    assert dashboard['port_pressure']['initial_idle_scan']['phase'] == 'candidate'
    assert dashboard['port_pressure']['goal_boundaries'][0]['phase'] == boundary_phase
    assert any(event[0] == 'goal' for event in events) == (boundary_phase == 'healthy')


def test_fallback_exclusion_handles_delayed_native_goal_acceptance(cycle_setup, monkeypatch):
    from test_port_pressure import measurement, session

    from kg_microbe_workflows.port_pressure import decide
    fixture, instance, _events = prepare(cycle_setup, monkeypatch, phase='healthy')
    original = instance.port_pressure
    fallback = []
    def pressure(*, apply=False, boundary=None, excluded_repository_keys=(), **kwargs):
        if boundary is None and apply:
            # Native observations deliberately remain old/idle after the new
            # goal was sent; explicit tick exclusions carry dispatch authority.
            result = decide({}, measurement({1234: 4000, 9000: 1200}, host=9000),
                            [session(1234, 'traitmech'), session(9000, 'othermech')], {},
                            now=10000, excluded_repository_keys=excluded_repository_keys)
            fallback.append(result)
            return result
        return original(apply=apply, boundary=boundary, **kwargs)
    monkeypatch.setattr(instance, 'port_pressure', pressure)
    instance.sweep(apply=True)
    assert fallback[0]['candidate']['pid'] == 9000
    assert 'dispatch was attempted' in fallback[0]['excluded'][0]['reasons'][0]
    assert fixture.observation['goal_identity'] == GOAL
