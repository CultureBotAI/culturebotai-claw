#!/usr/bin/env python3
"""Report open issues and open PRs per repository across claw and the Mechs.

    python scripts/fleet_issue_status.py [--json | --markdown] [--all-issues]
                                         [--repo OWNER/REPO] [--triage-file FILE]
                                         [--markdown-file FILE] [--no-prs]

`fleet_pr_status.py` lists every open PR. This report is the other half of
"where does the fleet stand?": one row per repository with its open-issue
count, how many are unassigned, how many have gone quiet, the age of the
oldest, and the open-PR count beside it, sorted by largest issue queue first.
Review annotations are recommendations, separate from GitHub labels and state.
The datestamped TSV, JSON issue_rows and Markdown ledger carry every issue.

It keeps the same denominator discipline as the PR report, because the same
three traps apply: `gh issue list` truncates silently (30 by default), a repo
whose query fails vanishes from a hand-rolled loop, and filesystem discovery
misses any Mech not cloned. Membership comes from the fleet manifest and
nothing else; every repository appears in the coverage line even with nothing
open; a failed query is named and the totals become a lower bound.

Note that GitHub's `open_issues_count` on the repository object counts pull
requests too. This report uses `gh issue list`, which does not, so its numbers
are smaller than the badge on the repository page and are the ones that mean
"issues".

Exit codes: 0 complete report produced, 1 one or more repositories could not
be queried or a listing reached its limit, and 2 bad usage or `gh` unavailable.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fcntl  # noqa: F401 - re-exported for lock-contract tests
import html
import json
import os  # noqa: F401 - re-exported for lock-contract tests
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fleet_common import (  # noqa: E402
    CONTROL_PLANE_REPOSITORY,  # noqa: F401
    DEFAULT_TSV_DIR,
    GhError,
    _cell,
    _gh,
    _listing,
    fleet_repository_identities,
    snapshot_lock_for,
    snapshot_lock_path_for,
    tsv_path_for,
    write_snapshot_tsv,
)

from kg_microbe_fleet import FleetManifest, FleetManifestError  # noqa: E402

ISSUE_FIELDS = "number,title,labels,assignees,author,milestone,createdAt,updatedAt,url"
PR_FIELDS = "number,isDraft,mergeable"

#: TSV columns. Fixed and ordered, so snapshots from different days diff and
#: concatenate cleanly; append new columns at the end rather than inserting.
TSV_COLUMNS = (
    "snapshot_utc", "repo", "number", "url", "title", "labels", "assignees",
    "author", "milestone", "created_at", "updated_at", "age_days",
    "days_since_update",
    "issue_key", "review_priority", "review_action", "review_reason",
    "review_evidence", "defer_until",
)

REVIEW_DEFAULTS = {
    "review_priority": "Unranked", "review_action": "unreviewed",
    "review_reason": "", "review_evidence": "", "defer_until": "",
}


def all_open_issues(repository: str) -> list[dict]:
    """Paginate REST, exclude PRs, and check unique membership against GraphQL.

    A moving queue fails this check visibly; rerun rather than reporting a
    partial acquisition as complete. Counts do not freeze changing issue text.
    """
    pages = json.loads(_gh([
        "api", "--method", "GET", "--paginate", "--slurp",
        f"repos/{repository}/issues?state=open&per_page=100",
    ], timeout=180))
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise GhError("invalid paginated issue response")
    items = [item for page in pages for item in page if "pull_request" not in item]
    owner, name = repository.split("/", 1)
    count = json.loads(_gh([
        "api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}",
        "-f", "query=query($owner:String!, $name:String!) { "
        "repository(owner:$owner, name:$name) { nameWithOwner issues(states:OPEN) { totalCount } } }",
    ]))
    remote = (count.get("data") or {}).get("repository")
    if count.get("errors") or not isinstance(remote, dict):
        raise GhError("independent issue count unavailable")
    if remote.get("nameWithOwner", "").casefold() != repository.casefold():
        raise GhError("independent issue count repository identity mismatch")
    expected = (remote.get("issues") or {}).get("totalCount")
    numbers = [item["number"] for item in items]
    if type(expected) is not int or len(set(numbers)) != len(items) or len(items) != expected:
        raise GhError(f"issue coverage mismatch: fetched {len(items)}, unique {len(set(numbers))}, expected {expected}")
    return sorted([{
        "number": item["number"], "title": item["title"],
        "labels": item.get("labels", []), "assignees": item.get("assignees", []),
        "author": item.get("user"), "milestone": item.get("milestone"),
        "createdAt": item["created_at"], "updatedAt": item["updated_at"],
        "url": item["html_url"],
    } for item in items], key=lambda item: -item["number"])


def open_issues(repository: str, issue_limit: int) -> tuple[list[dict], bool]:
    return _listing("issue", repository, ISSUE_FIELDS, issue_limit, gh=_gh)


def open_prs(repository: str, pr_limit: int) -> tuple[list[dict], bool]:
    return _listing("pr", repository, PR_FIELDS, pr_limit, gh=_gh)


def collect(
    issue_limit: int,
    pr_limit: int,
    include_prs: bool = True,
    manifest: FleetManifest | None = None,
    *,
    all_issues: bool = False,
    selected_repositories: list[str] | None = None,
) -> dict:
    """Query the exact manifest fleet and record every per-repo failure.

    A repository whose issue query fails is not queried for PRs either: half a
    row would read as a whole one. It goes to `errors` and out of every total.
    With `include_prs=False` the `prs` mapping stays empty rather than holding
    an empty list per repository, which `--json` would print as zero open PRs.
    """

    identities = fleet_repository_identities(manifest)
    if selected_repositories is not None:
        unknown = set(selected_repositories) - set(identities)
        if unknown:
            raise ValueError("repositories outside manifest plus claw: " + ", ".join(sorted(unknown)))
        identities = tuple(identity for identity in identities if identity in selected_repositories)
    repositories = [identity.rsplit("/", 1)[-1] for identity in identities]
    owners = {identity.split("/", 1)[0] for identity in identities}
    result: dict = {
        "org": next(iter(owners)) if len(owners) == 1 else "manifest-defined",
        "repository_identities": dict(zip(repositories, identities)),
        "repos_queried": repositories,
        "issue_limit": issue_limit,
        "pr_limit": pr_limit,
        "include_prs": include_prs,
        "all_issues": all_issues,
        "issue_listing_truncated": [],
        "pr_listing_truncated": [],
        "issues": {},
        "prs": {},
        "errors": {},
    }
    failures = (GhError, subprocess.TimeoutExpired, json.JSONDecodeError,
                KeyError, TypeError, AttributeError)
    for repo, identity in zip(repositories, identities):
        try:
            if all_issues:
                issues, truncated = all_open_issues(identity), False
            else:
                issues, truncated = open_issues(identity, issue_limit)
        except failures as exc:
            result["errors"][repo] = f"issues: {str(exc)[:200]}"
            continue
        prs: list[dict] = []
        prs_truncated = False
        if include_prs:
            try:
                prs, prs_truncated = open_prs(identity, pr_limit)
            except failures as exc:
                result["errors"][repo] = f"prs: {str(exc)[:200]}"
                continue
        result["issues"][repo] = issues
        if include_prs:
            # Never store a plausible zero for a query that was not made.
            result["prs"][repo] = prs
        if truncated:
            result["issue_listing_truncated"].append(repo)
        if prs_truncated:
            result["pr_listing_truncated"].append(repo)
    return result


def snapshot_is_complete(data: dict) -> bool:
    """True when every fleet repo was queried and nothing hit a limit."""
    return not (
        data["errors"]
        or data["issue_listing_truncated"]
        or data["pr_listing_truncated"]
    )


def _parse_time(value: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _days_between(earlier: str, now: _dt.datetime) -> int:
    # Clamped: a timestamp after `now` (clock skew between GitHub and the
    # caller) must not render as a negative age.
    return max(0, (now - _parse_time(earlier)).days)


def summarize(issues: list[dict], now: _dt.datetime, stale_days: int) -> dict:
    """Per-repository counts, computed against the passed `now` and never the
    wall clock, so a snapshot summarises the same way whenever it is read."""

    unassigned = sum(1 for issue in issues if not issue.get("assignees"))
    stale = sum(
        1 for issue in issues
        if _days_between(issue["updatedAt"], now) >= stale_days
    )
    oldest = max(
        (_days_between(issue["createdAt"], now) for issue in issues),
        default=None,
    )
    return {
        "open": len(issues),
        "unassigned": unassigned,
        "stale": stale,
        "oldest_age_days": oldest,
    }


def _pr_summary(prs: list[dict]) -> dict:
    return {
        "open": len(prs),
        "conflicts": sum(1 for pr in prs if pr.get("mergeable") == "CONFLICTING"),
        "drafts": sum(1 for pr in prs if pr.get("isDraft")),
    }


def ranked_repositories(data: dict) -> list[str]:
    """Largest queue first; stable manifest ties; failed acquisitions last."""
    return sorted(data["repos_queried"], key=lambda repo: (
        repo in data["errors"], -len(data["issues"].get(repo, [])),
    ))


def issue_key(data: dict, repo: str, issue: dict) -> str:
    return f"{data['repository_identities'][repo]}#{issue['number']}"


def review_for(data: dict, repo: str, issue: dict) -> dict:
    return {**REVIEW_DEFAULTS, **data.get("triage", {}).get(issue_key(data, repo, issue), {})}


def load_triage(path: Path, data: dict) -> dict:
    """Validate report annotations; no label, closure or other GitHub writes."""
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate triage key: {key}")
            obj[key] = value
        return obj

    annotations = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(annotations, dict):
        raise ValueError("triage file must be an object keyed by owner/repository#number")
    current = {issue_key(data, repo, issue): issue for repo in data["repos_queried"]
               for issue in data["issues"].get(repo, [])}
    for key, value in annotations.items():
        if key not in current:
            raise ValueError(f"triage issue not in fetched open set: {key}")
        if not isinstance(value, dict) or set(value) - (set(REVIEW_DEFAULTS) | {"updated_at"}):
            raise ValueError(f"invalid triage fields: {key}")
        if value.get("updated_at") != current[key]["updatedAt"]:
            raise ValueError(f"stale triage updated_at: {key}")
        if value.get("review_priority") not in ("P0", "P1", "P2", "P3", "Unranked"):
            raise ValueError(f"invalid review_priority: {key}")
        if value.get("review_action") not in ("keep", "close", "defer"):
            raise ValueError(f"invalid review_action: {key}")
        if any(not isinstance(value.get(field), str) or not value[field].strip()
               for field in ("review_reason", "review_evidence")):
            raise ValueError(f"review_reason and review_evidence required: {key}")
        if not isinstance(value.get("defer_until", ""), str):
            raise ValueError(f"defer_until must be text: {key}")
        if value["review_action"] == "defer" and not value.get("defer_until", "").strip():
            raise ValueError(f"defer needs a revisit date or trigger in defer_until: {key}")
        if value["review_action"] != "defer" and value.get("defer_until"):
            raise ValueError(f"defer_until only applies to defer: {key}")
        if value["review_action"] == "close" and value["review_priority"] != "Unranked":
            raise ValueError(f"close candidates have no remaining priority; use Unranked: {key}")
    return {key: {field: value.get(field, default) for field, default in REVIEW_DEFAULTS.items()}
            for key, value in annotations.items()}


def repository_summary(data: dict, snapshot_utc: str, stale_days: int) -> list[dict]:
    rows = []
    for repo in ranked_repositories(data):
        row = {"repo": repo, "repository": data["repository_identities"][repo]}
        if repo in data["errors"]:
            row.update(status="error", error=data["errors"][repo], open=None,
                       reviewed=None, unreviewed=None, keep=None, close=None, defer=None)
        else:
            issues = data["issues"][repo]
            row.update(summarize(issues, _parse_time(snapshot_utc), stale_days))
            actions = [review_for(data, repo, issue)["review_action"] for issue in issues]
            row.update({action: actions.count(action) for action in ("unreviewed", "keep", "close", "defer")})
            row["reviewed"] = len(issues) - row["unreviewed"]
            row["status"] = "partial" if repo in data["issue_listing_truncated"] or repo in data["pr_listing_truncated"] else "complete"
            if data.get("include_prs", True):
                row["prs"] = _pr_summary(data["prs"][repo])
        rows.append(row)
    return rows


def issue_rows(data: dict, snapshot_utc: str) -> list[dict]:
    """Raw report rows, ordered by repository backlog, then issue number."""

    now = _parse_time(snapshot_utc)
    rows = []
    for repo in ranked_repositories(data):
        for issue in sorted(data["issues"].get(repo, []), key=lambda item: -item["number"]):
            rows.append({
                "snapshot_utc": snapshot_utc,
                "repo": repo,
                "number": issue["number"],
                "url": issue.get("url", ""),
                "title": issue.get("title") or "",
                "labels": ",".join(
                    label.get("name", "") for label in issue.get("labels") or []
                ),
                "assignees": ",".join(
                    person.get("login", "") for person in issue.get("assignees") or []
                ),
                "author": (issue.get("author") or {}).get("login", ""),
                "milestone": (issue.get("milestone") or {}).get("title", "") or "",
                "created_at": issue.get("createdAt", ""),
                "updated_at": issue.get("updatedAt", ""),
                "age_days": _days_between(issue["createdAt"], now),
                "days_since_update": _days_between(issue["updatedAt"], now),
                "issue_key": issue_key(data, repo, issue),
                **review_for(data, repo, issue),
            })
    return rows


def tsv_rows(data: dict, snapshot_utc: str) -> list[dict]:
    return [{key: _cell(value) for key, value in row.items()}
            for row in issue_rows(data, snapshot_utc)]


def tsv_path(out_dir: Path, snapshot_utc: str, complete: bool) -> Path:
    """Datestamped, and marked `.partial` when coverage was incomplete, so the
    fact travels with the file after the console warning is gone."""
    return tsv_path_for("fleet_issue_status", out_dir, snapshot_utc, complete)


def _snapshot_lock_path(out_dir: Path, snapshot_utc: str) -> Path:
    """One persistent lock inode shared by both completeness variants."""
    return snapshot_lock_path_for("fleet_issue_status", out_dir, snapshot_utc)


def _snapshot_lock(out_dir: Path, snapshot_utc: str) -> Iterator[None]:
    """Lock one date without following or replacing the stable lock inode."""
    return snapshot_lock_for("fleet_issue_status", out_dir, snapshot_utc)


def write_tsv(data: dict, out_dir: Path, snapshot_utc: str) -> Path:
    return write_snapshot_tsv(
        "fleet_issue_status",
        TSV_COLUMNS,
        tsv_rows(data, snapshot_utc),
        out_dir,
        snapshot_utc,
        snapshot_is_complete(data),
    )


def render(data: dict, snapshot_utc: str, stale_days: int) -> str:
    now = _parse_time(snapshot_utc)
    include_prs = data.get("include_prs", True)
    lines: list[str] = []
    total_issues = 0
    total_prs = 0

    header = (
        f"{'REPO':<21} {'ISSUES':>6} {'UNASSIGNED':>10} {'STALE ' + str(stale_days) + 'd+':>10} "
        f"{'OLDEST':>7}"
    )
    if include_prs:
        header += f" {'PRs':>4} {'CONFLICTS':>9} {'DRAFTS':>6}"
    header += " REVIEWED UNREVIEWED KEEP CLOSE DEFER"
    rows: list[str] = []
    summaries = {row["repo"]: row for row in repository_summary(data, snapshot_utc, stale_days)}
    for repo in ranked_repositories(data):
        if repo in data["errors"]:
            row = f"{repo:<21} {'?':>6} {'?':>10} {'?':>10} {'?':>7}"
            if include_prs:
                row += f" {'?':>4} {'?':>9} {'?':>6}"
            rows.append(row + "        ?          ?    ?     ?     ?  NOT QUERIED")
            continue
        issues = summarize(data["issues"].get(repo, []), now, stale_days)
        total_issues += issues["open"]
        oldest = "" if issues["oldest_age_days"] is None else f"{issues['oldest_age_days']}d"
        row = (
            f"{repo:<21} {issues['open']:>6} {issues['unassigned']:>10} "
            f"{issues['stale']:>10} {oldest:>7}"
        )
        if include_prs:
            prs = _pr_summary(data["prs"].get(repo, []))
            total_prs += prs["open"]
            row += f" {prs['open']:>4} {prs['conflicts']:>9} {prs['drafts']:>6}"
        summary = summaries[repo]
        row += (f" {summary['reviewed']:>8} {summary['unreviewed']:>10}"
                f" {summary['keep']:>4} {summary['close']:>5} {summary['defer']:>5}")
        rows.append(row)

    headline = f"Open issues across the {data['org']} fleet: {total_issues}"
    if include_prs:
        headline += f"; open PRs: {total_prs}"
    lines.append(headline)
    lines.append("")
    lines.append(header)
    lines.extend(rows)

    lines.append("")
    lines.append("Coverage")
    per_repo = ", ".join(
        f"{r}={len(data['issues'].get(r, []))}"
        for r in data["repos_queried"]
        if r not in data["errors"]
    )
    lines.append(f"  queried {len(data['repos_queried'])} repos: {per_repo}")
    lines.append(
        f"  stale = no update in {stale_days}+ days as of {snapshot_utc}; "
        "issue counts exclude pull requests"
    )
    lines.append("  review actions are recommendations only; counts do not assign priority")
    if data["issue_listing_truncated"]:
        lines.append(
            f"  WARNING: issue listing reached --issue-limit ({data['issue_limit']}) in "
            + ", ".join(data["issue_listing_truncated"])
            + "; those counts are truncated. Re-run with a higher --issue-limit."
        )
    if data["pr_listing_truncated"]:
        lines.append(
            f"  WARNING: PR listing reached --pr-limit ({data['pr_limit']}) in "
            + ", ".join(data["pr_listing_truncated"])
            + "; those counts are truncated. Re-run with a higher --pr-limit."
        )
    for repo, err in data["errors"].items():
        lines.append(f"  ERROR {repo}: NOT QUERIED — {err}")
    if data["errors"]:
        lines.append(
            "  ^ the totals above EXCLUDE those repos; they are lower bounds."
        )
    return "\n".join(lines)


def _markdown_cell(value: object) -> str:
    text = " ".join(str(value if value is not None else "?").split())
    text = html.escape(text, quote=False).replace("\\", "&#92;")
    for character, entity in (("|", "&#124;"), ("`", "&#96;"), ("[", "&#91;"),
                              ("]", "&#93;"), ("*", "&#42;"), ("_", "&#95;")):
        text = text.replace(character, entity)
    return text


def render_markdown(data: dict, snapshot_utc: str, stale_days: int) -> str:
    summaries = repository_summary(data, snapshot_utc, stale_days)
    fields = ["repo", "open", "unassigned", "stale", "oldest_age_days"]
    headings = ["Repository", "Open issues", "Unassigned", f"Stale {stale_days}d+", "Oldest (days)"]
    if data.get("include_prs", True):
        fields.extend(["pr_open", "pr_conflicts", "pr_drafts"])
        headings.extend(["PRs", "Conflicts", "Drafts"])
    fields.extend(["reviewed", "unreviewed", "keep", "close", "defer", "status"])
    headings.extend(["Reviewed", "Unreviewed", "Keep", "Close", "Defer", "Coverage"])
    lines = ["# Fleet issue review intake", "", f"Snapshot: {snapshot_utc}", "",
             "Repositories sorted by open-issue count, most to least. Review actions are recommendations.", "",
             "| " + " | ".join(headings) + " |",
             "|" + "|".join("---" if field in {"repo", "status"} else "---:" for field in fields) + "|"]
    for row in summaries:
        values = {**row, **{f"pr_{key}": value for key, value in row.get("prs", {}).items()}}
        if row["status"] != "error" and row["oldest_age_days"] is None:
            values["oldest_age_days"] = ""
        lines.append("| " + " | ".join(_markdown_cell(values.get(field)) for field in fields) + " |")
    lines.extend(["", "## Issue ledger", "",
                  "| Issue | Title | Labels | Priority | Action | Reason | Evidence | Revisit date / trigger |",
                  "|---|---|---|---|---|---|---|---|"])
    for row in issue_rows(data, snapshot_utc):
        # Construct links from validated scope and numeric issue identity, never issue prose.
        identity, number = row["issue_key"].rsplit("#", 1)
        link = f"[{_markdown_cell(row['issue_key'])}](https://github.com/{identity}/issues/{number})"
        values = [row[field] for field in ("title", "labels", "review_priority", "review_action",
                                          "review_reason", "review_evidence", "defer_until")]
        lines.append("| " + link + " | " + " | ".join(_markdown_cell(value) for value in values) + " |")
    coverage = render(data, snapshot_utc, stale_days).split("\nCoverage\n", 1)[1]
    lines.extend(["", "## Coverage", ""])
    lines.extend(_markdown_cell(line) + "  " for line in coverage.splitlines())
    return "\n".join(lines)


def write_markdown(data: dict, path: Path, snapshot_utc: str, stale_days: int) -> None:
    """Atomically save the same acquisition rendered to stdout and TSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(render_markdown(data, snapshot_utc, stale_days) + "\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleet_issue_status")
    ap.add_argument("--issue-limit", type=int, default=500,
                    help="cap on open issues listed per repo; gh defaults to "
                         "30 and truncates silently")
    ap.add_argument("--pr-limit", type=int, default=200,
                    help="cap on open PRs counted per repo")
    ap.add_argument("--stale-days", type=int, default=60,
                    help="an issue with no update in this many days is stale")
    ap.add_argument("--no-prs", action="store_false", dest="include_prs",
                    help="issues only; skip the PR columns and queries")
    output = ap.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", dest="as_json")
    output.add_argument("--markdown", action="store_true", help="print summary and full issue ledger as Markdown")
    ap.add_argument("--all-issues", action="store_true", help="paginate all issues and verify an independent count")
    ap.add_argument("--repo", action="append", help="exact manifest or claw owner/repository; repeat for a subset")
    ap.add_argument("--triage-file", type=Path, help="JSON review annotations keyed by owner/repository#number")
    ap.add_argument("--markdown-file", type=Path, help="also save Markdown from this same acquisition")
    ap.add_argument("--tsv-dir", type=Path, default=DEFAULT_TSV_DIR,
                    help=f"where the datestamped TSV lands (default {DEFAULT_TSV_DIR})")
    ap.add_argument("--no-tsv", action="store_true",
                    help="print the table only; write no snapshot file")
    args = ap.parse_args(argv)

    if args.issue_limit <= 0 or args.pr_limit <= 0:
        print("--issue-limit and --pr-limit must be positive integers", file=sys.stderr)
        return 2
    if args.stale_days < 0:
        print("--stale-days must not be negative", file=sys.stderr)
        return 2
    if shutil.which("gh") is None:
        print("gh not found on PATH", file=sys.stderr)
        return 2
    try:
        options = {}
        if args.all_issues:
            options["all_issues"] = True
        if args.repo is not None:
            options["selected_repositories"] = args.repo
        data = collect(args.issue_limit, args.pr_limit, args.include_prs, **options)
        if args.triage_file:
            data["triage"] = load_triage(args.triage_file, data)
    except (FleetManifestError, ValueError, OSError) as exc:
        print(f"report input failed validation: {exc}", file=sys.stderr)
        return 2

    snapshot_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    if args.markdown_file:
        try:
            write_markdown(data, args.markdown_file, snapshot_utc, args.stale_days)
        except OSError as exc:
            print(f"Markdown write failed: {exc}", file=sys.stderr)
            return 2

    if args.as_json:
        print(json.dumps({**data, "snapshot_utc": snapshot_utc,
                          "stale_days": args.stale_days,
                          "repository_summary": repository_summary(data, snapshot_utc, args.stale_days),
                          "issue_rows": issue_rows(data, snapshot_utc)},
                         indent=2, sort_keys=True))
    elif args.markdown:
        print(render_markdown(data, snapshot_utc, args.stale_days))
    else:
        print(render(data, snapshot_utc, args.stale_days))

    if not args.no_tsv:
        path = write_tsv(data, args.tsv_dir, snapshot_utc)
        n = len(tsv_rows(data, snapshot_utc))
        marker = "" if snapshot_is_complete(data) else "  [PARTIAL — see warnings above]"
        print(f"\nSnapshot: {path}  ({n} issue rows){marker}",
              file=sys.stderr if args.as_json or args.markdown else sys.stdout)

    return 0 if snapshot_is_complete(data) else 1


if __name__ == "__main__":
    sys.exit(main())
