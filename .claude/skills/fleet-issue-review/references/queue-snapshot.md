# Complete queue snapshots

Use explicit identities from the saved fleet inventory. This example collects
one repository into a fresh directory; run it separately for every selected
repository. Failed collections stay visible in fleet coverage while independent
repositories continue. Commands require `gh`, `jq`, and Bash.

Set `review_repo` to an exact selected `owner/repository`, and `review_dir` to a
new directory for that repository before running this block. Do not reuse a
previous snapshot after a failed request.

```bash
set -euo pipefail
test -n "$review_repo"
test -d "$review_dir"
date -u +%Y-%m-%dT%H:%M:%SZ > "$review_dir/started-utc.txt"
gh repo view "$review_repo" --json nameWithOwner,url,defaultBranchRef \
  > "$review_dir/repository.json"
gh api --method GET --paginate --slurp \
  "repos/$review_repo/issues?state=open&per_page=100" \
  > "$review_dir/issue-pages.json"
jq '[.[][] | select(has("pull_request") | not)]' \
  "$review_dir/issue-pages.json" > "$review_dir/issues.json"
gh api --method GET --paginate --slurp \
  "repos/$review_repo/pulls?state=open&per_page=100" \
  > "$review_dir/pr-pages.json"
jq 'add // []' "$review_dir/pr-pages.json" > "$review_dir/prs.json"

review_owner="${review_repo%%/*}"
review_name="${review_repo#*/}"
gh api graphql -f owner="$review_owner" -f name="$review_name" -f query='
  query($owner:String!, $name:String!) {
    repository(owner:$owner, name:$name) {
      nameWithOwner
      defaultBranchRef { name target { oid } }
      issues(states:OPEN) { totalCount }
      pullRequests(states:OPEN) { totalCount }
    }
  }' > "$review_dir/counts.json"
jq -e '.data.repository != null and ((.errors // []) | length == 0)' \
  "$review_dir/counts.json" > /dev/null

for issue_number in $(jq -r '.[].number' "$review_dir/issues.json"); do
  gh api --method GET --paginate --slurp \
    "repos/$review_repo/issues/$issue_number/comments?per_page=100" \
    > "$review_dir/comments-$issue_number-pages.json"
  jq 'add // []' "$review_dir/comments-$issue_number-pages.json" \
    > "$review_dir/comments-$issue_number.json"
done
date -u +%Y-%m-%dT%H:%M:%SZ > "$review_dir/finished-utc.txt"
```

Take the default branch and SHA from `counts.json`'s `defaultBranchRef`; do not
infer that every repository uses `main`. A null branch needs an explicit finding.
The REST issues endpoint includes PRs, which the filter deliberately removes.
The PR snapshot includes drafts and head/base SHAs for overlap and dependency
checks. Fetch additional PR details and paginate changed-file lists where a
verdict needs them; avoid a deep review of every PR during issue triage.

Before declaring collection complete, verify:

- No API command failed; no GraphQL `errors` or inaccessible repository data.
- Both API identities match the selected identity, allowing GitHub's case
  normalization; investigate renames instead of silently changing fleet scope.
- Unique issue numbers equal both the issue array length and independent
  `issues.totalCount`; do the analogous check for PRs and `pullRequests.totalCount`.
- Each comment file contains unique comment IDs and its count matches the
  corresponding issue's `comments` field. Read every page, not a capped nested
  comments connection from `gh issue list`.

Reconcile count mismatches with another metadata/queue fetch: an issue can close
or acquire comments during acquisition. Matching counts alone do not establish
a stable snapshot; compare identities, `updated_at`, and body/comment contents.
At final refresh, retain the initial evidence and save a fresh snapshot, including
all comment pages, so edited comments with unchanged counts are detected. For
issues that left the open set, fetch their current state and comments explicitly.
Track added, closed, reopened, and changed issues in coverage; do not drop them.

Retain stdout artifacts and error/exit information separately. A partly written
JSON file or a failed request is an evidence gap, never an empty successful queue.
Do not print credentials or authenticated remote URLs into review artifacts.
