#!/usr/bin/env python3
"""Catalogue every branch across claw and the Mech repos, in one fixed format.

    python scripts/fleet_branch_status.py [--json] [--no-compare]
                                          [--ref-limit N] [--stale-days N]

`fleet_pr_status.py` answers "what is open?" from the PR side. A branch with no
PR is invisible to it, and so is a branch whose PR merged months ago and was
never deleted. Both are real: the fleet carried 50 non-default branches when
this was written, most of them already merged.

The trap this closes is a **denominator** one, the same shape as the PR script's
and as `github-pages-status`'s "N commits behind": a bare branch count reads as
open work, and is mostly cleanup. So nothing here reports a total without the
disposition breakdown that says what those branches actually are.

Dispositions, decided per branch:

  merged      an associated PR merged -- the branch is finished, delete it
  open-pr     an associated PR is open -- in flight, and `fleet_pr_status`
              is the report that covers it
  closed-pr   every associated PR was closed unmerged -- someone decided
              against it; the branch is a leftover
  no-pr       no PR ever opened -- either work in progress that nobody can
              see, or an abandoned experiment

AHEAD and BEHIND are reported separately from disposition and must be read
*with* it, because this fleet squash-merges. A squash merge replays a branch as
one new commit, so the branch's own commits never appear on the default branch
and it keeps reporting `ahead>0` forever. Of the 47 merged branches present
when this was written, 33 still read as ahead by one to twelve commits, and
none of that was unfinished work.

  disposition=merged   the work landed; AHEAD is a squash-merge artifact and
                       says nothing about unique work. Deletable.
  otherwise            AHEAD is the branch's unmerged commits, and `ahead=0`
                       means the default branch already contains everything
                       it has.

Reading AHEAD alone is the mistake this layout exists to prevent: it would
report a fully-landed fleet as carrying two hundred commits of open work.

Exit codes: 0 complete catalogue produced, 1 one or more repositories could not
be queried or a ref listing reached its limit, 2 bad usage or `gh` unavailable.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

from kg_microbe_fleet import FleetManifest, FleetManifestError, load_fleet_manifest

#: The control plane is catalogued beside the Mechs but is not itself a Mech.
CONTROL_PLANE_REPOSITORY = "CultureBotAI/culturebotai-claw"

#: Fixed and ordered, so snapshots from different days diff and concatenate
#: cleanly; append new columns at the end rather than inserting.
TSV_COLUMNS = (
    "snapshot_utc", "repo", "branch", "disposition", "ahead", "behind",
    "last_commit_utc", "age_days", "author", "sha", "pull_requests", "url",
)

DISPOSITIONS = ("open-pr", "no-pr", "closed-pr", "merged")

_REFS_QUERY = """
query($owner:String!,$name:String!,$cursor:String){
  repository(owner:$owner,name:$name){
    defaultBranchRef{ name }
    refs(refPrefix:"refs/heads/",first:100,after:$cursor,
         orderBy:{field:TAG_COMMIT_DATE,direction:DESC}){
      pageInfo{ hasNextPage endCursor }
      nodes{
        name
        target{ ... on Commit { oid committedDate author{ name } } }
        associatedPullRequests(first:10){ nodes{ number state } }
      }
    }
  }
}
"""


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


def _graphql(query: str, **variables: str) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        args += ["-f", f"{key}={value}"]
    return json.loads(_gh(args))


def branches(repository: str, ref_limit: int) -> tuple[list[dict], str, bool]:
    """Every branch in `repository`, its default branch name, and truncation.

    Returns the raw ref nodes rather than a verdict, so `collect` owns every
    interpretation and a test can drive it with hand-built data.
    """
    owner, name = repository.split("/", 1)
    nodes: list[dict] = []
    cursor: str | None = None
    truncated = False
    default = ""
    while True:
        variables = {"owner": owner, "name": name}
        if cursor is not None:
            variables["cursor"] = cursor
        payload = _graphql(_REFS_QUERY, **variables)
        repo = (payload.get("data") or {}).get("repository") or {}
        default = ((repo.get("defaultBranchRef") or {}).get("name")) or default
        refs = repo.get("refs") or {}
        nodes.extend(refs.get("nodes") or [])
        if len(nodes) >= ref_limit:
            nodes = nodes[:ref_limit]
            truncated = True
            break
        page = refs.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return nodes, default, truncated


def _compare_query(default_branch: str, names: list[str]) -> str:
    """One aliased `compare` per branch, under a single `ref(default)`.

    Direction matters and is easy to invert. `ref(X).compare(headRef: Y)`
    reports Y relative to X, so with X as the *default* branch, `aheadBy` is
    the branch's own unfinished commits and `behindBy` is how far it has
    fallen behind. Verified against `GET /compare/main...branch`, which is the
    ground truth this fleet reads elsewhere. Reversing the two produces
    plausible numbers for every branch, which is why `tests/` pins it with a
    fixture whose two values differ.
    """
    aliases = "\n".join(
        f'    a{index}: compare(headRef:{json.dumps(name)}){{ aheadBy behindBy }}'
        for index, name in enumerate(names)
    )
    return (
        'query($owner:String!,$name:String!){\n'
        '  repository(owner:$owner,name:$name){\n'
        f'    ref(qualifiedName:{json.dumps("refs/heads/" + default_branch)}){{\n'
        f'{aliases}\n'
        '    }\n'
        '  }\n'
        '}\n'
    )


def compare_to_default(
    repository: str, default_branch: str, names: list[str]
) -> dict[str, dict]:
    """`{branch: {"ahead": n, "behind": n}}` for each branch versus default."""

    if not names:
        return {}
    owner, name = repository.split("/", 1)
    payload = _graphql(
        _compare_query(default_branch, names), owner=owner, name=name
    )
    ref = ((payload.get("data") or {}).get("repository") or {}).get("ref") or {}
    result: dict[str, dict] = {}
    for index, branch in enumerate(names):
        entry = ref.get(f"a{index}")
        if not entry:
            continue
        result[branch] = {
            "ahead": entry.get("aheadBy"),
            "behind": entry.get("behindBy"),
        }
    return result


def disposition(pull_requests: list[dict]) -> str:
    """What the branch's PR history says about it.

    MERGED wins over any other state: a branch whose PR merged is finished even
    if a later PR from it was closed, and reporting it as `closed-pr` would send
    someone to re-open work that already landed.
    """
    states = {pr.get("state") for pr in pull_requests}
    if not states:
        return "no-pr"
    if "MERGED" in states:
        return "merged"
    if "OPEN" in states:
        return "open-pr"
    return "closed-pr"


def _age_days(committed: str, now: _dt.datetime) -> int | None:
    try:
        when = _dt.datetime.fromisoformat(committed.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (now - when).days


def collect(
    ref_limit: int,
    compare: bool = True,
    manifest: FleetManifest | None = None,
    now: _dt.datetime | None = None,
) -> dict:
    """Query the exact manifest fleet and record every per-repo failure."""

    now = now or _dt.datetime.now(_dt.timezone.utc)
    identities = fleet_repository_identities(manifest)
    repositories = [identity.rsplit("/", 1)[-1] for identity in identities]
    result: dict = {
        "repository_identities": dict(zip(repositories, identities)),
        "repos_queried": repositories,
        "ref_limit": ref_limit,
        "compared": compare,
        "ref_listing_truncated": [],
        "compare_failed": [],
        "default_branch": {},
        "branches": {},
        "errors": {},
    }
    for repo, identity in zip(repositories, identities):
        try:
            nodes, default, truncated = branches(identity, ref_limit)
        except (GhError, subprocess.TimeoutExpired, json.JSONDecodeError,
                KeyError, ValueError) as exc:
            result["errors"][repo] = str(exc)[:200]
            continue
        result["default_branch"][repo] = default
        if truncated:
            result["ref_listing_truncated"].append(repo)

        rows = []
        for node in nodes:
            name = node.get("name") or ""
            if name == default:
                continue
            target = node.get("target") or {}
            prs = ((node.get("associatedPullRequests") or {}).get("nodes")) or []
            committed = target.get("committedDate") or ""
            rows.append({
                "branch": name,
                "sha": (target.get("oid") or "")[:8],
                "last_commit_utc": committed,
                "age_days": _age_days(committed, now),
                "author": (target.get("author") or {}).get("name") or "",
                "pull_requests": [
                    {"number": pr.get("number"), "state": pr.get("state")}
                    for pr in prs
                ],
                "disposition": disposition(prs),
                "ahead": None,
                "behind": None,
                "url": f"https://github.com/{identity}/tree/{name}",
            })

        if compare and rows and default:
            try:
                measured = compare_to_default(
                    identity, default, [row["branch"] for row in rows]
                )
            except (GhError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                result["compare_failed"].append(repo)
                result["errors"][f"{repo} (compare)"] = str(exc)[:200]
            else:
                for row in rows:
                    row.update(measured.get(row["branch"], {}))

        # Oldest last: a catalogue is read newest-first, and a stable sort keeps
        # two runs diffable.
        rows.sort(key=lambda r: (r["last_commit_utc"] or "", r["branch"]), reverse=True)
        result["branches"][repo] = rows
    return result


def snapshot_is_complete(data: dict) -> bool:
    """True when every fleet repo was catalogued and nothing hit a limit."""
    return not (
        data["errors"] or data["ref_listing_truncated"] or data["compare_failed"]
    )


def _cell(value: object) -> object:
    """Flatten strings and keep spreadsheet software from executing them.

    Same reasoning as `fleet_pr_status`: guaranteeing no tab or newline in a
    field is what lets the file be written unquoted, which is TSV's whole
    appeal. A branch name cannot contain whitespace, but an author name can.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    flattened = " ".join(value.split())
    if flattened.startswith(("=", "+", "-", "@")):
        return "'" + flattened
    return flattened


def tsv_rows(data: dict, snapshot_utc: str) -> list[dict]:
    """One row per non-default branch, every disposition included.

    Deliberately unfiltered: the table is a view, the TSV is the record, and a
    snapshot that silently omits rows is the failure this script exists to
    avoid.
    """
    rows = []
    for repo in data["repos_queried"]:
        for branch in data["branches"].get(repo, []):
            rows.append({key: _cell(value) for key, value in {
                "snapshot_utc": snapshot_utc,
                "repo": repo,
                "branch": branch["branch"],
                "disposition": branch["disposition"],
                "ahead": branch["ahead"],
                "behind": branch["behind"],
                "last_commit_utc": branch["last_commit_utc"],
                "age_days": branch["age_days"],
                "author": branch["author"],
                "sha": branch["sha"],
                "pull_requests": " ".join(
                    f"#{pr['number']}:{pr['state']}"
                    for pr in branch["pull_requests"]
                ),
                "url": branch["url"],
            }.items()})
    return rows


DEFAULT_TSV_DIR = Path(__file__).resolve().parents[1] / "workspace" / "reports"


def tsv_path(out_dir: Path, snapshot_utc: str, complete: bool) -> Path:
    """Datestamped, and marked `.partial` when coverage was incomplete.

    The filename carries the fact because the console warning does not survive:
    a month later the file is all anyone has.
    """
    stem = f"fleet_branch_status_{snapshot_utc[:10]}"
    if not complete:
        stem += ".partial"
    return out_dir / f"{stem}.tsv"


def write_tsv(data: dict, out_dir: Path, snapshot_utc: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = tsv_path(out_dir, snapshot_utc, snapshot_is_complete(data))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(TSV_COLUMNS), delimiter="\t",
            quoting=csv.QUOTE_NONE, escapechar="\\", lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(tsv_rows(data, snapshot_utc))
    return path


BRANCH_WIDTH = 44


def _name(text: str, width: int = BRANCH_WIDTH) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def render(data: dict, stale_days: int) -> str:
    """The report. Never a total without the breakdown that explains it."""

    lines: list[str] = []
    total = sum(len(rows) for rows in data["branches"].values())
    counts = {name: 0 for name in DISPOSITIONS}
    for rows in data["branches"].values():
        for row in rows:
            counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1

    lines.append(
        f"Branches across the CultureBotAI fleet (excluding default): {total}"
    )
    lines.append("")
    lines.append(
        "  " + "   ".join(f"{name}={counts.get(name, 0)}" for name in DISPOSITIONS)
    )
    lines.append("")
    lines.append(
        f"{'REPO':<22}{'BRANCH':<{BRANCH_WIDTH + 2}}{'DISPOSITION':<12}"
        f"{'AHEAD':>6}{'BEHIND':>7}{'AGE':>6}"
    )
    for repo in data["repos_queried"]:
        for row in data["branches"].get(repo, []):
            ahead = "?" if row["ahead"] is None else str(row["ahead"])
            behind = "?" if row["behind"] is None else str(row["behind"])
            age = "?" if row["age_days"] is None else f"{row['age_days']}d"
            lines.append(
                f"{repo:<22}{_name(row['branch']):<{BRANCH_WIDTH + 2}}"
                f"{row['disposition']:<12}{ahead:>6}{behind:>7}{age:>6}"
            )

    lines.append("")
    lines.append("Coverage")
    per_repo = ", ".join(
        f"{repo}={len(data['branches'].get(repo, []))}"
        if repo not in data["errors"] else f"{repo}=FAILED"
        for repo in data["repos_queried"]
    )
    lines.append(f"  catalogued {len(data['repos_queried'])} repos: {per_repo}")

    if not data["compared"]:
        lines.append(
            "  --no-compare: AHEAD/BEHIND not measured, so no branch here is "
            "known to be safe to delete"
        )
    for repo in data["compare_failed"]:
        lines.append(
            f"  {repo}: comparison failed, so its AHEAD/BEHIND are unknown "
            f"rather than zero"
        )
    for repo in data["ref_listing_truncated"]:
        lines.append(
            f"  {repo}: reached --ref-limit {data['ref_limit']}; its branches "
            f"are undercounted -- raise the limit"
        )
    for repo, error in data["errors"].items():
        lines.append(f"  {repo}: ERROR: {error}")

    merged = counts.get("merged", 0)
    if merged:
        squashed = sum(
            1
            for repo in data["repos_queried"]
            for row in data["branches"].get(repo, [])
            if row["disposition"] == "merged" and (row["ahead"] or 0) > 0
        )
        note = ""
        if squashed:
            note = (
                f" ({squashed} still read AHEAD>0, which is the squash-merge "
                f"artifact and not unfinished work)"
            )
        lines.append(
            f"  {merged} branch(es) have a merged PR and can be deleted{note}"
        )
    contained = [
        (repo, row)
        for repo in data["repos_queried"]
        for row in data["branches"].get(repo, [])
        if row["ahead"] == 0 and row["disposition"] != "merged"
    ]
    if contained:
        lines.append(
            f"  {len(contained)} unmerged branch(es) hold no commits the "
            f"default branch lacks: "
            + ", ".join(f"{repo}:{row['branch']}" for repo, row in contained[:8])
        )
    stale = [
        (repo, row)
        for repo in data["repos_queried"]
        for row in data["branches"].get(repo, [])
        if row["disposition"] == "no-pr"
        and row["age_days"] is not None
        and row["age_days"] >= stale_days
    ]
    if stale:
        lines.append(
            f"  {len(stale)} branch(es) have no PR and no commit in "
            f"{stale_days}+ days: "
            + ", ".join(f"{repo}:{row['branch']}" for repo, row in stale[:8])
            + (" ..." if len(stale) > 8 else "")
        )
    if not snapshot_is_complete(data):
        lines.append(
            "  INCOMPLETE: the totals above are lower bounds, not the answer"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleet_branch_status")
    ap.add_argument("--ref-limit", type=int, default=500,
                    help="cap on branches listed per repo (default 500); "
                         "reaching it undercounts and is reported")
    ap.add_argument("--stale-days", type=int, default=60,
                    help="a no-PR branch older than this is called out (default 60)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--no-compare", action="store_false", dest="compare",
                    help="skip the ahead/behind measurement (one extra API "
                         "call per repo); AHEAD/BEHIND then read '?'")
    ap.add_argument("--tsv-dir", type=Path, default=DEFAULT_TSV_DIR,
                    help=f"where the datestamped TSV lands (default {DEFAULT_TSV_DIR})")
    ap.add_argument("--no-tsv", action="store_true",
                    help="print the table only; write no snapshot file")
    args = ap.parse_args(argv)

    if args.ref_limit <= 0:
        print("--ref-limit must be a positive integer", file=sys.stderr)
        return 2
    if args.stale_days < 0:
        print("--stale-days must not be negative", file=sys.stderr)
        return 2
    if shutil.which("gh") is None:
        print("gh not found on PATH", file=sys.stderr)
        return 2

    try:
        data = collect(args.ref_limit, compare=args.compare)
    except FleetManifestError as exc:
        print(f"fleet manifest failed validation: {exc}", file=sys.stderr)
        return 2

    snapshot_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    if args.as_json:
        print(json.dumps({**data, "snapshot_utc": snapshot_utc},
                         indent=2, sort_keys=True))
    else:
        print(render(data, args.stale_days))

    if not args.no_tsv:
        path = write_tsv(data, args.tsv_dir, snapshot_utc)
        count = len(tsv_rows(data, snapshot_utc))
        marker = "" if snapshot_is_complete(data) else "  [PARTIAL]"
        print(f"\nSnapshot: {path}  ({count} rows){marker}",
              file=sys.stderr if args.as_json else sys.stdout)

    return 0 if snapshot_is_complete(data) else 1


if __name__ == "__main__":
    sys.exit(main())
