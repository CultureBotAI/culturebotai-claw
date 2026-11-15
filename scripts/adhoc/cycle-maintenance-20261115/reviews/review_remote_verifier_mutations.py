"""Offline mutation controls for the PR-maintenance parent-2.1 contract, 2026-11-15.

Finding: https://github.com/CultureBotAI/culturebotai-claw/issues/1253.

Inputs: current source tree plus a separate clean, owned detached review worktree.
Outputs: exact copied-source/test hashes and pytest mutation logs beside that
review worktree. The source tree is never edited and no remote action is made.
Only the copy of pr_maintenance_remote.py is mutated and always restored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tree", required=True, type=Path)
    parser.add_argument("--review-tree", required=True, type=Path)
    args = parser.parse_args()
    source, root = args.source_tree.resolve(), args.review_tree.resolve()
    if source == root or source.is_relative_to(root) or root.is_relative_to(source):
        raise SystemExit("source and review trees must be separate")
    if Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                   text=True).strip()).resolve() != root:
        raise SystemExit("review path must be a Git worktree root")
    if subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=root,
                      capture_output=True).returncode != 1:
        raise SystemExit("review worktree must be detached")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root):
        raise SystemExit("review worktree must start clean")
    out = root.parent
    input_hashes = {}
    for name in ("kg_microbe_workflows", "kg_microbe_fleet"):
        path = Path("src") / name
        for file in sorted((source / path).rglob("*")):
            if file.is_symlink():
                raise SystemExit("source package symlink requires explicit review")
            if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                input_hashes[str(file.relative_to(source))] = sha(file.read_bytes())
        shutil.copytree(source / path, root / path, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    test = "tests/test_pr_maintenance_remote.py"
    shutil.copy2(source / test, root / test)
    input_hashes[test] = sha((root / test).read_bytes())
    module = root / "src/kg_microbe_workflows/pr_maintenance_remote.py"
    original = module.read_bytes()
    cases = [
        ("zero-checks-green", "unknown or not success", "unknown",
         test + "::test_no_check_rollup_or_zero_checks_cannot_claim_green[False]"),
        ("skip-inventory-reread", "if again != raw:", "if False and again != raw:",
         test + "::test_capture_never_accepts_inventory_changed_while_collecting_checks"),
        ("wrong-reviewed-head", 'or proofs[number].get("head_sha") != item["final_head_sha"]',
         'or False', test + "::test_merged_disposition_needs_the_same_independently_verified_proof"),
        ("registered-path-ignored", "or candidate in registered", "or False",
         test + "::test_cleanup_cannot_claim_present_symlink_registered_or_protected_worktree_removed[registered]"),
        ("unchecked-preservation-hash", 'if digest != descriptor.get("sha256") or digest != value["preservation_manifest_sha256"]:',
         "if False:", test + "::test_preservation_manifest_is_read_and_all_three_hash_references_agree"),
    ]
    receipts = []
    def run(name, selected):
        command = [sys.executable, "-m", "pytest", "-q", *selected,
                   "--basetemp=" + str(out / ("pytest-" + name))]
        environment = dict(os.environ, PYTHONPATH=str(root / "src"),
                           PYTHONPYCACHEPREFIX=str(out / ("pycache-" + name)))
        result = subprocess.run(command, cwd=root, env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / (name + ".log")).write_bytes(result.stdout)
        return {"name": name, "exit_code": result.returncode, "log_sha256": sha(result.stdout),
                "test_selection": selected}
    receipts.append(run("control", [test]))
    if receipts[-1]["exit_code"] != 0:
        raise SystemExit("baseline is not green; inspect retained control.log")
    try:
        for name, before, after, selected in cases:
            if original.decode().count(before) != 1:
                raise RuntimeError("mutation anchor missing or ambiguous: " + name)
            changed = original.decode().replace(before, after).encode()
            module.write_bytes(changed)
            result = run(name, [selected])
            result.update(before=before, after=after, mutated_source_sha256=sha(changed))
            receipts.append(result)
            module.write_bytes(original)
    finally:
        module.write_bytes(original)
    proof = {"at": datetime.now(timezone.utc).isoformat(), "original_module_sha256": sha(original),
             "restored_module_sha256": sha(module.read_bytes()), "input_sha256": input_hashes,
             "helper_sha256": sha(Path(__file__).read_bytes()), "receipts": receipts,
             "original_source_untouched": (source / "src/kg_microbe_workflows/pr_maintenance_remote.py").read_bytes() == original}
    (out / "counterfactuals.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"source_sha256": sha(original), "cases": [
        [item["name"], item["exit_code"]] for item in receipts]}))


if __name__ == "__main__":
    main()
