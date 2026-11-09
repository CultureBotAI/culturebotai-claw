#!/usr/bin/env python3
"""Reproduce the seventh review's LaunchAgent escapes against scripts/cron_status.py.

Purpose: Codex's seventh adversarial review of PR #820 found exceptions that
still escape collect_local and abort the whole cron-status report: an XML plist
naming an unknown encoding (LookupError), and a LaunchAgents directory whose
parent cannot be searched (is_dir raises PermissionError on Python 3.13). While
reproducing them, a third turned up: a deeply nested binary plist
(RecursionError). It prints one line per case and exits 1 unless every case is
named as a local-source error with any valid sibling plist still listed.
Inputs: none; run from the claw checkout root. Plists are written to a temporary
directory; crontab is faked as absent and launchctl as not-found, so no real
scheduler is read or changed.
Outputs: stdout only.
Serves: PR #820 and the round-7 review issue #837. Written 2026-11-05.
"""
from __future__ import annotations

import os
import plistlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "scripts/adhoc")
import cron_status as cs  # noqa: E402
from repro_cron_status_launchd_round6 import GOOD, fake_run  # noqa: E402


def deep_binary_plist(depth: int = 100_000) -> bytes:
    """A binary plist of `depth` nested one-element arrays: valid framing, too deep to parse."""
    header = b"bplist00"
    body, offsets, position = b"", [], len(header)
    for index in range(depth):
        offsets.append(position)
        item = bytes([0xA1]) + (index + 1).to_bytes(4, "big") if index < depth - 1 else bytes([0xA0])
        body += item
        position += len(item)
    table = b"".join(offset.to_bytes(4, "big") for offset in offsets)
    trailer = bytes(6) + bytes([4, 4]) + depth.to_bytes(8, "big") + bytes(8) + position.to_bytes(8, "big")
    return header + body + table + trailer


def run(name: str, agents: Path, expect_good: bool) -> bool:
    try:
        jobs, errors = cs.collect_local(fake_run, agents)
    except BaseException as exc:  # the defect being reproduced is an escape
        print(f"raised      {name}: {type(exc).__name__}: {str(exc)[:100]}")
        return False
    listed = [job.job for job in jobs]
    print(f"{'incomplete' if errors else 'complete  '}  {name}: listed={listed} errors={[e[:100] for e in errors]}")
    return bool(errors) and (("me.good" in listed) == expect_good)


def file_case(name: str, content: bytes) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        agents = Path(tmp)
        (agents / "good.plist").write_bytes(plistlib.dumps(GOOD))
        (agents / "bad.plist").write_bytes(content)
        return run(name, agents, expect_good=True)


def blocked_parent_case() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        parent = Path(tmp) / "blocked"
        agents = parent / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "good.plist").write_bytes(plistlib.dumps(GOOD))
        parent.chmod(0)
        try:
            return run("unsearchable parent directory", agents, expect_good=False)
        finally:
            parent.chmod(0o700)


def main() -> int:
    ok = file_case("unknown XML encoding", b'<?xml version="1.0" encoding="bogus"?><plist><dict/></plist>')
    ok &= file_case("deeply nested binary plist", deep_binary_plist())
    if os.geteuid() != 0:  # root searches a mode-0 directory anyway
        ok &= blocked_parent_case()
    print("all cases incomplete as required" if ok else "DEFECTS REPRODUCED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
