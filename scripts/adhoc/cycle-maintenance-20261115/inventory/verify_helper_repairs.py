"""Verify helper repairs without repeating the historical full review; 2026-11-15.

Issues 1263–1266. Inputs: retained audit/review, original PR1197 test worktree,
current helper source. Outputs: NEW private detailed evidence directory and NEW
public checksum-bound receipt beside this helper. Runs offline synthetic tests,
exact historical packaging and only the four paired mutation cases. No Git,
GitHub, runtime or original-evidence writes; no live inventory acquisition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audit-dir", "review-dir", "worktree", "evidence-dir", "receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    here = Path(__file__).resolve().parent
    root = here.parents[3]
    area, receipt = args.evidence_dir.absolute(), args.receipt.absolute()
    if (area.exists() or area.is_symlink() or receipt.exists() or receipt.is_symlink()
            or receipt.parent.resolve() != here):
        parser.error("evidence and receipt must be new; receipt belongs beside this helper")
    area.mkdir(parents=True, exist_ok=False)
    source = args.worktree / "scripts/fleet_issue_status.py"
    original = digest(source)
    observations = []

    def run(label, command):
        value = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=120,
            env={**os.environ, "PYTHONPATH": os.pathsep.join([str(root), str(root / "src")]),
                 "PYTHONDONTWRITEBYTECODE": "1"})
        log = area / (label + ".log")
        log.write_text(value.stdout + value.stderr)
        observations.append({"operation": label, "exit_code": value.returncode,
                             "log_sha256": digest(log)})
        if value.returncode:
            raise ValueError(label + " verification failed; detailed evidence retained")
        return value.stdout

    stdout = run("regressions", [sys.executable, "-m", "pytest", "-q",
        "tests/test_cycle_maintenance_inventory_helpers.py", "-p", "no:cacheprovider"])
    run("historical-packaging", [sys.executable, str(here / "package_inventory.py"),
        "--audit-dir", str(args.audit_dir), "--review-dir", str(args.review_dir),
        "--output-dir", str(area / "package")])
    run("paired-mutations", [sys.executable, str(here / "review_pr1197_mutations.py"),
        "--worktree", str(args.worktree), "--output", str(area / "paired-mutations")])
    package = json.loads((area / "package/inventory-and-review.json").read_text())
    mutations = json.loads((area / "paired-mutations/results.json").read_text())
    if digest(source) != original or not mutations["source_unchanged"]:
        raise ValueError("review source bytes changed")
    rows = [{"case": item["mutation"], "killed": item["killed"],
             "baseline_tests": len(item["attempts"]["baseline"]["collected"]),
             "mutant_tests": len(item["attempts"]["mutant"]["collected"])} for item in mutations["results"]]
    if not rows or not all(row["killed"] for row in rows):
        raise ValueError("paired mutation controls did not all pass")
    hashes = {p.name: digest(p) for p in sorted(here.glob("*.py"))}
    hashes["tests/test_cycle_maintenance_inventory_helpers.py"] = digest(root / "tests/test_cycle_maintenance_inventory_helpers.py")
    value = {"date": "2026-11-15", "repository": "CultureBotAI/culturebotai-claw",
        "repair_issues": [1263, 1264, 1265, 1266], "passed": True,
        "historical_summary_preserved_sha256": digest(here / "inventory-and-review.json"),
        "historical_input_sha256": package["historical_input_sha256"],
        "repaired_helpers": package["helpers"], "verified_source_sha256": hashes,
        "observations": observations, "pytest_summary": re.findall(r"\d+ passed in [\d.]+s", stdout),
        "paired_mutations": rows, "review_source_sha256": original,
        "full_historical_review_rerun": False, "original_evidence_modified": False,
        "live_api_calls": False}
    text = json.dumps(value, indent=2) + "\n"
    if re.search(r"/(?:Users|home)/[A-Za-z0-9]", text) or re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        raise ValueError("public receipt hygiene check failed")
    with receipt.open("x") as stream:
        stream.write(text)
    print(json.dumps({"passed": True, "paired_mutations_killed": len(rows),
                      "pytest_summary": value["pytest_summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
