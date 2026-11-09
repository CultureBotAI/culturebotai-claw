"""Read-only, provenance-bearing fleet triage from structured review observations."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

from git import Repo
from git.exc import BadName, BadObject, GitCommandError

from kg_microbe_governance.artifacts.scripts import record_review as contract

SEVERITY_ORDER = {name: index for index, name in enumerate(("blocker", "major", "minor", "informational"))}
TERMINAL = frozenset({"resolved", "rejected", "accepted_risk"})


def _commit(root: Path, ref: str):
    try:
        repository = Repo(root)
        repository.git.update_environment(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
        return repository.commit(ref)
    except (BadName, BadObject, GitCommandError, ValueError) as exc:
        raise contract.ReviewError(f"cannot inspect Git snapshot: {ref}") from exc


def collect_repository(root: Path, expected: str, *, ref: str | None = "origin/main") -> dict:
    """Capture one validated source surface; never fetch, switch branches, or run checks."""
    if contract.repository_identity(root).lower() != expected.lower():
        raise contract.ReviewError("configured review repository identity does not match the fleet")
    commit = _commit(root, ref or "HEAD")
    revision = commit.hexsha

    def blob(name):
        try:
            entry = commit.tree / name
        except KeyError as exc:
            raise contract.ReviewError(f"Git snapshot input missing: {name}") from exc
        if entry.type != "blob" or entry.mode not in {0o100644, 0o100755}:
            raise contract.ReviewError(f"Git snapshot input is not a regular file: {name}")
        return entry

    def reader(name):
        if ref is None:
            return contract.read_bytes(root, name)
        entry = blob(name)
        if entry.size > 32 * 1024 * 1024:
            raise contract.ReviewError(f"review document exceeds the byte limit: {name}")
        return entry.data_stream.read()

    if ref is None:
        paths = contract.review_paths(root)
        source = "working_tree"
    else:
        try:
            tree = commit.tree / contract.REPORT_ROOT
        except KeyError:
            nodes = []
        else:
            if tree.type != "tree":
                raise contract.ReviewError("structured review root is not a Git directory")
            nodes = tree.traverse()
        entries = {}
        for node in nodes:
            if node.type == "tree":
                continue
            name = node.path
            if node.mode not in {0o100644, 0o100755} or node.type != "blob":
                raise contract.ReviewError(f"review Git entry is not a regular file: {name}")
            parts = contract.relative_path(name).parts
            if len(parts) != 4 or parts[-1] not in {"review.yaml", "review.md"}:
                raise contract.ReviewError(f"unexpected structured review Git entry: {name}")
            entries[name] = True
        paths = sorted(name for name in entries if name.endswith("/review.yaml"))
        expected_paths = {part for name in paths for part in (name, name.removesuffix("yaml") + "md")}
        if set(entries) != expected_paths:
            raise contract.ReviewError("Git snapshot contains an incomplete review bundle")
        source = "git_ref"
    reports = []
    input_hashes: dict[str, str | None] = {}
    provenance_cache = {}
    for relative in paths:
        markdown_path = relative.removesuffix("yaml") + "md"
        raw, markdown = reader(relative), reader(markdown_path)
        review = contract.parse_review_bundle(relative, raw, markdown)
        if review["repository"].lower() != expected.lower():
            raise contract.ReviewError(f"foreign review in {expected}: {relative}")
        provenance_source = review["source"]
        provenance_key = (provenance_source["git_revision"], provenance_source["state"],
                          tuple((i["path"], i["sha256"]) for i in provenance_source["inputs"])
                          if provenance_source["state"] == "git_commit" else ())
        if provenance_key not in provenance_cache:
            provenance_cache[provenance_key] = contract.source_provenance(root, review)
        changed, unavailable = [], []
        for item in review["source"]["inputs"]:
            name = item["path"]
            if name not in input_hashes:
                try:
                    if ref is None:
                        digest = contract.file_sha256(root, name)
                    else:
                        stream = blob(name).data_stream
                        hasher = hashlib.sha256()
                        while chunk := stream.read(1024 * 1024):
                            hasher.update(chunk)
                        digest = hasher.hexdigest()
                except (OSError, contract.ReviewError):
                    input_hashes[name] = None
                else:
                    input_hashes[name] = digest
            digest = input_hashes[name]
            if digest is None:
                unavailable.append(item["path"])
            elif digest != item["sha256"]:
                changed.append(item["path"])
        currentness = "unknown" if unavailable else "changed" if changed else "matches_observed_surface"
        reports.append({"path": relative, "sha256": contract.content_sha256(raw), "record": review,
                        "source_provenance": provenance_cache[provenance_key],
                        "source_currentness": currentness, "changed_inputs": changed,
                        "unavailable_inputs": unavailable})
    return {"repository": expected, "surface": source, "ref": ref, "revision": revision,
            "remote_freshness": "not_checked", "status": "observed" if reports else "no_structured_reviews",
            "reports": reports, "error": None}


def _occurrence_key(repo: str, review_id: str, finding_id: str) -> tuple[str, str, str]:
    return repo.lower(), review_id, finding_id


def triage(repositories: list[dict]) -> dict:
    """Build issue histories; clean later reviews do not close old findings.

    Only explicit predecessor links advance a disposition. Conflicting terminal
    heads and incomplete lineage remain visible, never resolved by latest time.
    """
    occurrences: dict[tuple, dict] = {}
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    review_ids = set()
    review_records = {}
    review_summaries = []
    diagnostics = []
    provenance_diagnostics = []
    repository_names = {}
    for repository in repositories:
        # Keep the first inventory spelling even across case-variant input groups.
        name = repository_names.setdefault(repository["repository"].lower(), repository["repository"])
        for report in repository.get("reports", []):
            review = report["record"]
            contract.validate_review(review)
            if repository["repository"].lower() != review["repository"].lower():
                raise contract.ReviewError("review identity disagrees with its inventory repository")
            review_key = (review["repository"].lower(), review["review_id"])
            if review_key in review_ids:
                raise contract.ReviewError(f"duplicate review identity: {review_key}")
            review_ids.add(review_key)
            review_records[review_key] = review
            provenance = report.get("source_provenance", {"status": "unverified", "reason": "not evaluated"})
            if provenance["status"] not in {"working_tree_attestation", "git_commit_verified"}:
                provenance_diagnostics.append({"repository": name,
                                               "review_id": review["review_id"], **provenance})
            review_summaries.append({
                "record": review,
                "repository": name,
                "source_provenance": provenance,
                **{key: review[key] for key in ("review_id", "kind", "finished_at",
                                                "completion", "verdict", "scientific_review", "scope")},
                **{key: report[key] for key in ("path", "sha256", "source_currentness",
                                                "changed_inputs", "unavailable_inputs")},
            })
            for finding in review["findings"]:
                key = _occurrence_key(review["repository"], review["review_id"], finding["finding_id"])
                occurrences[key] = {
                    "repository": name, "review_id": review["review_id"],
                    "finished_at": review["finished_at"], "path": report["path"],
                    "source_currentness": report["source_currentness"], "finding": finding,
                    "source_provenance": provenance,
                    "actions": [a for a in review["actions"] if finding["finding_id"] in a["finding_ids"]],
                }
                groups[(review["repository"].lower(), finding["issue_key"])].append(key)
    issues = []
    for (repo, issue_key), keys in sorted(groups.items()):
        children: dict[tuple, set] = defaultdict(set)
        parents: dict[tuple, set] = defaultdict(set)
        errors = []
        for key in keys:
            item = occurrences[key]
            candidates = set()
            invalid = False
            if item["source_provenance"]["status"] not in {"working_tree_attestation", "git_commit_verified"}:
                errors.append({"review_id": key[1], "finding_id": key[2],
                               "error": "source provenance " + item["source_provenance"]["status"]})
            for previous in item["finding"].get("previous_occurrences", []):
                predecessor = _occurrence_key(previous["repository"], previous["review_id"], previous["finding_id"])
                prior = occurrences.get(predecessor)
                error = None
                if item["source_provenance"]["status"] not in {"working_tree_attestation", "git_commit_verified"}:
                    error = "unverified successor provenance cannot supersede an occurrence"
                elif prior is None:
                    error = "previous occurrence is unavailable"
                elif prior["finding"]["issue_key"] != issue_key:
                    error = "previous occurrence has a different issue key"
                elif contract.timestamp(prior["finished_at"]) > contract.timestamp(item["finished_at"]):
                    error = "previous occurrence is chronologically later"
                elif not set(prior["finding"]["target_ids"]) <= set(item["finding"]["target_ids"]):
                    error = "superseding occurrence does not cover the previous affected targets"
                if error:
                    invalid = True
                    errors.append({"review_id": key[1], "finding_id": key[2], "error": error})
                else:
                    candidates.add(predecessor)
            if not invalid:
                parents[key].update(candidates)
                for predecessor in candidates:
                    children[predecessor].add(key)
        pending = {key: set(parents[key]) for key in keys}
        while pending:
            ready = {key for key, predecessors in pending.items() if not predecessors}
            if not ready:
                errors.append({"review_id": "multiple", "finding_id": "multiple", "error": "cyclic disposition lineage"})
                # A cycle makes supersession unreliable; preserve every observation's work.
                children.clear()
                break
            pending = {key: predecessors - ready for key, predecessors in pending.items() if key not in ready}
        heads = [occurrences[key] for key in keys if not children[key]]
        statuses = {item["finding"]["status"] for item in heads}
        if errors:
            status = "unverified_lineage"
        elif len(statuses) == 1:
            status = next(iter(statuses))
        elif statuses <= {"open", "deferred"}:
            status = "open"
        else:
            status = "conflicting_dispositions"
        if not heads:
            heads = [occurrences[key] for key in keys]
        severity = min((item["finding"]["severity"] for item in heads), key=SEVERITY_ORDER.__getitem__)
        history = sorted((occurrences[key] for key in keys),
                         key=lambda item: (contract.timestamp(item["finished_at"]), item["review_id"]))
        issues.append({"repository": repository_names[repo], "issue_key": issue_key,
                       "status": status, "severity": severity,
                       "title": history[-1]["finding"]["title"],
                       "categories": sorted({item["finding"]["category"] for item in heads}),
                       "target_ids": sorted({target for item in heads for target in item["finding"]["target_ids"]}),
                       "tags": sorted({tag for item in heads for tag in item["finding"].get("tags", [])}),
                       "head_source_states": sorted({item["source_currentness"] for item in heads}),
                       "heads": [{"review_id": item["review_id"], "finding_id": item["finding"]["finding_id"],
                                  "status": item["finding"]["status"], "source_currentness": item["source_currentness"],
                                  "source_provenance": item["source_provenance"]}
                                 for item in heads],
                       "occurrences": history, "lineage_errors": errors})
        diagnostics.extend({"repository": repository_names[repo], "issue_key": issue_key, **error} for error in errors)
    issues.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["repository"].lower(), item["issue_key"]))
    proposals = {}
    for issue in issues:
        if issue["status"] in TERMINAL:
            continue
        for head in issue["heads"]:
            record = review_records[(issue["repository"].lower(), head["review_id"])]
            by_id = {item["action_id"]: item for item in record["actions"]}
            pending = [item["action_id"] for item in record["actions"]
                       if head["finding_id"] in item["finding_ids"]]
            visited = set()
            while pending:
                action_id = pending.pop()
                if action_id in visited:
                    continue
                visited.add(action_id)
                action = by_id[action_id]
                key = (issue["repository"].lower(), head["review_id"], action_id)
                proposal = proposals.setdefault(key, {
                    "repository": issue["repository"], "review_id": head["review_id"],
                    "source_currentness": head["source_currentness"],
                    "for_issues": [], "action": action,
                    "execution_status": "not_established",
                })
                if issue["issue_key"] not in proposal["for_issues"]:
                    proposal["for_issues"].append(issue["issue_key"])
                pending.extend(action.get("depends_on", []))
    repository_rows = [{key: item[key] for key in ("repository", "surface", "ref", "revision", "remote_freshness", "status", "error")}
                       | {"repository": repository_names[item["repository"].lower()],
                          "review_count": len(item.get("reports", []))} for item in repositories]
    return {"format_version": 1, "repositories": repository_rows,
            "reviews": sorted(review_summaries, key=lambda r: (r["repository"].lower(), r["finished_at"], r["review_id"])),
            "issues": issues, "planning_inputs": [proposals[key] for key in sorted(proposals)],
            "lineage_diagnostics": diagnostics,
            "provenance_diagnostics": provenance_diagnostics,
            "counts": {"repositories": len(repositories), "reviews": len(review_ids),
                       "finding_occurrences": len(occurrences), "distinct_issues": len(issues),
                       "by_status": dict(sorted(Counter(i["status"] for i in issues).items())),
                       "by_severity": dict(sorted(Counter(i["severity"] for i in issues).items())),
                       "by_category": dict(sorted(Counter(c for i in issues for c in i["categories"]).items())),
                       "by_repository": dict(sorted(Counter(i["repository"] for i in issues).items()))},
            "limitations": [
                "Only schema-valid structured reviews are aggregated; legacy prose is not interpreted.",
                "A missing report or a later clean review does not resolve an earlier finding.",
                "Review verdicts apply to declared scopes; validation does not certify scientific truth.",
                "Remote freshness is not checked. Git references are local cached snapshots.",
                "Planning inputs are proposals from unresolved issue heads plus prerequisites; execution is not established.",
            ]}


def render_summary(report: dict, format: str) -> str:
    if format == "json":
        return json.dumps(report, indent=2, sort_keys=True) + "\n"
    headers = ["repository", "issue_key", "severity", "status", "title", "categories", "targets", "head_source_states"]
    rows = [[item["repository"], item["issue_key"], item["severity"], item["status"], item["title"],
             ", ".join(item["categories"]), ", ".join(item["target_ids"]),
             ("mixed: " if len(item["head_source_states"]) > 1 else "") + ", ".join(item["head_source_states"])]
            for item in report["issues"]]
    if format == "tsv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)
        return stream.getvalue()
    if format != "markdown":
        raise contract.ReviewError(f"unknown aggregate format: {format}")
    lines = ["# Fleet Record Review Triage", "", "## Inventory", ""]
    lines += contract._table(["Repository", "Surface", "Revision", "Status", "Reviews"], [
        [r["repository"], r["surface"], r["revision"], r["status"], r["review_count"]]
        for r in report["repositories"]])
    lines += ["", "## Issues", ""] + contract._table(headers, rows)
    lines += ["", "## Planning Inputs", "",
              "Proposed work and prerequisites, not evidence that any action was performed.", ""]
    lines += contract._table(["Repository / review / action", "Issues", "Proposed action", "Owners",
                              "Depends on", "Acceptance", "Source currentness"], [
        [f"{p['repository']} / {p['review_id']} / {p['action']['action_id']}",
         ", ".join(p["for_issues"]), p["action"]["description"],
         ", ".join(f"{o['repository']}:{o['path']}" for o in p["action"].get("owner_paths", []))
         or p["action"].get("ownership_note", ""),
         ", ".join(p["action"].get("depends_on", [])),
         "; ".join(p["action"]["acceptance_checks"]), p["source_currentness"]]
        for p in report["planning_inputs"]])
    lines += ["", "## Coverage And Limits", ""]
    lines += ["- " + contract._text(item) for item in report["limitations"]]
    for item in report["repositories"]:
        if item["error"]:
            lines += [f"- {contract._text(item['repository'])}: {contract._text(item['error'])}"]
    for item in report["lineage_diagnostics"]:
        lines += [f"- {contract._text(item['repository'])}/{contract._text(item['issue_key'])}: "
                  + contract._text(item["error"])]
    for item in report["provenance_diagnostics"]:
        lines += [f"- {contract._text(item['repository'])}/{contract._text(item['review_id'])}: "
                  f"provenance {contract._text(item['status'])}: {contract._text(item['reason'])}"]
    return "\n".join(lines) + "\n"
