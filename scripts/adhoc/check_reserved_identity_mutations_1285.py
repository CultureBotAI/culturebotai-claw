"""Distinguish future admission identity/key guards for #1285, 2026-11-15.

Inputs: current workflow and focused regression. Output: new JSON receipt path.
Each fresh-process green/red/green check restores the exact workflow bytes.
No remote operations or admission changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = ".github/workflows/governance-fleet-audit.yaml"
TEST = "tests/test_id_label_workflow.py::test_reserved_audit_key_will_not_break_a_later_fleet_admission"
CASES = (
    ("literal_identity",
     "from kg_microbe_governance.private_scaleup_audit import PRIVATE as private_repository",
     'private_repository = "CultureBotAI/ScaleupMech"'),
    ("literal_key", 'private_key = private_repository.rsplit("/", 1)[-1].casefold()',
     'private_key = "scaleupmech"'),
)


def run() -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="reserved-identity-bytecode-") as bytecode:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONPYCACHEPREFIX": bytecode}
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", TEST],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Receipt already exists; preserve earlier evidence")
    path = ROOT / RELATIVE
    original = path.read_bytes()
    text = original.decode()
    receipts = []
    for name, old, new in CASES:
        if text.count(old) != 2:
            raise ValueError(f"Expected both workflow selectors for {name}")
        green = run()
        if green.returncode or "1 passed" not in green.stdout:
            raise RuntimeError(green.stdout + green.stderr)
        try:
            path.write_text(text.replace(old, new))
            red = run()
            if red.returncode != 1 or "1 failed" not in red.stdout or "AssertionError" not in red.stdout:
                raise RuntimeError(red.stdout + red.stderr)
        finally:
            path.write_bytes(original)
        restored = run()
        if restored.returncode or "1 passed" not in restored.stdout or path.read_bytes() != original:
            raise RuntimeError("Restored regression failed: " + restored.stdout + restored.stderr)
        receipts.append({
            "name": name, "path": RELATIVE, "test": TEST,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "mutated_sha256": hashlib.sha256(text.replace(old, new).encode()).hexdigest(),
            "green_exit": green.returncode, "red_exit": red.returncode,
            "restored_exit": restored.returncode, "restored_bytes": True,
            "failure": red.stdout,
        })
        print(f"Verified green/red/green: {name}", flush=True)
    with args.output.open("x") as handle:
        json.dump({"captured_at": datetime.now(timezone.utc).isoformat(),
                   "mutations": receipts}, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
