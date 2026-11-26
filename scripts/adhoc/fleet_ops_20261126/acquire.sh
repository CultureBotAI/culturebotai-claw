#!/usr/bin/env bash
# Repository identity must come from the pinned manifest. Run from pinned CLAW.
set -euo pipefail
repo="$1"
out="$2"
python_bin="$3"
mkdir -p "$out"
date -u +%Y-%m-%dT%H:%M:%SZ > "$out/started-utc.txt"
PYTHONPATH=src "$python_bin" scripts/fleet_issue_status.py --all-issues --no-prs --repo "$repo" --json --markdown-file "$out/intake.md" --tsv-dir "$out" > "$out/intake.json"
gh repo view "$repo" --json nameWithOwner,url,defaultBranchRef > "$out/repository.json"
gh api --paginate --slurp "repos/$repo/issues?state=open&per_page=100" > "$out/issue-pages.json"
jq '[.[][] | select(has("pull_request") | not)]' "$out/issue-pages.json" > "$out/issues.json"
gh api --paginate --slurp "repos/$repo/pulls?state=open&per_page=100" > "$out/pr-pages.json"
jq 'add // []' "$out/pr-pages.json" > "$out/prs.json"
gh api graphql -f owner="${repo%%/*}" -f name="${repo#*/}" -f query='query($owner:String!,$name:String!){repository(owner:$owner,name:$name){nameWithOwner defaultBranchRef{name target{oid}} issues(states:OPEN){totalCount} pullRequests(states:OPEN){totalCount}}}' > "$out/counts.json"
jq -e '.data.repository != null and ((.errors // [])|length == 0)' "$out/counts.json" >/dev/null
jq -e --slurpfile c "$out/counts.json" 'length == (map(.number)|unique|length) and length == $c[0].data.repository.issues.totalCount' "$out/issues.json" >/dev/null
jq -e --slurpfile c "$out/counts.json" 'length == (map(.number)|unique|length) and length == $c[0].data.repository.pullRequests.totalCount' "$out/prs.json" >/dev/null
for n in $(jq -r '.[]|select(.comments>0)|.number' "$out/issues.json"); do
  gh api --paginate --slurp "repos/$repo/issues/$n/comments?per_page=100" > "$out/comments-$n-pages.json"
  jq 'add // []' "$out/comments-$n-pages.json" > "$out/comments-$n.json"
  expected=$(jq --argjson n "$n" '.[]|select(.number==$n)|.comments' "$out/issues.json")
  jq -e --argjson count "$expected" 'length == $count and length == (map(.id)|unique|length)' "$out/comments-$n.json" >/dev/null
done
date -u +%Y-%m-%dT%H:%M:%SZ > "$out/finished-utc.txt"
