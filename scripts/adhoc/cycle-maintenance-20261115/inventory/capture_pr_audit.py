"""Read-only claw PR maintenance snapshot; 2026-11-15. Writes local audit evidence only.
Inputs: public CultureBotAI/culturebotai-claw GitHub API via authenticated gh.
Outputs: paginated raw metadata plus a compact inventory. No GitHub/Git writes.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir", type=Path, required=True,
                    help="Private durable evidence directory; raw metadata may contain author identities")
ROOT = parser.parse_args().output_dir.resolve()
ROOT.mkdir(parents=True, exist_ok=True)
REPO = "CultureBotAI/culturebotai-claw"

def gh(args):
    return json.loads(subprocess.check_output(["gh", *args], text=True))

def save(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2) + "\n")

def get_pages(endpoint, name):
    pages = gh(["api", "--method", "GET", "--paginate", "--slurp", endpoint])
    save(name + "-pages.json", pages)
    return [row for page in pages for row in page]

def per_pr(pr):
    n = pr["number"]
    result = {"detail": gh(["api", f"repos/{REPO}/pulls/{n}"])}
    for name, endpoint in {
        "comments": f"repos/{REPO}/issues/{n}/comments?per_page=100",
        "reviews": f"repos/{REPO}/pulls/{n}/reviews?per_page=100",
        "review-comments": f"repos/{REPO}/pulls/{n}/comments?per_page=100",
        "files": f"repos/{REPO}/pulls/{n}/files?per_page=100",
    }.items():
        result[name] = get_pages(endpoint, f"pr-{n}-{name}")
    save(f"pr-{n}.json", result)
    return result

started = datetime.now(timezone.utc).isoformat()
main = gh(["api", f"repos/{REPO}/commits/main"])
save("main-before.json", {"sha": main["sha"], "tree": main["commit"]["tree"]["sha"]})
rows = get_pages(f"repos/{REPO}/pulls?state=open&per_page=100", "open-pulls-before")
fields = "number,title,isDraft,headRefOid,headRefName,baseRefOid,baseRefName,updatedAt,createdAt,mergeable,mergeStateStatus,reviewDecision,autoMergeRequest,statusCheckRollup"
checks = gh(["pr", "list", "--repo", REPO, "--state", "open", "--limit", "500", "--json", fields])
save("pr-checks-before.json", checks)
query = 'query { repository(owner:"CultureBotAI", name:"culturebotai-claw") { defaultBranchRef { target { oid } } pullRequests(states:OPEN, first:100) { totalCount pageInfo { hasNextPage endCursor } nodes { number headRefOid baseRefOid isDraft reviewDecision mergeQueueEntry { position state } autoMergeRequest { enabledAt mergeMethod } } } } }'
graph = gh(["api", "graphql", "-f", "query=" + query])
save("independent-open-count-and-queue.json", graph)
with ThreadPoolExecutor(max_workers=5) as pool:
    results = list(pool.map(per_pr, rows))
for n in (1230, 1248, 849):
    issue = gh(["api", f"repos/{REPO}/issues/{n}"])
    issue["all_comments"] = get_pages(f"repos/{REPO}/issues/{n}/comments?per_page=100", f"issue-{n}-comments")
    save(f"issue-{n}.json", issue)
after = get_pages(f"repos/{REPO}/pulls?state=open&per_page=100", "open-pulls-after")
main_after = gh(["api", f"repos/{REPO}/commits/main"])
save("main-after.json", {"sha": main_after["sha"], "tree": main_after["commit"]["tree"]["sha"]})
count = graph["data"]["repository"]["pullRequests"]
summary = {"started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(), "repository": REPO, "main": main["sha"], "main_after": main_after["sha"], "rest_count": len(rows), "graphql_total": count["totalCount"], "graphql_has_next_page": count["pageInfo"]["hasNextPage"], "unique_numbers": sorted({p["number"] for p in rows}), "after_numbers": sorted({p["number"] for p in after})}
assert len(rows) == len({p["number"] for p in rows}) == count["totalCount"]
assert not count["pageInfo"]["hasNextPage"]
save("snapshot-summary.json", summary)
print(json.dumps(summary))
