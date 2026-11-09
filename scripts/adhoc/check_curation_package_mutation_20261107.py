#!/usr/bin/env python3
"""Prove #985 support-shadow tests reject the old verification gap, 2026-11-07.

Inputs: this repository and an interpreter with pytest. Output: exclusive local
workspace with an isolated mutant, logs and hash-bound JSON receipt. The reviewed
source tree is never edited; the mutant is never imported by an adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.absolute()
    if output.exists() or ".." in output.parts or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("Mutation proof requires a new unaliased output directory")
    output.mkdir(parents=True)
    selected = "tests/test_curation_distribution.py::test_optional_review_support_module_shadowing_is_rejected"
    command = [str(args.python.resolve(strict=True)), "-m", "pytest", "-c", "/dev/null", "-q", selected]
    baseline = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
    (output / "baseline.log").write_text(baseline.stdout + baseline.stderr)
    if baseline.returncode != 0 or "2 passed" not in baseline.stdout:
        raise ValueError("Baseline support-shadow regressions did not pass")
    mutant = output / "mutant"
    paths = ["tests/test_curation_distribution.py", "scripts/adhoc/stage_curation_distribution_20261107.py",
             "scripts/adhoc/verify_curation_distribution_20261107.py"]
    for relative in paths:
        target = mutant / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    verifier = mutant / paths[-1]
    original = verifier.read_text()
    marker = 'if name.endswith(".py")) if reviews else ['
    if original.count(marker) != 1:
        raise ValueError("Expected exactly one full-closure selection guard")
    verifier.write_text(original.replace(marker, 'if name.endswith(".py")) if False else ['))
    rejected = subprocess.run(command, cwd=mutant, capture_output=True, text=True, timeout=120)
    (output / "mutant.log").write_text(rejected.stdout + rejected.stderr)
    if rejected.returncode != 1 or "2 failed" not in rejected.stdout or "DID NOT RAISE" not in rejected.stdout:
        raise ValueError("Mutant did not fail the intended support-shadow assertions")
    receipt = {
        "issue": "CultureBotAI/culturebotai-claw#985", "baseline_tests_passed": 2,
        "mutant_tests_failed": 2, "failure": "support shadowing no longer raises",
        "source_verifier_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "mutant_verifier_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
        "baseline_log_sha256": hashlib.sha256((output / "baseline.log").read_bytes()).hexdigest(),
        "mutant_log_sha256": hashlib.sha256((output / "mutant.log").read_bytes()).hexdigest(),
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with (output / "receipt.json").open("x") as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
