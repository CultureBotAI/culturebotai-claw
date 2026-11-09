"""Read-only publication proof for explicitly recorded goal deliverable commits.

Remote-tracking refs are observations, not current origin authority. A caller
may supply commits from an independently verified merged PR; other commits must
be contained by freshly advertised origin branches. No fetch or mutation occurs.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}")
ORIGIN = re.compile(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?")


class PublicationError(ValueError):
    """A recorded deliverable lacks bounded, current origin publication proof."""


def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def recorded_commits(value: Any, *, head: str | None = None) -> list[str]:
    if (not isinstance(value, list) or len(value) > 4096
            or any(not isinstance(s, str) or not SHA.fullmatch(s) for s in value)
            or len(value) != len(set(value))):
        raise PublicationError("deliverable_commits must be a bounded list of unique full commit SHAs")
    if head is not None and head not in value:
        raise PublicationError("deliverable_commits must include the reviewed PR head")
    return list(value)


def verify_origin_publication(
    commits: Sequence[str], repository_roots: Sequence[Path], github_repository: str, *,
    verified_merged_pr_commits: Iterable[str] = (),
    runner: Callable[..., Any] = _run,
    max_queries: int = 2048, max_seconds: float = 30,
) -> dict[str, Any]:
    """Prove each commit is published without trusting stale local remote refs.

    Roots must already have been resolved/owned by the caller. Origin identity is
    checked again here. A squash merge may retain source commits in its verified
    PR rather than the default branch's ancestry; that is valid publication.
    Unknown objects, network failures and bounded-out proofs never permit closure.
    """
    wanted = recorded_commits(list(commits))
    proven_pr = set(recorded_commits(list(verified_merged_pr_commits)))
    proofs = {sha: {"method": "verified_merged_pr"} for sha in wanted if sha in proven_pr}
    remaining = set(wanted) - proofs.keys()
    if not remaining:
        return {"commits": wanted, "proofs": proofs, "complete": True}
    started, queries = time.monotonic(), 0

    def query(args: list[str]) -> Any:
        nonlocal queries
        left = max_seconds - (time.monotonic() - started)
        if queries >= max_queries or left <= 0:
            raise PublicationError("origin publication proof exceeded its read-only query budget")
        queries += 1
        return runner(args, check=False, timeout=min(5, left))

    def read(root: Path, *args: str) -> Any:
        return query(["git", "-C", str(root), *args])

    try:
        for root in dict.fromkeys(repository_roots):
            identity = read(root, "remote", "get-url", "origin")
            match = ORIGIN.fullmatch(identity.stdout.strip()) if identity.returncode == 0 else None
            if not match or match.group(1).casefold() != github_repository.casefold():
                raise PublicationError("origin identity changed before deliverable publication verification")
            advertised = read(root, "ls-remote", "--heads", "origin")
            if advertised.returncode != 0 or len(advertised.stdout) > 1_000_000:
                raise PublicationError("current origin branch inventory is unavailable or too large")
            refs: dict[str, str] = {}
            for line in advertised.stdout.splitlines():
                fields = line.split("\t")
                if (len(fields) != 2 or not SHA.fullmatch(fields[0])
                        or not fields[1].startswith("refs/heads/") or fields[1] in refs):
                    raise PublicationError("malformed current origin branch inventory")
                refs[fields[1]] = fields[0]
            if not refs or len(refs) > 4096:
                raise PublicationError("current origin branches are empty or exceed the proof bound")
            for sha in remaining.copy():
                if sha in refs.values():
                    proofs[sha] = {"method": "current_origin_branch_tip", "tip": sha}
                    remaining.remove(sha)
            # Main is a useful first probe, but every advertised branch may prove
            # publication. No remote-tracking-ref name participates in this test.
            tips = dict.fromkeys(refs[name] for name in sorted(refs, key=lambda n: (n != "refs/heads/main", n)))
            for tip in tips:
                if not remaining:
                    break
                for sha in sorted(remaining):
                    # Local replace/graft metadata must not establish publication.
                    # Compare the immutable SHAs on GitHub, independently of the
                    # local object graph; pagination cannot truncate these fields.
                    result = query(["gh", "api", "--hostname", "github.com",
                        f"repos/{github_repository}/compare/{sha}...{tip}?per_page=1",
                        "--jq", "{status, base: .base_commit.sha, merge_base: .merge_base_commit.sha}"])
                    if result.returncode != 0:
                        continue  # Unavailable/unknown comparisons never authorize.
                    try:
                        comparison = json.loads(result.stdout)
                    except (TypeError, json.JSONDecodeError) as error:
                        raise PublicationError("malformed origin ancestry response") from error
                    if not isinstance(comparison, dict) or comparison.get("base") != sha:
                        raise PublicationError("origin ancestry identity mismatch")
                    if (comparison.get("status") in {"ahead", "identical"}
                            and comparison.get("merge_base") == sha):
                        proofs[sha] = {"method": "current_origin_branch_ancestor", "tip": tip}
                        remaining.remove(sha)
            if not remaining:
                break
    except (OSError, subprocess.SubprocessError) as error:
        raise PublicationError("origin publication measurement failed; closure remains held") from error
    if remaining:
        raise PublicationError(f"{len(remaining)} recorded deliverable commits lack current origin publication proof")
    return {"commits": wanted, "proofs": proofs, "complete": True}
