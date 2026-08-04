#!/usr/bin/env python3
"""Report every open PR across claw and the Mech repos, in one fixed format.

    python scripts/fleet_pr_status.py [--json] [--include-drafts/--no-drafts]
                                      [--org ORG] [--limit N]

Why a script rather than "just run `gh pr list`": the answer to "what is open?"
has to be reproducible and complete, and the ad-hoc version is neither. Three
traps this closes, each of which has produced a wrong answer in this fleet:

  * `gh repo list` and `gh pr list` BOTH truncate silently at `--limit`
    (`gh pr list` defaults to 30). A short answer looks like a complete one.
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
import json
import re
import shutil
import subprocess
import sys

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
    "number,title,isDraft,author,createdAt,updatedAt,headRefName,"
    "mergeable,mergeStateStatus,additions,deletions,changedFiles"
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


def discover_repos(org: str, limit: int) -> tuple[list[str], int]:
    """Fleet repo names from the ORG, plus the org's total repo count.

    Returns the total so the caller can tell a complete listing from one that
    hit `--limit`; `gh repo list` gives no other signal that it truncated.
    """
    raw = _gh(["repo", "list", org, "--limit", str(limit), "--json", "name"])
    names = [r["name"] for r in json.loads(raw)]
    return sorted(n for n in names if FLEET_PATTERN.search(n)), len(names)


def order_repos(found: list[str]) -> tuple[list[str], list[str]]:
    """(ordered repos, ones not in PREFERRED_ORDER)."""
    known = [r for r in PREFERRED_ORDER if r in found]
    extra = sorted(r for r in found if r not in PREFERRED_ORDER)
    return known + extra, extra


def open_prs(org: str, repo: str, limit: int) -> list[dict]:
    raw = _gh([
        "pr", "list", "--repo", f"{org}/{repo}", "--state", "open",
        "--limit", str(limit), "--json", PR_FIELDS,
    ])
    prs = json.loads(raw)
    # Newest first: the fleet reads its backlog that way, and a stable sort
    # keeps two runs diffable.
    return sorted(prs, key=lambda p: -p["number"])


def collect(org: str, limit: int) -> dict:
    repos, org_total = discover_repos(org, limit)
    ordered, unexpected = order_repos(repos)
    result: dict = {
        "org": org,
        "repos_queried": ordered,
        "unexpected_repos": unexpected,
        "org_repo_count": org_total,
        "limit": limit,
        "truncation_risk": org_total >= limit,
        "prs": {},
        "errors": {},
    }
    for repo in ordered:
        try:
            prs = open_prs(org, repo, limit)
        except (GhError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            result["errors"][repo] = str(exc)[:200]
            continue
        result["prs"][repo] = prs
        if len(prs) >= limit:
            result["truncation_risk"] = True
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
                f"{draft + _mergeable(pr):<9} {size:>13}  {pr['title'][:58]}"
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
    if data["truncation_risk"]:
        lines.append(
            f"  WARNING: a listing reached --limit ({data['limit']}); "
            "counts may be truncated. Re-run with a higher --limit."
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
    ap.add_argument("--limit", type=int, default=200,
                    help="per-listing cap; both gh listings truncate silently")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--include-drafts", action="store_true", default=True)
    ap.add_argument("--no-drafts", action="store_false", dest="include_drafts")
    args = ap.parse_args(argv)

    if shutil.which("gh") is None:
        print("gh not found on PATH", file=sys.stderr)
        return 2
    try:
        data = collect(args.org, args.limit)
    except GhError as exc:
        print(f"discovery failed: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(render(data, args.include_drafts))
    return 1 if data["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
