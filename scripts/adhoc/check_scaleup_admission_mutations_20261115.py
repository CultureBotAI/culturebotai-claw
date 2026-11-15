"""Run fresh-process regression mutations for #1174/#1076/#1254, 2026-11-15.

Inputs: this branch's repaired files and focused tests. Output: retained JSON
receipts. Restores the exact input bytes after each bounded local mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    row_path = "src/kg_microbe_governance/cycle_release_audit.py"
    original_row = (ROOT / row_path).read_text()
    guard_start = original_row.index("        if (\n            not isinstance(row, Mapping)")
    guard_end = original_row.index("        rows.append(dict(row))", guard_start)
    workflow_path = ".github/workflows/governance-fleet-audit.yaml"
    candidate_path = "docs/reviews/2026-11-15-scaleup-admission/candidate.yaml"
    evidence_path = "docs/reviews/2026-11-15-scaleup-admission/evidence.json"
    evidence = json.loads((ROOT / evidence_path).read_bytes())
    wrong_tree = {**evidence, "git_tree": {**evidence["git_tree"], "sha": evidence["revision"]}}
    mutations = [
        ("unchecked_deferred_row", row_path,
         original_row[:guard_start] + original_row[guard_end:],
         "tests/test_governance_private_release_hook.py::test_deferred_row_contract_rejects_forged_verification_or_counts"),
        ("literal_bootstrap_key", workflow_path,
         (ROOT / workflow_path).read_text().replace(
             'private_key = private_repository.rsplit("/", 1)[-1].casefold()',
             'private_key = "scaleupmech"'),
         "tests/test_id_label_workflow.py::test_reserved_audit_key_will_not_break_a_later_fleet_admission"),
        ("copied_assay_reason", candidate_path,
         (ROOT / candidate_path).read_text().replace(
             "Scale-transfer evidence is not a microbial environment inventory.",
             "Assay evidence is not a microbial environment inventory."),
         "tests/test_scaleup_admission_candidate.py::test_scaleup_candidate_preserves_domain_reasons_and_withholds_execution"),
        ("commit_used_as_tree", evidence_path, json.dumps(wrong_tree, indent=2) + "\n",
         "tests/test_scaleup_admission_candidate.py::test_scaleup_candidate_is_review_only_and_bound_to_a_nonempty_tree"),
    ]
    receipts = []
    for name, relative, mutated, target in mutations:
        path = ROOT / relative
        original = path.read_bytes()
        if original == mutated.encode():
            raise ValueError(f"Mutation made no change: {name}")
        try:
            path.write_text(mutated)
            with tempfile.TemporaryDirectory(prefix="scaleup-mutation-bytecode-") as bytecode:
                env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
                       "PYTHONPYCACHEPREFIX": bytecode}
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "--maxfail=1", target],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
                )
            if result.returncode != 1 or "FAILED " not in result.stdout:
                raise ValueError(f"Mutation did not fail its assertion: {name}\n{result.stdout}\n{result.stderr}")
            receipts.append({"name": name, "path": relative, "test": target,
                             "original_sha256": hashlib.sha256(original).hexdigest(),
                             "mutated_sha256": hashlib.sha256(mutated.encode()).hexdigest(),
                             "exit_code": result.returncode, "output": result.stdout})
        finally:
            path.write_bytes(original)
        print(f"Verified distinguishing mutation: {name}", flush=True)
    output = ROOT / "docs/reviews/2026-11-15-scaleup-admission/mutations.json"
    output.write_text(json.dumps({"captured_at": datetime.now(timezone.utc).isoformat(),
                                  "mutations": receipts}, indent=2) + "\n")


if __name__ == "__main__":
    main()
