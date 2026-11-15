"""Verify malformed worktree-inventory regression, 2026-11-15.

Finding: https://github.com/CultureBotAI/culturebotai-claw/issues/1253.

Inputs: separate detached source-copy review tree and exact expected module hash.
Outputs: control/mutant logs and parser-counterfactual.json beside the worktree.
Related: PR-maintenance porcelain completeness finding reproduced by the tests.
This changes only the isolated module copy, restores it in finally, and performs
no remote operation or real worktree cleanup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-tree", required=True, type=Path)
    parser.add_argument("--expected-source-sha256", required=True)
    args = parser.parse_args()
    root = args.review_tree.resolve()
    if Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                   text=True).strip()).resolve() != root:
        raise SystemExit("not a worktree root")
    if subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=root,
                      capture_output=True).returncode != 1:
        raise SystemExit("review worktree must be detached")
    source = root / "src/kg_microbe_workflows/pr_maintenance_remote.py"
    original = source.read_bytes()
    if digest(original) != args.expected_source_sha256:
        raise SystemExit("source differs from selected review snapshot")
    before = "registered.update(parse_worktree_inventory(output.stdout))"
    after = ('registered.update(Path(line[9:]).resolve() for line in output.stdout.splitlines() '
             'if line.startswith("worktree "))')
    if original.decode().count(before) != 1:
        raise SystemExit("parser anchor missing or ambiguous")
    node = "tests/test_pr_maintenance_remote.py::test_partial_or_malformed_extra_worktree_blocks_are_not_silently_discarded"
    def run(name):
        process = subprocess.run([sys.executable, "-m", "pytest", "-q", node,
            "--basetemp=" + str(root.parent / ("pytest-" + name))], cwd=root,
            env=dict(os.environ, PYTHONPATH=str(root / "src"),
                     PYTHONPYCACHEPREFIX=str(root.parent / ("pycache-" + name))),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (root.parent / (name + ".log")).write_bytes(process.stdout)
        return {"name": name, "exit_code": process.returncode, "log_sha256": digest(process.stdout)}
    control = run("parser-control")
    if control["exit_code"]:
        raise SystemExit("control failed")
    try:
        source.write_bytes(original.decode().replace(before, after).encode())
        mutant = run("parser-mutant")
    finally:
        source.write_bytes(original)
    result = {"source_sha256": digest(original), "restored_sha256": digest(source.read_bytes()),
              "helper_sha256": digest(Path(__file__).read_bytes()), "test_selection": node,
              "before": before, "after": after, "receipts": [control, mutant]}
    (root.parent / "parser-counterfactual.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
