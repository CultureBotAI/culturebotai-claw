"""Resident-loop rebind protocol; no Terminal, agent or live runtime access."""
import copy
import fcntl
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mech_approval_bindings', ROOT / 'scripts/mech_approval_bindings.py')
bindings = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bindings
spec.loader.exec_module(bindings)
spec = importlib.util.spec_from_file_location('prepare_approval', ROOT / 'scripts/prepare_mech_approval_binding_reload.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def write(path, data):
    path.write_bytes(bindings.encoded(data))


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monitor = tmp_path / 'monitor.py'
    monitor.write_text('# fixture monitor\n')
    target = {'pid': 42, 'tty': '/dev/ttys001', 'root': str(tmp_path),
              'process_identity': '42 old process', 'native_session_id': 'same-conversation'}
    approval_row = {'pid': 42, 'tty': target['tty'], 'cwd': target['root'],
                    'identity': target['process_identity'], 'started': 'old',
                    'recovery_identity': 'stable-before-restarts', 'native_session_id': target['native_session_id'],
                    'inline_approval_conversation_ids': ['unchanged-reviewer'], 'unknown': {'preserve': True}}
    targets, supervisor, controller = [tmp_path / name for name in ('targets.json', 'supervisor.json', 'controller.json')]
    status, journal = tmp_path / 'status.json', tmp_path / 'binding-reload.json'
    lockdir = tmp_path / 'input-locks'
    lockdir.mkdir()
    write(targets, [approval_row])
    write(supervisor, {'targets': [target], 'policy': 'untouched'})
    config = {'version': 1, 'state_dir': str(tmp_path), 'services': {'approvals': {
        'source_sha256': {str(path): bindings.digest(path.read_bytes()) for path in (monitor, targets, Path(bindings.__file__))},
        'session_targets_file': str(targets), 'status_file': str(status),
        'binding_reload': {'version': 1, 'journal': str(journal), 'adapter': bindings.__file__, 'input_lock_dir': str(lockdir)}}}}
    write(controller, config)
    now = [100.0]
    def identity_reader(pid):
        return {'pid': pid, 'started': 'resident-start'}
    monkeypatch.setattr(bindings, 'verify_consumer', lambda *args: None)
    resident = bindings.ResidentBindings(controller, targets, monitor, input_lock_dir=lockdir, clock=lambda: now[0], identity_reader=identity_reader, consumer_verifier=lambda *args: None)
    def acknowledge():
        resident.refresh()
        write(status, {'pid': os.getpid(), 'binding_reload': resident.acknowledgment()})
    acknowledge()
    def plan():
        return bindings.prepare_rebind(controller, [targets, supervisor], target, input_lock_dir=lockdir, now=lambda: now[0], identity_reader=identity_reader, consumer_verifier=lambda *args: None)
    def tick(_):
        now[0] += .1
        acknowledge()
    return SimpleNamespace(**locals(), new={'pid': 1042, 'tty': target['tty'], 'process_identity': '1042 new process', 'started': 'new'})


def test_resident_ack_and_budget_identity_survive_while_tty_lock_held(environment):
    e = environment
    history = e.tmp_path / 'attempts.json'
    write(history, {'attempts': [{'identity': 'stable-before-restarts', 'outcome': 'sent'}] * 3})
    original = history.read_bytes()
    recovery = SimpleNamespace(targets=copy.deepcopy(e.resident.targets))
    plan = e.plan()
    with (e.lockdir / 'ttys001.lock').open('w') as tty_lock:
        fcntl.flock(tty_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with bindings.rebind_lease(plan):
            receipt = bindings.install_rebind(plan, e.new, evidence={'boundary': 'verified', 'model': 'exact'})
            # A genuine resident instance reloads without the TTY lock, but input
            # remains forbidden while the installed transaction awaits ack.
            e.resident.refresh(recovery)
            assert not e.resident.current(recovery.targets[e.target['tty']])
            completed = bindings.await_rebind(plan, receipt, sleep=e.tick)
            assert completed['state'] == 'complete'
        assert e.resident.current(recovery.targets[e.target['tty']])
    assert recovery.targets[e.target['tty']]['pid'] == 1042
    assert recovery.targets[e.target['tty']]['recovery_identity'] == 'stable-before-restarts'
    assert history.read_bytes() == original
    assert recovery.targets[e.target['tty']]['inline_approval_conversation_ids'] == ['unchanged-reviewer']
    manifest = json.loads((Path(completed['evidence']) / 'prepared.json').read_text())
    assert manifest['restart_evidence_sha256']
    assert json.loads(e.controller.read_text())['services']['approvals']['source_sha256'][str(e.targets)] == bindings.digest(e.targets.read_bytes())
    assert (Path(completed['evidence']) / '00-before').exists()
    assert (Path(completed['evidence']) / 'acknowledgment.json').exists()


def test_static_monitor_or_stale_ack_refuses_before_any_write(environment):
    e = environment
    write(e.status, {'pid': os.getpid()})
    before = [p.read_bytes() for p in (e.targets, e.supervisor, e.controller)]
    with pytest.raises(bindings.BindingError, match='acknowledgment missing'):
        e.plan()
    assert before == [p.read_bytes() for p in (e.targets, e.supervisor, e.controller)]
    assert not e.journal.exists()


@pytest.mark.parametrize('field', ['generation', 'targets_sha256', 'config_sha256', 'source_sha256', 'effective', 'consumer', 'observed_at'])
def test_each_ack_proof_is_required(environment, field):
    e = environment
    data = json.loads(e.status.read_text())
    data['binding_reload'][field] = -999 if field == 'observed_at' else 'wrong'
    write(e.status, data)
    with pytest.raises(bindings.BindingError):
        e.plan()


def test_lifecycle_contention_blocks_before_rebind(environment):
    e = environment
    plan = e.plan()
    with (e.tmp_path / 'lifecycle.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(bindings.BindingError, match='lifecycle operation'):
            with bindings.rebind_lease(plan):
                pytest.fail('contended lease entered')
    assert not e.journal.exists()


@pytest.mark.parametrize('file', ['targets', 'supervisor', 'controller'])
def test_cas_prevents_overwrite_of_concurrent_change(environment, file):
    e = environment
    plan = e.plan()
    changed = getattr(e, file)
    changed.write_bytes(changed.read_bytes() + b'\n')
    expected = changed.read_bytes()
    with pytest.raises(bindings.BindingError, match='CAS drift|source pin mismatch'):
        with bindings.rebind_lease(plan):
            bindings.install_rebind(plan, e.new)
    assert changed.read_bytes() == expected and not e.journal.exists()


def test_no_effective_reload_never_reports_complete(environment):
    e = environment
    plan = e.plan()
    with bindings.rebind_lease(plan):
        receipt = bindings.install_rebind(plan, e.new)
        def tick(_):
            e.now[0] += .1
        with pytest.raises(bindings.BindingError, match='acknowledgment failed'):
            bindings.await_rebind(plan, receipt, timeout=.2, sleep=tick)
    assert json.loads(e.journal.read_text())['state'] == 'installed'
    assert not (Path(receipt['manifest']['evidence']) / 'complete.json').exists()
    assert not e.resident.current(e.approval_row)


def test_partial_write_leaves_durable_hold_and_before_evidence(environment, monkeypatch):
    e = environment
    plan = e.plan()
    original = bindings.replace
    def fail(path, raw):
        if str(path) == str(e.supervisor):
            raise OSError('injected write failure')
        original(path, raw)
    monkeypatch.setattr(bindings, 'replace', fail)
    with bindings.rebind_lease(plan), pytest.raises(OSError, match='injected'):
        bindings.install_rebind(plan, e.new)
    journal = json.loads(e.journal.read_text())
    assert journal['state'] == 'prepared'
    assert (Path(journal['evidence']) / '00-before').read_bytes() == plan['before'][str(e.targets)]
    assert not e.resident.current(e.approval_row)


@pytest.mark.parametrize('field,value', [('cwd', '/other'), ('native_session_id', 'other'),
                                         ('recovery_identity', 'reset-budget'), ('inline_approval_conversation_ids', [])])
def test_unjournaled_or_stable_identity_change_rejected(environment, field, value):
    e = environment
    plan = e.plan()
    with bindings.rebind_lease(plan):
        receipt = bindings.install_rebind(plan, e.new)
        data = json.loads(e.targets.read_text())
        data[0][field] = value
        write(e.targets, data)
        config = json.loads(e.controller.read_text())
        config['services']['approvals']['source_sha256'][str(e.targets)] = bindings.digest(e.targets.read_bytes())
        write(e.controller, config)
        manifest = receipt['manifest']
        manifest['after'][str(e.targets)] = bindings.digest(e.targets.read_bytes())
        manifest['after'][str(e.controller)] = bindings.digest(e.controller.read_bytes())
        write(e.journal, manifest)
        with pytest.raises(bindings.BindingError, match='stable binding field'):
            e.resident.refresh()


def test_duplicate_and_symlink_inputs_fail_closed(environment):
    e = environment
    with pytest.raises(bindings.BindingError, match='duplicate'):
        bindings.rows([e.approval_row, e.approval_row])
    alias = e.tmp_path / 'alias'
    alias.symlink_to(e.targets)
    with pytest.raises(bindings.BindingError, match='symlink'):
        bindings.read(alias)


def test_immutable_evidence_cannot_be_replaced(tmp_path):
    path = tmp_path / 'evidence.json'
    bindings.create(path, b'first')
    with pytest.raises(FileExistsError):
        bindings.create(path, b'second')
    assert path.read_bytes() == b'first'


LEGACY_MONITOR = '''from pathlib import Path
import fcntl
from token_limit_recovery import Recovery
ROOT = ROOT_FIXTURE
INPUT_LOCK_DIR = ROOT / "input-locks"
SESSIONS = {42: 'ttys001'}
def classify(screen):
    return ('command', 1) if screen == 'exact-authorized-prompt' else None
def live_ttys():
    return ['/dev/ttys001']
def try_redraw(record, target):
    with (INPUT_LOCK_DIR / 'ttys001.lock').open('a') as input_lock:
        fcntl.flock(input_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if record["tty"] not in live_ttys():
            return None
        run_jxa('redraw', target)
def main():
    recovery = Recovery(ROOT, SESSIONS)
    record = {'tty': '/dev/ttys001'}
    target = recovery.targets[record['tty']]
    recovery.consider(record)
    for _ in range(1):
        try:
            ttys = live_ttys()
            for tty in ttys:
                with (INPUT_LOCK_DIR / 'ttys001.lock').open('a') as input_lock:
                    fcntl.flock(input_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if tty not in live_ttys():
                        continue
                    run_jxa('approval', target)
        except RuntimeError:
            raise
    counts, pending_other = {'command': 123}, []
    return {
                  "counts": counts, "pending_other": pending_other,
    }
'''
LEGACY_RECOVERY = '''import fcntl
import time
class Recovery:
    def __init__(self, root, sessions, *, adapter=terminal, now=time.time):
        self.adapter = adapter
        self.root = root
        self.targets = {'/dev/ttys001': {'pid': 42, 'tty': '/dev/ttys001'}}
    def consider(self, record):
        target = self.targets[record['tty']]
        detail = {'tty': record['tty']}
        with (self.root / 'input-locks' / 'ttys001.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            live = self.adapter.live_process(target['pid'])
            self.adapter.send(live)
'''


def test_generated_legacy_hooks_block_all_three_input_paths(tmp_path, monkeypatch):
    """Execute transformed functions, proving guards rather than string presence."""
    (tmp_path / 'input-locks').mkdir()
    monitor, recovery = prepare.transformed(LEGACY_MONITOR, LEGACY_RECOVERY, tmp_path / 'config.json')
    actions, checks = [], []
    class Resident:
        def __init__(self, *args, **kwargs):
            self.sessions = {42: 'ttys001'}
        def refresh(self, *args):
            pass
        def current(self, target):
            checks.append(target['pid'])
            return False
        def acknowledgment(self):
            return {'version': 1}
    monkeypatch.setattr(bindings, 'ResidentBindings', Resident)
    terminal = SimpleNamespace(live_process=lambda pid: actions.append('inspect') or pid,
                               send=lambda value: actions.append('recovery'))
    recovery_module = type(sys)('token_limit_recovery')
    recovery_module.terminal = terminal
    exec(compile(recovery, 'generated-recovery', 'exec'), recovery_module.__dict__)
    monkeypatch.setitem(sys.modules, 'token_limit_recovery', recovery_module)
    namespace = {'ROOT_FIXTURE': tmp_path, '__file__': str(tmp_path / 'monitor.py'),
                 'run_jxa': lambda kind, value: actions.append(kind)}
    exec(compile(monitor, 'generated-monitor', 'exec'), namespace)
    namespace['try_redraw']({'tty': '/dev/ttys001'}, {'pid': 42, 'tty': '/dev/ttys001'})
    status = namespace['main']()
    assert checks == [42, 42, 42]
    assert actions == []
    assert status['counts'] == {'command': 123}
    assert namespace['classify']('exact-authorized-prompt') == ('command', 1)
    assert namespace['classify']('something-else') is None


def test_prepare_only_exact_hash_and_output_preservation(tmp_path):
    runtime, proposals = tmp_path / 'runtime', tmp_path / 'proposals'
    runtime.mkdir()
    proposals.mkdir()
    monitor, recovery = runtime / 'monitor.py', runtime / 'token_limit_recovery.py'
    monitor.write_text(LEGACY_MONITOR)
    recovery.write_text(LEGACY_RECOVERY)
    before = (monitor.read_bytes(), recovery.read_bytes())
    args = (monitor, bindings.digest(before[0]), recovery, bindings.digest(before[1]), tmp_path / 'config.json')
    with pytest.raises(bindings.BindingError, match='hash mismatch'):
        prepare.prepare(monitor, '0' * 64, recovery, args[3], args[4], proposals / 'bad')
    assert not (proposals / 'bad').exists()
    result = prepare.prepare(*args, proposals / 'patch')
    assert result['authority'] == 'prepare_only'
    assert (monitor.read_bytes(), recovery.read_bytes()) == before
    with pytest.raises(bindings.BindingError, match='must be new'):
        prepare.prepare(*args, proposals / 'patch')
    with pytest.raises(bindings.BindingError, match='inside the live'):
        prepare.prepare(*args, runtime / 'unsafe')


def test_legacy_drift_is_not_patched_by_approximation(tmp_path):
    with pytest.raises(bindings.BindingError, match='anchor missing'):
        prepare.transformed(LEGACY_MONITOR.replace('Recovery(ROOT, SESSIONS)', 'OtherRecovery(ROOT,SESSIONS)'),
                            LEGACY_RECOVERY, tmp_path / 'config.json')


def test_input_validation_cannot_ack_reload_before_recovery_adopts(environment):
    e = environment
    recovery = SimpleNamespace(targets=copy.deepcopy(e.resident.targets))
    before = e.resident.acknowledgment()
    plan = e.plan()
    with bindings.rebind_lease(plan):
        receipt = bindings.install_rebind(plan, e.new)
        assert not e.resident.current(e.approval_row)
        # A per-input freshness check must not publish newly loaded mappings
        # while token recovery still holds the old generation.
        assert e.resident.acknowledgment() == before
        assert recovery.targets[e.target['tty']]['pid'] == 42
        e.resident.refresh(recovery)
        assert e.resident.acknowledgment()['generation'] == receipt['manifest']['transaction_id']
        assert recovery.targets[e.target['tty']]['pid'] == 1042


def test_lock_root_mismatch_refuses_baseline_and_prequit(environment):
    e = environment
    wrong = e.tmp_path / 'other-locks'
    wrong.mkdir()
    with pytest.raises(bindings.BindingError, match='input lock directory mismatch'):
        bindings.prepare_rebind(e.controller, [e.targets, e.supervisor], e.target,
                                input_lock_dir=wrong, now=lambda: e.now[0],
                                identity_reader=e.identity_reader, consumer_verifier=lambda *args: None)
    with pytest.raises(bindings.BindingError, match='input lock directory mismatch'):
        bindings.ResidentBindings(e.controller, e.targets, e.monitor, input_lock_dir=wrong,
                                  clock=lambda: e.now[0], identity_reader=e.identity_reader,
                                  consumer_verifier=lambda *args: None)
    assert not e.journal.exists()


def test_pinned_monitor_code_drift_refuses_under_lease_before_input(environment):
    e = environment
    plan = e.plan()
    e.monitor.write_text('# changed after preflight, despite old fresh ack\n')
    with pytest.raises(bindings.BindingError, match='source pin mismatch'):
        with bindings.rebind_lease(plan):
            pytest.fail('source drift was accepted before quit')
    assert not e.journal.exists()


def test_resident_cannot_claim_reloaded_code_after_disk_and_pin_change(environment):
    e = environment
    plan = e.plan()
    with bindings.rebind_lease(plan):
        receipt = bindings.install_rebind(plan, e.new)
        e.monitor.write_text('# different policy code, not loaded by the resident\n')
        config = json.loads(e.controller.read_text())
        config['services']['approvals']['source_sha256'][str(e.monitor)] = bindings.digest(e.monitor.read_bytes())
        write(e.controller, config)
        journal = receipt['manifest']
        journal['after'][str(e.controller)] = bindings.digest(e.controller.read_bytes())
        write(e.journal, journal)
        with pytest.raises(bindings.BindingError, match='resident code pins changed'):
            e.resident.refresh()
    assert e.resident.acknowledgment()['source_sha256'][str(e.monitor)] != bindings.digest(e.monitor.read_bytes())
