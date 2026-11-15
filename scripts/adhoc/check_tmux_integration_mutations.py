#!/usr/bin/env python3
"""Prove integration regressions detect issues 1244/1245, 2026-11-15.

Inputs: generic integration generator and synthetic tests. Outputs: retained
mutated source and pytest logs under ignored .temp/tmux-standard/integration-mutations.
Fresh processes exercise each mutation; no private source or live session is used.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/adhoc/prepare_tmux_observer_integration.py"
OUT = ROOT / ".temp/tmux-standard/integration-mutations"
MUTATIONS = {
    "execute_cached_bytecode": (
        "exec(compile(raw,str(path),'exec'),module.__dict__)",
        "spec.loader.exec_module(module)",
    ),
    "load_dependency_before_stop": (
        '"    args=p.parse_args(argv);state=safe_state(args.state_dir)")',
        '"    args=p.parse_args(argv);state=safe_state(args.state_dir)\\n"\n'
        '                          "    if args.tmux_adapter:load_tmux_adapter(args.tmux_adapter,args.tmux_reviewed_sha256)")',
    ),
}


def main():
    original = SOURCE.read_text()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (before, after) in MUTATIONS.items():
        if original.count(before) != 1:
            raise SystemExit("Mutation no longer uniquely matches: " + name)
        path = OUT / (name + ".py")
        path.write_text(original.replace(before, after))
        env = dict(os.environ, MECH_TMUX_INTEGRATION_SOURCE=str(path),
                   PYTHONPYCACHEPREFIX=str(OUT / (name + "-pycache")))
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_tmux_observer_integration.py"],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        (OUT / (name + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode != 1 or " failed" not in result.stdout:
            raise SystemExit("Mutation did not produce assertion failures: " + name)
        print(name + ": rejected by regression tests", flush=True)


if __name__ == "__main__":
    main()
