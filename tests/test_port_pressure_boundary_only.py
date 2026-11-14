"""The canary cannot recycle an otherwise idle session between goal boundaries."""

import pytest

from kg_microbe_workflows.port_pressure import decide, normalize_config


def choose(*, boundary=False, count=4013, host=12293, config=None, session=None, state=None):
    target = {
        'repository_key': 'communitymech', 'pid': 42,
        'conversation_ids': {key: 'same-conversation' for key in ('index', 'supervisor', 'log')},
        'verified_identity': True, 'idle': True, 'busy': False, 'prompt': False,
        'blocked_tasks': [], **(session or {}),
    }
    return decide(
        {'mode': 'restart', 'restart_policy': 'goal_boundary_only',
         'restart_repository_keys': ['communitymech'], 'hourly_cap': 1, **(config or {})},
        {'known': True, 'host_listeners': host, 'per_pid': {42: count}, 'agy_pids': [42],
         'ephemeral_low': 49152, 'ephemeral_high': 65535},
        [target], state or {}, now=10_000,
        boundary={'repository_key': 'communitymech', 'pid': 42} if boundary else None,
    )


def test_critical_pressure_without_boundary_never_selects_idle_canary():
    result = choose()
    assert result['phase'] == 'blocked' and result['candidate'] is None
    assert result['healthy'] is False and result['triggers']
    assert 'verified goal boundary' in result['policy_hold']


def test_legacy_combined_policy_still_selects_idle_offender():
    assert normalize_config()['restart_policy'] == 'goal_boundary_or_idle'
    result = choose(config={'restart_policy': 'goal_boundary_or_idle'})
    assert result['phase'] == 'candidate' and result['candidate']['pid'] == 42


@pytest.mark.parametrize('value', ['boundary', '', None, True, 1, [], {}])
def test_unrecognized_policy_is_refused(value):
    with pytest.raises((ValueError, TypeError)):
        normalize_config({'restart_policy': value})
    result = choose(config={'restart_policy': value})
    assert result['phase'] == 'unknown' and result['candidate'] is None


def test_actual_boundary_uses_inclusive_500_threshold_despite_host_pressure():
    below = choose(boundary=True, count=499)
    at = choose(boundary=True, count=500)
    assert below['phase'] == 'healthy' and below['candidate'] is None
    assert at['phase'] == 'candidate' and at['candidate']['pid'] == 42


@pytest.mark.parametrize('session', [
    {'idle': False}, {'busy': True}, {'prompt': True}, {'busy': None},
    {'blocked_tasks': [{'kind': 'timer', 'state': 'running'}]},
])
def test_boundary_never_converts_busy_prompting_or_timer_work_to_idle(session):
    result = choose(boundary=True, session=session)
    assert result['phase'] == 'blocked' and result['candidate'] is None


def test_boundary_keeps_allowlist_hourly_cap_and_cooldown():
    result = choose(boundary=True, config={'restart_repository_keys': []})
    assert result['phase'] == 'off' and result['candidate'] is None
    result = choose(boundary=True, state={'restart_history': [
        {'repository_key': 'habitatmech', 'completed_at': 9999}]})
    assert result['phase'] == 'limited' and result['candidate'] is None
    result = choose(boundary=True, config={'hourly_cap': 2}, state={'restart_history': [
        {'repository_key': 'communitymech', 'completed_at': 9999}]})
    assert result['phase'] == 'blocked' and result['candidate'] is None


def test_boundary_only_still_fails_closed_on_unknown_identity():
    result = choose(session={'conversation_ids': {'index': 'changed', 'supervisor': 'same', 'log': 'same'}})
    assert result['phase'] == 'unknown' and result['candidate'] is None
    assert 'conversation-ID mismatch' in result['disable_reason']
