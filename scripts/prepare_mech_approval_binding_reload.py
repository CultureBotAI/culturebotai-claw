#!/usr/bin/env python3
"""Prepare an exact-hash legacy approval-monitor patch; never install or run it."""
import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

from mech_approval_bindings import BindingError, create, safe


def one(text, before, after):
    if text.count(before) != 1:
        raise BindingError('legacy source anchor missing or ambiguous: ' + before[:80])
    return text.replace(before, after, 1)


def transformed(monitor, recovery, controller):
    if monitor.count('INPUT_LOCK_DIR = ROOT / "input-locks"') != 1:
        raise BindingError('legacy monitor input lock directory is unverified')
    original = ast.parse(monitor)
    policy = {node.name: ast.dump(node) for node in original.body
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name not in ('main', 'try_redraw')}
    monitor = one(monitor, 'from token_limit_recovery import Recovery',
                  'from token_limit_recovery import Recovery\nfrom mech_approval_bindings import ResidentBindings')
    mappings = re.findall(r'^SESSIONS = .*$', monitor, flags=re.M)
    if len(mappings) != 1:
        raise BindingError('expected one literal SESSIONS declaration')
    ast.literal_eval(mappings[0].partition(' = ')[2])
    monitor = one(monitor, mappings[0],
                  'BINDINGS = ResidentBindings(Path(' + repr(str(controller)) + '),\n'
                  '                            ROOT / "token-recovery-targets.json", Path(__file__).resolve(),\n'
                  '                            input_lock_dir=INPUT_LOCK_DIR)\n'
                  'SESSIONS = BINDINGS.sessions')
    monitor = one(monitor, 'Recovery(ROOT, SESSIONS)',
                  'Recovery(ROOT, SESSIONS, target_guard=BINDINGS.current)')
    monitor = one(monitor, '        try:\n            ttys = live_ttys()',
                  '        try:\n            BINDINGS.refresh(recovery)\n            ttys = live_ttys()')
    monitor = one(monitor, '        if record["tty"] not in live_ttys():',
                  '        if record["tty"] not in live_ttys() or not BINDINGS.current(target):')
    monitor = one(monitor, '                    if tty not in live_ttys():',
                  '                    if tty not in live_ttys() or not BINDINGS.current(target):')
    monitor = one(monitor, '                  "counts": counts, "pending_other": pending_other,',
                  '                  "binding_reload": BINDINGS.acknowledgment(),\n'
                  '                  "counts": counts, "pending_other": pending_other,')
    after = ast.parse(monitor)
    for node in after.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in policy:
            if ast.dump(node) != policy[node.name]:
                raise BindingError('approval policy changed: ' + node.name)
    recovery = one(recovery, 'def __init__(self, root, sessions, *, adapter=terminal, now=time.time):',
                   'def __init__(self, root, sessions, *, adapter=terminal, now=time.time, target_guard=lambda target: True):')
    recovery = one(recovery, '        self.adapter = adapter',
                   '        self.adapter = adapter\n        self.target_guard = target_guard')
    recovery = one(recovery, "            live = self.adapter.live_process(target['pid'])",
                   "            if not self.target_guard(target):\n"
                   "                return {**detail, 'status': 'binding-changed'}\n"
                   "            live = self.adapter.live_process(target['pid'])")
    ast.parse(recovery)
    return monitor, recovery


def prepare(monitor_path, monitor_sha256, recovery_path, recovery_sha256, controller_config, output):
    monitor_path, recovery_path = safe(monitor_path), safe(recovery_path)
    controller_config = safe(controller_config)
    output = safe(output, directory=True)
    if output.exists():
        raise BindingError('output directory must be new')
    if any(output == path.parent or path.parent in output.parents for path in (monitor_path, recovery_path)):
        raise BindingError('output cannot be inside the live approval runtime')
    inputs = [(monitor_path, monitor_sha256), (recovery_path, recovery_sha256)]
    contents = []
    for path, expected in inputs:
        raw = path.read_bytes()
        if not re.fullmatch('[0-9a-f]{64}', expected) or hashlib.sha256(raw).hexdigest() != expected:
            raise BindingError('reviewed source hash mismatch: ' + str(path))
        contents.append(raw.decode())
    monitor, recovery = transformed(*contents, controller_config)
    output.mkdir(mode=0o700, parents=False)
    create(output / 'monitor.py', monitor.encode())
    create(output / 'token_limit_recovery.py', recovery.encode())
    adapter = Path(__file__).with_name('mech_approval_bindings.py')
    create(output / adapter.name, adapter.read_bytes())
    manifest = {'version': 1, 'authority': 'prepare_only', 'controller_config': str(controller_config),
                'inputs': {str(path): expected for path, expected in inputs},
                'outputs': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}}
    create(output / 'manifest.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('monitor', 'recovery', 'controller-config', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--monitor-sha256', required=True)
    parser.add_argument('--recovery-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(args.monitor, args.monitor_sha256, args.recovery, args.recovery_sha256,
                         args.controller_config, args.output)
    except (BindingError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
