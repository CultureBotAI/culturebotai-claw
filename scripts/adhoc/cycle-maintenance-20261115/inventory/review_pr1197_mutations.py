#!/usr/bin/env python3
"""Offline PR1197 mutation review; 2026-11-15, issues 1198/1199/1263.

Inputs: review worktree source/tests. Outputs: NEW durable directory with paired
baseline/mutant pytest receipts and logs. Only source in child memory is changed.
A setup/import/collection failure is never evidence that a mutant was killed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

CASES = {
    "descending-order": ('-len(data["issues"].get(repo, []))', 'len(data["issues"].get(repo, []))', "test_backlog_order_is_descending_with_stable_ties_and_errors_last"),
    "stale-overlay": ('if value.get("updated_at") != current[key]["updatedAt"]:', "if False:", "test_invalid_or_stale_annotations_are_refused"),
    "closed-window": ("if start <= closed_at <= end:", "if True:", "test_closed_window_includes_both_boundaries_excludes_prs_and_reopened"),
    "markdown-metrics": ('fields.extend(["pr_open", "pr_conflicts", "pr_drafts"])', "fields.extend([])", "test_markdown_preserves_backlog_and_optional_pr_metrics"),
}


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def child(worktree, receipt, name, mode):
    import pytest

    source = worktree / "scripts/fleet_issue_status.py"
    code = source.read_text()
    before, after, selected = CASES[name]
    if code.count(before) != 1:
        raise ValueError("mutation anchor must match exactly once")
    sys.path[:0] = [str(worktree / part) for part in ("scripts", "src", ".")]
    spec = importlib.util.spec_from_file_location("fleet_issue_status", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fleet_issue_status"] = module
    exec(compile(code.replace(before, after) if mode == "mutant" else code,
                 str(source), "exec"), module.__dict__)
    observations = {"case": name, "mode": mode, "collection_errors": [],
                    "collected": [], "reports": [], "mutation_applied": mode == "mutant"}

    class Recorder:
        def pytest_collection_finish(self, session):
            observations["collected"] = [item.nodeid for item in session.items]

        def pytest_collectreport(self, report):
            if report.failed:
                observations["collection_errors"].append(report.nodeid)

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_makereport(self, item, call):
            result = yield
            report = result.get_result()
            observations["reports"].append({"nodeid": report.nodeid,
                "when": report.when, "outcome": report.outcome,
                "exception_type": call.excinfo.typename if call.excinfo else None})

    result = int(pytest.main(["-q", str(worktree / "tests/test_fleet_issue_status.py")
                             + "::" + selected, "-p", "no:cacheprovider"], plugins=[Recorder()]))
    observations["exit_code"] = result
    write_new(receipt, observations)
    return result


def valid_attempt(value, mode, name):
    """Require actual selected test calls, successful setup/teardown, and no skips."""
    if (not isinstance(value, dict) or value.get("case") != name or value.get("mode") != mode
            or value.get("mutation_applied") is not (mode == "mutant")
            or value.get("collection_errors") != []):
        return False
    nodes, reports = value.get("collected"), value.get("reports")
    if (not isinstance(nodes, list) or not nodes or len(nodes) != len(set(nodes))
            or not isinstance(reports, list)):
        return False
    selected = CASES[name][2]
    if any(not isinstance(node, str) or not (node.endswith("::" + selected)
           or "::" + selected + "[" in node) for node in nodes):
        return False
    calls = []
    for node in nodes:
        found = [row for row in reports if row.get("nodeid") == node]
        if len(found) != 3 or {row.get("when") for row in found} != {"setup", "call", "teardown"}:
            return False
        if any(row.get("outcome") != "passed" for row in found if row["when"] != "call"):
            return False
        calls.extend(row for row in found if row["when"] == "call")
    if len(reports) != len(nodes) * 3:
        return False
    if mode == "baseline":
        return value.get("exit_code") == 0 and all(row.get("outcome") == "passed" for row in calls)
    failures = [row for row in calls if row.get("outcome") == "failed"]
    return (value.get("exit_code") == 1 and bool(failures)
            and all(row.get("outcome") in {"passed", "failed"} for row in calls)
            and all(row.get("exception_type") in {"AssertionError", "Failed"} for row in failures))


def paired_kill(baseline, mutant, name):
    return (valid_attempt(baseline, "baseline", name)
            and valid_attempt(mutant, "mutant", name)
            and baseline["collected"] == mutant["collected"])


def review(worktree, output):
    worktree = worktree.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("review requires a new output directory")
    source = worktree / "scripts/fleet_issue_status.py"
    original = source.read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for name in CASES:
        attempts = {}
        for mode in ("baseline", "mutant"):
            receipt = output / f"{name}-{mode}.json"
            env = {**os.environ, "PYTHONPYCACHEPREFIX": str(output / f"cache-{name}-{mode}"),
                   "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
            command = [sys.executable, str(Path(__file__).resolve()), "--worktree", str(worktree),
                       "--output", str(receipt), "--case", name, "--mode", mode]
            run = subprocess.run(command, env=env, cwd=worktree, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            with (output / f"{name}-{mode}.log").open("x") as stream:
                stream.write(run.stdout)
            value = json.loads(receipt.read_text()) if receipt.is_file() else None
            if isinstance(value, dict) and value.get("exit_code") != run.returncode:
                value = None
            attempts[mode] = value
        results.append({"mutation": name, "killed": paired_kill(attempts["baseline"], attempts["mutant"], name),
                        "source_sha256": hashlib.sha256(original).hexdigest(), "attempts": attempts})
    unchanged = source.read_bytes() == original
    write_new(output / "results.json", {"source_unchanged": unchanged, "results": results})
    return unchanged and all(row["killed"] for row in results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--mode", choices=("baseline", "mutant"))
    args = parser.parse_args(argv)
    if bool(args.case) != bool(args.mode):
        parser.error("case and mode are internal paired child arguments")
    if args.case:
        return child(args.worktree, args.output, args.case, args.mode)
    return 0 if review(args.worktree, args.output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
