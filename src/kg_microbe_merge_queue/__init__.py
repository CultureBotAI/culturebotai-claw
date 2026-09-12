"""Inspect and reconcile native GitHub merge queues for the manifest fleet.

Only an explicit apply writes GitHub. A saved plan binds repository identity,
workflow bytes, existing protection and the packaged policy; stale plans fail
before any write. Receipts retain partial progress if a later API call fails.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import yaml

from kg_microbe_fleet import UniqueKeySafeLoader, load_fleet_manifest

RULESET_NAME = "CLAW merge queue"
CLAW = "CultureBotAI/culturebotai-claw"
ACTIONS_APP_ID = 15368
QUEUE_PARAMETERS = {
    "check_response_timeout_minutes": 120,
    "grouping_strategy": "ALLGREEN",
    "max_entries_to_build": 3,
    "max_entries_to_merge": 1,
    "merge_method": "SQUASH",
    "min_entries_to_merge": 1,
    "min_entries_to_merge_wait_minutes": 5,
}
RULESET_FIELDS = ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")


class QueueError(ValueError):
    """Unsafe, incomplete, stale or unsupported queue configuration."""


class GitHub:
    """Use the existing gh authentication without handling or printing tokens."""

    def request(self, endpoint: str, method: str = "GET", body=None, *, unprotected_ok=False):
        args = ["gh", "api", "--method", method, endpoint]
        if body is not None:
            args += ["--input", "-"]
        result = subprocess.run(
            args, input=None if body is None else json.dumps(body),
            text=True, capture_output=True, check=False,
        )
        if result.returncode:
            if unprotected_ok and "(HTTP 404)" in result.stderr:
                response = json.loads(result.stdout)
                if response.get("message") == "Branch not protected":
                    return None
            raise QueueError(f"{method} {endpoint}: {result.stderr.strip()}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def pages(self, endpoint: str, field: str | None = None):
        values = []
        for page in range(1, 101):
            sep = "&" if "?" in endpoint else "?"
            response = self.request(f"{endpoint}{sep}per_page=100&page={page}")
            batch = response[field] if field else response
            values.extend(batch)
            if len(batch) < 100:
                return values
        raise QueueError(f"Pagination limit reached: {endpoint}")


def identities() -> dict[str, str]:
    fleet = load_fleet_manifest()
    return {"claw": CLAW, **{key: fleet.get(key).github for key in fleet.keys}}


def load_policy(path: Path | None = None) -> dict:
    policy = json.loads((path or Path(__file__).with_name("policy.json")).read_text())
    if set(policy) != set(identities()):
        raise QueueError("Queue policy keys must equal the fleet manifest plus claw")
    for key, workflows in policy.items():
        if not isinstance(workflows, dict) or not workflows:
            raise QueueError(f"{key}: empty workflow policy")
        names = []
        for workflow, contexts in workflows.items():
            if not workflow.startswith(".github/workflows/") or ".." in workflow.split("/"):
                raise QueueError(f"{key}: invalid workflow path {workflow}")
            if not isinstance(contexts, list) or not contexts or not all(
                isinstance(name, str) and name.strip() == name and name for name in contexts
            ):
                raise QueueError(f"{key}: invalid required contexts")
            names.extend(contexts)
        if len(names) != len(set(names)):
            raise QueueError(f"{key}: duplicate required context names")
    return policy


def desired_ruleset(workflows: dict) -> dict:
    contexts = sorted(name for names in workflows.values() for name in names)
    return {
        "name": RULESET_NAME, "target": "branch", "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {"type": "pull_request", "parameters": {
                "dismiss_stale_reviews_on_push": False, "require_code_owner_review": False,
                "require_last_push_approval": False, "required_approving_review_count": 0,
                "required_review_thread_resolution": False,
            }},
            {"type": "required_status_checks", "parameters": {
                "required_status_checks": [
                    {"context": name, "integration_id": ACTIONS_APP_ID} for name in contexts
                ],
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": False,
            }},
            {"type": "merge_queue", "parameters": dict(QUEUE_PARAMETERS)},
        ],
    }


def canonical_ruleset(ruleset: dict) -> dict:
    """Discard response metadata and normalize API defaults/order for comparison."""
    result = {key: ruleset.get(key) for key in RULESET_FIELDS}
    result = json.loads(json.dumps(result))
    for rule in result["rules"] or []:
        params = rule.get("parameters", {})
        if rule["type"] == "required_status_checks":
            params.setdefault("do_not_enforce_on_create", False)
            params["required_status_checks"] = sorted(
                params["required_status_checks"], key=lambda item: item["context"]
            )
        if rule["type"] == "pull_request":
            # Observed defaults on the live rules API when omitted from POST.
            # Compare explicit values so altered or unknown fields remain drift.
            params.setdefault("dismissal_restriction", {"enabled": False, "allowed_actors": []})
            params.setdefault("require_extra_approval_for_unattributed_changes", True)
            # GitHub may return these default empty/false additions.
            if params.get("allowed_merge_methods") == ["merge", "squash", "rebase"]:
                params.pop("allowed_merge_methods")
            if params.get("required_reviewers") == []:
                params.pop("required_reviewers")
    result["rules"] = sorted(result["rules"] or [], key=lambda rule: rule["type"])
    return result


def workflow_errors(text: str, contexts: list[str] | None = None) -> list[str]:
    """Check queue triggers and required job execution without interpreting shell."""
    document = yaml.load(text, Loader=UniqueKeySafeLoader)
    if not isinstance(document, dict):
        return ["workflow must be a mapping"]
    events = document.get("on", document.get(True, {}))
    if isinstance(events, list):
        events = dict.fromkeys(events)
    if not isinstance(events, dict):
        return ["workflow must declare pull_request and merge_group"]
    errors = []
    for event in ("pull_request", "merge_group"):
        if event not in events:
            errors.append(f"missing {event} trigger")
            continue
        config = events[event] or {}
        if not isinstance(config, dict):
            errors.append(f"invalid {event} trigger")
            continue
        if any(key in config for key in ("paths", "paths-ignore", "branches-ignore")):
            errors.append(f"{event} must not filter required checks")
        if config.get("branches") not in (None, ["main"]):
            errors.append(f"{event} has unsupported branch filter")
        types = config.get("types")
        if event == "merge_group" and types is not None and "checks_requested" not in types:
            errors.append("merge_group must include checks_requested")
        if event == "pull_request" and types is not None and not {
            "opened", "synchronize", "reopened"
        } <= set(types):
            errors.append("pull_request is missing normal validation activity types")
    jobs = document.get("jobs") or {}
    if not isinstance(jobs, dict) or not all(isinstance(job, dict) for job in jobs.values()):
        return [*errors, "jobs must be a mapping of job definitions"]
    required = set()
    for label, node in jobs.items():
        name = str(node.get("name", label))
        prefix = name.split("${{", 1)[0]
        if any(context == name or context.startswith(name + " (")
               or context.startswith(name + " / ")
               or ("${{" in name and context.startswith(prefix))
               for context in contexts or []):
            required.add(label)
    # A skipped prerequisite skips its dependents too, even when the dependent
    # has no condition of its own. Apply the execution guard transitively.
    pending = list(required)
    while pending:
        label = pending.pop()
        needs = jobs[label].get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if not isinstance(needs, list) or not all(isinstance(need, str) for need in needs):
            errors.append(f"{label}: needs must name static jobs")
            continue
        for need in needs:
            if need not in jobs:
                errors.append(f"{label}: unresolved prerequisite {need}")
            elif need not in required:
                required.add(need)
                pending.append(need)
    for label, node in [("workflow", document), *list(jobs.items())]:
        concurrency = node.get("concurrency") or {}
        if node is not document and "concurrency" in node:
            # Jobs and workflows share a concurrency namespace. A run-id
            # expression alone cannot rule out self-contention or collisions
            # between matrix jobs; the supported policy schedules whole runs.
            errors.append(f"{label}: job concurrency is unsupported; isolate runs at workflow level")
        if concurrency and (
            not isinstance(concurrency, dict)
            or not re.search(
                r"\$\{\{\s*(?:github\.run_id|github\.event_name == 'pull_request' "
                r"&& github\.ref \|\| github\.run_id)\s*\}\}",
                str(concurrency.get("group", "")),
            )
        ):
            errors.append(f"{label}: concurrency must isolate non-PR runs with github.run_id")
        if isinstance(concurrency, dict) and concurrency.get("cancel-in-progress") not in (
            None, False, "${{ github.event_name == 'pull_request' }}"
        ):
            errors.append(f"{label}: cancellation must be PR-only or disabled")
        if node is document or label not in required:
            continue
        if "if" in node or node.get("continue-on-error"):
            errors.append(f"{label}: required jobs and prerequisites must be unconditional and fail closed")
        checkouts = [step.get("with", {}) for step in node.get("steps", [])
                     if step.get("uses", "").startswith("actions/checkout@")]
        candidates = [options for options in checkouts
                      if options.get("repository") in (None, "${{ github.repository }}")
                      and options.get("ref") in (None, "${{ github.sha }}")]
        if checkouts and not candidates:
            errors.append(f"{label}: candidate checkout must use the event commit and repository")
        candidate_paths = []
        for options in candidates:
            path = options.get("path", ".")
            if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or path.startswith("/") or any(
                part in ("..", "") for part in path.split("/")
            ) or "${{" in path or "\\" in path:
                errors.append(f"{label}: candidate checkout needs a static relative path without traversal")
                continue
            candidate_paths.append("/".join(part for part in path.split("/") if part != ".") or ".")
        for options in checkouts:
            if options in candidates:
                continue
            ref = options.get("ref")
            path = options.get("path")
            trusted_audit_base = (
                path == "fleet/trusted-claw"
                and options.get("repository") in (None, "${{ github.repository }}")
                and ref == "${{ github.event_name == 'pull_request' && "
                "github.event.pull_request.base.sha || github.event_name == 'merge_group' "
                "&& github.event.merge_group.base_sha || github.event_name == 'push' "
                "&& github.sha || 'main' }}"
            )
            auxiliary = isinstance(ref, str) and re.fullmatch(r"[0-9a-f]{40}", ref)
            if not trusted_audit_base and not auxiliary:
                errors.append(f"{label}: auxiliary checkout needs an immutable full commit SHA")
            if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or path.startswith("/") or any(
                part in (".", "..", "") for part in path.split("/")
            ) or "${{" in path or "\\" in path:
                errors.append(f"{label}: auxiliary checkout needs an explicit separate path")
            elif any(candidate == "." or candidate == path or candidate.startswith(path + "/")
                     or path.startswith(candidate + "/") for candidate in candidate_paths):
                errors.append(f"{label}: auxiliary checkout overlaps the event candidate")
    return errors


def content(api: GitHub, repo: str, path: str, ref: str) -> dict:
    return api.request(f"repos/{repo}/contents/{quote(path)}?ref={quote(ref, safe='')}")


def snapshot(api: GitHub, repo: str, workflows: dict) -> dict:
    base = f"repos/{repo}"
    metadata = api.request(base)
    branch = api.request(f"{base}/branches/main")
    summaries = api.pages(f"{base}/rulesets?includes_parents=true")
    rulesets = [api.request(f"{base}/rulesets/{rule['id']}") for rule in summaries]
    return {
        "repository": {key: metadata.get(key) for key in (
            "id", "full_name", "private", "archived", "default_branch", "permissions",
            "allow_auto_merge", "allow_squash_merge",
        )},
        "owner_type": metadata["owner"]["type"],
        "main_sha": branch["commit"]["sha"],
        "rulesets": rulesets,
        "classic_protection": api.request(f"{base}/branches/main/protection", unprotected_ok=True),
        "effective_rules": api.pages(f"{base}/rules/branches/main"),
        "workflows": {
            path: content(api, repo, path, branch["commit"]["sha"])
            for path in workflows
        },
    }


def managed_ruleset(state: dict, repo: str) -> dict | None:
    matches = [rule for rule in state["rulesets"] if rule["name"] == RULESET_NAME]
    if len(matches) > 1:
        raise QueueError(f"{repo}: duplicate managed rulesets")
    if matches and (
        matches[0].get("source_type") != "Repository"
        or matches[0].get("source", "").lower() != repo.lower()
    ):
        raise QueueError(f"{repo}: managed ruleset name belongs to inherited policy")
    return matches[0] if matches else None


def readiness_errors(state: dict, repo: str, workflows: dict | None = None) -> list[str]:
    metadata = state["repository"]
    errors = []
    if metadata["full_name"].lower() != repo.lower():
        errors.append("repository identity mismatch")
    if metadata["private"] or state["owner_type"] != "Organization":
        errors.append("automatic rollout supports public organization repositories only")
    if metadata["archived"] or metadata["default_branch"] != "main":
        errors.append("repository must be active with default branch main")
    if not metadata.get("permissions", {}).get("admin"):
        errors.append("administration permission required")
    if not metadata["allow_squash_merge"]:
        errors.append("repository must already allow squash merges")
    if state.get("classic_protection") is not None:
        errors.append("classic branch protection exists; reconcile it explicitly before adoption")
    managed = managed_ruleset(state, repo)
    for rule in state["effective_rules"]:
        if rule["type"] == "merge_queue" and (
            managed is None or rule.get("ruleset_id") != managed["id"]
        ):
            errors.append("another ruleset already manages this branch's queue")
        is_foreign = managed is None or rule.get("ruleset_id") != managed["id"]
        if is_foreign and rule["type"] in ("workflows", "required_deployments"):
            errors.append("existing workflow/deployment requirements need explicit queue review")
        if is_foreign and rule["type"] == "required_status_checks":
            declared = {name for names in (workflows or {}).values() for name in names}
            for check in rule.get("parameters", {}).get("required_status_checks", []):
                if check["context"] not in declared or check.get("integration_id") not in (
                    None, ACTIONS_APP_ID
                ):
                    errors.append(f"existing required context is outside queue policy: {check}")
    for path, blob in state["workflows"].items():
        errors.extend(f"{path}: {error}" for error in workflow_errors(
            base64.b64decode(blob["content"]).decode(), (workflows or {}).get(path)
        ))
    return errors


def context_evidence(api: GitHub, repo: str, workflows: dict, state: dict) -> dict:
    """Require passing real jobs from the exact workflow bytes being enabled.

    A renamed, missing or duplicate context must not strand the queue. Search
    only the ten most recent completed runs per workflow; older evidence needs
    a fresh CI run, never an inferred check name.
    """
    evidence = {}
    for path, names in workflows.items():
        endpoint = f"repos/{repo}/actions/workflows/{Path(path).name}/runs"
        runs = api.request(f"{endpoint}?status=completed&per_page=10")["workflow_runs"]
        for run in runs:
            if run["event"] not in ("pull_request", "push", "merge_group"):
                continue
            if run["conclusion"] != "success":
                continue
            blob = content(api, repo, path, run["head_sha"])
            if blob["sha"] != state["workflows"][path]["sha"]:
                continue
            jobs = api.pages(f"repos/{repo}/actions/runs/{run['id']}/jobs", "jobs")
            if all(sum(job["name"] == name for job in jobs) == 1 and any(
                job["name"] == name and job["conclusion"] == "success" for job in jobs
            ) for name in names):
                evidence[path] = {"run_id": run["id"], "head_sha": run["head_sha"],
                                  "url": run["html_url"], "contexts": names}
                break
        if path not in evidence:
            raise QueueError(f"{path}: no passing run with current workflow bytes and exact "
                             "required contexts among the ten recent completed runs")
    return evidence


def configuration_matches(state: dict, wanted: dict, repo: str) -> bool:
    managed = managed_ruleset(state, repo)
    return bool(managed and state["repository"]["allow_auto_merge"] and
                canonical_ruleset(managed) == canonical_ruleset(wanted) and any(
                    rule["type"] == "merge_queue" and rule.get("ruleset_id") == managed["id"]
                    for rule in state["effective_rules"]
                ))


def fingerprint(state: dict) -> str:
    """Bind stable settings and workflow bytes, allowing unrelated main advances."""
    stable = {key: state[key] for key in ("repository", "owner_type", "rulesets", "effective_rules", "classic_protection")}
    stable["workflows"] = {path: blob["sha"] for path, blob in state["workflows"].items()}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def plan(api: GitHub, keys: list[str] | None = None) -> dict:
    policy = load_policy()
    repos = identities()
    selected = list(repos) if keys is None else keys
    if len(selected) != len(set(selected)) or not set(selected) <= set(repos):
        raise QueueError("Select distinct manifest keys or claw")
    rows = []
    for key in selected:
        repo = repos[key]
        row: dict = {"key": key, "repository": repo, "desired": desired_ruleset(policy[key])}
        try:
            state = snapshot(api, repo, policy[key])
            errors = readiness_errors(state, repo, policy[key])
            row.update(before=state, fingerprint=fingerprint(state), errors=errors)
            if not errors:
                row["evidence"] = context_evidence(api, repo, policy[key], state)
            row["status"] = "blocked" if errors else (
                "unchanged" if configuration_matches(state, row["desired"], repo) else "planned"
            )
        except (QueueError, KeyError, TypeError, yaml.YAMLError) as exc:
            row.update(status="blocked", errors=[str(exc)])
        rows.append(row)
    return {"version": 1, "repositories": rows}


def write_json(path: Path, value: dict, *, exclusive: bool = False) -> None:
    """Publish complete, durable JSON without truncating an existing receipt."""
    serialized = json.dumps(value, indent=2) + "\n"
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            # A hard link publishes the complete file without replacing any path.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        temporary.unlink(missing_ok=True)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _journaled_write(api: GitHub, endpoint: str, method: str, body: dict,
                     receipt: dict, result: dict, receipt_path: Path,
                     expected_ruleset_id: int | None = None) -> None:
    """Persist intent before dispatch; a lost response never means no mutation."""
    attempt = {"method": method, "endpoint": endpoint, "body": copy.deepcopy(body),
               "status": "pending"}
    result["attempts"].append(attempt)
    result["status"] = "updating"
    try:
        write_json(receipt_path, receipt)
    except (OSError, ValueError, TypeError):
        attempt["status"] = "not sent"
        raise
    try:
        response = api.request(endpoint, method, body)
        if method in ("POST", "PUT"):
            rule_id = response.get("id") if isinstance(response, dict) else None
            if type(rule_id) is not int or rule_id <= 0 or (
                expected_ruleset_id is not None and rule_id != expected_ruleset_id
            ):
                raise QueueError("Ruleset write response has no valid matching ID")
            action = {"method": method, "ruleset_id": rule_id}
        else:
            if not isinstance(response, dict) or response.get("allow_auto_merge") is not True:
                raise QueueError("Repository write response does not confirm auto-merge")
            action = {"allow_auto_merge": True}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        attempt.update(status="unknown", error=str(exc))
        raise QueueError(f"{method} {endpoint}: outcome unknown; inspect GitHub before retry: {exc}") from exc
    attempt["status"] = "confirmed"
    attempt["response"] = action
    result["actions"].append(action)
    write_json(receipt_path, receipt)


def apply(api: GitHub, saved: dict, receipt_path: Path) -> dict:
    """Revalidate the whole plan before writing; never overwrite unrelated rulesets."""
    policy, repos = load_policy(), identities()
    if saved.get("version") != 1 or not saved.get("repositories"):
        raise QueueError("Invalid or empty plan")
    rows = saved["repositories"]
    keys = [row["key"] for row in rows]
    if len(set(keys)) != len(keys) or not set(keys) <= set(repos):
        raise QueueError("Plan contains duplicate or unknown repositories")
    verified_plan = copy.deepcopy(saved)
    for row, verified in zip(rows, verified_plan["repositories"], strict=True):
        key, repo = row["key"], repos[row["key"]]
        if row["repository"] != repo or row["desired"] != desired_ruleset(policy[key]):
            raise QueueError(f"{key}: plan differs from installed policy; regenerate it")
        if row["status"] not in ("planned", "unchanged") or row.get("errors"):
            raise QueueError(f"{key}: plan is blocked")
        try:
            baseline_matches = fingerprint(row["before"]) == row["fingerprint"]
        except (KeyError, TypeError, ValueError) as exc:
            raise QueueError(f"{key}: invalid saved baseline; regenerate plan") from exc
        if not baseline_matches:
            raise QueueError(f"{key}: saved baseline differs from its fingerprint; regenerate plan")
        current = snapshot(api, repo, policy[key])
        if readiness_errors(current, repo, policy[key]) or fingerprint(current) != row["fingerprint"]:
            raise QueueError(f"{key}: settings or workflow bytes changed; regenerate plan")
        # Evidence is fetched again; a tampered plan cannot assert passing CI.
        verified["evidence"] = context_evidence(api, repo, policy[key], current)
        verified["before"] = current
    receipt: dict = {"version": 1, "plan": verified_plan, "repositories": [
        {"key": row["key"], "repository": row["repository"],
         "status": "not updated", "actions": [], "attempts": []} for row in rows
    ]}
    write_json(receipt_path, receipt, exclusive=True)
    for row, verified, result in zip(rows, verified_plan["repositories"], receipt["repositories"], strict=True):
        key, repo = row["key"], row["repository"]
        try:
            # Recheck immediately before this repository's first write as well.
            current = snapshot(api, repo, policy[key])
            if fingerprint(current) != row["fingerprint"]:
                raise QueueError("Settings or workflows changed during fleet apply")
            # The receipt's rollback baseline comes from the immediate live read.
            verified["before"] = current
            managed = managed_ruleset(current, repo)
            if not managed or canonical_ruleset(managed) != canonical_ruleset(row["desired"]):
                endpoint = f"repos/{repo}/rulesets"
                method = "POST"
                if managed:
                    endpoint += f"/{managed['id']}"
                    method = "PUT"
                _journaled_write(api, endpoint, method, row["desired"], receipt, result,
                                 receipt_path, managed["id"] if managed else None)
            if not current["repository"]["allow_auto_merge"]:
                _journaled_write(api, f"repos/{repo}", "PATCH", {"allow_auto_merge": True},
                                 receipt, result, receipt_path)
            after = snapshot(api, repo, policy[key])
            result["after"] = after
            if not configuration_matches(after, row["desired"], repo):
                raise QueueError("GitHub read-back differs from desired queue policy")
            result["status"] = "updated" if result["actions"] else "unchanged"
            write_json(receipt_path, receipt)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            result.update(status="failed", error=str(exc))
            try:
                write_json(receipt_path, receipt)
            except (OSError, ValueError, TypeError) as receipt_exc:
                raise QueueError(f"{key}: {exc}; receipt update failed: {receipt_exc}; "
                                 f"inspect the last durable receipt at {receipt_path} and GitHub "
                                 "before retrying") from exc
            raise QueueError(f"{key}: {exc}; partial results saved to {receipt_path}") from exc
    return receipt


def table(rows: list[dict]) -> str:
    """Changed rows first; unchanged, blocked and unattempted targets at the end."""
    ordered = sorted(rows, key=lambda row: row["status"] not in ("updated", "planned"))
    lines = ["| Repository | Result | Details |", "| --- | --- | --- |"]
    for row in ordered:
        detail = row.get("error") or "; ".join(row.get("errors", []))
        lines.append(f"| {row['repository']} | {row['status']} | {detail.replace('|', '/')} |")
    return "\n".join(lines)
