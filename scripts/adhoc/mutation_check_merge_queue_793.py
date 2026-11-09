#!/usr/bin/env python3
"""Mutation check for #793: every condition of the pin-derived claw checkout rule is tested.

Purpose: AGENTS.md requires reverting a fix to confirm its test goes red. Each
mutant below removes one condition from the rule in
src/kg_microbe_merge_queue/__init__.py. The mutant is applied in place, the
merge-queue execution tests run in a fresh Python process, and the original
bytes are then restored from a backup, never from git, so uncommitted work is
safe.
Inputs: none; run from the claw checkout root.
Outputs: one line per mutant, killed or SURVIVED; a nonzero exit if any
survives.
Serves: culturebotai-claw#793, #818. Written 2026-11-05.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOURCE = Path("src/kg_microbe_merge_queue/__init__.py")
TESTS = ["tests/test_merge_queue_execution.py"]
MUTANTS = [
    ("pin-derived exception unused", "if not trusted_audit_base and not auxiliary and not pin_derived:",
     "if not trusted_audit_base and not auxiliary:"),
    ("governed-bytes condition dropped",
     '                and hashlib.sha256(text.encode("utf-8")).hexdigest() in governed_workflow_digests()\n', ""),
    ("repository condition dropped", "                options.get(\"repository\") == CLAW\n", "                True\n"),
    ("step-output ref condition dropped",
     "                and isinstance(ref, str) and PIN_DERIVED_REF.fullmatch(ref) is not None\n", ""),
    # #818: hashing a normalised text would admit bytes vendored-sync rejects.
    ("hash input normalises CRLF", 'hashlib.sha256(text.encode("utf-8"))',
     'hashlib.sha256(text.replace("\\r\\n", "\\n").encode("utf-8"))'),
    ("hash input strips a BOM", 'hashlib.sha256(text.encode("utf-8"))',
     'hashlib.sha256(text.lstrip("\\ufeff").encode("utf-8"))'),
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
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
                                   capture_output=True, text=True)
        killed = completed.returncode != 0
        print(f"{'killed   ' if killed else 'SURVIVED '} {name}")
        survivors += not killed
finally:
    SOURCE.write_bytes(original)
print(f"{len(MUTANTS) - survivors} of {len(MUTANTS)} mutants killed")
sys.exit(1 if survivors else 0)
