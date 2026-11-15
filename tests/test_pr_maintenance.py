"""Adversarial PR-maintenance accounting without GitHub or repository mutations."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kg_microbe_workflows import WorkflowError
from kg_microbe_workflows.pr_maintenance import (
    PR_MAINTENANCE_POLICY,
    majority_failures,
    pr_maintenance_blockers,
    validate_pr_maintenance,
    validate_pr_maintenance_policy,
    validate_pr_snapshot,
)

REPO = "CultureBotAI/ExampleMech"
HEAD = "a" * 40
BASE = "b" * 40
NOW = "2026-11-15T12:00:00Z"


def row(number=1, *, green=False, draft=False, updated="2026-11-14T12:00:00Z"):
    return {"number": number, "title": "A measured change", "updatedAt": updated,
            "is_draft": draft, "head_sha": HEAD, "base_sha": BASE,
            "head_branch": f"topic/{number}", "base_branch": "main",
            "checks_state": "green" if green else "pending", "mergeability": "mergeable",
            "failing_checks": [], "checks_complete": True, "check_count": 1}


def snapshot(rows=None, *, limit=25, source="default"):
    rows = [] if rows is None else rows
    return {"repository": REPO, "frozen_at": NOW, "complete": True,
            "total_count": len(rows), "pages": max(1, (len(rows) + 99) // 100), "prs": rows,
            "open_non_draft_limit": limit, "limit_source": source}


def evidence(rows=None, *, status="retained", limit=25, source="default"):
    rows = [] if rows is None else rows
    data = {"parent_version": "2.1.0", "stage_key": "open_issue_triage",
            "github_repository": REPO, "outcome": "completed",
            "artifacts": [{"kind": "supporting", "path": "proof.json"}],
            "pr_maintenance": {
                "frozen_at": NOW, "inventory": rows,
                "dispositions": [{"number": item["number"], "head_sha": item["head_sha"],
                                  "status": status, "reason": "Waiting for a measured prerequisite",
                                  "resolution_evidence": ["proof.json"]} for item in rows],
                "shared_check_fixes": [], "open_non_draft_limit": limit,
                "limit_source": source,
                "remaining_open_non_draft": [item["number"] for item in rows if not item["is_draft"]],
            }}
    return data


def materialize(root, data):
    result = data["pr_maintenance"]
    frozen = snapshot(result["inventory"], limit=result["open_non_draft_limit"],
                      source=result["limit_source"])
    frozen["frozen_at"] = result["frozen_at"]
    for name, kind, value in (
        ("inventory.json", "pr_inventory", frozen),
        ("dispositions.json", "pr_dispositions", {"pr_maintenance": result}),
    ):
        (root / name).write_text(json.dumps(value))
        data["artifacts"].append({"kind": kind, "path": name})
    return frozen


def test_complete_inventory_covers_drafts_and_non_drafts():
    validate_pr_snapshot(snapshot([row(), row(2, draft=True)]), REPO)


@pytest.mark.parametrize("change", [
    {"complete": False}, {"total_count": 2}, {"pages": 0}, {"repository": "wrong/repo"},
    {"open_non_draft_limit": True}, {"open_non_draft_limit": 26},
])
def test_invalid_inventory_and_default_limit_fail_closed(change):
    value = snapshot([row()])
    value.update(change)
    with pytest.raises(WorkflowError):
        validate_pr_snapshot(value, REPO)


def test_manifest_can_override_the_default_limit():
    validate_pr_snapshot(snapshot([row()], limit=3, source="manifest"), REPO)


@pytest.mark.parametrize("field,value", [
    ("checks_complete", False), ("check_count", 0), ("failing_checks", ["pytest"]),
])
def test_incomplete_zero_or_failed_checks_cannot_claim_green(field, value):
    pr = row(green=True)
    pr[field] = value
    with pytest.raises(WorkflowError):
        validate_pr_snapshot(snapshot([pr]), REPO)


def test_late_and_duplicate_inventory_entries_are_rejected():
    for prs in ([row(updated="2026-11-15T12:00:01Z")], [row(), row()]):
        with pytest.raises(WorkflowError):
            validate_pr_snapshot(snapshot(prs), REPO)


def test_empty_inventory_is_explicit_and_valid():
    data = evidence()
    data["outcome"] = "no_findings"
    validate_pr_maintenance(data)
    assert pr_maintenance_blockers(data) == []


@pytest.mark.parametrize("failure", ["omitted", "duplicate", "wrong-head"])
def test_each_frozen_pr_needs_one_exact_head_disposition(failure):
    data = evidence([row()])
    rows = data["pr_maintenance"]["dispositions"]
    if failure == "omitted":
        rows.clear()
    elif failure == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    else:
        rows[0]["head_sha"] = "c" * 40
    with pytest.raises(WorkflowError):
        validate_pr_maintenance(data)


def test_green_pr_cannot_be_retained_or_budget_deferred():
    with pytest.raises(WorkflowError, match="green PRs require full closure"):
        validate_pr_maintenance(evidence([row(green=True)]))


def test_green_blocker_needs_evidence_prerequisite_and_holds_goal():
    data = evidence([row(green=True)], status="blocked")
    with pytest.raises(WorkflowError, match="needs its prerequisite"):
        validate_pr_maintenance(data)
    data["pr_maintenance"]["dispositions"][0]["prerequisite"] = "Recorded owner approval pending"
    with pytest.raises(WorkflowError, match="must hold the goal"):
        validate_pr_maintenance(data)
    data["outcome"] = "blocked"
    validate_pr_maintenance(data)
    assert pr_maintenance_blockers(data) == [1]


def test_merged_pr_needs_final_head_merge_and_artifact_binding():
    data = evidence([row(green=True)], status="merged")
    result = data["pr_maintenance"]
    result["remaining_open_non_draft"] = []
    with pytest.raises(WorkflowError, match="exact final head and merge"):
        validate_pr_maintenance(data)
    disposition = result["dispositions"][0]
    disposition.update(final_head_sha=HEAD, merge_sha="c" * 40)
    validate_pr_maintenance(data)
    disposition["resolution_evidence"] = ["unbound.json"]
    with pytest.raises(WorkflowError, match="missing or repeated evidence"):
        validate_pr_maintenance(data)


def test_stale_draft_boundary_uses_idle_updated_time_and_fourteen_days():
    frozen = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    for seconds, stale in ((14 * 86400 - 1, False), (14 * 86400, True)):
        updated = (frozen - timedelta(seconds=seconds)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        data = evidence([row(draft=True, updated=updated)], status="closed_stale")
        if stale:
            validate_pr_maintenance(data)
        else:
            with pytest.raises(WorkflowError, match="at least fourteen days"):
                validate_pr_maintenance(data)
    with pytest.raises(WorkflowError, match="stale drafts must be closed"):
        validate_pr_maintenance(evidence([row(draft=True, updated="2026-11-01T12:00:00Z")]))


def test_age_never_closes_a_ready_pr_as_a_stale_draft():
    with pytest.raises(WorkflowError, match="requires a draft"):
        validate_pr_maintenance(evidence([row(updated="2026-10-01T12:00:00Z")], status="closed_stale"))


def test_conflict_requires_refresh_close_or_blocker_without_force():
    pr = row()
    pr["mergeability"] = "conflicting"
    data = evidence([pr])
    with pytest.raises(WorkflowError, match="conflicting PRs"):
        validate_pr_maintenance(data)
    disposition = data["pr_maintenance"]["dispositions"][0]
    disposition.update(status="refreshed", final_head_sha="d" * 40)
    validate_pr_maintenance(data)
    disposition["final_head_sha"] = HEAD
    with pytest.raises(WorkflowError, match="changed final head"):
        validate_pr_maintenance(data)


def test_superseded_or_duplicate_requires_real_distinct_successor_identity():
    data = evidence([row()], status="closed_superseded")
    data["pr_maintenance"]["remaining_open_non_draft"] = []
    disposition = data["pr_maintenance"]["dispositions"][0]
    for bad in (f"https://github.com/{REPO}/pull/1", "https://github.com/other/repo/pull/2", None):
        disposition["replacement_pr_url"] = bad
        with pytest.raises(WorkflowError, match="different same-repository successor"):
            validate_pr_maintenance(data)
    disposition["replacement_pr_url"] = f"https://github.com/{REPO}/pull/2"
    validate_pr_maintenance(data)


def test_non_draft_limit_counts_new_arrivals_and_does_not_discard_frozen_members():
    data = evidence([row(), row(2, draft=True)], limit=1, source="manifest")
    validate_pr_maintenance(data)
    data["pr_maintenance"]["remaining_open_non_draft"].append(99)
    with pytest.raises(WorkflowError, match="must hold the goal"):
        validate_pr_maintenance(data)
    data["outcome"] = "blocked"
    validate_pr_maintenance(data)
    assert pr_maintenance_blockers(data) == [1, 99]
    data["pr_maintenance"]["remaining_open_non_draft"] = []
    with pytest.raises(WorkflowError, match="disappeared from the count"):
        validate_pr_maintenance(data)


def test_source_check_fix_requires_strict_majority_and_one_accounting_record():
    prs = [row(i) for i in range(1, 5)]
    for pr in prs[:2]:
        pr.update(checks_state="failing", failing_checks=["fleet-audit"])
    assert majority_failures(prs) == {}
    prs[2].update(checks_state="failing", failing_checks=["fleet-audit"])
    assert majority_failures(prs) == {"fleet-audit": [1, 2, 3]}
    data = evidence(prs)
    with pytest.raises(WorkflowError, match="one source-level disposition"):
        validate_pr_maintenance(data)
    data["pr_maintenance"]["shared_check_fixes"] = [{
        "check_name": "fleet-audit", "affected_pr_numbers": [1, 2, 3], "status": "fixed",
        "reason": "Repair canonical source once", "source_repository": REPO, "source_issue_url": f"https://github.com/{REPO}/issues/10",
        "source_fix_pr_url": f"https://github.com/{REPO}/pull/11", "resolution_evidence": ["proof.json"],
    }]
    validate_pr_maintenance(data)
    data["pr_maintenance"]["shared_check_fixes"][0]["affected_pr_numbers"] = [1, 2]
    with pytest.raises(WorkflowError, match="observed majority"):
        validate_pr_maintenance(data)


def test_immutable_artifacts_bind_all_inventory_and_disposition_bytes(tmp_path):
    data = evidence([row()])
    materialize(tmp_path, data)
    validate_pr_maintenance(data, repository_root=tmp_path)
    path = tmp_path / "inventory.json"
    frozen = json.loads(path.read_text())
    frozen["prs"][0]["head_sha"] = "f" * 40
    path.write_text(json.dumps(frozen))
    with pytest.raises(WorkflowError, match="entire frozen inventory"):
        validate_pr_maintenance(data, repository_root=tmp_path)


def test_revisions_cannot_replace_frozen_head_or_limit():
    old = evidence([row()])
    new = copy.deepcopy(old)
    new["pr_maintenance"]["limit_source"] = "manifest"
    with pytest.raises(WorkflowError, match="preserve the frozen inventory and limit"):
        validate_pr_maintenance(new, supersedes=old)


def test_policy_cannot_strip_exact_head_closure_or_authority_hold():
    validate_pr_maintenance_policy(PR_MAINTENANCE_POLICY)
    for key in ("green_prs_require_closure_policy", "explicit_authority_required", "delete_only_owned_worktrees"):
        weakened = dict(PR_MAINTENANCE_POLICY)
        weakened[key] = False
        with pytest.raises(WorkflowError):
            validate_pr_maintenance_policy(weakened)
    with pytest.raises(WorkflowError):
        validate_pr_maintenance_policy(None)


def test_green_stale_draft_can_close_with_a_proven_stale_reason():
    data = evidence([row(green=True, draft=True, updated="2026-11-01T12:00:00Z")], status="closed_stale")
    validate_pr_maintenance(data)


def test_additive_linkml_vocabulary_preserves_legacy_and_accepts_pr_result(tmp_path):
    from test_issue_triage_contract import triage_evidence

    from kg_microbe_workflows import _shape

    legacy = triage_evidence(tmp_path, empty=True)
    _shape(legacy, "IssueTriageEvidence")
    current = copy.deepcopy(legacy)
    current["parent_version"] = "2.1.0"
    current["pr_maintenance"] = evidence()["pr_maintenance"]
    _shape(current, "IssueTriageEvidence")
    current["pr_maintenance"]["unexpected_field"] = True
    with pytest.raises(WorkflowError):
        _shape(current, "IssueTriageEvidence")


@pytest.mark.parametrize(("guard", "replacement", "selected", "failure"), [
    ('and disposition["head_sha"] == original["head_sha"],', 'and True,',
     "test_each_frozen_pr_needs_one_exact_head_disposition[wrong-head]", "DID NOT RAISE"),
    ('status in TERMINAL | {"blocked"},', 'True,',
     "test_green_pr_cannot_be_retained_or_budget_deferred", "DID NOT RAISE"),
    ('if len(remaining) > result.get("open_non_draft_limit", 25):', 'if False:',
     "test_non_draft_limit_counts_new_arrivals_and_does_not_discard_frozen_members", "DID NOT RAISE"),
    ('>= timedelta(days=14)', '> timedelta(days=14)',
     "test_stale_draft_boundary_uses_idle_updated_time_and_fourteen_days", "stale closure requires"),
    ('if len(numbers) * 2 > len(rows)', 'if len(numbers) * 2 >= len(rows)',
     "test_source_check_fix_requires_strict_majority_and_one_accounting_record", "AssertionError"),
])
def test_fresh_process_guard_mutations(tmp_path, guard, replacement, selected, failure):
    helper = Path(__file__).resolve().parents[1] / "src/kg_microbe_workflows/pr_maintenance.py"
    runner = r"""
import pathlib, sys, types
import pytest
helper, test_file, guard, replacement, selected = sys.argv[1:]
source = pathlib.Path(helper).read_text()
assert source.count(guard) == 1
mutant = types.ModuleType("kg_microbe_workflows.mutated_pr_maintenance")
mutant.__package__ = "kg_microbe_workflows"
mutant.__file__ = helper
exec(compile(source.replace(guard, replacement), helper, "exec"), mutant.__dict__)
class Plugin:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            for name in ("validate_pr_maintenance", "pr_maintenance_blockers", "majority_failures"):
                setattr(item.module, name, getattr(mutant, name))
raise SystemExit(pytest.main([test_file + "::" + selected, "-q", "-p", "no:cacheprovider"],
                            plugins=[Plugin()]))
"""
    result = subprocess.run(
        [sys.executable, "-c", runner, str(helper), __file__, guard, replacement, selected],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPYCACHEPREFIX": str(tmp_path / "fresh-bytecode")},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert failure in result.stdout, result.stdout + result.stderr


def test_shared_source_fix_can_bind_canonical_claw_without_conferring_authority():
    pr = row()
    pr.update(checks_state="failing", failing_checks=["vendored-sync"])
    data = evidence([pr])
    source = "CultureBotAI/culturebotai-claw"
    data["pr_maintenance"]["shared_check_fixes"] = [{
        "check_name": "vendored-sync", "affected_pr_numbers": [1], "status": "blocked",
        "reason": "Canonical fix needs its owner's review", "source_repository": source,
        "source_issue_url": f"https://github.com/{source}/issues/10",
        "resolution_evidence": ["proof.json"], "prerequisite": "Reviewed canonical fix",
    }]
    data["outcome"] = "blocked"
    validate_pr_maintenance(data)
    data["pr_maintenance"]["shared_check_fixes"][0]["source_issue_url"] = f"https://github.com/{REPO}/issues/10"
    with pytest.raises(WorkflowError, match="source issue"):
        validate_pr_maintenance(data)


def test_row_facts_are_validated_without_access_to_artifact_files():
    data = evidence([row(green=True)], status="merged")
    result = data["pr_maintenance"]
    result["remaining_open_non_draft"] = []
    result["dispositions"][0].update(final_head_sha=HEAD, merge_sha="c" * 40)
    result["inventory"][0]["check_count"] = 0
    with pytest.raises(WorkflowError, match="zero or incomplete"):
        validate_pr_maintenance(data)
