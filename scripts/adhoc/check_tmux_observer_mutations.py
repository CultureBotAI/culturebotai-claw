#!/usr/bin/env python3
"""Check tmux observer regression sensitivity for claw issue 1238, 2026-11-15.

Inputs: committed observer and its synthetic tests. Outputs: retained mutated
source copies and pytest logs under ignored .temp/tmux-standard/mutations/.
Each variant runs in a fresh Python process; no live session is accessed.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/mech_session_tmux.py"
OUT = ROOT / ".temp/tmux-standard/mutations"
MUTATIONS = {
    "omit_post_capture_identity": (
        'native = {"state": "unknown", "reason": "native identity changed during capture"}\n        verify_transport(binding, runner, stat_socket)',
        'native = {"state": "unknown", "reason": "native identity changed during capture"}\n        # mutation: no second identity check',
    ),
    "ignore_socket_incarnation": (
        'require(stat_socket(binding["tmux"]["socket"]) == binding["tmux"]["socket_identity"],',
        'require(True,',
    ),
    "ignore_native_ancestry": (
        'require(descendant(binding["native_process"]["pid"], binding["pane"]["pid"], runner),',
        'require(True,',
    ),
    "accept_wrong_native_thread": (
        'require(meta.get("id") == native["thread_id"] and meta.get("cwd") == binding["root"],',
        'require(True,',
    ),
    "ignore_native_capture_race": (
        'if native != native_before:',
        'if False:',
    ),
    "blocking_registry_open": (
        'def read_registry(path):\n    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)',
        'def read_registry(path):\n    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)',
    ),
}


def main():
    original = SOURCE.read_text()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (before, after) in MUTATIONS.items():
        if original.count(before) != 1:
            raise SystemExit("Mutation no longer uniquely matches: " + name)
        source = OUT / (name + ".py")
        source.write_text(original.replace(before, after))
        env = dict(os.environ, MECH_TMUX_OBSERVER_SOURCE=str(source),
                   PYTHONPYCACHEPREFIX=str(OUT / (name + "-pycache")))
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_mech_session_tmux.py"],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        (OUT / (name + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode != 1 or " failed" not in result.stdout:
            raise SystemExit("Mutation did not produce assertion failures: " + name)
        print(name + ": rejected by regression tests", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
