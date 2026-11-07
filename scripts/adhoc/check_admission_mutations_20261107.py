#!/usr/bin/env python3
"""Prove #960 boundary regressions fail when their guards are removed, 2026-11-07.

Inputs: current canonical sources/tests. Outputs: isolated mutants, child logs
and a receipt in a new ignored workspace directory. Production files are never
edited. Each mutation runs pytest in a fresh Python process with fresh bytecode.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/kg_microbe_governance/infrastructure_admission.py"
HELPER = ROOT / "scripts/adhoc/verify_edgemech_admission_canary_20261107.py"
WORKFLOW = ROOT / ".github/workflows/governance-fleet-audit.yaml"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=["capability", "payload", "bootstrap", "source_snapshot", "receipt", "workflow_guard"])
    args = parser.parse_args()
    output = args.output.absolute()
    if not output.is_relative_to(ROOT / "workspace") or ".." in output.parts:
        raise ValueError("Use a new literal workspace directory")
    output.mkdir(parents=False, exist_ok=False)
    module_bytes, helper_bytes = MODULE.read_bytes(), HELPER.read_bytes()
    workflow_bytes = WORKFLOW.read_bytes()
    policy_test = (ROOT / "tests/test_governance_infrastructure_admission.py").read_text()
    cases = [
        ("capability", 'elif capability.get("status") not in {"disabled", "not_applicable"}:',
         "elif False:", "test_even_rehashed_candidate_cannot_expand_declared_transition[capability]"),
        ("payload", "if admitted != prior:", "if False:",
         "test_even_rehashed_candidate_cannot_expand_declared_transition[payload]"),
        ("bootstrap", 'if main != policy["bootstrap_main_ref"]:', "if False:",
         "test_candidate_completeness_distinguishes_exact_bootstrap_from_changed_main"),
        ("source_snapshot", "    from .cycle_release_audit import _snapshot\n",
         "    return parse_manifest(current_manifest), dict(current_payloads)\n    from .cycle_release_audit import _snapshot\n",
         "test_initial_admission_source_ref_must_authenticate_actual_objects[absent]"),
    ]
    reports = []
    for name, old, new, node in cases:
        if args.only and args.only != name:
            continue
        source = module_bytes.decode()
        if source.count(old) != 1:
            raise ValueError(f"Mutation target is no longer exact: {name}")
        mutant = output / f"mutant_{name}.py"
        mutant.write_text(source.replace(old, new))
        preamble = (
            "import importlib.util as _mutation_util\nimport sys as _mutation_sys\n"
            f"_mutation_spec = _mutation_util.spec_from_file_location('kg_microbe_governance.infrastructure_admission', {str(mutant)!r})\n"
            "_mutation_module = _mutation_util.module_from_spec(_mutation_spec)\n"
            "_mutation_sys.modules[_mutation_spec.name] = _mutation_module\n"
            "_mutation_spec.loader.exec_module(_mutation_module)\n"
        )
        test = output / f"test_{name}_mutant.py"
        marker = "from __future__ import annotations\n"
        test.write_text(policy_test.replace(marker, marker + preamble, 1))
        reports.append(run(output, name, test, node))
    if not args.only or args.only == "receipt":
        mutant = output / "mutant_receipt.py"
        source = helper_bytes.decode()
        begin, end = source.index("def receipt_path("), source.index("def main():")
        mutant.write_text(source[:begin] +
                          'def receipt_path(path, consumer_root):\n'
                          '    path = path.absolute()\n'
                          '    if path.is_relative_to(consumer_root) or path.exists() or path.is_symlink():\n'
                          '        raise ValueError("Use a new receipt path outside the Edge checkout")\n'
                          '    return path\n\n\n' + source[end:])
        test = output / "test_receipt_mutant.py"
        text = (ROOT / "tests/test_edgemech_admission_canary.py").read_text()
        old = 'HELPER = Path(__file__).resolve().parents[1] / "scripts/adhoc/verify_edgemech_admission_canary_20261107.py"'
        if old not in text:
            raise ValueError("Receipt test loader changed")
        test.write_text(text.replace(old, f"HELPER = Path({str(mutant)!r})"))
        reports.append(run(output, "receipt", test, "test_receipt_parent_symlink_into_consumer_is_rejected"))
    if not args.only or args.only == "workflow_guard":
        mutant = output / "workflow-without-ref-guard.yaml"
        guard = ('          if ! [[ "$source_ref" =~ ^[0-9a-f]{40}$ ]]; then\n'
                 "            printf '%s\\n' 'Refusing invalid infrastructure data ref' >&2\n"
                 '            exit 2\n          fi\n')
        source = workflow_bytes.decode()
        if source.count(guard) != 1:
            raise ValueError("Workflow guard changed")
        mutant.write_text(source.replace(guard, ""))
        test = output / "test_workflow_mutant.py"
        text = (ROOT / "tests/test_governance_cycle_release_workflow.py").read_text()
        old = 'WORKFLOW = ROOT / ".github/workflows/governance-fleet-audit.yaml"'
        if old not in text:
            raise ValueError("Workflow test loader changed")
        test.write_text(text.replace(old, f"WORKFLOW = Path({str(mutant)!r})"))
        reports.append(run(output, "workflow_guard", test,
                           "test_only_protected_preparation_selects_one_immutable_data_fetch[True-main]",
                           expected="assert (0 != 0)"))
    if (MODULE.read_bytes() != module_bytes or HELPER.read_bytes() != helper_bytes
            or WORKFLOW.read_bytes() != workflow_bytes):
        raise ValueError("Production source unexpectedly changed")
    receipt = {"format": "edgemech-admission-mutation-proof/v1", "mutations": reports,
               "source_sha256": hashlib.sha256(module_bytes).hexdigest(),
               "helper_sha256": hashlib.sha256(helper_bytes).hexdigest(),
               "workflow_sha256": hashlib.sha256(workflow_bytes).hexdigest(),
               "production_sources_unchanged": True}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


def run(output, name, test, node, expected="DID NOT RAISE"):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src"), str(ROOT)))
    env["PYTHONPYCACHEPREFIX"] = str(output / f"bytecode-{name}")
    result = subprocess.run([sys.executable, "-m", "pytest", f"{test}::{node}", "-q"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    (output / f"{name}.log").write_text(result.stdout + result.stderr)
    if result.returncode != 1 or expected not in result.stdout:
        raise ValueError(f"Mutation did not produce the intended missing-guard assertion: {name}")
    return {"guard": name, "regression_failed_as_expected": True, "exit_code": result.returncode}


if __name__ == "__main__":
    main()
