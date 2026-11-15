"""Offline, immutable PR-maintenance evidence for parent 2.1.

These validators judge recorded claims and bound artifact bytes. The supervisor
must independently observe GitHub and verify each merged PR's exact-head closure;
no function in this module mutates a repository or grants action authority.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from . import WorkflowError, _read_regular
from .issue_triage import _time

PR_MAINTENANCE_POLICY = {
    "stale_draft_days": 14,
    "default_open_pr_limit": 25,
    "count_non_draft_only": True,
    "freeze_scope_at_stage_start": True,
    "complete_inventory_required": True,
    "close_superseded_and_duplicate_with_reason": True,
    "refresh_or_close_conflicts_without_force": True,
    "fix_majority_check_failures_at_source": True,
    "green_prs_require_closure_policy": True,
    "delete_only_owned_worktrees": True,
    "explicit_authority_required": True,
    "blocked_closure_holds_goal": True,
}
SNAPSHOT_KEYS = {
    "repository", "frozen_at", "complete", "total_count", "pages", "prs",
    "open_non_draft_limit", "limit_source",
}
ROW_KEYS = {
    "number", "title", "updatedAt", "is_draft", "head_sha", "base_sha",
    "head_branch", "base_branch", "checks_state", "mergeability",
    "failing_checks", "checks_complete", "check_count",
}
TERMINAL = {
    "merged", "closed_superseded", "closed_duplicate", "closed_stale", "closed_conflicting",
}
STATUSES = TERMINAL | {"refreshed", "retained", "blocked"}
SHA = re.compile(r"[0-9a-f]{40}\Z")


def _require(condition: object, message: str) -> None:
    if not condition:
        raise WorkflowError(message)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _numbers(values: object) -> bool:
    return (isinstance(values, list) and all(type(n) is int and n > 0 for n in values)
            and len(values) == len(set(values)))


def _url(value: object, repository: str, kind: str) -> bool:
    return (isinstance(value, str) and re.fullmatch(
        r"https://github\.com/" + re.escape(repository) + "/" + kind + r"/[1-9]\d*", value
    ) is not None)


def _unique(rows: list[dict], key: str, label: str) -> dict:
    result = {row[key]: row for row in rows}
    _require(len(result) == len(rows), f"duplicate {label}")
    return result


def validate_pr_maintenance_policy(policy: dict | None) -> None:
    _require(isinstance(policy, dict) and policy == PR_MAINTENANCE_POLICY
             and all(type(policy[key]) is type(value) for key, value in PR_MAINTENANCE_POLICY.items()),
             "PR maintenance must retain the complete reviewed policy")


def validate_pr_snapshot(snapshot: dict, github_repository: str) -> None:
    _require(isinstance(snapshot, dict) and set(snapshot) == SNAPSHOT_KEYS,
             "frozen PR inventory has an invalid shape")
    _require(snapshot["repository"] == github_repository and snapshot["complete"] is True,
             "frozen PR inventory is incomplete or belongs to another repository")
    frozen = _time(snapshot["frozen_at"])
    rows = snapshot["prs"]
    _require(isinstance(rows, list) and type(snapshot["total_count"]) is int
             and snapshot["total_count"] == len(rows)
             and type(snapshot["pages"]) is int
             and snapshot["pages"] >= max(1, (len(rows) + 99) // 100),
             "frozen PR count or pagination is incomplete")
    limit = snapshot["open_non_draft_limit"]
    _require(type(limit) is int and 1 <= limit <= 1000
             and snapshot["limit_source"] in {"default", "manifest"}
             and (snapshot["limit_source"] != "default" or limit == 25),
             "invalid frozen PR limit or source")
    _validate_pr_rows(rows, frozen)


def _validate_pr_rows(rows: list[dict], frozen) -> None:
    _require(isinstance(rows, list), "frozen PR rows must be a list")
    numbers = []
    for row in rows:
        _require(isinstance(row, dict) and set(row) == ROW_KEYS,
                 "frozen PR entry has an invalid shape")
        _require(type(row["number"]) is int and row["number"] > 0
                 and _text(row["title"]) and type(row["is_draft"]) is bool
                 and _sha(row["head_sha"]) and _sha(row["base_sha"])
                 and _text(row["head_branch"]) and _text(row["base_branch"]),
                 "invalid frozen PR identity")
        _require(_time(row["updatedAt"]) <= frozen,
                 "PR changed after the frozen inventory cutoff")
        _require(row["checks_state"] in {"green", "failing", "pending", "unknown"}
                 and row["mergeability"] in {"mergeable", "conflicting", "unknown"}
                 and type(row["checks_complete"]) is bool
                 and type(row["check_count"]) is int and row["check_count"] >= 0,
                 "invalid frozen PR check or mergeability state")
        failed = row["failing_checks"]
        _require(isinstance(failed, list) and all(_text(name) for name in failed)
                 and len(failed) == len(set(failed)) and len(failed) <= row["check_count"],
                 "invalid frozen failed-check inventory")
        _require((row["checks_state"] == "failing") == bool(failed),
                 "frozen failed checks disagree with check state")
        if row["checks_state"] == "green":
            _require(row["checks_complete"] and row["check_count"] > 0,
                     "zero or incomplete checks cannot establish green")
        if not row["checks_complete"]:
            _require(row["checks_state"] in {"unknown", "failing"},
                     "incomplete checks must remain unknown or failing")
        numbers.append(row["number"])
    _require(len(numbers) == len(set(numbers)), "duplicate PR in frozen inventory")


def majority_failures(rows: list[dict]) -> dict[str, list[int]]:
    """A majority is strictly more than half of all frozen open PRs."""
    failed: dict[str, list[int]] = {}
    for row in rows:
        for name in row["failing_checks"]:
            failed.setdefault(name, []).append(row["number"])
    return {name: sorted(numbers) for name, numbers in failed.items()
            if len(numbers) * 2 > len(rows)}


def pr_maintenance_blockers(data: dict) -> list[int]:
    result = data.get("pr_maintenance", {})
    blocked = {row["number"] for row in result.get("dispositions", [])
               if row["status"] == "blocked"}
    for fix in result.get("shared_check_fixes", []):
        if fix["status"] == "blocked":
            blocked.update(fix["affected_pr_numbers"])
    remaining = result.get("remaining_open_non_draft", [])
    if len(remaining) > result.get("open_non_draft_limit", 25):
        blocked.update(remaining)
    return sorted(blocked)


def _artifact(data: dict, kind: str, root: Path) -> object:
    rows = [item for item in data["artifacts"] if item["kind"] == kind]
    _require(len(rows) == 1, f"PR maintenance requires exactly one {kind} artifact")
    try:
        return json.loads(_read_regular(root / rows[0]["path"], root))
    except (ValueError, UnicodeError) as exc:
        raise WorkflowError(f"{kind} must contain the documented JSON payload") from exc


def validate_pr_maintenance(
    data: dict, *, repository_root: Path | None = None,
    previous: dict | None = None, supersedes: dict | None = None,
) -> None:
    """Validate full accounting; live publication and action claims remain external."""
    _require(data.get("parent_version") == "2.1.0"
             and data.get("stage_key") == "open_issue_triage",
             "PR maintenance belongs to parent 2.1 stage one")
    result = data.get("pr_maintenance")
    _require(isinstance(result, dict), "parent 2.1 requires PR maintenance evidence")
    assert isinstance(result, dict)  # The explicit guard above remains active under -O.
    frozen = _time(result["frozen_at"])
    rows = result["inventory"]
    _validate_pr_rows(rows, frozen)
    inventory = _unique(rows, "number", "PR inventory member")
    dispositions = _unique(result["dispositions"], "number", "PR disposition")
    _require(set(dispositions) == set(inventory), "every frozen PR needs one disposition")
    paths = {item["path"] for item in data["artifacts"]}
    remaining = result["remaining_open_non_draft"]
    _require(_numbers(remaining), "remaining PR inventory must contain distinct positive numbers")
    limit = result["open_non_draft_limit"]
    _require(type(limit) is int and 1 <= limit <= 1000
             and result["limit_source"] in {"default", "manifest"}
             and (result["limit_source"] != "default" or limit == 25),
             "invalid PR limit or source")
    for number, disposition in dispositions.items():
        original = inventory[number]
        status = disposition["status"]
        _require(status in STATUSES and _text(disposition["reason"])
                 and disposition["head_sha"] == original["head_sha"],
                 "PR disposition must bind its frozen head and reason")
        refs = disposition["resolution_evidence"]
        _require(isinstance(refs, list) and len(refs) == len(set(refs)) and set(refs) <= paths,
                 "PR disposition refers to missing or repeated evidence")
        if status != "retained":
            _require(bool(refs), "PR action or blocker requires artifact-backed evidence")
        if status == "blocked":
            _require(_text(disposition.get("prerequisite")), "blocked PR needs its prerequisite")
        if status == "merged":
            _require(_sha(disposition.get("final_head_sha")) and _sha(disposition.get("merge_sha")),
                     "merged PR needs its exact final head and merge")
        if status == "refreshed":
            _require(_sha(disposition.get("final_head_sha"))
                     and disposition["final_head_sha"] != original["head_sha"],
                     "refreshed PR needs a changed final head")
        if status in {"closed_superseded", "closed_duplicate"}:
            url = disposition.get("replacement_pr_url")
            _require(_url(url, data["github_repository"], "pull")
                     and url != f"https://github.com/{data['github_repository']}/pull/{number}",
                     "duplicate or superseded PR needs a different same-repository successor")
        stale = original["is_draft"] and frozen - _time(original["updatedAt"]) >= timedelta(days=14)
        if status == "closed_stale":
            _require(stale, "stale closure requires a draft idle for at least fourteen days")
        if status == "closed_conflicting":
            _require(original["mergeability"] == "conflicting",
                     "conflict closure requires an observed conflict")
        if stale:
            _require(status in TERMINAL | {"refreshed", "blocked"},
                     "stale drafts must be closed, refreshed or explicitly blocked")
        if original["mergeability"] == "conflicting":
            _require(status in TERMINAL | {"refreshed", "blocked"},
                     "conflicting PRs must be closed, refreshed or explicitly blocked")
        if original["checks_state"] == "green":
            _require(status in TERMINAL | {"blocked"},
                     "green PRs require full closure or an explicit blocker")
        if status in TERMINAL:
            _require(number not in remaining, "closed PR remains in the open-PR count")
        elif not original["is_draft"]:
            _require(number in remaining, "remaining non-draft PR disappeared from the count")
    expected = majority_failures(rows)
    fixes = _unique(result["shared_check_fixes"], "check_name", "shared check fix")
    _require(set(fixes) == set(expected), "every majority check failure needs one source-level disposition")
    for name, fix in fixes.items():
        source_repository = fix["source_repository"]
        _require(source_repository in {data["github_repository"], "CultureBotAI/culturebotai-claw"},
                 "shared check source must be the consumer or canonical claw repository")
        _require(_numbers(fix["affected_pr_numbers"])
                 and sorted(fix["affected_pr_numbers"]) == expected[name]
                 and fix["status"] in {"fixed", "blocked"} and _text(fix["reason"])
                 and _url(fix["source_issue_url"], source_repository, "issues"),
                 "shared check fix must bind the observed majority and source issue")
        refs = fix["resolution_evidence"]
        _require(bool(refs) and len(refs) == len(set(refs)) and set(refs) <= paths,
                 "shared check fix needs artifact-backed evidence")
        if fix["status"] == "fixed":
            _require(_url(fix.get("source_fix_pr_url"), source_repository, "pull"),
                     "fixed shared check needs its source PR")
        else:
            _require(_text(fix.get("prerequisite")), "blocked shared check needs its prerequisite")
    blockers = pr_maintenance_blockers(data)
    _require(not blockers or data["outcome"] == "blocked",
             "blocked PR closure or exceeded WIP limit must hold the goal")
    _require(data["outcome"] != "no_findings" or not rows,
             "no_findings cannot hide a nonempty PR inventory")
    if supersedes is not None:
        old = supersedes.get("pr_maintenance")
        _require(isinstance(old, dict) and all(old[key] == result[key] for key in (
            "frozen_at", "inventory", "open_non_draft_limit", "limit_source",
        )), "PR evidence revisions must preserve the frozen inventory and limit")
    if previous is not None and "pr_maintenance" in previous:
        _require(previous["parent_version"] == "2.1.0",
                 "previous PR maintenance evidence has an invalid parent identity")
    if repository_root is not None:
        root = Path(repository_root)
        snapshot = _artifact(data, "pr_inventory", root)
        _require(isinstance(snapshot, dict), "frozen PR inventory must be a JSON object")
        assert isinstance(snapshot, dict)
        validate_pr_snapshot(snapshot, data["github_repository"])
        _require(snapshot["prs"] == rows and snapshot["frozen_at"] == result["frozen_at"]
                 and snapshot["open_non_draft_limit"] == limit
                 and snapshot["limit_source"] == result["limit_source"],
                 "PR result must preserve the entire frozen inventory and limit")
        _require(_artifact(data, "pr_dispositions", root) == {"pr_maintenance": result},
                 "PR dispositions artifact must match the structured evidence")
