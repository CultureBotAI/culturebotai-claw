"""Prove physical-publication regressions for #1284, 2026-11-15.

Inputs: this isolated candidate's publisher and fixed-timestamp regression tests.
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
SOURCE = "scripts/mech_progress_publish.py"
BASE = "tests/test_progress_public_membership.py::"
POLICY_TEST = BASE + "test_policy_only_change_rewrites_physical_documents_before_noop"
CASES = {
    "physical-comparison": (
        b"    if previous_documents == bundle and previous_head:",
        b"    if previous == bundle and previous_head:",
        POLICY_TEST + "[publish]",
    ),
    "physical-read": (
        b'    return head, {"history": history, "snapshot": snapshot}',
        b"    return head, public_bundle(history, snapshot, manifest, expand=False)",
        POLICY_TEST + "[collect_once]",
    ),
    "collector-evidence": (
        b"bundle, head, remote, initialize=initialize, api=api, previous_documents=documents,",
        b"bundle, head, remote, initialize=initialize, api=api,",
        POLICY_TEST + "[collect_once]",
    ),
    "absent-physical-proof": (
        b"    if previous_documents == bundle and previous_head:",
        b"    if (previous_documents or previous) == bundle and previous_head:",
        BASE + "test_projected_previous_without_physical_evidence_cannot_skip_publication",
    ),
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
    source = ROOT / SOURCE
    original = source.read_bytes()
    receipts = []
    for name in ([args.case] if args.case else CASES):
        needle, replacement, selector = CASES[name]
        if original.count(needle) != 1:
            raise ValueError(f"Mutation anchor changed: {name}")
        baseline = run(selector)
        if baseline.returncode:
            raise RuntimeError(baseline.stdout + baseline.stderr)
        try:
            source.write_bytes(original.replace(needle, replacement))
            red = run(selector)
            if red.returncode != 1 or "failed" not in red.stdout:
                raise RuntimeError(f"Mutation survived: {name}\n{red.stdout}{red.stderr}")
        finally:
            source.write_bytes(original)
        restored = run(selector)
        if restored.returncode or source.read_bytes() != original:
            raise RuntimeError(restored.stdout + restored.stderr)
        receipts.append({
            "case": name, "selector": selector,
            "source_sha256": {SOURCE: hashlib.sha256(original).hexdigest()},
            "baseline_exit": baseline.returncode, "mutant_exit": red.returncode,
            "restored_exit": restored.returncode,
        })
        print(f"{name}: green/red/green", file=sys.stderr, flush=True)
    output = json.dumps({
        "issue": 1284, "checked_at": datetime.now(timezone.utc).isoformat(),
        "fresh_pytest_processes": True, "cases": receipts,
    }, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
