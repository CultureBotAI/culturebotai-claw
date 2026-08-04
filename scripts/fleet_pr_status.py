#!/usr/bin/env python3
"""Report every open PR across claw and the Mech repos, in one fixed format.

    python scripts/fleet_pr_status.py [--json] [--include-drafts/--no-drafts]
                                      [--org ORG] [--repo-limit N] [--pr-limit N]

Why a script rather than "just run `gh pr list`": the answer to "what is open?"
has to be reproducible and complete, and the ad-hoc version is neither. Three
traps this closes, each of which has produced a wrong answer in this fleet:

  * `gh repo list` and `gh pr list` BOTH truncate silently at their limit
    (`gh pr list` defaults to 30). A short answer looks like a complete one.
    The two are capped separately, because they fail differently: repo-listing
    truncation drops WHOLE REPOS, PR-listing truncation undercounts within one.
  * Repos discovered from the local filesystem miss any repo not cloned --
    ProteinTraitsMech was invisible to local sweeps for weeks -- and include
    stale clones that are many commits behind the remote.
  * A repo whose query FAILS silently drops out of a hand-rolled loop, so the
    report reads as "nothing open there" when it means "we did not look".

Every one of those is a denominator problem, so this prints the denominator:
which repos were queried, which failed, and whether any limit was reached.

Exit codes: 0 report produced (with or without open PRs), 1 one or more repos
could not be queried, 2 bad usage or `gh` unavailable.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: A repo is in the fleet if it is claw or ends in "mech" (any casing --
#: `proteintraitsmech` is lowercase on GitHub while its directory is not).
FLEET_PATTERN = re.compile(r"(?i)mech$|^culturebotai-claw$")

DEFAULT_ORG = "CultureBotAI"

#: Fixed display order, so two runs of the report diff cleanly. Repos found by
#: discovery but absent here are appended alphabetically and flagged as new --
#: a sixth Mech appearing is the thing this must not silently absorb.
PREFERRED_ORDER = (
    "culturebotai-claw",
    "CultureMech",
    "MediaIngredientMech",
    "CommunityMech",
    "TraitMech",
    "proteintraitsmech",
)

PR_FIELDS = (
    "number,title,isDraft,author,createdAt,updatedAt,headRefName,url,"
    "mergeable,mergeStateStatus,additions,deletions,changedFiles"
)

#: TSV columns. Fixed and ordered, so snapshots from different days diff and
#: concatenate cleanly; append new columns at the end rather than inserting.
TSV_COLUMNS = (
    "snapshot_utc", "repo", "number", "url", "title", "state", "mergeable",
    "is_draft", "author", "additions", "deletions", "changed_files",
    "head_ref", "created_at", "updated_at",
)


class GhError(RuntimeError):
    pass


def _gh(args: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout).strip() or "gh failed")
    return proc.stdout


def discover_repos(org: str, repo_limit: int) -> tuple[list[str], int]:
    """Fleet repo names from the ORG, plus the org's total repo count.

    Returns the total so the caller can tell a complete listing from one that
    hit the limit; `gh repo list` gives no other signal that it truncated.
    """
    raw = _gh(["repo", "list", org, "--limit", str(repo_limit), "--json", "name"])
    names = [r["name"] for r in json.loads(raw)]
    return sorted(n for n in names if FLEET_PATTERN.search(n)), len(names)


def order_repos(found: list[str]) -> tuple[list[str], list[str]]:
    """(ordered repos, ones not in PREFERRED_ORDER)."""
    known = [r for r in PREFERRED_ORDER if r in found]
    extra = sorted(r for r in found if r not in PREFERRED_ORDER)
    return known + extra, extra


def open_prs(org: str, repo: str, pr_limit: int) -> list[dict]:
    raw = _gh([
        "pr", "list", "--repo", f"{org}/{repo}", "--state", "open",
        "--limit", str(pr_limit), "--json", PR_FIELDS,
    ])
    prs = json.loads(raw)
    # Newest first: the fleet reads its backlog that way, and a stable sort
    # keeps two runs diffable.
    return sorted(prs, key=lambda p: -p["number"])


def collect(org: str, repo_limit: int, pr_limit: int) -> dict:
    """Two limits, tracked separately.

    They bound unrelated quantities -- how many repos an org has, and how many
    PRs one repo has open -- and they fail differently: a repo-listing
    truncation silently drops whole repos from the report, while a PR-listing
    truncation undercounts within one. Sharing a number meant the warning
    could not say which knob to turn.
    """
    repos, org_total = discover_repos(org, repo_limit)
    ordered, unexpected = order_repos(repos)
    result: dict = {
        "org": org,
        "repos_queried": ordered,
        "unexpected_repos": unexpected,
        "org_repo_count": org_total,
        "repo_limit": repo_limit,
        "pr_limit": pr_limit,
        "repo_listing_truncated": org_total >= repo_limit,
        "pr_listing_truncated": [],
        "prs": {},
        "errors": {},
    }
    for repo in ordered:
        try:
            prs = open_prs(org, repo, pr_limit)
        except (GhError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            result["errors"][repo] = str(exc)[:200]
            continue
        result["prs"][repo] = prs
        if len(prs) >= pr_limit:
            result["pr_listing_truncated"].append(repo)
    return result


def _mergeable(pr: dict) -> str:
    """UNKNOWN is not a synonym for conflicting.

    GitHub computes mergeability lazily, so a freshly-pushed or freshly-rebased
    PR reports UNKNOWN until someone asks a second time. Rendering that as a
    problem sends people chasing a conflict that does not exist.
    """
    state = pr.get("mergeable") or "UNKNOWN"
    return {"MERGEABLE": "ok", "CONFLICTING": "CONFLICTS", "UNKNOWN": "?"}.get(
        state, state
    )


TITLE_WIDTH = 58


def _title(text: str, width: int = TITLE_WIDTH) -> str:
    """Truncate visibly. A cut title with no marker reads as a whole one --
    the same looks-complete-but-is-not failure this report exists to avoid,
    at the level of a single cell."""
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


DEFAULT_TSV_DIR = Path(__file__).resolve().parents[1] / "workspace" / "reports"


def snapshot_is_complete(data: dict) -> bool:
    """True when every fleet repo was queried and nothing hit a limit."""
    return not (
        data["errors"]
        or data["repo_listing_truncated"]
        or data["pr_listing_truncated"]
    )


def _cell(value: object) -> object:
    """Flatten any string so a cell can never contain a tab or newline.

    This is what lets the file be written unquoted, and TSV's whole appeal is
    that `cut -f5` and `awk -F'\\t'` work. Under csv's default quoting a title
    containing a double quote gets wrapped and its quotes doubled -- correct to
    a csv reader, visibly mangled to every naive consumer. Guaranteeing no
    delimiters in the data removes the need to quote at all.
    """
    return " ".join(value.split()) if isinstance(value, str) else value


def tsv_rows(data: dict, snapshot_utc: str) -> list[dict]:
    """One row per open PR, drafts included.

    Deliberately NOT filtered by --no-drafts: the table is a view, the TSV is
    the record. A snapshot that silently omits rows is the thing this whole
    script exists to avoid, and `is_draft` lets any consumer filter for itself.
    """
    rows = []
    for repo in data["repos_queried"]:
        for pr in data["prs"].get(repo, []):
            rows.append({k: _cell(v) for k, v in {
                "snapshot_utc": snapshot_utc,
                "repo": repo,
                "number": pr["number"],
                "url": pr.get("url", ""),
                "title": pr.get("title") or "",
                "state": _mergeable(pr),
                "mergeable": pr.get("mergeable") or "UNKNOWN",
                "is_draft": "true" if pr.get("isDraft") else "false",
                "author": (pr.get("author") or {}).get("login", ""),
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "changed_files": pr.get("changedFiles", 0),
                "head_ref": pr.get("headRefName", ""),
                "created_at": pr.get("createdAt", ""),
                "updated_at": pr.get("updatedAt", ""),
            }.items()})
    return rows


def tsv_path(out_dir: Path, snapshot_utc: str, complete: bool) -> Path:
    """Datestamped, and marked `.partial` when coverage was incomplete.

    The filename carries that fact because the console warning does not
    survive: a month later the file is all anyone has, and a partial snapshot
    that looks whole is worse than no snapshot. Re-running on the same date
    overwrites -- the file means "the state on that date", not an append log.
    """
    stem = f"fleet_pr_status_{snapshot_utc[:10]}"
    if not complete:
        stem += ".partial"
    return out_dir / f"{stem}.tsv"


def write_tsv(data: dict, out_dir: Path, snapshot_utc: str) -> Path:
    complete = snapshot_is_complete(data)
    path = tsv_path(out_dir, snapshot_utc, complete)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = tsv_rows(data, snapshot_utc)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=list(TSV_COLUMNS), delimiter="\t",
            lineterminator="\n", extrasaction="raise",
            quoting=csv.QUOTE_NONE, quotechar=None,
        )
        w.writeheader()
        w.writerows(rows)
    return path


def render(data: dict, include_drafts: bool) -> str:
    lines: list[str] = []
    total = 0
    hidden_drafts = 0
    rows: list[tuple[str, dict]] = []

    for repo in data["repos_queried"]:
        for pr in data["prs"].get(repo, []):
            if pr.get("isDraft") and not include_drafts:
                hidden_drafts += 1
                continue
            rows.append((repo, pr))
            total += 1

    lines.append(f"Open PRs across the {data['org']} fleet: {total}")
    lines.append("")

    if rows:
        lines.append(f"{'REPO':<21} {'PR':>5}  {'STATE':<9} {'SIZE':>13}  TITLE")
        for repo, pr in rows:
            size = f"+{pr['additions']}/-{pr['deletions']}"
            draft = "draft " if pr.get("isDraft") else ""
            lines.append(
                f"{repo:<21} {'#' + str(pr['number']):>5}  "
                f"{draft + _mergeable(pr):<9} {size:>13}  {_title(pr['title'])}"
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Coverage")
    per_repo = ", ".join(
        f"{r}={len(data['prs'].get(r, []))}"
        for r in data["repos_queried"]
        if r not in data["errors"]
    )
    lines.append(f"  queried {len(data['repos_queried'])} repos: {per_repo}")

    if hidden_drafts:
        lines.append(f"  {hidden_drafts} draft PR(s) hidden (--include-drafts to show)")
    if data["unexpected_repos"]:
        lines.append(
            "  NEW repos not in the known fleet list: "
            + ", ".join(data["unexpected_repos"])
        )
    if data["repo_listing_truncated"]:
        lines.append(
            f"  WARNING: repo discovery reached --repo-limit "
            f"({data['repo_limit']}); ENTIRE REPOS may be missing from this "
            "report. Re-run with a higher --repo-limit."
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
            "  ^ the total above EXCLUDES those repos; it is a lower bound."
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleet_pr_status")
    ap.add_argument("--org", default=DEFAULT_ORG)
    ap.add_argument("--repo-limit", type=int, default=300,
                    help="cap on org repo discovery; gh truncates silently "
                         "(default 300, org had 38 at time of writing)")
    ap.add_argument("--pr-limit", type=int, default=200,
                    help="cap on open PRs listed per repo; gh defaults to 30 "
                         "and truncates silently")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--tsv-dir", type=Path, default=DEFAULT_TSV_DIR,
                    help=f"where the datestamped TSV lands (default {DEFAULT_TSV_DIR})")
    ap.add_argument("--no-tsv", action="store_true",
                    help="print the table only; write no snapshot file")
    ap.add_argument("--include-drafts", action="store_true", default=True)
    ap.add_argument("--no-drafts", action="store_false", dest="include_drafts")
    args = ap.parse_args(argv)

    if shutil.which("gh") is None:
        print("gh not found on PATH", file=sys.stderr)
        return 2
    try:
        data = collect(args.org, args.repo_limit, args.pr_limit)
    except GhError as exc:
        print(f"discovery failed: {exc}", file=sys.stderr)
        return 2

    snapshot_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    if args.as_json:
        print(json.dumps({**data, "snapshot_utc": snapshot_utc},
                         indent=2, sort_keys=True))
    else:
        print(render(data, args.include_drafts))

    if not args.no_tsv:
        path = write_tsv(data, args.tsv_dir, snapshot_utc)
        n = len(tsv_rows(data, snapshot_utc))
        marker = "" if snapshot_is_complete(data) else "  [PARTIAL — see warnings above]"
        print(f"\nSnapshot: {path}  ({n} rows, drafts included){marker}",
              file=sys.stderr if args.as_json else sys.stdout)

    return 1 if data["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
