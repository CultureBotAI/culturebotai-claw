"""Verify #1148's legacy fixture scope distinction in fresh pytest processes.

Inputs: current integration checkout and its Python test environment.
Outputs: printed red/green receipt; original test bytes restored even on error.
Purpose: repair the post-expansion Edge fixture, issue #1148, 2026-11-10.
Run only when no other invocation is testing this file.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "tests/test_governance_infrastructure_admission.py"
SELECTOR = "tests/test_governance_infrastructure_admission.py::test_post_admission_catalogue_addition_permits_withheld_capability_and_rejects_drift"
FIX = '''    fleet["mechs"] = {
        key: fleet["mechs"][key]
        for key in json.loads(admitted_manifest)["consumers"]
    }
'''


def run():
    env = dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}:{ROOT}")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", SELECTOR, "--tb=short"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )


def main():
    original = TARGET.read_bytes()
    text = original.decode()
    assert text.count(FIX) == 1
    baseline = run()
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    try:
        TARGET.write_text(text.replace(FIX, ""))
        mutant = run()
        assert mutant.returncode == 1, mutant.stdout + mutant.stderr
        assert "Admission fleet identities differ from governance" in mutant.stdout
    finally:
        TARGET.write_bytes(original)
    restored = run()
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert TARGET.read_bytes() == original
    print(json.dumps({
        "issue": 1148,
        "test": SELECTOR,
        "test_sha256": hashlib.sha256(original).hexdigest(),
        "baseline_exit": baseline.returncode,
        "original_fixture_mutant_exit": mutant.returncode,
        "restored_exit": restored.returncode,
        "production_code_changed": False,
    }, indent=2))


if __name__ == "__main__":
    main()
