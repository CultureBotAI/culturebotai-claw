"""Synthetic tests for the optional passive-monitor integration, issues 1244/1245.

No private observer source, host binding, session, or workflow is used.
"""
import argparse
import hashlib
import importlib.util
import os
import py_compile
import re
import stat
from pathlib import Path

import pytest

SOURCE = Path(os.environ.get("MECH_TMUX_INTEGRATION_SOURCE",
                            Path(__file__).parents[1] / "scripts/adhoc/prepare_tmux_observer_integration.py"))
SPEC = importlib.util.spec_from_file_location("tmux_integration_proposal", SOURCE)
proposal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proposal)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def loader_namespace():
    values = {"require": require, "re": re, "os": os, "stat": stat,
              "importlib": importlib, "digest": lambda raw: hashlib.sha256(raw).hexdigest()}
    exec(proposal.HELPERS, values)
    return values


def test_loader_executes_hashed_source_not_timestamp_valid_bytecode(tmp_path):
    path = tmp_path / "adapter.py"
    path.write_text("VALUE = 'stale'\n")
    stamp = path.stat()
    py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
    path.write_text("VALUE = 'fresh'\n")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    values = loader_namespace()
    values["load_tmux_adapter"](path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert values["checked_tmux_adapter"]().VALUE == "fresh"


def test_loaded_adapter_dependency_change_holds_observation(tmp_path):
    path = tmp_path / "adapter.py"
    path.write_text("VALUE = 'fresh'\n")
    values = loader_namespace()
    values["load_tmux_adapter"](path, hashlib.sha256(path.read_bytes()).hexdigest())
    path.write_text("VALUE = 'other'\n")
    with pytest.raises(ValueError, match="changed"):
        values["checked_tmux_adapter"]()


LEGACY_PROTOCOL = '''
def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['status','stop','start','run','once'])
    p.add_argument('--state-dir',type=Path,default=Path('/private/example'))
    p.add_argument('--registry',type=Path)
    args=p.parse_args(argv);state=safe_state(args.state_dir)
    if args.command=='status':events.append(('status',state));return 0
    if args.command=='stop':events.append(('owned-stop',state));return 0
    require(args.registry is not None and args.registry.is_absolute(),'Absolute registry required')
    events.append(('observe',state));return 0
'''


@pytest.mark.parametrize("command", ["status", "stop"])
def test_lifecycle_stays_available_when_adapter_missing_or_changed(command):
    events = []

    def missing_adapter(*_args):
        raise AssertionError("Lifecycle must not load its broken observation dependency")

    values = {"argparse": argparse, "Path": Path, "safe_state": lambda path: path,
              "events": events, "require": require, "load_tmux_adapter": missing_adapter}
    exec(proposal.add_tmux_cli_guards(LEGACY_PROTOCOL), values)
    assert values["main"]([command, "--tmux-adapter", "/missing/adapter.py",
                           "--tmux-reviewed-sha256", "0" * 64]) == 0
    assert events[0][0] == ("owned-stop" if command == "stop" else "status")


@pytest.mark.parametrize("command", ["start", "run", "once"])
def test_observation_paths_still_require_reviewed_dependency(command):
    events = []

    def changed_adapter(*_args):
        raise ValueError("reviewed source differs")

    values = {"argparse": argparse, "Path": Path, "safe_state": lambda path: path,
              "events": events, "require": require, "load_tmux_adapter": changed_adapter}
    exec(proposal.add_tmux_cli_guards(LEGACY_PROTOCOL), values)
    with pytest.raises(ValueError, match="reviewed source"):
        values["main"]([command, "--registry", "/private/example/registry.json",
                        "--tmux-adapter", "/changed/adapter.py", "--tmux-reviewed-sha256", "0" * 64])
    assert events == []
