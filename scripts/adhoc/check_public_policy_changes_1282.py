"""Prove #1282 policy-change regressions against reviewed PR #1280, 2026-11-15.

Inputs: this isolated candidate and immutable reviewed commit aed6275103.
Outputs: fresh-pytest green/red/green JSON receipts; source bytes are restored.
Run without concurrent edits or tests. No Git or network mutation is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEWED = "aed62751030672300f3ee4394c37357c435b0d00"
FILES = ("src/kg_microbe_progress/__init__.py", "scripts/mech_progress_publish.py")
BASE = "tests/test_progress_public_membership.py::"
CASES = {
    "second-exclusion": (FILES, BASE + "test_policy_change_reads_reconciles_and_republishes_retained_membership[exclude_again]"),
    "reenabled-member": (FILES, BASE + "test_policy_change_reads_reconciles_and_republishes_retained_membership[reenable]"),
    "retained-history": ((FILES[1],), BASE + "test_policy_change_reads_reconciles_and_republishes_retained_membership[reenable]"),
    "snapshot-validation": ((FILES[0],), BASE + "test_retained_subset_still_validates_its_exact_membership_and_evidence[omitted]"),
}


def run(selector: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", selector],
        cwd=ROOT, env=dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}:{ROOT}"),
        text=True, capture_output=True, check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipts = []
    for name in ([args.case] if args.case else CASES):
        files, selector = CASES[name]
        originals = {relative: (ROOT / relative).read_bytes() for relative in files}
        baseline = run(selector)
        if baseline.returncode:
            raise RuntimeError(baseline.stdout + baseline.stderr)
        try:
            for relative, original in originals.items():
                if name == "snapshot-validation":
                    needle = b"    validate_bundle(history, snapshot, retained)"
                    if original.count(needle) != 1:
                        raise ValueError("Retained snapshot validator changed")
                    mutant = original.replace(needle, b"    validate_history(history, fleet)")
                else:
                    mutant = subprocess.run(
                        ["git", "show", f"{REVIEWED}:{relative}"], cwd=ROOT,
                        capture_output=True, check=True,
                    ).stdout
                (ROOT / relative).write_bytes(mutant)
            red = run(selector)
            if red.returncode != 1 or "failed" not in red.stdout:
                raise RuntimeError(f"Mutation survived: {name}\n{red.stdout}{red.stderr}")
        finally:
            for relative, original in originals.items():
                (ROOT / relative).write_bytes(original)
        restored = run(selector)
        if restored.returncode or any((ROOT / path).read_bytes() != raw for path, raw in originals.items()):
            raise RuntimeError(restored.stdout + restored.stderr)
        receipts.append({
            "case": name, "selector": selector,
            "source_sha256": {path: hashlib.sha256(raw).hexdigest() for path, raw in originals.items()},
            "baseline_exit": baseline.returncode, "mutant_exit": red.returncode,
            "restored_exit": restored.returncode,
        })
        print(f"{name}: green/red/green", file=sys.stderr, flush=True)
    output = json.dumps({
        "issue": 1282, "reviewed_commit": REVIEWED,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "fresh_pytest_processes": True, "cases": receipts,
    }, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
