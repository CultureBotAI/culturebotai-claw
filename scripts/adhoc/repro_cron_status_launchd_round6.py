#!/usr/bin/env python3
"""Reproduce the sixth review's LaunchAgent findings against scripts/cron_status.py.

Purpose: Codex's sixth adversarial review of PR #820 reported three ways a broken
LaunchAgent source still produced a report that looks complete, or no report at
all. This script checks each one. It prints one line per case,
"complete", "incomplete" or "raised", and exits 1 if any case does not come out
incomplete with the valid sibling plist still listed.
Inputs: none; run from the claw checkout root. Plists are written to a temporary
directory, crontab is faked as absent and launchctl as not-found, so no real
scheduler is read or changed.
Outputs: stdout only.
Serves: PR #820 and the round-6 review issue. Written 2026-11-05.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "scripts")
import cron_status as cs  # noqa: E402

GOOD = {"Label": "me.good", "StartInterval": 3600}
BAD_FIELDS = {
    "calendar is a string": {"Label": "bad", "StartCalendarInterval": "oops"},
    "calendar list of non-dicts": {"Label": "bad", "StartCalendarInterval": ["oops", 42]},
    "calendar list with one non-dict": {"Label": "bad", "StartCalendarInterval": [{"Hour": 6}, 42]},
    "calendar value is a string": {"Label": "bad", "StartCalendarInterval": {"Hour": "six"}},
    "calendar key unknown": {"Label": "bad", "StartCalendarInterval": {"Hours": 6}},
    "calendar hour out of range": {"Label": "bad", "StartCalendarInterval": {"Hour": 24}},
    "interval is a string": {"Label": "bad", "StartInterval": "60"},
    "interval is negative": {"Label": "bad", "StartInterval": -1},
    "interval is zero": {"Label": "bad", "StartInterval": 0},
    "interval is a boolean": {"Label": "bad", "StartInterval": True},
    "label missing": {"StartInterval": 60},
    "label empty": {"Label": "", "StartInterval": 60},
}


def fake_run(command: list[str]) -> subprocess.CompletedProcess:
    if command[0] == "crontab":
        return subprocess.CompletedProcess(command, 1, "", "crontab: no crontab for me")
    return subprocess.CompletedProcess(command, 113, "", 'Could not find service "x" in domain')


def case(name: str, prepare) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "LaunchAgents"
        directory.mkdir()
        (directory / "good.plist").write_bytes(plistlib.dumps(GOOD))
        prepare(directory)
        try:
            jobs, errors = cs.collect_local(fake_run, directory)
        except Exception as exc:  # the defect being reproduced is an escape
            print(f"raised      {name}: {type(exc).__name__}: {exc}")
            return False
        finally:
            directory.chmod(0o700)
        listed = [job.job for job in jobs]
        verdict = "incomplete" if errors else "complete  "
        print(f"{verdict}  {name}: listed={listed} errors={errors}")
        # An unreadable directory cannot list its good plist; everything else must.
        expect_good = name != "unreadable directory"
        return bool(errors) and (("me.good" in listed) == expect_good)


def main() -> int:
    ok = True
    for name, data in BAD_FIELDS.items():
        ok &= case(name, lambda d, data=data: (d / "bad.plist").write_bytes(plistlib.dumps(data)))
    ok &= case("truncated XML plist", lambda d: (d / "bad.plist").write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'))
    if os.geteuid() != 0:  # root reads a mode-0 directory anyway
        ok &= case("unreadable directory", lambda d: d.chmod(0))
    print("all cases incomplete as required" if ok else "DEFECTS REPRODUCED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
