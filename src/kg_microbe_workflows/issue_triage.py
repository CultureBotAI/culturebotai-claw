"""Offline validation of frozen issue triage and the shared elapsed-time budget.

Recorded GitHub actions are claims until the supervisor independently verifies
remote closure. This module never calls GitHub, assigns labels or starts agents.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import WorkflowError, _read_regular, _unique

SEVERITIES = ("critical", "high", "medium", "low")
LABELS = tuple(f"severity:{value}" for value in SEVERITIES)
PRIORITY_MAPPINGS = (
    *(dict(repository_key="cellstructuremech", label=f"P{i}", severity=value)
      for i, value in enumerate(SEVERITIES)),
    *(dict(repository_key="habitatmech", label=f"priority: P{i}", severity=value)
      for i, value in enumerate(SEVERITIES[:3])),
)
POLICY = {
    "severity_labels": list(LABELS), "required_severities": ["critical", "high"],
    "deferred_budget_seconds": 14400, "min_deferred_groups": 1, "max_deferred_groups": 2,
    "budget_clock": "shared_wall_clock", "budget_after_required_resolution": True,
    "carry_unused_budget": False, "freeze_scope_at_stage_start": True,
    "new_issues_next_cycle": True, "stable_group_ids": True,
    "tracking_issue_and_subissues": True, "primary_role": "codex_primary",
    "secondary_role": "agy_secondary", "rollout_label": "rollout:cycle-v2",
    "delegated_label": "claw-delegated", "legacy_priority_mappings": list(PRIORITY_MAPPINGS),
}


def validate_triage_policy(policy: dict | None) -> None:
    if policy != POLICY:
        raise WorkflowError("issue_triage_policy must preserve the approved severity, scope, roles and budget")


def _time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value
    ):
        raise WorkflowError("issue triage timestamps must be full UTC timestamps")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowError("invalid issue triage timestamp") from exc


def severity_from_labels(labels: list[str], repository_key: str) -> str | None:
    """Map existing priority metadata without inventing another priority label."""
    present = [label[len("severity:"):] for label in labels if label.startswith("severity:")]
    if len(present) > 1 or any(value not in SEVERITIES for value in present):
        raise WorkflowError("issue must have at most one recognized severity label before triage")
    mapped = {row["severity"] for row in PRIORITY_MAPPINGS
              if row["repository_key"] == repository_key and row["label"] in labels}
    if len(mapped) > 1 or (present and mapped and present[0] not in mapped):
        raise WorkflowError("existing severity and priority labels disagree")
    return present[0] if present else next(iter(mapped), None)


def validate_issue_snapshot(snapshot: dict, github_repository: str) -> None:
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "repository", "frozen_at", "issues", "complete", "total_count", "pages"
    }:
        raise WorkflowError("frozen issue inventory has an invalid shape")
    if snapshot["repository"] != github_repository or snapshot["complete"] is not True:
        raise WorkflowError("frozen issue inventory is incomplete or belongs to another repository")
    frozen = _time(snapshot["frozen_at"])
    issues = snapshot["issues"]
    if (not isinstance(issues, list) or type(snapshot["total_count"]) is not int
            or snapshot["total_count"] != len(issues) or type(snapshot["pages"]) is not int
            or snapshot["pages"] < max(1, (len(issues) + 99) // 100)):
        raise WorkflowError("frozen issue inventory count or pagination is incomplete")
    numbers = []
    for item in issues:
        if not isinstance(item, dict) or set(item) != {"number", "title", "labels", "updatedAt"}:
            raise WorkflowError("frozen issue entry has an invalid shape")
        if (type(item["number"]) is not int or item["number"] < 1
                or not isinstance(item["title"], str) or not item["title"].strip()
                or not isinstance(item["labels"], list)
                or any(not isinstance(label, str) or not label.strip() for label in item["labels"])
                or len(set(item["labels"])) != len(item["labels"])):
            raise WorkflowError("invalid frozen issue identity or labels")
        if _time(item["updatedAt"]) > frozen:
            raise WorkflowError("issue changed after the frozen inventory cutoff")
        numbers.append(item["number"])
    if len(numbers) != len(set(numbers)):
        raise WorkflowError("duplicate issue in frozen inventory")


def issue_triage_blockers(data: dict) -> list[int]:
    triage = data.get("issue_triage", {})
    mandatory = {item["number"] for item in triage.get("inventory", [])
                 if item["severity"] in {"critical", "high"}}
    return sorted(item["number"] for item in triage.get("dispositions", [])
                  if item["number"] in mandatory and item["status"] == "blocked")


def _artifact_payload(data: dict, kind: str, root: Path) -> object:
    artifacts = [artifact for artifact in data["artifacts"] if artifact["kind"] == kind]
    if len(artifacts) != 1:
        raise WorkflowError(f"issue triage requires exactly one {kind} artifact")
    try:
        return json.loads(_read_regular(root / artifacts[0]["path"], root))
    except (ValueError, UnicodeError) as exc:
        raise WorkflowError(f"{kind} must contain the documented JSON payload") from exc


def validate_issue_triage(
    data: dict, *, repository_root: Path | None = None,
    previous: dict | None = None, supersedes: dict | None = None,
) -> None:
    triage = data["issue_triage"]
    inventory = _unique(triage["inventory"], "number")
    groups = _unique(triage["groups"], "group_id")
    plans = _unique(triage["group_plans"], "group_id")
    dispositions = _unique(triage["dispositions"], "number")
    if data["findings"] or data["groups"] or data["infra_tasks"]:
        raise WorkflowError("issue triage cannot consume review findings or infrastructure tasks")
    if data["outcome"] == "no_findings" and inventory:
        raise WorkflowError("no_findings cannot hide a nonempty open-issue inventory")
    if set(plans) != set(groups) or set(dispositions) != set(inventory):
        raise WorkflowError("every frozen issue needs one disposition and every group one plan")
    frozen = _time(data["scope_frozen_at"])
    for issue in inventory.values():
        if _time(issue["updatedAt"]) > frozen:
            raise WorkflowError("assessed issue is newer than the frozen inventory")
        labels = issue["assigned_labels"]
        if len(set(labels)) != len(labels) or [label for label in labels if label.startswith("severity:")] != [f"severity:{issue['severity']}"]:
            raise WorkflowError("assign exactly one matching severity label to every reviewed issue")
        existing = severity_from_labels(issue["labels"], data["repository_key"])
        if existing is not None and issue["severity"] != existing:
            raise WorkflowError("triage must preserve the existing severity or mapped priority")
        if not set(issue["labels"]) <= set(labels):
            raise WorkflowError("triage must preserve existing labels, including priority labels")
    covered = []
    for group_id, group in groups.items():
        numbers = group["issue_numbers"]
        if not numbers or group["size"] != len(numbers) or len(set(numbers)) != len(numbers):
            raise WorkflowError("group size must count its distinct frozen issue members")
        covered.extend(numbers)
        for number in numbers:
            if number not in dispositions or dispositions[number]["group_id"] != group_id:
                raise WorkflowError("issue/group/disposition identities disagree")
    if len(covered) != len(set(covered)) or set(covered) != set(inventory):
        raise WorkflowError("groups must partition the complete frozen issue inventory")
    paths = {item["path"] for item in data["artifacts"]}
    carry = set()
    for number, item in dispositions.items():
        status = item["status"]
        mandatory = inventory[number]["severity"] in {"critical", "high"}
        if mandatory and status == "deferred":
            raise WorkflowError("critical and high issues must resolve or hold on a prerequisite")
        if status == "blocked" and not item.get("prerequisite"):
            raise WorkflowError("blocked issues need a recorded prerequisite")
        if status in {"deferred", "blocked"}:
            carry.add(item["group_id"])
        else:
            refs = item.get("resolution_evidence", [])
            if not refs or not set(refs) <= paths:
                raise WorkflowError("terminal issue dispositions require artifact-backed evidence")
        if status == "fixed":
            prs = item.get("pr_urls", [])
            pattern = re.escape(f"https://github.com/{data['github_repository']}/pull/") + r"[1-9]\d*"
            if not prs or any(not re.fullmatch(pattern, url) for url in prs) or not item.get("commit_sha"):
                raise WorkflowError("fixed issues require same-repository PR and commit references")
        if status == "duplicate":
            duplicate = item.get("duplicate_of", "")
            pattern = re.escape(f"https://github.com/{data['github_repository']}/issues/") + r"[1-9]\d*"
            if not re.fullmatch(pattern, duplicate) or duplicate.endswith(f"/issues/{number}"):
                raise WorkflowError("duplicate disposition needs a different same-repository issue")
    if (len(triage["carry_forward_group_ids"]) != len(set(triage["carry_forward_group_ids"]))
            or set(triage["carry_forward_group_ids"]) != carry):
        raise WorkflowError("carry-forward groups must exactly retain deferred and blocked scope")
    blocked = issue_triage_blockers(data)
    if bool(blocked) != (data["outcome"] == "blocked"):
        raise WorkflowError("blocked critical/high issues must hold the goal with outcome blocked")
    budget = triage["budget"]
    if type(budget["limit_seconds"]) is not int or budget["limit_seconds"] != 14400:
        raise WorkflowError("deferred budget is exactly four hours shared wall-clock time")
    selected = budget["selected_group_ids"]
    if len(selected) != len(set(selected)) or not set(selected) <= groups.keys() or len(selected) > 2:
        raise WorkflowError("select at most two distinct frozen deferred groups")
    prior_budget = supersedes["issue_triage"]["budget"] if supersedes is not None else None
    prior_selected = prior_budget["selected_group_ids"] if prior_budget is not None else []
    prior_intervals = prior_budget["work_intervals"] if prior_budget is not None else []
    if selected[:len(prior_selected)] != prior_selected:
        raise WorkflowError("the cycle-wide group selection is cumulative across revisions")
    newly_selected = selected[len(prior_selected):]
    intervals = budget["work_intervals"]
    if prior_budget is not None and prior_budget.get("started_at") is not None:
        if prior_budget["started_at"] != budget.get("started_at"):
            raise WorkflowError("revising evidence cannot restart the shared budget")
        if prior_budget.get("critical_high_completed_at") != budget.get("critical_high_completed_at"):
            raise WorkflowError("revisions must preserve the original mandatory-work completion time")
        if _time(budget.get("ended_at", "")) < _time(prior_budget["ended_at"]):
            raise WorkflowError("the cumulative budget observation cannot move backwards")
    if intervals[:len(prior_intervals)] != prior_intervals:
        raise WorkflowError("revisions must retain every previously recorded work interval")
    def budget_eligible(number):
        return (inventory[number]["severity"] in {"medium", "low"}
                and dispositions[number]["status"] in {"fixed", "deferred"})

    optional_groups = [key for key, group in groups.items() if any(
        budget_eligible(number) for number in group["issue_numbers"])]
    def rank(group_id):
        items = [inventory[number] for number in groups[group_id]["issue_numbers"]
                 if budget_eligible(number)]
        return (-len(items), -sum(item["severity"] == "medium" for item in items), group_id)
    # Previously worked groups still consume the two-group allowance even if
    # their latest disposition is blocked. Only new admissions are re-ranked.
    ranked = sorted((group_id for group_id in optional_groups if group_id not in prior_selected), key=rank)
    if not blocked and ranked and not selected:
        raise WorkflowError("after mandatory issues, work one or two largest remaining groups")
    if newly_selected != ranked[:len(newly_selected)]:
        raise WorkflowError("deferred groups must be largest first, with severity mix breaking ties")
    if selected:
        if blocked and (not prior_selected or newly_selected or intervals != prior_intervals):
            raise WorkflowError("deferred work cannot begin while critical/high issues remain blocked")
        required_done = _time(budget.get("critical_high_completed_at", ""))
        start, end = _time(budget.get("started_at", "")), _time(budget.get("ended_at", ""))
        if not frozen <= required_done <= start <= end or (end - start).total_seconds() > 14400:
            raise WorkflowError("shared four-hour window must begin after critical/high completion")
        worked = set()
        for interval in intervals:
            left, right = _time(interval["started_at"]), _time(interval["ended_at"])
            if interval["group_id"] not in selected or not start <= left < right <= end:
                raise WorkflowError("both actors must work within the same shared elapsed budget")
            worked.add(interval["group_id"])
        if worked != set(selected):
            raise WorkflowError("each selected deferred group needs observed work inside the budget")
    elif intervals or any(key in budget for key in ("started_at", "ended_at")) or not budget.get("unused_reason"):
        raise WorkflowError("unused deferred budget needs a reason and cannot contain work")
    for number, item in dispositions.items():
        if inventory[number]["severity"] in {"medium", "low"} and item["status"] == "fixed" and item["group_id"] not in selected:
            raise WorkflowError("optional fixes must belong to a selected budgeted group")
    active = set(selected) | {dispositions[number]["group_id"] for number in inventory
                              if inventory[number]["severity"] in {"critical", "high"}}
    for group_id in active:
        group = groups[group_id]
        pattern = re.escape(f"https://github.com/{data['github_repository']}/issues/") + r"[1-9]\d*"
        if not re.fullmatch(pattern, group.get("tracking_issue_url", "")):
            raise WorkflowError("each active group requires a same-repository tracking issue")
        if sorted(group.get("sub_issue_numbers", [])) != sorted(group["issue_numbers"]):
            raise WorkflowError("every active group member must be recorded as a sub-issue")
    if previous is not None:
        old = previous.get("issue_triage")
        if (old is None or previous["run_id"] != data["run_id"]
                or previous["cycle"] != data["cycle"] - 1):
            raise WorkflowError("issue triage lineage must reference the previous cycle's issue triage")
        for group in old["groups"]:
            if group["group_id"] in old["carry_forward_group_ids"]:
                for number in set(group["issue_numbers"]) & inventory.keys():
                    if dispositions[number]["group_id"] != group["group_id"]:
                        raise WorkflowError("deferred issue groups must retain stable IDs across cycles")
    if supersedes is not None:
        old = supersedes["issue_triage"]
        old_source = [item["sha256"] for item in supersedes["artifacts"] if item["kind"] == "issue_inventory"]
        current_source = [item["sha256"] for item in data["artifacts"] if item["kind"] == "issue_inventory"]
        frozen_group_fields = ("group_id", "issue_numbers", "size", "shared_cause")
        old_groups = _unique(old["groups"], "group_id")
        if (old_source != current_source or data["scope_frozen_at"] != supersedes["scope_frozen_at"]
                or old["inventory"] != triage["inventory"] or old_groups.keys() != groups.keys()
                or any(any(old_groups[group_id][field] != group[field]
                           for field in frozen_group_fields) for group_id, group in groups.items())):
            raise WorkflowError("triage revisions must preserve frozen inventory and stable grouping")
        # An inactive group need not have a GitHub tracking issue yet. Activation
        # may add that coordination metadata without changing its frozen scope.
        # Once an identity is recorded it cannot be silently replaced or removed.
        for group_id, group in groups.items():
            previous_group = old_groups[group_id]
            if ("tracking_issue_url" in previous_group
                    and group.get("tracking_issue_url") != previous_group["tracking_issue_url"]):
                raise WorkflowError("triage revisions must preserve existing tracking issue identity")
            if not set(previous_group.get("sub_issue_numbers", [])) <= set(group.get("sub_issue_numbers", [])):
                raise WorkflowError("triage revisions cannot remove recorded sub-issue identities")
            if group_id not in active and any(previous_group.get(field) != group.get(field)
                                               for field in ("tracking_issue_url", "sub_issue_numbers")):
                raise WorkflowError("new group coordination metadata requires activation")
    if repository_root is not None:
        root = Path(repository_root)
        snapshot = _artifact_payload(data, "issue_inventory", root)
        if not isinstance(snapshot, dict):
            raise WorkflowError("frozen issue inventory must be a JSON object")
        validate_issue_snapshot(snapshot, data["github_repository"])
        assessed = [{key: item[key] for key in ("number", "title", "labels", "updatedAt")}
                    for item in triage["inventory"]]
        if snapshot["frozen_at"] != data["scope_frozen_at"] or snapshot["issues"] != assessed:
            raise WorkflowError("assessment must preserve the entire supervisor-frozen inventory")
        for kind, payload in (("issue_groups", {"groups": triage["groups"]}),
                              ("group_plans", {"plans": triage["group_plans"]}),
                              ("dispositions", {"dispositions": triage["dispositions"]})):
            if _artifact_payload(data, kind, root) != payload:
                raise WorkflowError(f"{kind} artifact must match the structured evidence")
