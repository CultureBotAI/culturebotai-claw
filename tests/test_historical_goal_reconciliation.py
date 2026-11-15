"""Sanitized DUF C3S5: separate historical closure, external goal and next dispatch."""
from __future__ import annotations

import copy
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_multi_pr_receipts import (  # noqa: F401 -- shared offline fixtures
    OrderedRemote,
    cycle_setup,
    duf,
    setup,
    supervisor,
    write_registry,
)

import kg_microbe_progress as progress
from kg_microbe_workflows import reconciliation as rec


@pytest.fixture
def case(duf):  # noqa: F811 -- shared pytest fixture
    # Synthetic compatible future receipt: intake is already in its verified
    # final closure head. Real DUF 365/367 lacks the later 455 task (test below).
    state = duf
    state.ledger['adopted_goal']['start_step_index'] = 10144
    state.receipt['goal_identity'] = copy.deepcopy(state.ledger['adopted_goal'])
    state.target['native_session_id'] = state.ledger['adopted_goal']['conversation_id']
    state.current = {**state.ledger['adopted_goal'], 'start_step_index': 11642,
                     'started_at': '2026-10-29T01:00:00Z'}
    notebook = state.repo / 'INFRA_TASKS.md'
    notebook.write_text(notebook.read_text().replace('tasks: []',
        'tasks:\n- task_id: DUF-INFRA-0004\n  summary: Adopt seven-goal profile through infrastructure closure\n  status: note'))
    state.receipt['goal_outputs']['infra_tasks']['sha256'] = rec.sha(notebook.read_bytes())
    state.remote = OrderedRemote(state)
    state.external = {'number': 387, 'head_sha': 'd' * 40, 'merge_commit_sha': 'e' * 40}
    state.proof = {'historical_goal_identity': state.ledger['adopted_goal'], 'current_goal_identity': state.current,
                   'historical_completions': [{'step_index': 11000}], 'current_completions': [{'step_index': 12000}]}
    state.instance.native = SimpleNamespace(reconciliation_evidence=lambda *args: copy.deepcopy(state.proof))
    def runner(args, **kwargs):
        if args[:3] == ['git', '-C', str(supervisor.ROOT)]:
            assert args[3:] in [['rev-parse', 'HEAD'], ['status', '--porcelain=v1', '--untracked-files=all']]
            out = 'f' * 40 if args[3] == 'rev-parse' else ''
        elif args == ['git', '-C', str(state.repo), 'show', 'HEAD:INFRA_TASKS.md']:
            out = notebook.read_text()
        elif args == ['gh', 'api', 'repos/CultureBotAI/DUFMech/pulls/387']:
            out = json.dumps({'merged': True, 'head': {'sha': state.external['head_sha']},
                'merge_commit_sha': state.external['merge_commit_sha'],
                'base': {'repo': {'full_name': state.target['github_repository']}}})
        else:
            return state.remote(args, **kwargs)
        return SimpleNamespace(stdout=out, stderr='', returncode=0)
    state.instance.runner = runner
    state.instance.notifier = object()  # No terminal-capable object is available.
    state.config_path = state.runtime / 'config.json'
    state.config_path.write_text(json.dumps(state.config))
    state.instance.save(state.target, state.ledger)
    (state.session / 'completion.json').write_text(json.dumps(state.receipt))
    write_registry(state)
    (state.runtime / 'STOP').write_text('operator maintenance\n')
    state.review = state.runtime / 'independent-review.md'
    state.review.write_text('Synthetic independent exact-record review.\n')
    state.record_path = state.runtime / 'assessment.json'
    state.record = new_record(state)
    write_record(state)
    return state


def new_record(state, operation='close_historical_goal', prior=None):
    ledger = json.loads((state.session / 'ledger.json').read_text())
    now = datetime.now(timezone.utc)
    return {'schema_version': '1.0.0', 'operation': operation, 'record_status': 'reviewed',
        'assessed_at': (now - timedelta(minutes=1)).isoformat(), 'expires_at': (now + timedelta(hours=1)).isoformat(),
        'requested_by': 'synthetic operator', 'reason': 'Preserve historical closure identity and separate external work',
        'repository_key': state.target['repository_key'], 'run_id': ledger['run_id'], 'cycle': ledger['cycle'],
        'stage': ledger['stage'], 'parent_version': ledger['parent_version'], 'workflow_sha256': ledger['workflow']['sha256'],
        'historical_goal_identity': copy.deepcopy(ledger['adopted_goal']), 'current_goal_identity': state.current,
        'fingerprints': rec.fingerprints(state.config_path, state.session, state.target, state.proof),
        'required_infra_tasks': ['DUF-INFRA-0004'], 'external_pr': state.external,
        'review': {'reviewer': 'independent synthetic reviewer', 'artifact': state.review.name, 'sha256': rec.sha(state.review.read_bytes())},
        'prerequisites': [], 'reconciliation_sha256': prior, 'implementation_commit': 'f' * 40,
        'implementation_sha256': {p: rec.sha((supervisor.ROOT / p).read_bytes()) for p in rec.IMPLEMENTATION_PATHS}}


def write_record(state):
    state.record_path.write_text(json.dumps(state.record, indent=2) + '\n')


def apply(state):
    return rec.prepare(state.instance, supervisor, state.config_path, state.record_path,
                       rec.sha(state.record_path.read_bytes()), apply=True)


def read_ledger(state):
    return json.loads((state.session / 'ledger.json').read_text())


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_dry_run_and_atomic_closure_preserve_historical_identity(case):
    before = tree(case.runtime)
    plan = rec.prepare(case.instance, supervisor, case.config_path, case.record_path)
    assert tree(case.runtime) == before and plan['to_stage'] == 6 and not plan['sent_input']
    result = apply(case)
    ledger = read_ledger(case)
    assert result['status'] == 'applied'
    audit = json.loads(next((case.session / 'operator-reconciliations').glob('*/audit.json')).read_text())
    assert audit['result']['status'] == 'prepared'
    assert audit['result']['ledger_after_sha256'] == rec.canonical(ledger)
    assert ledger['adopted_goal']['start_step_index'] == 10144
    assert ledger['completed_stages'][-1]['goal_identity']['start_step_index'] == 10144
    assert ledger['completed_stages'][:-1] == case.ledger['completed_stages']
    assert ledger['actions'] == case.ledger['actions'] and ledger['workflow'] == case.ledger['workflow']
    assert ledger['cycle'] == 3 and ledger['stage'] == 6 and ledger['awaiting_goal']
    assert [p['pr_number'] for p in ledger['completed_stages'][-1]['verification']['prs']] == [365, 367]
    assert ledger['infra_scope']['tasks'][0]['task_id'] == 'DUF-INFRA-0004'
    assert ledger['historical_goal_boundary']['released_by'] is None
    assert (case.runtime / 'STOP').is_file()
    after = tree(case.runtime)
    assert apply(case)['status'] == 'already_applied' and tree(case.runtime) == after


def release(state):
    prior = apply(state)['reconciliation_sha256']
    state.record = new_record(state, 'release_boundary', prior)
    state.record_path = state.runtime / 'release.json'
    write_record(state)
    apply(state)
    return read_ledger(state)


def exact_start_input(state, action, identity):
    """Synthetic native full-input proof, separate from goal text or transport."""
    action.setdefault('message', '/goal next reviewed objective [' + action['marker'] + ']')
    action.setdefault('native_step_index', state.ledger['adopted_goal']['start_step_index'])
    observation = copy.deepcopy(state.observation)
    observation.update(goal_identity=copy.deepcopy(identity))
    observation['native'].update(conversation_id=identity['conversation_id'], root=state.target['root'],
        workspace_identity={'verified': True},
        current_goal={**identity, 'state': 'completed', 'goal_text': action['message']},
        user_input_evidence={'schema_version': 1, 'truncated': False, 'inputs': [{
            'step_index': identity['start_step_index'], 'status_number': 3, 'created_at': identity['started_at'],
            'supported_input_shape': True, 'text_sha256': rec.sha(action['message'].encode()),
            'text_length': len(action['message']), 'native_goal_declaration': True}]})
    return observation


def test_release_never_sends_and_future_dispatch_retains_readiness_identity_duplicate_gates(case):
    ledger = release(case)
    observation = {**case.observation, 'goal_identity': case.current}
    decision = supervisor.decide(ledger, observation)
    assert decision['action'] == 'start_goal'
    assert supervisor.decide(ledger, {**observation, 'ready': False})['phase'] == 'waiting'
    assert supervisor.decide(ledger, {**observation, 'goal_state': 'active'})['phase'] == 'blocked'
    assert supervisor.decide(ledger, case.observation)['phase'] == 'blocked'
    ledger['actions'][decision['action_id']] = {'kind': 'start_goal', 'stage': 6, 'cycle': 3,
        'goal_identity': ledger['adopted_goal'], 'state': 'sent', 'marker': 'unique-next-goal',
        'native_session_id': case.current['conversation_id'], 'reserved_epoch_ms': 0}
    assert supervisor.decide(ledger, observation)['phase'] == 'awaiting_native_acceptance'
    # An external goal that repeats the marker is not the newly dispatched goal.
    observation['native']['current_goal']['goal_text'] = 'unique-next-goal'
    case.instance.reconcile(case.target, ledger, observation)
    assert ledger['awaiting_goal']
    next_goal = {**case.current, 'start_step_index': 13000, 'started_at': '2026-11-07T01:00:00Z'}
    observation = exact_start_input(case, ledger['actions'][decision['action_id']], next_goal)
    case.instance.reconcile(case.target, ledger, observation)
    assert ledger['adopted_goal'] == next_goal and not ledger['awaiting_goal']
    assert 'historical_goal_boundary' not in ledger
    assert len(ledger['completed_stages']) == len(case.ledger['completed_stages']) + 1


def test_unreleased_boundary_blocks_even_with_stale_receipt_and_fake_pending_marker(case):
    apply(case)
    ledger = read_ledger(case)
    obs = {**case.observation, 'goal_identity': case.current}
    assert supervisor.decide(ledger, obs)['phase'] == 'blocked'
    with pytest.raises(rec.ReconciliationError, match='separate operator release'):
        rec.boundary_goal(ledger)
    ledger['actions']['fake'] = {'kind': 'start_goal', 'stage': 6, 'cycle': 3,
        'goal_identity': ledger['adopted_goal'], 'state': 'sent', 'marker': 'fake-next',
        'native_session_id': case.current['conversation_id'], 'reserved_epoch_ms': 0}
    obs['native']['current_goal']['goal_text'] = 'fake-next'
    case.instance.reconcile(case.target, ledger, obs)
    assert ledger['awaiting_goal'] and ledger['adopted_goal']['start_step_index'] == 10144


@pytest.mark.parametrize('name', rec.FINGERPRINTS)
def test_any_changed_fingerprint_refuses_without_writes(case, name):
    case.record['fingerprints'][name] = '0' * 64
    write_record(case)
    before = tree(case.runtime)
    with pytest.raises(rec.ReconciliationError, match='live fingerprint'):
        apply(case)
    assert tree(case.runtime) == before


@pytest.mark.parametrize('failure', ['receipt', 'intake', 'external', 'review', 'source', 'approval', 'stop'])
def test_missing_authority_or_prerequisite_preserves_state(case, failure):
    if failure == 'receipt':
        case.receipt['issues'][0]['fix_commit_sha'] = '0' * 40
        (case.session / 'completion.json').write_text(json.dumps(case.receipt))
        case.record['fingerprints'] = rec.fingerprints(case.config_path, case.session, case.target, case.proof)
    elif failure == 'intake':
        case.record['required_infra_tasks'] = ['missing-committed-intake']
    elif failure == 'external':
        case.record['external_pr'] = {**case.external, 'number': 365}
    elif failure == 'review':
        case.record['review']['sha256'] = '0' * 64
    elif failure == 'source':
        case.record['implementation_sha256'][rec.IMPLEMENTATION_PATHS[0]] = '0' * 64
    elif failure == 'stop':
        (case.runtime / 'STOP').unlink()
    write_record(case)
    before = tree(case.runtime)
    with pytest.raises((ValueError, FileNotFoundError, supervisor.SupervisorError)):
        if failure == 'approval':
            rec.prepare(case.instance, supervisor, case.config_path, case.record_path, '0' * 64, apply=True)
        else:
            apply(case)
    assert tree(case.runtime) == before


def test_change_during_validation_and_auxiliary_write_failure_cannot_commit_ledger(case, monkeypatch):
    original = (case.session / 'ledger.json').read_bytes()
    calls = 0
    def changing_proof(*args):
        nonlocal calls
        calls += 1
        return case.proof if calls == 1 else {**case.proof, 'changed': True}
    case.instance.native.reconciliation_evidence = changing_proof
    with pytest.raises(rec.ReconciliationError, match='during verification'):
        apply(case)
    assert (case.session / 'ledger.json').read_bytes() == original
    case.instance.native.reconciliation_evidence = lambda *args: case.proof
    def fail(*args, **kwargs):
        raise OSError('simulated interrupted auxiliary transaction')
    monkeypatch.setattr(rec.ValidatedWriteTransaction, 'commit', fail)
    with pytest.raises(OSError, match='interrupted'):
        apply(case)
    assert (case.session / 'ledger.json').read_bytes() == original


def test_post_auxiliary_drift_leaves_ledger_uncommitted_and_retry_held(case):
    original = (case.session / 'ledger.json').read_bytes()
    calls = 0
    def changing_proof(*args):
        nonlocal calls
        calls += 1
        return case.proof if calls < 3 else {**case.proof, 'changed': True}
    case.instance.native.reconciliation_evidence = changing_proof
    with pytest.raises(rec.ReconciliationError, match='before ledger commit'):
        apply(case)
    assert (case.session / 'ledger.json').read_bytes() == original
    audits = list((case.session / 'operator-reconciliations').glob('*/audit.json'))
    assert len(audits) == 1
    audit = json.loads(audits[0].read_text())
    assert audit['result']['status'] == 'prepared'
    assert audit['commit_point'] == 'atomic ledger replacement'
    case.instance.native.reconciliation_evidence = lambda *args: case.proof
    with pytest.raises(rec.ReconciliationError, match='append-only'):
        apply(case)


def test_record_closed_contract_draft_and_release_tampering(case):
    draft = copy.deepcopy(case.record)
    draft.update(record_status='draft', review=None, prerequisites=['ordered receipt not ready'])
    rec.validate_record(draft)
    with pytest.raises(rec.ReconciliationError, match='draft'):
        rec.validate_record(draft, reviewed=True)
    with pytest.raises(rec.ReconciliationError, match='closed contract'):
        rec.validate_record({**draft, 'allow_identity_override': True})
    with pytest.raises(rec.ReconciliationError, match='duplicate JSON'):
        rec.decode(b'{"stage":5,"stage":6}')
    with pytest.raises(rec.ReconciliationError, match='nonfinite'):
        rec.decode(b'{"stage":NaN}')
    ledger = release(case)
    release_id = ledger['historical_goal_boundary']['released_by']
    changed = ledger['historical_releases'].pop(release_id)
    changed['historical_goal_identity'] = {**changed['historical_goal_identity'], 'start_step_index': 10143}
    new_id = rec.canonical(changed)
    ledger['historical_releases'][new_id] = changed
    ledger['historical_goal_boundary']['released_by'] = new_id
    with pytest.raises(rec.ReconciliationError, match='release context'):
        rec.boundary_goal(ledger)


def test_cli_apply_requires_stopped_exclusive_supervisor_and_input_locks(case, monkeypatch, capsys):
    import sys
    scripts = str(supervisor.ROOT / 'scripts')
    monkeypatch.syspath_prepend(scripts)
    spec = importlib.util.spec_from_file_location('reconcile_cli', Path(scripts) / 'mech_goal_reconcile.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setitem(sys.modules, 'mech_session_supervisor', supervisor)
    monkeypatch.setattr(cli.supervisor, 'validate_config', lambda c: c)
    monkeypatch.setattr(cli.supervisor, 'Supervisor', lambda *a, **kw: case.instance)
    case.config['native_reader_path'] = str(supervisor.ROOT / 'scripts/mech_session_native.py')
    case.config_path.write_text(json.dumps(case.config))
    locks = Path(case.config['input_lock_dir'])
    locks.mkdir()
    arguments = ['--record', str(case.record_path), '--config', str(case.config_path), '--apply',
                 '--approved-sha256', rec.sha(case.record_path.read_bytes())]
    monkeypatch.setattr(cli, 'prepare', lambda *a, **kw: {'status': 'lock-tested', 'sent_input': False})
    with cli.lock(case.runtime / 'supervisor.lock'):
        with pytest.raises(BlockingIOError):
            cli.main(arguments)
    with cli.lock(locks / 'ttys030.lock'):
        with pytest.raises(BlockingIOError):
            cli.main(arguments)
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'lock-tested'


def test_real_duf_late_adoption_intake_cannot_be_falsely_attributed_to_367(case):
    # Actual chronology: 365 fixes, 367 manifest repair, 455 later adoption task.
    # The local task cannot be smuggled into either old head by updating a receipt.
    old_notebook = (case.repo / 'INFRA_TASKS.md').read_text().split('tasks:')[0] + 'tasks: []\n```\n<!-- mech-infra-tasks:end -->\n'
    for branch in case.remote.trees.values():
        branch['INFRA_TASKS.md'] = case.remote.blob(old_notebook.encode())
    before = tree(case.runtime)
    with pytest.raises(supervisor.SupervisorError, match='committed|head|versioned|artifact'):
        apply(case)
    assert tree(case.runtime) == before


def test_progress_counts_only_historical_stage5_and_both_ordered_prs(case):
    _, before = progress.collect_progress([case.runtime])
    apply(case)
    history, after = progress.collect_progress([case.runtime])
    assert after['totals']['completed_goals'] == before['totals']['completed_goals'] + 1
    assert after['totals']['completed_cycles'] == before['totals']['completed_cycles'] == 0
    assert after['totals']['unique_prs'] == after['totals']['merged_prs'] == 2
    assert len(history['associations']) == 2
    public = json.dumps({'history': history, 'snapshot': after})
    assert 'synthetic-duf-native-goal' not in public and 'start_step_index' not in public
    assert '11642' not in public
    assert '#387' not in public and '/pull/387' not in public


@pytest.mark.parametrize('drift', ['profile', 'snapshot', 'archive'])
def test_ordinary_workflow_pin_drift_cannot_reconcile(case, drift):
    case.target.pop('workflow_next_profile_path', None)
    case.config_path.write_text(json.dumps(case.config))
    case.record['fingerprints'] = rec.fingerprints(case.config_path, case.session, case.target, case.proof)
    write_record(case)
    case.instance.check_workflow(case.target, case.ledger)
    if drift == 'profile':
        path = Path(case.target['workflow_profile_path'])
        profile = json.loads(path.read_text())
        profile['stages'][0]['goal_text'] += ' unreviewed change'
        path.write_text(json.dumps(profile))
    else:
        path = (case.session / 'effective-workflow.json' if drift == 'snapshot' else
                case.session / 'cycles/cycle-000003/effective-workflow.json')
        data = json.loads(path.read_text())
        data['effective']['stages'][0]['goal_text'] += ' unreviewed change'
        path.write_text(json.dumps(data))
    before = tree(case.runtime)
    with pytest.raises((supervisor.SupervisorError, rec.ReconciliationError), match='pinned|archived'):
        apply(case)
    assert tree(case.runtime) == before


def test_matching_workflow_snapshots_are_not_rewritten_and_queued_profile_is_retained(case):
    case.instance.check_workflow(case.target, case.ledger)
    paths = [case.session / 'effective-workflow.json', case.session / 'cycles/cycle-000003/effective-workflow.json']
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    # Existing supported same-path queued candidate does not rewrite active contract.
    profile = Path(case.target['workflow_profile_path'])
    profile.write_text(profile.read_text() + '\n')
    apply(case)
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths] == before


@pytest.mark.parametrize('missing', [False, True])
def test_workflow_drift_during_auxiliary_commit_is_still_held(case, monkeypatch, missing):
    original = (case.session / 'ledger.json').read_bytes()
    real_commit = rec.ValidatedWriteTransaction.commit
    def drift(*args, **kwargs):
        result = real_commit(*args, **kwargs)
        path = case.session / 'cycles/cycle-000003/effective-workflow.json'
        data = json.loads(path.read_text())
        data['effective']['stages'][0]['goal_text'] += ' changed after verification'
        if missing:
            path.unlink()
        else:
            path.write_text(json.dumps(data))
        return result
    monkeypatch.setattr(rec.ValidatedWriteTransaction, 'commit', drift)
    with pytest.raises((supervisor.SupervisorError, rec.ReconciliationError), match='archived|disappeared'):
        apply(case)
    assert (case.session / 'ledger.json').read_bytes() == original
    assert json.loads(next((case.session / 'operator-reconciliations').glob('*/audit.json')).read_text())['result']['status'] == 'prepared'


def _configure_later_intake_case(case):
    """Set up real DUF chronology: 365/367 have old notebook, 455 adds DUF-INFRA-0004 at HEAD."""
    current_notebook_bytes = (case.repo / 'INFRA_TASKS.md').read_bytes()
    old_notebook = (
        current_notebook_bytes.decode().split('\ntasks:')[0]
        + '\ntasks: []\n```\n<!-- mech-infra-tasks:end -->\n'
    )
    old_notebook_bytes = old_notebook.encode()
    old_blob = case.remote.blob(old_notebook_bytes)
    current_blob = case.remote.blob(current_notebook_bytes)
    for branch in case.remote.trees.values():
        branch['INFRA_TASKS.md'] = old_blob
    intake_pr = {
        'number': 455,
        'head_sha': 'a' * 40,
        'merge_commit_sha': 'de2fdf959acb5e7a1cb1e4139e6936f4ffdf5498',
    }
    case.remote.trees['HEAD'] = {**case.remote.current_tree, 'INFRA_TASKS.md': current_blob}
    case.remote.parents[intake_pr['merge_commit_sha']] = [case.receipt['prs'][-1]['merge_commit_sha']]
    case.remote.raw_changes[intake_pr['merge_commit_sha']] = ''
    case.remote.add_change(intake_pr['merge_commit_sha'], 'INFRA_TASKS.md', old_blob, current_blob)
    case.receipt['goal_outputs']['infra_tasks']['sha256'] = rec.sha(old_notebook_bytes)
    (case.session / 'completion.json').write_text(json.dumps(case.receipt))
    head_367 = case.receipt['pr']['head_sha']
    base_runner = case.instance.runner

    def runner(args, **kwargs):
        if args == ['git', '-C', str(case.repo), 'show', f'{head_367}:INFRA_TASKS.md']:
            return SimpleNamespace(stdout=old_notebook, stderr='', returncode=0)
        if args == ['gh', 'api', 'repos/CultureBotAI/DUFMech/pulls/455']:
            return SimpleNamespace(
                stdout=json.dumps({
                    'merged': True,
                    'head': {'sha': intake_pr['head_sha']},
                    'merge_commit_sha': intake_pr['merge_commit_sha'],
                    'base': {
                        'ref': case.target['default_branch'],
                        'repo': {'full_name': case.target['github_repository']},
                    },
                }),
                stderr='',
                returncode=0,
            )
        return base_runner(args, **kwargs)

    case.instance.runner = runner
    case.record = new_record(case)
    case.record['schema_version'] = '1.1.0'
    case.record['later_intake'] = {
        'historical_infra_notebook_sha256': rec.sha(old_notebook_bytes),
        'current_infra_notebook_sha256': rec.sha(current_notebook_bytes),
        'intake_pr': intake_pr,
    }
    write_record(case)
    return old_notebook_bytes, current_notebook_bytes, intake_pr


def test_later_intake_contract_reconciles_real_duf_chronology_and_releases_boundary(case):
    old_bytes, current_bytes, intake_pr = _configure_later_intake_case(case)
    _, before_progress = progress.collect_progress([case.runtime])
    result = apply(case)
    assert result['status'] == 'applied'
    ledger = read_ledger(case)
    reconciliation_id = result['reconciliation_sha256']
    entry = ledger['historical_reconciliations'][reconciliation_id]
    assert entry['later_intake_verification'] == {
        'number': 455,
        'head_sha': intake_pr['head_sha'],
        'merge_commit_sha': intake_pr['merge_commit_sha'],
        'merged': True,
        'historical_infra_notebook_sha256': rec.sha(old_bytes),
        'current_infra_notebook_sha256': rec.sha(current_bytes),
    }
    assert [p['pr_number'] for p in ledger['completed_stages'][-1]['verification']['prs']] == [365, 367]
    assert ledger['infra_scope']['tasks'][0]['task_id'] == 'DUF-INFRA-0004'
    history, after_progress = progress.collect_progress([case.runtime])
    assert after_progress['totals']['completed_goals'] == before_progress['totals']['completed_goals'] + 1
    assert after_progress['totals']['unique_prs'] == after_progress['totals']['merged_prs'] == 2
    public = json.dumps({'history': history, 'snapshot': after_progress})
    assert '#387' not in public and '/pull/387' not in public
    assert '#455' not in public and '/pull/455' not in public

    release_record = new_record(case, 'release_boundary', reconciliation_id)
    release_record['schema_version'] = '1.1.0'
    release_record['later_intake'] = copy.deepcopy(case.record['later_intake'])
    case.record = release_record
    case.record_path = case.runtime / 'release.json'
    write_record(case)
    apply(case)
    released = read_ledger(case)
    assert rec.boundary_goal(released) == case.current


@pytest.mark.parametrize('tamper', ['same_digest', 'duplicate_external', 'wrong_changes', 'already_in_367'])
def test_later_intake_contract_refuses_invalid_provenance(case, tamper):
    old_bytes, current_bytes, intake_pr = _configure_later_intake_case(case)
    if tamper == 'same_digest':
        case.record['later_intake']['historical_infra_notebook_sha256'] = rec.sha(current_bytes)
    elif tamper == 'duplicate_external':
        case.record['later_intake']['intake_pr']['number'] = 387
    elif tamper == 'wrong_changes':
        case.remote.add_change(
            intake_pr['merge_commit_sha'],
            'data/families/manifest.json',
            '0' * 40,
            case.remote.blob(b'changed\n'),
        )
    elif tamper == 'already_in_367':
        head_367 = case.receipt['pr']['head_sha']
        base_runner = case.instance.runner
        case.receipt['goal_outputs']['infra_tasks']['sha256'] = rec.sha(current_bytes)
        (case.session / 'completion.json').write_text(json.dumps(case.receipt))
        case.record['later_intake']['historical_infra_notebook_sha256'] = rec.sha(current_bytes)
        case.record['later_intake']['current_infra_notebook_sha256'] = 'b' * 64
        case.record['fingerprints'] = rec.fingerprints(case.config_path, case.session, case.target, case.proof)
        case.record['fingerprints']['infra_notebook_sha256'] = 'b' * 64

        def runner_same(args, **kwargs):
            if args == ['git', '-C', str(case.repo), 'show', f'{head_367}:INFRA_TASKS.md']:
                return SimpleNamespace(stdout=current_bytes.decode(), stderr='', returncode=0)
            return base_runner(args, **kwargs)

        case.instance.runner = runner_same
    write_record(case)
    before = tree(case.runtime)
    with pytest.raises((rec.ReconciliationError, supervisor.SupervisorError)):
        apply(case)
    assert tree(case.runtime) == before
