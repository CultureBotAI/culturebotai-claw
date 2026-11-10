#!/usr/bin/env python3
"""Review historical-goal reconciliation; apply only an exact approved record.

Default planning performs read-only native/Git/GitHub checks, never a terminal
observation or input. --validate-record checks draft shape without live queries.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

import mech_session_supervisor as supervisor

from kg_microbe_workflows.reconciliation import (
    ReconciliationError,
    decode,
    prepare,
    regular_bytes,
    require,
    validate_record,
)


@contextmanager
def lock(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), "lock path is a symlink")
    require(path.parent.is_dir(), "lock directory must already exist")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), "lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--validate-record", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-sha256")
    args = parser.parse_args(argv)
    record_path = args.record.absolute()
    record = decode(regular_bytes(record_path))
    if args.validate_record:
        require(not args.apply and not args.approved_sha256, "shape validation cannot apply")
        validate_record(record)
        print(json.dumps({"status": "valid_record", "record_status": record["record_status"], "applied": False}))
        return 0
    require(args.config is not None, "--config is required for a plan or application")
    config_path = args.config.absolute()
    config = supervisor.validate_config(decode(regular_bytes(config_path)))
    # Use the reviewed deployed reader, never a configurable alternate adapter.
    require(Path(config["native_reader_path"]).resolve() == supervisor.ROOT / "scripts/mech_session_native.py",
            "reconciliation requires the deployed reviewed native reader")
    instance = supervisor.Supervisor(config, notifier=object())
    if args.apply:
        target = next((t for t in config["targets"] if t["repository_key"] == record["repository_key"]), None)
        require(target is not None, "unknown repository")
        regular_bytes(instance.runtime / "STOP")
        with lock(instance.runtime / "supervisor.lock"):
            with lock(Path(config["input_lock_dir"]) / (Path(target["tty"]).name + ".lock")):
                result = prepare(instance, supervisor, config_path, record_path, args.approved_sha256, apply=True)
    else:
        require(args.approved_sha256 is None, "approval digest is only accepted with --apply")
        result = prepare(instance, supervisor, config_path, record_path)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReconciliationError, supervisor.SupervisorError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error), "sent_input": False}), file=sys.stderr)
        raise SystemExit(1)
