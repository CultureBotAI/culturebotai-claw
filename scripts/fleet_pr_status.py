#!/usr/bin/env python3
"""Report every open PR across claw and the Mech repos, in one fixed format.

    python scripts/fleet_pr_status.py [--json] [--include-drafts/--no-drafts]
                                      [--pr-limit N]

Why a script rather than "just run `gh pr list`": the answer to "what is open?"
has to be reproducible and complete, and the ad-hoc version is neither. Three
traps this closes, each of which has produced a wrong answer in this fleet:

  * `gh pr list` truncates silently at its limit (30 by default). A short answer
    looks like a complete one, so this command records when the explicit limit
    was reached.
  * Repos discovered from the local filesystem miss any repo not cloned --
    ProteinTraitsMech was invisible to local sweeps for weeks -- and include
    stale clones that are many commits behind the remote.
  * A repo whose query FAILS silently drops out of a hand-rolled loop, so the
    report reads as "nothing open there" when it means "we did not look".

Every one of those is a denominator problem, so this prints the denominator:
which repos were queried, which failed, and whether any limit was reached.

Exit codes: 0 complete report produced (with or without open PRs), 1 one or
more repositories could not be queried or a PR listing reached its limit, and
2 bad usage or `gh` unavailable.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from kg_microbe_fleet import FleetManifest, FleetManifestError, load_fleet_manifest

#: The control plane is reported beside the Mechs but is not itself a Mech.
#: Every Mech identity and its order come exclusively from the manifest.
CONTROL_PLANE_REPOSITORY = "CultureBotAI/culturebotai-claw"

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


def fleet_repository_identities(
    manifest: FleetManifest | None = None,
) -> tuple[str, ...]:
    """Return claw plus the exact manifest-defined Mech fleet, in stable order."""

    manifest = manifest or load_fleet_manifest()
    return (CONTROL_PLANE_REPOSITORY,) + tuple(
        mech.github for mech in manifest.mechs.values()
    )


def open_prs(repository: str, pr_limit: int) -> list[dict]:
    raw = _gh([
        "pr", "list", "--repo", repository, "--state", "open",
        "--limit", str(pr_limit), "--json", PR_FIELDS,
    ])
    prs = json.loads(raw)
    # Newest first: the fleet reads its backlog that way, and a stable sort
    # keeps two runs diffable.
    return sorted(prs, key=lambda p: -p["number"])


def collect(pr_limit: int, manifest: FleetManifest | None = None) -> dict:
    """Query the exact manifest fleet and record every per-repo failure."""

    identities = fleet_repository_identities(manifest)
    repositories = [identity.rsplit("/", 1)[-1] for identity in identities]
    owners = {identity.split("/", 1)[0] for identity in identities}
    result: dict = {
        "org": next(iter(owners)) if len(owners) == 1 else "manifest-defined",
        "repository_identities": dict(zip(repositories, identities)),
        "repos_queried": repositories,
        "pr_limit": pr_limit,
        "pr_listing_truncated": [],
        "prs": {},
        "errors": {},
    }
    for repo, identity in zip(repositories, identities):
        try:
            prs = open_prs(identity, pr_limit)
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
    return not (data["errors"] or data["pr_listing_truncated"])


def _cell(value: object) -> object:
    """Flatten strings and keep spreadsheet software from executing them.

    This is what lets the file be written unquoted, and TSV's whole appeal is
    that `cut -f5` and `awk -F'\\t'` work. Under csv's default quoting a title
    containing a double quote gets wrapped and its quotes doubled -- correct to
    a csv reader, visibly mangled to every naive consumer. Guaranteeing no
    delimiters in the data removes the need to quote at all. Spreadsheet apps
    interpret cells beginning with ``=``, ``+``, ``-``, or ``@`` as formulas,
    so prefix those strings with an apostrophe after whitespace is flattened.
    """
    if not isinstance(value, str):
        return value
    flattened = " ".join(value.split())
    if flattened.startswith(("=", "+", "-", "@")):
        return "'" + flattened
    return flattened


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


def _snapshot_lock_path(out_dir: Path, snapshot_utc: str) -> Path:
    """One persistent lock inode shared by both completeness variants."""
    return out_dir / f".fleet_pr_status_{snapshot_utc[:10]}.lock"


@contextmanager
def _snapshot_lock(out_dir: Path, snapshot_utc: str) -> Iterator[None]:
    """Lock one date without following or replacing the stable lock inode."""

    lock_path = _snapshot_lock_path(out_dir, snapshot_utc)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def write_tsv(data: dict, out_dir: Path, snapshot_utc: str) -> Path:
    complete = snapshot_is_complete(data)
    path = tsv_path(out_dir, snapshot_utc, complete)
    counterpart = tsv_path(out_dir, snapshot_utc, not complete)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = tsv_rows(data, snapshot_utc)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=f".{path.name}.",
            newline="",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(
                handle,
                fieldnames=list(TSV_COLUMNS),
                delimiter="\t",
                lineterminator="\n",
                extrasaction="raise",
                quoting=csv.QUOTE_NONE,
                quotechar=None,
            )
            writer.writeheader()
            writer.writerows(rows)

        # The selected path and deletion of its opposite marker are one state
        # transition. Both complete and partial writers use this same stable
        # lock file, which must never be unlinked: replacing a lock inode while
        # another process waits on the old one would split the critical section.
        with _snapshot_lock(out_dir, snapshot_utc):
            os.replace(temporary, path)
            temporary = None
            counterpart.unlink(missing_ok=True)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
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

    if args.pr_limit <= 0:
        print("--pr-limit must be a positive integer", file=sys.stderr)
        return 2

    if shutil.which("gh") is None:
        print("gh not found on PATH", file=sys.stderr)
        return 2
    try:
        data = collect(args.pr_limit)
    except FleetManifestError as exc:
        print(f"fleet manifest failed validation: {exc}", file=sys.stderr)
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

    # A truncated query is just as incomplete as a failed repository query.
    # Keep the partial artifact for diagnosis, but never give automation a
    # success status for a snapshot the script itself labels incomplete.
    return 0 if snapshot_is_complete(data) else 1


if __name__ == "__main__":
    sys.exit(main())
