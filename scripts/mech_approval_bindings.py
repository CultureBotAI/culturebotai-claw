"""Pinned binding reload for the existing approvals loop; never sends input.

Standalone stdlib/Python 3.9 module. A resident reader reloads data without the
TTY lock; every caller must use current() *inside* its existing input lock.
The restart guard holds that lock and the existing lifecycle lock until ack.
"""
import contextlib
import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


class BindingError(RuntimeError):
    """Uncertain binding state; caller must hold and never retry input."""


def require(value, message):
    if not value:
        raise BindingError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe(path, directory=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'binding path must be absolute')
    for parent in (*reversed(path.parents), path):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), 'symlink binding path')
        require(not info.st_mode & stat.S_IWOTH or (stat.S_ISDIR(info.st_mode) and info.st_mode & stat.S_ISVTX),
                'untrusted binding path')
        if parent == path:
            require(info.st_uid == os.getuid(), 'binding path owned by another user')
            require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), 'wrong binding path type')
            require(directory or info.st_nlink == 1, 'hardlinked binding file')
    return path


def read(path):
    return safe(path).read_bytes()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def sync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace(path, raw):
    path = safe(path)
    safe(path.parent, directory=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        safe(path)
        os.replace(name, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def create(path, raw):
    path = safe(path)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(path.parent)


def identity(pid):
    require(type(pid) is int and pid > 0, 'invalid consumer PID')
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='],
                            text=True, capture_output=True, timeout=10, check=True)
    started = ' '.join(result.stdout.split())
    require(bool(started), 'consumer start unavailable')
    return {'pid': pid, 'started': started}


def verify_consumer(service, consumer):
    """Bind the acknowledgment writer to the configured monitor command/cwd."""
    pid = consumer['pid']
    command = subprocess.run(['/bin/ps', '-p', str(pid), '-ww', '-o', 'command='],
                             text=True, capture_output=True, timeout=10, check=True).stdout.strip()
    require(shlex.split(command) == service['argv'], 'consumer argv differs from controller')
    output = subprocess.run(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                            text=True, capture_output=True, timeout=10, check=True).stdout
    directories = [line[1:] for line in output.splitlines() if line.startswith('n')]
    require(directories == [service['cwd']], 'consumer cwd differs from controller')


def rows(data):
    value = data.get('targets') if isinstance(data, dict) else data
    require(isinstance(value, list) and bool(value), 'targets must be nonempty list')
    pids, ttys = set(), set()
    for row in value:
        require(isinstance(row, dict), 'target must be object')
        pid, tty = row.get('pid'), row.get('tty')
        require(type(pid) is int and pid > 0 and pid not in pids, 'invalid or duplicate target PID')
        require(isinstance(tty, str) and re.fullmatch(r'/dev/ttys[0-9]+', tty) and tty not in ttys,
                'invalid or duplicate target TTY')
        process = row.get('identity', row.get('process_identity'))
        cwd = row.get('cwd', row.get('root'))
        require(isinstance(process, str) and bool(process.strip()), 'missing process identity')
        require(isinstance(cwd, str) and Path(cwd).is_absolute(), 'missing target cwd')
        pids.add(pid)
        ttys.add(tty)
    return value


def changed(raw, target, new):
    data = decode(raw)
    entries = rows(data)
    matches = [row for row in entries if row['pid'] == target['pid']]
    require(len(matches) == 1, 'old PID missing or ambiguous')
    row = matches[0]
    require(row['tty'] == target['tty'] and row.get('cwd', row.get('root')) == target['root']
            and row.get('identity', row.get('process_identity')) == target['process_identity'], 'old target identity mismatch')
    require(row.get('native_session_id') == target['native_session_id'], 'native identity mismatch')
    require(new['tty'] == row['tty'] and type(new['pid']) is int and new['pid'] > 0
            and new['pid'] != row['pid'], 'invalid replacement PID/TTY')
    require(isinstance(new.get('started'), str) and bool(new['started'].strip())
            and isinstance(new.get('process_identity'), str) and bool(new['process_identity'].strip()), 'replacement identity missing')
    if 'recovery_identity' in row:
        require(isinstance(row['recovery_identity'], str) and bool(row['recovery_identity']), 'missing stable recovery identity')
    row['pid'] = new['pid']
    for name in ('identity', 'process_identity'):
        if name in row:
            row[name] = new['process_identity']
    if 'started' in row:
        row['started'] = new['started']
    rows(data)
    return encoded(data)


def configuration(path):
    raw = read(path)
    config = decode(raw)
    require(config.get('version') == 1, 'unsupported controller config')
    service = config['services']['approvals']
    capability = service.get('binding_reload')
    require(isinstance(capability, dict) and capability.get('version') == 1, 'approval reload capability unavailable')
    require(set(capability) == {'version', 'journal', 'adapter', 'input_lock_dir'}, 'unknown reload capability setting')
    for name in ('journal', 'adapter', 'input_lock_dir'):
        safe(capability[name], directory=name == 'input_lock_dir')
    hashes = service.get('source_sha256', {})
    require(capability['adapter'] in hashes and service['session_targets_file'] in hashes, 'adapter or targets integrity pin missing')
    require(digest(read(capability['adapter'])) == digest(read(Path(__file__).resolve())), 'reload adapter source differs')
    source_hashes = {}
    for source, expected in hashes.items():
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'malformed source pin')
        actual = digest(read(source))
        require(actual == expected, 'source pin mismatch: ' + source)
        source_hashes[source] = actual
    return raw, config, service, source_hashes


def verify_lock_root(service, actual):
    actual = safe(actual, directory=True)
    declared = safe(service['binding_reload']['input_lock_dir'], directory=True)
    require(actual == declared and actual.is_dir() and declared.is_dir(), 'input lock directory mismatch')
    require((actual.stat().st_dev, actual.stat().st_ino) == (declared.stat().st_dev, declared.stat().st_ino),
            'input lock directory identity mismatch')


def marker(path):
    path = safe(path)
    return decode(read(path)) if path.exists() else None


class ResidentBindings:
    """One instance in the existing monitor; does not alter recovery history."""
    def __init__(self, controller_config, targets_file, monitor_source, *, input_lock_dir, clock=time.time, identity_reader=identity, consumer_verifier=verify_consumer):
        self.controller = Path(controller_config)
        self.targets_file = Path(targets_file)
        self.monitor_source = Path(monitor_source)
        self.input_lock_dir = Path(input_lock_dir)
        self.clock, self.identity_reader = clock, identity_reader
        self.consumer = identity_reader(os.getpid())
        self.sessions, self.targets = {}, {}
        self.snapshot = None
        self.refresh()
        consumer_verifier(decode(read(self.controller))['services']['approvals'], self.consumer)

    def refresh(self, recovery=None):
        config_raw, config, service, sources = configuration(self.controller)
        verify_lock_root(service, self.input_lock_dir)
        require(service['session_targets_file'] == str(self.targets_file), 'resident targets path mismatch')
        require(str(self.monitor_source) in sources, 'resident monitor source unpinned')
        journal_path = service['binding_reload']['journal']
        journal = marker(journal_path)
        raw = read(self.targets_file)
        target_hash = digest(raw)
        if self.snapshot is not None:
            def code_pins(values):
                return {path: value for path, value in values.items() if path != str(self.targets_file)}
            require(code_pins(sources) == code_pins(self.snapshot['source_sha256']),
                    'resident code pins changed; monitor restart required')
        require(sources[str(self.targets_file)] == target_hash, 'torn target snapshot')
        generation = 'baseline:' + target_hash
        if journal is not None:
            require(journal.get('state') in ('installed', 'complete'), 'binding transaction is incomplete')
            generation = journal['transaction_id']
            require(journal['after'][str(self.targets_file)] == target_hash
                    and journal['after'][str(self.controller)] == digest(config_raw), 'journal/config/target mismatch')
        elif self.snapshot is not None:
            require(self.snapshot['targets_sha256'] == target_hash
                    and self.snapshot['config_sha256'] == digest(config_raw), 'unjournaled binding/config change')
        entries = rows(decode(raw))
        for row in entries:
            require(isinstance(row.get('recovery_identity'), str) and bool(row['recovery_identity']), 'stable recovery identity required')
        if self.snapshot is not None and target_hash != self.snapshot['targets_sha256']:
            before = {row['tty']: row for row in self.targets.values()}
            require(set(before) == {row['tty'] for row in entries}, 'target membership changed')
            for row in entries:
                def stable(value):
                    return {k: v for k, v in value.items() if k not in ('pid', 'identity', 'process_identity', 'started')}
                require(stable(row) == stable(before[row['tty']]), 'stable binding field changed')
        require(read(self.controller) == config_raw and read(self.targets_file) == raw
                and marker(journal_path) == journal, 'binding snapshot changed during read')
        self.sessions.clear()
        self.sessions.update({row['pid']: Path(row['tty']).name for row in entries})
        self.targets = {row['tty']: copy.deepcopy(row) for row in entries}
        if recovery is not None:
            recovery.targets = copy.deepcopy(self.targets)
        self.snapshot = {'version': 1, 'generation': generation, 'consumer': self.consumer,
                         'targets_sha256': target_hash, 'config_sha256': digest(config_raw),
                         'source_sha256': sources, 'effective': copy.deepcopy(entries), 'observed_at': self.clock()}
        return copy.deepcopy(self.snapshot)

    def current(self, target):
        """Validate only, after the TTY lock; never adopt a mid-sweep generation."""
        try:
            raw, _config, service, sources = configuration(self.controller)
            verify_lock_root(service, self.input_lock_dir)
            state = marker(service['binding_reload']['journal'])
            target_bytes = read(self.targets_file)
            generation = state['transaction_id'] if state is not None else 'baseline:' + digest(target_bytes)
            return (self.snapshot['generation'] == generation
                    and self.snapshot['targets_sha256'] == digest(target_bytes)
                    and self.snapshot['config_sha256'] == digest(raw)
                    and self.snapshot['source_sha256'] == sources
                    and (state is None or state['state'] == 'complete')
                    and read(self.controller) == raw and read(self.targets_file) == target_bytes
                    and marker(service['binding_reload']['journal']) == state
                    and self.targets.get(target.get('tty')) == target)
        except (BindingError, KeyError, TypeError, ValueError, OSError):
            return False

    def acknowledgment(self):
        return copy.deepcopy(self.snapshot)


def validate_ack(value, expected, *, now, identity_reader=identity):
    require(isinstance(value, dict), 'resident binding acknowledgment missing')
    require(value.get('version') == 1, 'unsupported resident acknowledgment')
    for key in ('generation', 'targets_sha256', 'config_sha256', 'source_sha256', 'effective'):
        require(value.get(key) == expected[key], 'resident acknowledgment mismatch: ' + key)
    require(value.get('consumer') == expected['consumer']
            and identity_reader(expected['consumer']['pid']) == expected['consumer'], 'resident consumer changed')
    observed = value.get('observed_at')
    require(type(observed) in (int, float) and expected.get('not_before', now - 30) <= observed <= now
            and now - observed <= 30, 'resident acknowledgment stale')


def prepare_rebind(controller_config, binding_paths, target, *, input_lock_dir, now=time.time, identity_reader=identity, consumer_verifier=verify_consumer):
    controller_config = safe(controller_config)
    raw, config, service, sources = configuration(controller_config)
    verify_lock_root(service, input_lock_dir)
    paths = list(dict.fromkeys(str(safe(path)) for path in binding_paths))
    require(service['session_targets_file'] in paths, 'approval targets absent from transaction')
    require(str(controller_config) not in paths, 'controller config cannot be target file')
    journal = marker(service['binding_reload']['journal'])
    require(journal is None or journal.get('state') == 'complete', 'unfinished binding transaction')
    status = decode(read(service['status_file']))
    ack = status.get('binding_reload')
    target_raw = read(service['session_targets_file'])
    expected = {'generation': journal['transaction_id'] if journal else 'baseline:' + digest(target_raw),
                'targets_sha256': digest(target_raw), 'config_sha256': digest(raw), 'source_sha256': sources,
                'effective': rows(decode(target_raw)), 'consumer': identity_reader(status['pid'])}
    validate_ack(ack, expected, now=now(), identity_reader=identity_reader)
    consumer_verifier(service, expected['consumer'])
    entries = rows(decode(target_raw))
    selected = [row for row in entries if row['pid'] == target['pid']]
    require(len(selected) == 1 and bool(selected[0].get('recovery_identity')), 'stable recovery identity missing')
    before = {path: read(path) for path in paths}
    # Validate all old bindings before quitting, using a harmless synthetic replacement.
    probe = {'pid': max(row['pid'] for raw_file in before.values() for row in rows(decode(raw_file))) + 1,
             'tty': target['tty'], 'process_identity': 'preflight only', 'started': 'preflight only'}
    for content in before.values():
        changed(content, target, probe)
    before[str(controller_config)] = raw
    return {'controller': str(controller_config), 'config': config, 'service': service, 'before': before,
            'target': copy.deepcopy(target), 'expected': expected, 'journal_before': journal,
            'clock': now, 'identity_reader': identity_reader, 'input_lock_dir': str(input_lock_dir), 'leased': False}


@contextlib.contextmanager
def rebind_lease(plan):
    lock = safe(Path(plan['config']['state_dir']) / 'lifecycle.lock')
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BindingError('monitor lifecycle operation in progress') from error
        check_before(plan)
        plan['leased'] = True
        yield plan
    finally:
        plan['leased'] = False
        os.close(fd)


def check_before(plan):
    _raw, _config, service, sources = configuration(plan['controller'])
    verify_lock_root(service, plan['input_lock_dir'])
    require(sources == plan['expected']['source_sha256'], 'source pins changed since preflight')
    require(all(read(path) == raw for path, raw in plan['before'].items()), 'binding CAS drift')
    require(marker(plan['service']['binding_reload']['journal']) == plan['journal_before'], 'binding journal drift')
    status = decode(read(plan['service']['status_file']))
    validate_ack(status.get('binding_reload'), plan['expected'], now=plan['clock'](), identity_reader=plan['identity_reader'])


def install_rebind(plan, new, *, evidence=None):
    require(plan['leased'], 'lifecycle lease required')
    check_before(plan)
    controller = plan['controller']
    after = {path: changed(raw, plan['target'], new) for path, raw in plan['before'].items() if path != controller}
    config = copy.deepcopy(plan['config'])
    targets = plan['service']['session_targets_file']
    config['services']['approvals']['source_sha256'][targets] = digest(after[targets])
    after[controller] = encoded(config)
    journal_path = Path(plan['service']['binding_reload']['journal'])
    evidence_root = safe(journal_path.parent / 'binding-reload-evidence', directory=True)
    evidence_root.mkdir(mode=0o700, exist_ok=True)
    transaction_id = uuid.uuid4().hex
    evidence_dir = evidence_root / transaction_id
    evidence_dir.mkdir(mode=0o700)
    sync_dir(evidence_root)
    manifest = {'version': 1, 'transaction_id': transaction_id, 'state': 'prepared',
                'created_at': plan['clock'](), 'old_pid': plan['target']['pid'], 'new_pid': new['pid'],
                'before': {path: digest(raw) for path, raw in plan['before'].items()},
                'after': {path: digest(raw) for path, raw in after.items()}, 'evidence': str(evidence_dir)}
    for index, path in enumerate(plan['before']):
        create(evidence_dir / ('%02d-before' % index), plan['before'][path])
        create(evidence_dir / ('%02d-after' % index), after[path])
    if evidence is not None:
        require(isinstance(evidence, dict), 'restart evidence must be object')
        restart_bytes = encoded(evidence)
        create(evidence_dir / 'restart-evidence.json', restart_bytes)
        manifest['restart_evidence_sha256'] = digest(restart_bytes)
    create(evidence_dir / 'prepared.json', encoded(manifest))
    replace(journal_path, encoded(manifest))
    # There is deliberately no automatic rollback after the process has changed.
    for path, raw_after in after.items():
        require(read(path) == plan['before'][path], 'binding CAS drift during install')
        replace(path, raw_after)
        require(read(path) == raw_after, 'binding replacement readback failed')
    manifest.update(state='installed', installed_at=plan['clock']())
    create(evidence_dir / 'installed.json', encoded(manifest))
    replace(journal_path, encoded(manifest))
    sources = dict(plan['expected']['source_sha256'])
    sources[targets] = digest(after[targets])
    expected = {'generation': transaction_id, 'targets_sha256': digest(after[targets]),
                'config_sha256': digest(after[controller]), 'source_sha256': sources,
                'effective': rows(decode(after[targets])), 'consumer': plan['expected']['consumer'],
                'not_before': manifest['installed_at']}
    return {'manifest': manifest, 'expected': expected, 'after': after}


def await_rebind(plan, receipt, *, timeout=15, sleep=time.sleep):
    require(plan['leased'], 'lifecycle lease required')
    deadline = plan['clock']() + timeout
    last_error = None
    while plan['clock']() < deadline:
        try:
            require(all(read(path) == raw for path, raw in receipt['after'].items()), 'installed binding drift')
            require(marker(plan['service']['binding_reload']['journal']) == receipt['manifest'], 'installed journal drift')
            status = decode(read(plan['service']['status_file']))
            validate_ack(status.get('binding_reload'), receipt['expected'], now=plan['clock'](), identity_reader=plan['identity_reader'])
            manifest = dict(receipt['manifest'], state='complete', acknowledged_at=plan['clock']())
            create(Path(manifest['evidence']) / 'acknowledgment.json', encoded(status['binding_reload']))
            create(Path(manifest['evidence']) / 'complete.json', encoded(manifest))
            replace(plan['service']['binding_reload']['journal'], encoded(manifest))
            return manifest
        except (BindingError, ValueError, KeyError, OSError) as error:
            last_error = error
        sleep(0.1)
    raise BindingError('resident binding acknowledgment failed: ' + str(last_error))
