"""A verified six-to-seven migration reaches the new goal-boundary key (#725)."""
from test_mech_cycle_v2_migration import IssuePages, candidate, page, with_issues
from test_mech_session_supervisor import (
    GOAL,
    cycle_instance,
    supervisor,
    write_goal_evidence,
)
from test_mech_session_supervisor import (
    cycle_setup as cycle_setup,
)
from test_mech_session_supervisor import (
    setup as setup,
)


def test_seven_goal_migration_dispatches_new_stage_key_through_boundary(cycle_setup, monkeypatch):
    fixture = cycle_setup
    sent = []
    instance = cycle_instance(fixture, monkeypatch, send=lambda _source, payload: sent.append(payload) or 'sent')
    fixture.config['port_pressure'] = {'mode': 'restart'}
    effective = candidate(fixture)
    fixture.ledger['stage'] = next(s['stage'] for s in fixture.ledger['workflow']['effective']['stages']
                                    if s['key'] == 'infrastructure')
    receipt = write_goal_evidence(fixture, fixture.ledger)
    fixture.remote.snapshot()
    with_issues(instance, fixture.remote, IssuePages([page([])]))
    ledger = instance.advance(fixture.target, fixture.ledger, receipt, {'status': 'merged'}, 'native_completed')
    assert ledger['workflow']['effective'] == effective
    assert ledger['cycle'] == 2 and ledger['parent_version'] == '2.0.0'
    boundaries = []

    def pressure(*, apply=False, boundary=None, **kwargs):
        assert apply and boundary['goal_identity'] == GOAL
        boundaries.append(boundary)
        return {'phase': 'healthy'}

    monkeypatch.setattr(instance, 'port_pressure', pressure)
    decision = supervisor.decide(ledger, fixture.observation)
    result = instance.dispatch(fixture.target, ledger, decision)
    assert result['state'] == 'uncertain'  # Transport succeeded; native acceptance is still unproven.
    assert 'action' not in supervisor.decide(ledger, fixture.observation)
    assert len(boundaries) == len(sent) == 1
    assert boundaries[0]['next_stage_key'] == 'open_issue_triage'
    assert sent[0]['message'].startswith('/goal Use the native skill for open_issue_triage')
