"""Read-only claw PR capture; 2026-11-15, issues 1230/1264.

Input: public GitHub API through gh. Output: a NEW private durable directory
with raw metadata and explicit acquisition agreement/drift. No remote writes.
This bounded helper refuses more than 100 PRs; it never claims an atomic snapshot.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

REPO = "CultureBotAI/culturebotai-claw"
FIELDS = ("number,title,isDraft,headRefOid,headRefName,baseRefOid,baseRefName,"
          "updatedAt,createdAt,mergeable,mergeStateStatus,reviewDecision,"
          "autoMergeRequest,statusCheckRollup")
QUERY = '''query { repository(owner:"CultureBotAI", name:"culturebotai-claw") {
 nameWithOwner defaultBranchRef { target { oid } }
 pullRequests(states:OPEN, first:100) { totalCount pageInfo { hasNextPage endCursor }
 nodes { number headRefOid baseRefOid isDraft reviewDecision
 mergeQueueEntry { position state } autoMergeRequest { enabledAt mergeMethod } } } } }'''


def gh(args):
    return json.loads(subprocess.check_output(["gh", *args], text=True, timeout=90))


def identities(rows, *, rest=False):
    if not isinstance(rows, list):
        raise ValueError("inventory must be a list")
    result = {}
    for row in rows:
        number = row["number"]
        if type(number) is not int or number <= 0 or number in result:
            raise ValueError("inventory contains invalid or repeated PR identities")
        head = row["head"]["sha"] if rest else row["headRefOid"]
        base = row["base"]["sha"] if rest else row["baseRefOid"]
        draft = row["draft"] if rest else row["isDraft"]
        if (not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head)
                or not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base)
                or type(draft) is not bool):
            raise ValueError("inventory contains malformed head/base/draft facts")
        result[number] = (head, base, draft)
    return result


def acquisition_agreement(before, checks, graph, after, main, main_after):
    """Validate every collection used by the report, not only one count."""
    repository = graph["data"]["repository"]
    connection = repository["pullRequests"]
    total = connection["totalCount"]
    if (graph.get("errors") or repository.get("nameWithOwner") != REPO
            or type(total) is not int or not 0 <= total <= 100
            or connection["pageInfo"]["hasNextPage"] is not False):
        raise ValueError("independent inventory is partial, foreign or over the safe bound")
    collections = {"rest_before": identities(before, rest=True),
                   "check_rows": identities(checks),
                   "graphql": identities(connection["nodes"]),
                   "rest_after": identities(after, rest=True)}
    reference = collections["rest_before"]
    if any(len(rows) != total or rows != reference for rows in collections.values()):
        raise ValueError("PR identity/head/base/draft acquisition drift across inventories")
    if main != main_after or repository["defaultBranchRef"]["target"]["oid"] != main:
        raise ValueError("main changed during inventory acquisition")
    return {"complete": True, "acquisition_agreement": True,
            "rest_count": total, "checks_count": len(checks), "graphql_total": total,
            "graphql_has_next_page": False, "unique_numbers": sorted(reference),
            "after_numbers": sorted(collections["rest_after"])}


def capture(root):
    root = Path(root).absolute()
    if root.exists() or root.is_symlink():
        raise ValueError("capture requires a new output directory")
    root.mkdir(parents=True, exist_ok=False)

    def save(name, data):
        with (root / name).open("x") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")

    def pages(endpoint, name):
        result = gh(["api", "--method", "GET", "--paginate", "--slurp", endpoint])
        if not isinstance(result, list) or any(not isinstance(page, list) for page in result):
            raise ValueError("malformed paginated REST response")
        save(name + "-pages.json", result)
        return [row for page in result for row in page]

    def per_pr(pr):
        number = pr["number"]
        result = {"detail": gh(["api", f"repos/{REPO}/pulls/{number}"])}
        for name, endpoint in {
            "comments": f"repos/{REPO}/issues/{number}/comments?per_page=100",
            "reviews": f"repos/{REPO}/pulls/{number}/reviews?per_page=100",
            "review-comments": f"repos/{REPO}/pulls/{number}/comments?per_page=100",
            "files": f"repos/{REPO}/pulls/{number}/files?per_page=100",
        }.items():
            result[name] = pages(endpoint, f"pr-{number}-{name}")
        save(f"pr-{number}.json", result)

    summary = {"started_at": datetime.now(timezone.utc).isoformat(),
               "repository": REPO, "complete": False, "acquisition_agreement": False}
    try:
        main = gh(["api", f"repos/{REPO}/commits/main"])
        save("main-before.json", {"sha": main["sha"], "tree": main["commit"]["tree"]["sha"]})
        rows = pages(f"repos/{REPO}/pulls?state=open&per_page=100", "open-pulls-before")
        identities(rows, rest=True)
        checks = gh(["pr", "list", "--repo", REPO, "--state", "open", "--limit", "500", "--json", FIELDS])
        save("pr-checks-before.json", checks)
        graph = gh(["api", "graphql", "-f", "query=" + QUERY])
        save("independent-open-count-and-queue.json", graph)
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(per_pr, rows))
        for number in (1230, 1248, 849):
            issue = gh(["api", f"repos/{REPO}/issues/{number}"])
            issue["all_comments"] = pages(f"repos/{REPO}/issues/{number}/comments?per_page=100", f"issue-{number}-comments")
            save(f"issue-{number}.json", issue)
        after = pages(f"repos/{REPO}/pulls?state=open&per_page=100", "open-pulls-after")
        latest = gh(["api", f"repos/{REPO}/commits/main"])
        save("main-after.json", {"sha": latest["sha"], "tree": latest["commit"]["tree"]["sha"]})
        summary.update(main=main["sha"], main_after=latest["sha"])
        summary.update(acquisition_agreement(rows, checks, graph, after, main["sha"], latest["sha"]))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        summary["acquisition_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        save("snapshot-summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(capture(args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
