#!/usr/bin/env python3
"""Report open issues and open PRs per repository across claw and the Mechs.

    python scripts/fleet_issue_status.py [--json] [--issue-limit N] [--pr-limit N]
                                         [--stale-days N] [--no-prs]

`fleet_pr_status.py` lists every open PR. This report is the other half of
"where does the fleet stand?": one row per repository with its open-issue
count, how many are unassigned, how many have gone quiet, the age of the
oldest, and the open-PR count beside it. Five hundred open issues do not fit in
a table, so the table is per repository and the datestamped TSV is the
per-issue record.

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
import csv
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from kg_microbe_fleet import FleetManifest, FleetManifestError, load_fleet_manifest

#: The control plane is reported beside the Mechs but is not itself a Mech.
CONTROL_PLANE_REPOSITORY = "CultureBotAI/culturebotai-claw"

ISSUE_FIELDS = "number,title,labels,assignees,author,milestone,createdAt,updatedAt,url"
PR_FIELDS = "number,isDraft,mergeable"

#: TSV columns. Fixed and ordered, so snapshots from different days diff and
#: concatenate cleanly; append new columns at the end rather than inserting.
TSV_COLUMNS = (
    "snapshot_utc", "repo", "number", "url", "title", "labels", "assignees",
    "author", "milestone", "created_at", "updated_at", "age_days",
    "days_since_update",
)

DEFAULT_TSV_DIR = Path(__file__).resolve().parents[1] / "workspace" / "reports"


class GhError(RuntimeError):
    pass


def _gh(args: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout).strip() or "gh failed")
    return proc.stdout


def fleet_repository_identities(
    manifest: FleetManifest | None = None,
) -> tuple[str, ...]:
    """Return claw plus the exact manifest-defined Mech fleet, in stable order."""

    manifest = manifest or load_fleet_manifest()
    return (CONTROL_PLANE_REPOSITORY,) + tuple(
        mech.github for mech in manifest.mechs.values()
    )


def _listing(kind: str, repository: str, fields: str, limit: int) -> tuple[list[dict], bool]:
    """Open issues or PRs, capped at `limit`, and whether more were left behind.

    Asks for one more than the cap: `gh ... list` returns a plain list with no
    more-pages indicator, so a listing that lands exactly on the limit is
    indistinguishable from one cut short by it unless the probe row is
    requested. It comes back only if something would have been dropped.
    Sorted newest-first before the slice, so the row dropped is the oldest.
    """
    raw = _gh([
        kind, "list", "--repo", repository, "--state", "open",
        "--limit", str(limit + 1), "--json", fields,
    ])
    items = json.loads(raw)
    truncated = len(items) > limit
    return sorted(items, key=lambda item: -item["number"])[:limit], truncated


def open_issues(repository: str, issue_limit: int) -> tuple[list[dict], bool]:
    return _listing("issue", repository, ISSUE_FIELDS, issue_limit)


def open_prs(repository: str, pr_limit: int) -> tuple[list[dict], bool]:
    return _listing("pr", repository, PR_FIELDS, pr_limit)


def collect(
    issue_limit: int,
    pr_limit: int,
    include_prs: bool = True,
    manifest: FleetManifest | None = None,
) -> dict:
    """Query the exact manifest fleet and record every per-repo failure.

    A repository whose issue query fails is not queried for PRs either: half a
    row would read as a whole one. It goes to `errors` and out of every total.
    With `include_prs=False` the `prs` mapping stays empty rather than holding
    an empty list per repository, which `--json` would print as zero open PRs.
    """

    identities = fleet_repository_identities(manifest)
    repositories = [identity.rsplit("/", 1)[-1] for identity in identities]
    owners = {identity.split("/", 1)[0] for identity in identities}
    result: dict = {
        "org": next(iter(owners)) if len(owners) == 1 else "manifest-defined",
        "repository_identities": dict(zip(repositories, identities)),
        "repos_queried": repositories,
        "issue_limit": issue_limit,
        "pr_limit": pr_limit,
        "include_prs": include_prs,
        "issue_listing_truncated": [],
        "pr_listing_truncated": [],
        "issues": {},
        "prs": {},
        "errors": {},
    }
    failures = (GhError, subprocess.TimeoutExpired, json.JSONDecodeError)
    for repo, identity in zip(repositories, identities):
        try:
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


def _cell(value: object) -> object:
    """Flatten strings and keep spreadsheet software from executing them.

    No delimiter can survive in the data, so the file is written unquoted and
    `cut -f5` works. Cells beginning with ``=``, ``+``, ``-`` or ``@`` are
    prefixed with an apostrophe after flattening, as in the PR snapshot.
    """
    if not isinstance(value, str):
        return value
    flattened = " ".join(value.split())
    if flattened.startswith(("=", "+", "-", "@")):
        return "'" + flattened
    return flattened


def tsv_rows(data: dict, snapshot_utc: str) -> list[dict]:
    """One row per open issue, in fixed repository order."""

    now = _parse_time(snapshot_utc)
    rows = []
    for repo in data["repos_queried"]:
        for issue in data["issues"].get(repo, []):
            rows.append({k: _cell(v) for k, v in {
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
            }.items()})
    return rows


def tsv_path(out_dir: Path, snapshot_utc: str, complete: bool) -> Path:
    """Datestamped, and marked `.partial` when coverage was incomplete, so the
    fact travels with the file after the console warning is gone."""
    stem = f"fleet_issue_status_{snapshot_utc[:10]}"
    if not complete:
        stem += ".partial"
    return out_dir / f"{stem}.tsv"


def write_tsv(data: dict, out_dir: Path, snapshot_utc: str) -> Path:
    complete = snapshot_is_complete(data)
    path = tsv_path(out_dir, snapshot_utc, complete)
    counterpart = tsv_path(out_dir, snapshot_utc, not complete)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=f".{path.name}.",
            newline="", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(
                handle, fieldnames=list(TSV_COLUMNS), delimiter="\t",
                lineterminator="\n", extrasaction="raise",
                quoting=csv.QUOTE_NONE, quotechar=None,
            )
            writer.writeheader()
            writer.writerows(tsv_rows(data, snapshot_utc))
        os.replace(temporary, path)
        temporary = None
        counterpart.unlink(missing_ok=True)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return path


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
    rows: list[str] = []
    for repo in data["repos_queried"]:
        if repo in data["errors"]:
            row = f"{repo:<21} {'?':>6} {'?':>10} {'?':>10} {'?':>7}"
            if include_prs:
                row += f" {'?':>4} {'?':>9} {'?':>6}"
            rows.append(row + "  NOT QUERIED")
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
    ap.add_argument("--json", action="store_true", dest="as_json")
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
        data = collect(args.issue_limit, args.pr_limit, args.include_prs)
    except FleetManifestError as exc:
        print(f"fleet manifest failed validation: {exc}", file=sys.stderr)
        return 2

    snapshot_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    if args.as_json:
        print(json.dumps({**data, "snapshot_utc": snapshot_utc,
                          "stale_days": args.stale_days},
                         indent=2, sort_keys=True))
    else:
        print(render(data, snapshot_utc, args.stale_days))

    if not args.no_tsv:
        path = write_tsv(data, args.tsv_dir, snapshot_utc)
        n = len(tsv_rows(data, snapshot_utc))
        marker = "" if snapshot_is_complete(data) else "  [PARTIAL — see warnings above]"
        print(f"\nSnapshot: {path}  ({n} issue rows){marker}",
              file=sys.stderr if args.as_json else sys.stdout)

    return 0 if snapshot_is_complete(data) else 1


if __name__ == "__main__":
    sys.exit(main())
