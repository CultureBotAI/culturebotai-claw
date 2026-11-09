#!/usr/bin/env python3
"""Prove exact-consumer and frozen postverify guards for #1004, 2026-11-08.

Inputs: current package and admitted-sync tests. Outputs: isolated copied package,
fresh-process failure log and hash-bound receipt under a new workspace path.
No production mutation, target synchronization, provider call or network access.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kg_microbe_governance/__init__.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--guard", required=True, choices=["consumer", "postverify"])
    args = parser.parse_args()
    output = args.output.absolute()
    if ".." in output.parts or not output.is_relative_to(ROOT / "workspace"):
        raise ValueError("Use a new literal workspace path")
    output.mkdir(exist_ok=False)
    package = output / "code/kg_microbe_governance"
    shutil.copytree(SOURCE.parent, package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    original = SOURCE.read_bytes()
    cases = {
        "consumer": ("if consumer == ADMITTED:", "if True:",
                     "test_admitted_source_is_never_a_generic_old_package_exception[other_consumer]", "DID NOT RAISE"),
        "postverify": ("remaining = _plan_sync(manifest, consumer, root, canonical_ref, desired=desired)",
                       "remaining = _plan_sync(manifest, consumer, root, canonical_ref)",
                       "test_public_admitted_plan_install_and_noop_keep_same_old_source", "Canonical artifact checksum drift"),
    }
    before, after, node, expected = cases[args.guard]
    text = original.decode()
    if text.count(before) != 1:
        raise ValueError("Mutation target changed")
    (package / "__init__.py").write_text(text.replace(before, after))
    test = output / "test_admitted_sync_mutant.py"
    text = (ROOT / "tests/test_governance_admitted_sync.py").read_text()
    text = text.replace("ROOT = Path(__file__).resolve().parents[1]", f"ROOT = Path({str(ROOT)!r})")
    # Assert import origin so an editable install cannot hide the mutation.
    text = text.replace("import kg_microbe_governance as governance",
                        "import kg_microbe_governance as governance\n"
                        f"assert Path(governance.__file__).resolve() == Path({str(package / '__init__.py')!r})")
    test.write_text(text)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(output / "code"), str(ROOT / "src"), str(ROOT)))
    env["PYTHONPYCACHEPREFIX"] = str(output / "bytecode")
    result = subprocess.run([sys.executable, "-m", "pytest", "-c", os.devnull, "-q", f"{test}::{node}"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    (output / "failure.log").write_text(log)
    if result.returncode != 1 or expected not in log:
        raise ValueError("Expected targeted mutation failure did not occur")
    if SOURCE.read_bytes() != original:
        raise ValueError("Production source changed")
    receipt = {"format": "edgemech-admitted-sync-mutation/v1", "guard": args.guard,
               "node": node, "expected_failure": expected, "exit_code": result.returncode,
               "source_sha256": hashlib.sha256(original).hexdigest(),
               "log_sha256": hashlib.sha256(log.encode()).hexdigest(),
               "production_source_unchanged": True}
    (output / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
