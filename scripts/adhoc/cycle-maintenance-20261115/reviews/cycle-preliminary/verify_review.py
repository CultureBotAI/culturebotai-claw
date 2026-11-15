"""Offline independent re-review of root-owned maintenance fixes, 2026-11-15.

Inputs: explicit checkout with source and existing regression tests, issues
#1257, #1258, #1259 and #1260. Output: a new hash-bound JSON review receipt.
Each counterfactual runs pytest in a fresh interpreter with an in-memory source
mutation and fresh disposable bytecode cache. No implementation file, Git ref,
GitHub state, runtime or session is changed. Raw pytest logs are never published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CASES = [
    {"issue": 1257, "module": "kg_microbe_workflows.pr_maintenance_remote",
     "source": "src/kg_microbe_workflows/pr_maintenance_remote.py",
     "test": "tests/test_pr_maintenance_remote.py::test_check_rollup_union_selects_ids_only_on_concrete_types",
     "old": " __typename ... on CheckRun{id name status conclusion}",
     "new": " id __typename ... on CheckRun{id name status conclusion}",
     "failure_marker": "AssertionError"},
    {"issue": 1258, "module": "kg_microbe_workflows.pr_maintenance_remote",
     "source": "src/kg_microbe_workflows/pr_maintenance_remote.py",
     "test": "tests/test_pr_maintenance_remote.py::test_terminal_draft_reopened_at_final_inventory_cannot_claim_closure",
     "old": "if latest is not None:", "new": "if False:",
     "failure_marker": "DID NOT RAISE"},
    {"issue": 1259, "module": "kg_microbe_progress.prs",
     "source": "src/kg_microbe_progress/prs.py",
     "test": "tests/test_progress_prs.py::test_maintenance_receipt_preserves_backlog_goal_ownership[None]",
     "old": "members = [member for member in members if member.get(\"number\") not in backlog]",
     "new": "members = members", "failure_marker": "AssertionError"},
    {"issue": 1260, "module": "test_mech_session_supervisor:supervisor",
     "source": "scripts/mech_session_supervisor.py",
     "test": "tests/test_mech_pr_maintenance_supervisor.py::test_transient_pr_capture_failure_leaves_no_partial_freshness_archive",
     "old": "validate_frozen_issue_scope(issue_scope, target)",
     "new": "validate_frozen_issue_scope(issue_scope, target)\n            self.write(path, issue_scope)",
     "failure_marker": "AssertionError"},
]
REVIEWED_SOURCES = {
    "src/kg_microbe_workflows/pr_maintenance_remote.py",
    "scripts/mech_session_supervisor.py",
    "src/kg_microbe_progress/prs.py",
    "src/kg_microbe_workflows/closure.py",
    "src/kg_microbe_fleet/__init__.py",
    "tests/test_pr_maintenance_remote.py",
    "tests/test_mech_pr_maintenance_supervisor.py",
    "tests/test_progress_prs.py",
    "tests/test_fleet_manifest.py",
}
ORIGINAL_EVIDENCE = {
    "test_review_reproductions.py": "f30cc66fc0a89f412eb97acd9cc49357b6601b6f60a55680b9f8bad7bd5e22a8",
    "REVIEW.md": "ba31173d54bc4ddbdbed8f5ef5cb0850c0b40fa47252cf13d6df489aa1b29fb4",
    "graphql-proof.json": "a6b1c36b1439c46a2f29be73db863965acf0afd1da1b00b0880e57dfc7b0f877",
}
CHILD = r'''
import importlib, json, pathlib, sys
import pytest
request = json.loads(sys.argv[1])
root = pathlib.Path.cwd()
sys.path.insert(0, str(root / "tests"))
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root))
if request["mutation"]:
    case = request["case"]
    module_name, _, attribute = case["module"].partition(":")
    module = importlib.import_module(module_name)
    if attribute:
        module = getattr(module, attribute)
    source = (root / case["source"]).read_text()
    if source.count(case["old"]) != 1:
        raise SystemExit("counterfactual target no longer matches exactly once")
    exec(compile(source.replace(case["old"], case["new"]), module.__file__, "exec"), module.__dict__)
raise SystemExit(pytest.main(["-q", *request["tests"]]))
'''


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def run(root: Path, tests: list[str], case: dict | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="cycle-review-bytecode-") as cache:
        env = os.environ.copy()
        env["PYTHONPYCACHEPREFIX"] = cache
        env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in (".", "src", "tests"))
        request = {"mutation": case is not None, "case": case, "tests": tests}
        result = subprocess.run(
            [sys.executable, "-c", CHILD, json.dumps(request)], cwd=root,
            env=env, capture_output=True, text=True, timeout=90,
        )
    expected = 1 if case else 0
    marker = case["failure_marker"] if case else None
    passed = result.returncode == expected and (marker is None or marker in result.stdout)
    summaries = re.findall(r"\d+ (?:passed|failed)(?:, \d+ \w+)* in [\d.]+s", result.stdout)
    return {"tests": tests, "mode": "counterfactual" if case else "baseline",
            "issue": case["issue"] if case else None,
            "returncode": result.returncode, "expected_returncode": expected,
            "expected_failure_marker": marker, "expectation_met": passed,
            "pytest_summary": summaries[-1] if summaries else "unavailable",
            "stdout_sha256": sha256(result.stdout.encode()),
            "stderr_sha256": sha256(result.stderr.encode())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    output = args.output.absolute()
    helper = Path(__file__).resolve()
    if (not (root / "pyproject.toml").is_file() or not helper.is_relative_to(root)
            or output.resolve().parent != helper.parent or output.exists() or output.is_symlink()):
        parser.error("use the owning checkout and a new receipt path beside this helper")
    source_hashes = {path: sha256((root / path).read_bytes()) for path in sorted(REVIEWED_SOURCES)}
    observations = [run(root, [case["test"] for case in CASES])]
    observations.extend(run(root, [case["test"]], case) for case in CASES)
    unchanged = source_hashes == {
        path: sha256((root / path).read_bytes()) for path in sorted(REVIEWED_SOURCES)}
    passed = unchanged and all(row["expectation_met"] for row in observations)
    value = {"schema_version": "1.0.0", "kind": "independent_root_integration_rereview",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "repository": "CultureBotAI/culturebotai-claw", "authority": "review_only",
        "source_sha256": source_hashes, "helper_path": helper.relative_to(root).as_posix(),
        "helper_sha256": sha256(helper.read_bytes()), "original_evidence_sha256": ORIGINAL_EVIDENCE,
        "observations": observations, "sources_unchanged": unchanged, "passed": passed,
        "excluded_from_independent_review": ["pure PR maintenance validator", "LinkML schema", "skill and guide changes"],
        "runtime_or_adoption_authority": False}
    with output.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"passed": passed, "sources_unchanged": unchanged,
                      "counterfactuals_detected": sum(row["expectation_met"] for row in observations[1:])}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
