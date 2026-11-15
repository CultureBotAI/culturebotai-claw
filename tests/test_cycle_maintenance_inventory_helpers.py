"""Offline regressions for inventory-helper findings 1263–1266."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / "scripts/adhoc/cycle-maintenance-20261115/inventory"


def load(name):
    path = DIRECTORY / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    source = path.read_text()
    mutation = json.loads(os.environ.get("CLAW_INVENTORY_TEST_MUTATION", "null"))
    if mutation and mutation["module"] == name:
        assert source.count(mutation["old"]) == 1
        source = source.replace(mutation["old"], mutation["new"])
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def inventory():
    rest = [{"number": number, "head": {"sha": "a" * 40},
             "base": {"sha": "b" * 40}, "draft": False} for number in (1, 2)]
    checks = [{"number": number, "headRefOid": "a" * 40,
               "baseRefOid": "b" * 40, "isDraft": False} for number in (1, 2)]
    graph = {"data": {"repository": {"nameWithOwner": "CultureBotAI/culturebotai-claw",
        "defaultBranchRef": {"target": {"oid": "c" * 40}},
        "pullRequests": {"totalCount": 2, "pageInfo": {"hasNextPage": False},
                         "nodes": copy.deepcopy(checks)}}}}
    return rest, checks, graph, copy.deepcopy(rest)


def test_capture_accepts_only_matching_complete_identity_collections():
    helper = load("capture_pr_audit")
    assert helper.acquisition_agreement(*inventory(), "c" * 40, "c" * 40)["complete"] is True


def test_empty_check_rows_cannot_borrow_rest_completeness():
    helper = load("capture_pr_audit")
    before, _, graph, after = inventory()
    with pytest.raises(ValueError, match="drift"):
        helper.acquisition_agreement(before, [], graph, after, "c" * 40, "c" * 40)


@pytest.mark.parametrize("damage", ["duplicate", "wrong-number", "head", "base", "draft",
                                     "graph-rows", "after-rows", "pagination", "main"])
def test_inventory_duplicates_identity_drift_and_incomplete_graph_refuse(damage):
    helper = load("capture_pr_audit")
    before, checks, graph, after = inventory()
    latest = "c" * 40
    if damage == "duplicate":
        checks[1] = checks[0]
    elif damage == "wrong-number":
        checks[1]["number"] = 3
    elif damage in {"head", "base", "draft"}:
        key = {"head": "headRefOid", "base": "baseRefOid", "draft": "isDraft"}[damage]
        checks[0][key] = True if damage == "draft" else "d" * 40
    elif damage == "graph-rows":
        graph["data"]["repository"]["pullRequests"]["nodes"] = []
    elif damage == "after-rows":
        after.pop()
    elif damage == "pagination":
        graph["data"]["repository"]["pullRequests"]["pageInfo"]["hasNextPage"] = True
    else:
        latest = "d" * 40
    with pytest.raises(ValueError):
        helper.acquisition_agreement(before, checks, graph, after, "c" * 40, latest)


def test_failed_capture_persists_explicit_incomplete_receipt(tmp_path, monkeypatch):
    helper = load("capture_pr_audit")
    before, _, graph, _ = inventory()
    def fake_gh(args):
        if args[:2] == ["pr", "list"]:
            return []
        if args[:2] == ["api", "graphql"]:
            return graph
        if args[-1].endswith("/commits/main"):
            return {"sha": "c" * 40, "commit": {"tree": {"sha": "d" * 40}}}
        if "pulls?state=open" in args[-1]:
            return [before]
        if "--paginate" in args:
            return [[]]
        return {"number": int(args[-1].rsplit("/", 1)[-1])}
    monkeypatch.setattr(helper, "gh", fake_gh)
    output = tmp_path / "capture"
    with pytest.raises(ValueError, match="drift"):
        helper.capture(output)
    summary = json.loads((output / "snapshot-summary.json").read_text())
    assert summary["complete"] is False and summary["acquisition_agreement"] is False
    assert "drift" in summary["acquisition_error"]
    with pytest.raises(ValueError, match="new output"):
        helper.capture(output)


def attempt(mode, *, failed=False):
    name = "descending-order"
    node = "tests/test_fleet_issue_status.py::" + load("review_pr1197_mutations").CASES[name][2]
    value = {"case": name, "mode": mode, "mutation_applied": mode == "mutant",
             "collection_errors": [], "collected": [node], "reports": [],
             "exit_code": 1 if failed else 0}
    for when in ("setup", "call", "teardown"):
        value["reports"].append({"nodeid": node, "when": when,
            "outcome": "failed" if failed and when == "call" else "passed",
            "exception_type": "AssertionError" if failed and when == "call" else None})
    return value


def test_real_paired_control_accepts_assertion_kill():
    helper = load("review_pr1197_mutations")
    assert helper.paired_kill(attempt("baseline"), attempt("mutant", failed=True), "descending-order")


def test_failed_baseline_cannot_establish_mutation_kill():
    helper = load("review_pr1197_mutations")
    assert not helper.paired_kill(attempt("baseline", failed=True), attempt("mutant", failed=True), "descending-order")


@pytest.mark.parametrize("damage", ["absent", "collection", "no-tests", "setup", "teardown", "skip", "import", "different-test", "survived"])
def test_unrelated_errors_skips_or_collection_failures_never_kill(damage):
    helper = load("review_pr1197_mutations")
    baseline, mutant = attempt("baseline"), attempt("mutant", failed=True)
    if damage == "absent":
        mutant = None
    elif damage == "collection":
        mutant["collection_errors"] = ["tests/test_fleet_issue_status.py"]
    elif damage == "no-tests":
        mutant.update(collected=[], reports=[])
    elif damage in {"setup", "teardown"}:
        next(r for r in mutant["reports"] if r["when"] == damage)["outcome"] = "failed"
    elif damage == "skip":
        mutant["reports"][1]["outcome"] = "skipped"
    elif damage == "import":
        mutant["reports"][1]["exception_type"] = "ImportError"
    elif damage == "different-test":
        mutant["collected"] = ["other.py::test_unrelated"]
    else:
        mutant = attempt("mutant")
    assert not helper.paired_kill(baseline, mutant, "descending-order")


def test_missing_anchors_cannot_create_a_pytest_receipt(tmp_path):
    source = tmp_path / "scripts/fleet_issue_status.py"
    source.parent.mkdir()
    source.write_text("# no mutation anchor\n")
    receipt = tmp_path / "receipt.json"
    result = subprocess.run([sys.executable, str(DIRECTORY / "review_pr1197_mutations.py"),
        "--worktree", str(tmp_path), "--output", str(receipt),
        "--case", "descending-order", "--mode", "mutant"], capture_output=True, text=True)
    assert result.returncode != 0 and "anchor" in result.stderr and not receipt.exists()


@pytest.mark.parametrize("kind", ["same", "nested", "symlink", "collision"])
def test_package_output_cannot_overwrite_or_alias_evidence(tmp_path, kind):
    helper = load("package_inventory")
    audit, review = tmp_path / "audit", tmp_path / "review"
    audit.mkdir()
    review.mkdir()
    original = audit / "capture_pr_audit.py"
    original.write_bytes(b"retained original\n")
    output = audit
    if kind == "nested":
        output = audit / "new-output"
    elif kind == "symlink":
        output = tmp_path / "alias"
        output.symlink_to(audit, target_is_directory=True)
    elif kind == "collision":
        output = tmp_path / "already-exists"
        output.mkdir()
    with pytest.raises(ValueError):
        helper.validate_destination(output, [audit, review])
    assert original.read_bytes() == b"retained original\n"


def test_existing_unrelated_output_is_refused(tmp_path):
    helper = load("package_inventory")
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(ValueError, match="new canonical"):
        helper.validate_destination(output, [tmp_path / "separate"])


def test_unknown_historical_report_cannot_receive_archival_pass(tmp_path):
    helper = load("package_inventory")
    report = tmp_path / "REVIEW.md"
    report.write_text("FAIL: this is a different report\n")
    with pytest.raises(ValueError, match="unrecognized historical"):
        helper.read_bound(report, helper.ARCHIVE_HASHES["review/REVIEW.md"])


def test_all_inputs_validate_before_any_output_is_written(tmp_path, monkeypatch):
    helper = load("package_inventory")
    audit, review, output = tmp_path / "audit", tmp_path / "review", tmp_path / "output"
    audit.mkdir()
    review.mkdir()
    original = audit / "capture_pr_audit.py"
    original.write_bytes(b"synthetic earlier validated input")
    (review / "REVIEW.md").write_text("FAIL: unknown later input\n")
    monkeypatch.setattr(helper, "ARCHIVE_HASHES", {
        "audit/capture_pr_audit.py": hashlib.sha256(original.read_bytes()).hexdigest(),
        "review/REVIEW.md": helper.ARCHIVE_HASHES["review/REVIEW.md"]})
    with pytest.raises(ValueError, match="unrecognized historical"):
        helper.package(audit, review, output)
    assert not output.exists() and original.read_bytes() == b"synthetic earlier validated input"


@pytest.mark.parametrize("name,option,expected", [
    ("package_source_reviews", "--evidence-root", "8f361c8b49222b363af157a55572e37d503e22ba55fc88fb68bd9c234f4e120a"),
    ("package_followup_reviews", "--reviews-root", "42ad7c3549aaf2428531aa41dcc0d0ca59c35cdfb524911d19093db2cc602615"),
    ("1112/package_review_pr1112_20261115", "--review-tree", "0f409dfc6059def0e31309c9dfe79c4b1fadd8fb7d907377353a2659218fe6d6"),
    ("1236/package_review_pr1236_20261115", "--review-tree", "f6508c1be607ed661ffbc05620631b7b8e24cef3280fef97c436f63a0b37f0e9"),
])
@pytest.mark.parametrize("kind", ["missing", "bogus", "existing-results"])
def test_retired_packagers_refuse_all_execution_without_overwriting(tmp_path, name, option, expected, kind):
    helper = DIRECTORY.parent / "reviews" / (name + ".py")
    archive = DIRECTORY / "archive" / (Path(name).name + ".executed.py.txt")
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    source = tmp_path / "source"
    if kind != "missing":
        source.mkdir()
        (source / "REVIEW.md").write_text("FAIL: retained original report\n")
        (source / "review.json").write_text('{"verdict":"fail"}\n')
    before = {p.name: p.read_bytes() for p in source.iterdir()} if source.exists() else {}
    result = subprocess.run([sys.executable, str(helper), option, str(source)],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "archival-only" in result.stderr
    after = {p.name: p.read_bytes() for p in source.iterdir()} if source.exists() else {}
    assert after == before and source.exists() == (kind != "missing")
    help_result = subprocess.run([sys.executable, str(helper), "--help"], capture_output=True, text=True)
    assert help_result.returncode == 0


@pytest.mark.parametrize("name,option", [
    ("package_source_reviews", "--evidence-root"),
    ("package_followup_reviews", "--reviews-root"),
    ("1112/package_review_pr1112_20261115", "--review-tree"),
    ("1236/package_review_pr1236_20261115", "--review-tree"),
])
def test_retired_packager_execution_never_reads_inputs_or_runs_commands(monkeypatch, name, option):
    import builtins

    path = DIRECTORY.parent / "reviews" / (name + ".py")
    spec = importlib.util.spec_from_file_location("retired_packager", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    def forbidden(*_args, **_kwargs):
        pytest.fail("retired entry point attempted filesystem or subprocess access")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    with pytest.raises(SystemExit) as error:
        module.main([option, "untrusted-synthetic-input"])
    assert error.value.code == 2


@pytest.mark.parametrize("mutation,test", [
    ({"module": "review_pr1197_mutations", "old": 'valid_attempt(baseline, "baseline", name)', "new": "True"},
     "test_failed_baseline_cannot_establish_mutation_kill"),
    ({"module": "capture_pr_audit", "old": '"check_rows": identities(checks),', "new": ""},
     "test_empty_check_rows_cannot_borrow_rest_completeness"),
    ({"module": "package_inventory", "old": 'if output.absolute() != canonical or output.exists() or output.is_symlink():', "new": "if False:"},
     "test_existing_unrelated_output_is_refused"),
    ({"module": "package_inventory", "old": "if digest(raw) != expected:", "new": "if False:"},
     "test_unknown_historical_report_cannot_receive_archival_pass"),
])
def test_fresh_process_mutations_detect_each_repaired_guard(tmp_path, mutation, test):
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", __file__ + "::" + test,
        "-p", "no:cacheprovider"], capture_output=True, text=True, timeout=60,
        env={**os.environ, "CLAW_INVENTORY_TEST_MUTATION": json.dumps(mutation),
             "PYTHONPYCACHEPREFIX": str(tmp_path / "bytecode")})
    assert result.returncode == 1 and ("DID NOT RAISE" in result.stdout or "assert not" in result.stdout), result.stdout + result.stderr
