"""Additive ordered closure receipt shape; no filesystem or completion authority."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
PR_FIELDS = {"number", "head_sha", "branch", "base"}
MEMBER_FIELDS = PR_FIELDS | {"merge_commit_sha", "review", "validation", "cleanup"}


def receipt_path(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and not any(ord(char) < 32 for char in value)
            and not PurePosixPath(value).is_absolute()
            and not any(part in {"", ".", ".."} for part in value.split("/")))


def multi_pr_members(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Return checked members, or [] for an unchanged single-PR receipt.

    The top-level PR and proofs continue to identify the final integration head.
    Shape validation never proves membership, authorship, review or merge facts.
    """
    if "prs" not in receipt:
        if "evidence_attributions" in receipt:
            raise ValueError("evidence attributions require ordered PRs")
        return []
    members = receipt["prs"]
    if (receipt.get("schema_version") != 2 or receipt.get("status") != "completed"
            or not isinstance(members, list) or not 2 <= len(members) <= 16):
        raise ValueError("ordered PRs require a completed v2 receipt and 2..16 members")
    numbers: set[int] = set()
    heads: set[str] = set()
    merges: set[str] = set()
    branches: set[str] = set()
    for member in members:
        if not isinstance(member, dict) or set(member) != MEMBER_FIELDS:
            raise ValueError("ordered PR member fields are incomplete or unknown")
        number = member["number"]
        head, merge, branch = member["head_sha"], member["merge_commit_sha"], member["branch"]
        if (type(number) is not int or number <= 0 or number in numbers
                or not isinstance(head, str) or not SHA.fullmatch(head) or head in heads
                or not isinstance(merge, str) or not SHA.fullmatch(merge) or merge in merges
                or not isinstance(branch, str) or not branch or branch.startswith("-") or branch in branches
                or not isinstance(member["base"], str) or not member["base"] or member["base"] == branch):
            raise ValueError("ordered PR member identity is invalid or repeated")
        review, validation, cleanup = member["review"], member["validation"], member["cleanup"]
        if (not isinstance(review, dict) or review.get("status") != "complete"
                or type(review.get("remaining_findings")) is not int or review["remaining_findings"] != 0
                or review.get("head_sha") != head):
            raise ValueError("every ordered PR needs a complete review at its exact head")
        if (not isinstance(validation, list) or not validation
                or any(not isinstance(item, dict) or not isinstance(item.get("command"), str)
                       or not item["command"].strip() or item.get("status") != "passed"
                       or item.get("head_sha") != head for item in validation)):
            raise ValueError("every ordered PR needs passing validation at its exact head")
        if (not isinstance(cleanup, dict) or any(cleanup.get(key) is not True for key in
                ("checkout_ready", "local_branch_deleted", "remote_branch_deleted"))):
            raise ValueError("every ordered PR needs branch cleanup")
        numbers.add(number)
        heads.add(head)
        merges.add(merge)
        branches.add(branch)
    last = members[-1]
    if (receipt.get("pr") != {key: last[key] for key in PR_FIELDS}
            or any(receipt.get(key) != last[key] for key in ("review", "validation", "cleanup"))):
        raise ValueError("final ordered PR must exactly match top-level PR and proofs")
    issues = receipt.get("issues")
    if not isinstance(issues, list) or any(
            not isinstance(issue, dict) or type(issue.get("pr_number")) is not int
            or issue["pr_number"] not in numbers for issue in issues):
        raise ValueError("every issue must name its exact ordered PR")
    for issue in issues:
        superseded = issue.get("superseded_paths", [])
        if (not isinstance(superseded, list) or len(superseded) > 256
                or ("superseded_paths" in issue and not superseded)):
            raise ValueError("superseded paths require 1..256 exact entries when present")
        seen_paths: set[str] = set()
        for item in superseded:
            if (not isinstance(item, dict) or set(item) != {"path", "pr_number", "commit_sha"}
                    or not receipt_path(item["path"]) or item["path"] in seen_paths
                    or type(item["pr_number"]) is not int or item["pr_number"] != issue["pr_number"]
                    or not isinstance(item["commit_sha"], str) or not SHA.fullmatch(item["commit_sha"])
                    or item["commit_sha"] == issue.get("fix_commit_sha")):
                raise ValueError("invalid, repeated or self-referential same-PR fix supersession")
            seen_paths.add(item["path"])
    attributions = receipt.get("evidence_attributions")
    if not isinstance(attributions, list):
        raise ValueError("ordered PRs require explicit evidence attributions")
    paths: set[str] = set()
    for item in attributions:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "pr_number", "commit_sha"}:
            raise ValueError("evidence attribution fields are incomplete or unknown")
        path = item["path"]
        if (not receipt_path(path) or path in paths
                or type(item["pr_number"]) is not int or item["pr_number"] not in numbers
                or not isinstance(item["sha256"], str) or not DIGEST.fullmatch(item["sha256"])
                or not isinstance(item["commit_sha"], str) or not SHA.fullmatch(item["commit_sha"])):
            raise ValueError("invalid or duplicate evidence attribution")
        paths.add(path)
    return members
