"""Bounded read-only PR observations for parent 2.1 maintenance.

Only the caller's existing closure verifier establishes review, merge and branch
cleanup. This module never merges, closes, rebases, installs or sends session input.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import WorkflowError
from .pr_maintenance import validate_pr_snapshot

PR_FIELDS = "number title updatedAt isDraft headRefOid baseRefOid headRefName baseRefName mergeable"
CONTEXT_FIELDS = """totalCount pageInfo{hasNextPage endCursor} nodes{
 __typename ... on CheckRun{id name status conclusion}
 ... on StatusContext{id context state}
}"""


def resolve_limit(repository_key: str, github: str, manifest_path: Path | None = None) -> tuple[int, str]:
    from kg_microbe_fleet import load_fleet_manifest
    if repository_key == "claw":
        if github != "CultureBotAI/culturebotai-claw":
            raise WorkflowError("claw PR maintenance identity differs")
        return 25, "default"
    mech = load_fleet_manifest(manifest_path).get(repository_key)
    if mech.github != github:
        raise WorkflowError("PR maintenance repository differs from the manifest")
    return (25, "default") if mech.open_pr_limit is None else (mech.open_pr_limit, "manifest")


class Observer:
    def __init__(self, github, runner, *, seconds=180):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github):
            raise WorkflowError("invalid PR maintenance repository")
        self.github = github
        self.owner, self.name = github.split("/")
        self.runner = runner
        self.deadline = time.monotonic() + seconds

    def query(self, query, **variables):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise WorkflowError("PR maintenance observation deadline exceeded")
        args = ["gh", "api", "graphql", "-f", "query=" + query,
                "-f", "owner=" + self.owner, "-f", "name=" + self.name]
        for key, value in variables.items():
            if value is not None:
                args.extend(["-F" if type(value) is int else "-f", f"{key}={value}"])
        result = self.runner(args, timeout=max(1, min(45, int(remaining))))
        if result.returncode:
            raise WorkflowError("PR maintenance query failed")
        try:
            payload = json.loads(result.stdout)
            source = payload["data"]["repository"]
            if payload.get("errors") or source["nameWithOwner"] != self.github:
                raise ValueError("wrong or unavailable repository")
            return source
        except (ValueError, KeyError, TypeError) as exc:
            raise WorkflowError("PR maintenance response unavailable or malformed") from exc

    @staticmethod
    def page(connection, total, seen_cursors):
        count, nodes, info = connection["totalCount"], connection["nodes"], connection["pageInfo"]
        if (type(count) is not int or not 0 <= count <= 10000 or not isinstance(nodes, list)
                or len(nodes) > 100 or (total is not None and total != count)
                or type(info["hasNextPage"]) is not bool):
            raise WorkflowError("PR maintenance inventory count changed or is invalid")
        cursor = info.get("endCursor") if info["hasNextPage"] else None
        if info["hasNextPage"] and (not nodes or not isinstance(cursor, str) or not cursor
                                    or cursor in seen_cursors):
            raise WorkflowError("PR maintenance pagination is repeated or incomplete")
        seen_cursors.add(cursor)
        return count, nodes, cursor

    def open_prs(self):
        query = ("query($owner:String!,$name:String!,$cursor:String){repository(owner:$owner,name:$name){"
                 "nameWithOwner pullRequests(first:100,after:$cursor,states:OPEN,orderBy:{field:CREATED_AT,direction:ASC}){"
                 "totalCount pageInfo{hasNextPage endCursor} nodes{" + PR_FIELDS + "}}}}")
        rows: list[dict] = []
        cursors: set[str | None] = set()
        cursor = total = None
        try:
            for page in range(1, 101):
                connection = self.query(query, cursor=cursor)["pullRequests"]
                total, nodes, cursor = self.page(connection, total, cursors)
                rows.extend(nodes)
                if cursor is None:
                    if len(rows) != total or len({p["number"] for p in rows}) != total:
                        raise WorkflowError("PR inventory does not cover each open PR exactly once")
                    return sorted(rows, key=lambda row: row["number"]), page
        except (KeyError, TypeError) as exc:
            raise WorkflowError("malformed open PR inventory") from exc
        raise WorkflowError("PR inventory exceeded its pagination bound")

    def checks(self, number, head):
        query = ("query($owner:String!,$name:String!,$number:Int!,$cursor:String){"
                 "repository(owner:$owner,name:$name){nameWithOwner pullRequest(number:$number){headRefOid "
                 "commits(last:1){nodes{commit{oid statusCheckRollup{contexts(first:100,after:$cursor){"
                 + CONTEXT_FIELDS + "}}}}}}}}")
        rows: list[dict] = []
        cursors: set[str | None] = set()
        cursor = total = None
        try:
            for _ in range(100):
                pr = self.query(query, number=number, cursor=cursor)["pullRequest"]
                commits = pr["commits"]["nodes"]
                if pr["headRefOid"] != head or len(commits) != 1 or commits[0]["commit"]["oid"] != head:
                    raise WorkflowError("PR head changed during check capture")
                rollup = commits[0]["commit"]["statusCheckRollup"]
                if rollup is None:
                    if rows:
                        raise WorkflowError("PR checks disappeared while paginating")
                    return {"checks_state": "unknown", "checks_complete": True,
                            "check_count": 0, "failing_checks": []}
                total, nodes, cursor = self.page(rollup["contexts"], total, cursors)
                rows.extend(nodes)
                if cursor is None:
                    if len(rows) != total or len({row["id"] for row in rows}) != total:
                        raise WorkflowError("PR check inventory is incomplete or duplicated")
                    return check_summary(rows)
        except (KeyError, TypeError) as exc:
            raise WorkflowError("malformed PR check inventory") from exc
        raise WorkflowError("PR checks exceeded pagination bound")

    def live_issue(self, number):
        query = ("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
                 "nameWithOwner issue(number:$number){number url state}}}")
        return self.query(query, number=number)["issue"]

    def live_pr(self, number):
        query = ("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
                 "nameWithOwner pullRequest(number:$number){" + PR_FIELDS +
                 " state merged mergeCommit{oid} url}}}")
        return self.query(query, number=number)["pullRequest"]


def check_summary(rows):
    failed, pending, unknown, success = set(), False, False, False
    for row in rows:
        if row["__typename"] == "CheckRun":
            name = row["name"]
            if row["status"] != "COMPLETED":
                pending = True
            elif row["conclusion"] == "SUCCESS":
                success = True
            elif row["conclusion"] in {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}:
                failed.add(name)
            elif row["conclusion"] not in {"NEUTRAL", "SKIPPED"}:
                unknown = True
        elif row["__typename"] == "StatusContext":
            if row["state"] == "SUCCESS":
                success = True
            elif row["state"] in {"ERROR", "FAILURE"}:
                failed.add(row["context"])
            elif row["state"] in {"PENDING", "EXPECTED"}:
                pending = True
            else:
                unknown = True
        else:
            unknown = True
    state = ("failing" if failed else "pending" if pending else
             "unknown" if unknown or not success else "green")
    return {"checks_state": state, "checks_complete": not unknown,
            "check_count": len(rows), "failing_checks": sorted(failed)}


def capture_pr_scope(target, runner, *, limit=25, limit_source="default"):
    observer = Observer(target["github_repository"], runner)
    raw, pages = observer.open_prs()
    rows = []
    for pr in raw:
        rows.append({"number": pr["number"], "title": pr["title"], "updatedAt": pr["updatedAt"],
                     "is_draft": pr["isDraft"], "head_sha": pr["headRefOid"], "base_sha": pr["baseRefOid"],
                     "head_branch": pr["headRefName"], "base_branch": pr["baseRefName"],
                     "mergeability": {"MERGEABLE": "mergeable", "CONFLICTING": "conflicting",
                                      "UNKNOWN": "unknown"}.get(pr["mergeable"], "unknown"),
                     **observer.checks(pr["number"], pr["headRefOid"])})
    again, _ = observer.open_prs()
    if again != raw:
        raise WorkflowError("open PR inventory changed during capture; retry without replacing frozen scope")
    snapshot = {"repository": target["github_repository"],
                "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "complete": True, "total_count": len(rows), "pages": pages,
                "open_non_draft_limit": limit, "limit_source": limit_source, "prs": rows}
    validate_pr_snapshot(snapshot, target["github_repository"])
    content = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    return {"sha256": hashlib.sha256(content.encode()).hexdigest(), "content": content,
            "frozen_at": snapshot["frozen_at"], "prs": rows,
            "open_non_draft_limit": limit, "limit_source": limit_source}


def validate_frozen_pr_scope(scope, github):
    content = scope.get("content")
    if not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != scope.get("sha256"):
        raise WorkflowError("frozen PR inventory checksum mismatch")
    snapshot = json.loads(content)
    validate_pr_snapshot(snapshot, github)
    for field in ("frozen_at", "prs", "open_non_draft_limit", "limit_source"):
        if scope.get(field) != snapshot[field]:
            raise WorkflowError("frozen PR scope metadata differs from its inventory")
    return snapshot


def verify_dispositions_live(evidence, target, receipt, verified_proof, runner):
    """Read back state after the caller completed its full closure verification."""
    result = evidence["pr_maintenance"]
    observer = Observer(target["github_repository"], runner)
    members = receipt.get("prs", [receipt.get("pr")])
    members = {p["number"]: p for p in members if p}
    frozen = {p["number"]: p for p in result["inventory"]}
    proofs = verified_proof.get("prs", [verified_proof])
    proofs = {p.get("pr_number"): p for p in proofs if isinstance(p, dict)}
    verified, observed = [], {}
    for item in result["dispositions"]:
        number, status = item["number"], item["status"]
        live = observer.live_pr(number)
        if live["number"] != number or live["url"] != f"https://github.com/{target['github_repository']}/pull/{number}":
            raise WorkflowError("PR disposition repository or identity differs")
        if live["headRefOid"] != item.get("final_head_sha", item["head_sha"]):
            raise WorkflowError("PR disposition head changed after review")
        if status == "merged":
            member = members.get(number, {})
            if (live["state"] != "MERGED" or live["merged"] is not True
                    or not live.get("mergeCommit") or live["mergeCommit"]["oid"] != item["merge_sha"]
                    or member.get("head_sha") != item["final_head_sha"]
                    or proofs.get(number, {}).get("status") != "merged"
                    or proofs[number].get("head_sha") != item["final_head_sha"]
                    or proofs[number].get("merge_commit_sha") != item["merge_sha"]):
                raise WorkflowError("merged maintenance PR lacks matching independently verified closure")
        elif status.startswith("closed_"):
            if live["state"] != "CLOSED" or live["merged"] is not False:
                raise WorkflowError("claimed closed PR remains open or was merged without closure proof")
            if item.get("replacement_pr_url"):
                replacement = int(item["replacement_pr_url"].rsplit("/", 1)[-1])
                other = observer.live_pr(replacement)
                if other["url"] != item["replacement_pr_url"] or other["state"] not in {"OPEN", "MERGED"}:
                    raise WorkflowError("superseding PR is not a live or merged replacement")
        else:
            if live["state"] != "OPEN":
                raise WorkflowError("retained PR state differs from its disposition")
            if live["isDraft"] and not frozen[number]["is_draft"]:
                raise WorkflowError("converting a ready PR to draft cannot evade the WIP limit")
            checks = observer.checks(number, live["headRefOid"])
            if checks["checks_state"] == "green" or live["mergeable"] == "CONFLICTING":
                raise WorkflowError("newly green or conflicting PR still requires closure or a blocked goal")
        observed[number] = live
        verified.append({"number": number, "state": live["state"], "head_sha": live["headRefOid"]})
    source_fixes = []
    for fix in result["shared_check_fixes"]:
        if fix["status"] != "fixed":
            raise WorkflowError("shared check prerequisite still blocks closure")
        source = Observer(fix["source_repository"], runner)
        issue_number = int(fix["source_issue_url"].rsplit("/", 1)[-1])
        issue = source.live_issue(issue_number)
        if (not isinstance(issue, dict) or issue.get("number") != issue_number
                or issue.get("url") != fix["source_issue_url"]
                or issue.get("state") not in {"OPEN", "CLOSED"}):
            raise WorkflowError("shared check source issue is not an actual repository issue")
        number = int(fix["source_fix_pr_url"].rsplit("/", 1)[-1])
        pr = source.live_pr(number)
        if (pr["url"] != fix["source_fix_pr_url"] or pr["state"] != "MERGED"
                or pr["merged"] is not True or not pr.get("mergeCommit")):
            raise WorkflowError("shared check source fix is not actually merged")
        source_fixes.append({"repository": fix["source_repository"], "pr_number": number,
                             "merge_sha": pr["mergeCommit"]["oid"]})
    current, _ = observer.open_prs()
    ready = sorted(p["number"] for p in current if not p["isDraft"])
    if ready != sorted(result["remaining_open_non_draft"]) or len(ready) > result["open_non_draft_limit"]:
        raise WorkflowError("current non-draft PR count differs or exceeds its frozen manifest limit")
    current_by_number = {pr["number"]: pr for pr in current}
    for number, earlier in observed.items():
        latest = current_by_number.get(number)
        if earlier["state"] in {"CLOSED", "MERGED"}:
            if latest is not None:
                raise WorkflowError("terminal PR reappeared in the final open inventory")
        elif (latest is None or any(latest.get(field) != earlier.get(field) for field in PR_FIELDS.split())):
            raise WorkflowError("retained PR changed before the final inventory readback")
        elif observer.checks(number, latest["headRefOid"])["checks_state"] == "green":
            raise WorkflowError("newly green PR requires closure at final readback")
    return {"verified_at": datetime.now(timezone.utc).isoformat(), "prs": verified,
            "remaining_open_non_draft": ready, "limit": result["open_non_draft_limit"],
            "source_fixes": source_fixes}



def parse_worktree_inventory(raw):
    """Consume every porcelain field; partial output cannot prove absence."""
    if not isinstance(raw, str) or not raw.endswith("\n\n"):
        raise WorkflowError("worktree registration inventory is empty or incomplete")
    roots = []
    for block in raw[:-2].split("\n\n"):
        fields = {}
        for line in block.splitlines():
            key, separator, value = line.partition(" ")
            if key in fields or key not in {"worktree", "HEAD", "branch", "detached", "bare", "locked", "prunable"}:
                raise WorkflowError("worktree registration inventory contains malformed fields")
            if key in {"bare", "detached"} and separator:
                raise WorkflowError("worktree registration flag has an unexpected value")
            fields[key] = value
        root = fields.get("worktree", "")
        if not Path(root).is_absolute() or not block.startswith("worktree "):
            raise WorkflowError("worktree registration path is missing or relative")
        if "bare" in fields:
            if set(fields) != {"worktree", "bare"}:
                raise WorkflowError("bare worktree registration has contradictory metadata")
        elif (not re.fullmatch(r"[0-9a-f]{40}", fields.get("HEAD", ""))
                or ("branch" in fields) == ("detached" in fields)
                or ("branch" in fields and not fields["branch"].startswith("refs/heads/"))):
            raise WorkflowError("worktree registration HEAD or branch metadata is malformed")
        path = Path(root).resolve()
        if path in roots:
            raise WorkflowError("worktree registration inventory repeats a path")
        roots.append(path)
    return roots


def verify_worktree_cleanup(receipt, target, runner, runtime=None):
    """Verify preserved audit bytes and absence of each owned feature worktree.

    The audit is evidence, not permission to remove a path. This is read-only and
    deliberately refuses a retained registration even when its path is missing.
    """
    from . import _read_regular
    roots = [Path(target["root"]).resolve()]
    if runtime is not None:
        roots.append(Path(runtime).resolve())
    members = receipt.get("prs", [receipt["pr"]])
    registered = set()
    for source in dict.fromkeys([target["root"], *target.get("session_repository_roots", [])]):
        output = runner(["git", "-C", source, "worktree", "list", "--porcelain"])
        if output.returncode:
            raise WorkflowError("owned worktree registration inventory unavailable")
        registered.update(parse_worktree_inventory(output.stdout))
    verified, seen = [], set()
    for member in members:
        cleanup = member.get("cleanup", receipt.get("cleanup"))
        if not isinstance(cleanup, dict):
            raise WorkflowError("worktree cleanup evidence missing")
        paths = cleanup.get("worktree_paths")
        audit = cleanup.get("worktree_cleanup", {})
        if (not isinstance(paths, list) or not paths
                or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths)
                or len(paths) != len(set(paths))
                or not isinstance(audit, dict) or not isinstance(audit.get("artifact"), str)):
            raise WorkflowError("owned feature-worktree paths and audit are required")
        path = Path(audit["artifact"])
        if not path.is_absolute():
            path = roots[0] / path
        boundary = next((root for root in roots if path.resolve().is_relative_to(root)), None)
        if boundary is None:
            raise WorkflowError("worktree cleanup audit escapes retained evidence roots")
        raw = _read_regular(path, boundary)
        if hashlib.sha256(raw).hexdigest() != audit.get("sha256"):
            raise WorkflowError("worktree cleanup audit bytes changed")
        value = json.loads(raw)
        if (value.get("repository") != target["github_repository"]
                or value.get("head_sha") != member["head_sha"]
                or value.get("branch") != member["branch"]
                or value.get("worktree_paths") != paths
                or not isinstance(value.get("preservation_manifest_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", value["preservation_manifest_sha256"])):
            raise WorkflowError("worktree cleanup audit identity or preservation proof differs")
        descriptor = value.get("preservation_manifest", {})
        if not isinstance(descriptor, dict) or not isinstance(descriptor.get("artifact"), str):
            raise WorkflowError("worktree cleanup lacks its retained preservation manifest")
        preserved_path = Path(descriptor["artifact"])
        if not preserved_path.is_absolute():
            preserved_path = roots[0] / preserved_path
        preserved_root = next((root for root in roots if preserved_path.resolve().is_relative_to(root)), None)
        if preserved_root is None:
            raise WorkflowError("preservation manifest escapes retained evidence roots")
        preserved_bytes = _read_regular(preserved_path, preserved_root)
        digest = hashlib.sha256(preserved_bytes).hexdigest()
        if digest != descriptor.get("sha256") or digest != value["preservation_manifest_sha256"]:
            raise WorkflowError("preservation manifest bytes changed")
        preservation = json.loads(preserved_bytes)
        if (preservation.get("inventory_includes_ignored") is not True
                or preservation.get("worktree_paths") != paths
                or not isinstance(preservation.get("retained_files"), list)):
            raise WorkflowError("preservation manifest lacks ignored-inclusive inventory")
        for retained in preservation["retained_files"]:
            if not isinstance(retained, dict) or not isinstance(retained.get("artifact"), str):
                raise WorkflowError("malformed retained file evidence")
            retained_path = Path(retained["artifact"])
            if not retained_path.is_absolute():
                retained_path = roots[0] / retained_path
            retained_root = next((root for root in roots if retained_path.resolve().is_relative_to(root)), None)
            if retained_root is None or hashlib.sha256(_read_regular(retained_path, retained_root)).hexdigest() != retained.get("sha256"):
                raise WorkflowError("retained valuable work is missing or changed")
        for item in paths:
            candidate = Path(item)
            if (candidate != candidate.resolve() or candidate in seen
                    or any(root.is_relative_to(candidate) for root in roots)
                    or candidate.exists() or candidate.is_symlink() or candidate in registered):
                raise WorkflowError("owned worktree is unsafe, repeated, still present or registered")
            seen.add(candidate)
        verified.append({"pr_number": member["number"], "head_sha": member["head_sha"],
                         "worktree_paths": paths, "audit_sha256": audit["sha256"]})
    return verified
