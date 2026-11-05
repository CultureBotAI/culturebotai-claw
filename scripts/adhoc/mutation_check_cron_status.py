#!/usr/bin/env python3
"""Mutation check for scripts/cron_status.py: each rule's test goes red when the rule is reverted.

Purpose: AGENTS.md requires confirming that a test for a distinction fails
when the distinction is removed. Each mutant is one exact replacement in
scripts/cron_status.py, asserted to match once. tests/test_cron_status.py runs
in a fresh Python process per mutant, and the original bytes are then restored
from a backup, never from git.
Inputs: none; run from the claw checkout root.
Outputs: one line per mutant, killed or SURVIVED; a nonzero exit if any
survives.
Serves: the cron-status skill PR. Written 2026-11-05.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOURCE = Path("scripts/cron_status.py")
MUTANTS = [
    ("lateness flagged at 2 h", "LATE = GRACE\n", "LATE = dt.timedelta(hours=2)\n"),
    ("disabled workflow not flagged", '    if status.state != "active":\n', "    if False:\n"),
    ("DOM/DOW combined with AND", "            return in_days or in_weekdays", "            return in_days and in_weekdays"),
    ("repository failure swallowed", "            failures[repository] = str(exc).splitlines()[0][:200]\n",
     "            pass\n"),
    ("start/step stops at its start", "            end = high if step != 1 else start", "            end = start"),
    ("silent workflow not flagged", "    if status.expected_due and total == 0:\n", "    if False:\n"),
]

original = SOURCE.read_bytes()
survivors = 0
try:
    for name, old, new in MUTANTS:
        text = original.decode("utf-8")
        if text.count(old) != 1:
            print(f"ERROR     {name}: matched {text.count(old)} times")
            survivors += 1
            continue
        SOURCE.write_text(text.replace(old, new), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                    "tests/test_cron_status.py"], capture_output=True, text=True)
        killed = completed.returncode != 0
        print(f"{'killed   ' if killed else 'SURVIVED '} {name}")
        survivors += not killed
finally:
    SOURCE.write_bytes(original)
print(f"{len(MUTANTS) - survivors} of {len(MUTANTS)} mutants killed")
sys.exit(1 if survivors else 0)
