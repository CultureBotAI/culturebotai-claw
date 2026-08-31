#!/usr/bin/env python3
"""Check every CultureBotAI Mech's published GitHub Pages revision against main.

The report is deliberately based on GitHub's remote state, not local clones:

* fleet membership comes from claw's manifest, which is the authority. The
  organization is *also* listed, and any Mech-named repository publishing a site
  without being a manifest member is reported as such rather than quietly folded
  in -- that gap is a finding, not a detail. AntibioticMech and HabitatMech were
  both in it when this was written;
* the published revision comes from the newest successful ``github-pages``
  deployment;
* freshness compares that revision with the current default-branch head; and
* the public site is requested independently, because a successful deployment
  record does not prove that the URL is reachable now.

"Behind by N commits" on its own is a poor answer to "is the site current".
Measured across the fleet, every Mech was one commit behind and in every case
the commit changed `.env.example`, a justfile recipe or a vendored script --
nothing the published site is built from. A site is only *stale* when main
carries changes to the files it is served from, so the compare is intersected
with the Pages source path GitHub reports (``source.path`` for a branch-served
site). Where that cannot be determined -- a site built by a workflow from
inputs only the workflow knows -- the report says the narrowing was not
possible rather than guessing.

A deployment that is queued or in progress is also not staleness: it is the
newest commit being published right now, and reporting it as STALE would train
a reader to ignore the column.

Exit codes: 0 all discovered Pages sites are current and reachable, 1 at least
one finding or incomplete repo check, 2 discovery/usage failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402

DEFAULT_ORG = "CultureBotAI"
DEFAULT_REPO_LIMIT = 300
DEFAULT_DEPLOYMENT_LIMIT = 20
FLEET_PATTERN = re.compile(r"(?i)mech$")
PREFERRED_ORDER = (
    "CultureMech",
    "MediaIngredientMech",
    "CommunityMech",
    "TraitMech",
    "proteintraitsmech",
    "HabitatMech",
    "CellStructureMech",
    "AntibioticMech",
)


class ApiError(RuntimeError):
    """A GitHub API response that could not be used."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 20):
        self.token = token
        self.timeout = timeout
        self.api_root = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "culturebotai-fleet-pages-status",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def json(self, path: str) -> Any:
        url = path if path.startswith("https://") else self.api_root + path
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", "replace"))
                detail = body.get("message", str(exc))
            except (json.JSONDecodeError, AttributeError):
                detail = str(exc)
            raise ApiError(f"HTTP {exc.code}: {detail}", exc.code) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ApiError(str(exc)) from exc

    def live(self, url: str) -> tuple[int | None, str, str | None]:
        headers = {"User-Agent": "culturebotai-fleet-pages-status"}
        request = urllib.request.Request(url, headers=headers, method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.geturl(), None
        except urllib.error.HTTPError as exc:
            if exc.code == 405:
                request = urllib.request.Request(url, headers=headers, method="GET")
                try:
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        return response.status, response.geturl(), None
                except urllib.error.HTTPError as get_exc:
                    return get_exc.code, get_exc.geturl(), None
                except (urllib.error.URLError, TimeoutError) as get_exc:
                    return None, url, str(get_exc)
            return exc.code, exc.geturl(), None
        except (urllib.error.URLError, TimeoutError) as exc:
            return None, url, str(exc)


@dataclass
class RepoStatus:
    repo: str
    default_branch: str
    pages_enabled: bool
    manifest_member: bool = False
    site_url: str | None = None
    live_http: int | None = None
    live_url: str | None = None
    main_sha: str | None = None
    published_sha: str | None = None
    published_at: str | None = None
    deployment_state: str | None = None
    latest_attempt_state: str | None = None
    build_type: str | None = None
    source_path: str | None = None
    freshness: str = "UNKNOWN"
    commits_behind: int | None = None
    site_files_changed: int | None = None
    site_paths_known: bool = False
    detail: str | None = None
    error: str | None = None


def _repo_order(name: str) -> tuple[int, str]:
    try:
        return PREFERRED_ORDER.index(name), ""
    except ValueError:
        return len(PREFERRED_ORDER), name.casefold()


def manifest_repo_names() -> set[str]:
    """The Mech repositories claw's manifest declares, by GitHub name.

    The manifest is the authority on membership (CLAUDE.md). Organization
    discovery is the wider net, and the difference between the two is reported
    rather than silently merged.
    """
    try:
        manifest = load_fleet_manifest()
    except Exception:  # noqa: BLE001 - a missing manifest must not hide sites
        return set()
    return {mech.github.split("/")[-1].casefold() for mech in manifest.mechs.values()}


def discover_repos(
    client: GitHubClient, org: str, repo_limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Return Mech repositories and whether org discovery exceeded the limit."""
    found: list[dict[str, Any]] = []
    page = 1
    # Paginate the entire organization before applying the Mech limit. Stopping
    # after ``repo_limit`` arbitrary org repos can miss Mechs that GitHub lists
    # later, while still claiming discovery was complete.
    while True:
        query = urllib.parse.urlencode(
            {"type": "all", "per_page": 100, "page": page}
        )
        batch = client.json(f"/orgs/{urllib.parse.quote(org)}/repos?{query}")
        if not isinstance(batch, list):
            raise ApiError("organization repository response was not a list")
        found.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    mechs = [repo for repo in found if FLEET_PATTERN.search(repo.get("name", ""))]
    mechs.sort(key=lambda repo: _repo_order(repo["name"]))
    return mechs[:repo_limit], len(mechs) > repo_limit


def _status_for_deployment(
    client: GitHubClient, org: str, repo: str, deployment_id: int
) -> dict[str, Any] | None:
    statuses = client.json(
        f"/repos/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}"
        f"/deployments/{deployment_id}/statuses?per_page=100"
    )
    return statuses[0] if statuses else None


def _classify_comparison(comparison: dict[str, Any]) -> tuple[str, int | None, str | None]:
    """Classify ``published...main`` using GitHub's compare response."""
    status = comparison.get("status")
    if status == "identical":
        return "CURRENT", 0, None
    if status == "ahead":
        behind = int(comparison.get("ahead_by", 0))
        return "STALE", behind, f"main is {behind} commit(s) ahead of the published site"
    if status == "behind":
        count = int(comparison.get("behind_by", 0))
        return "DEPLOYED_AHEAD", None, f"published revision is {count} commit(s) ahead of main"
    if status == "diverged":
        return "DIVERGED", None, "published revision and main have diverged"
    return "UNKNOWN", None, f"unrecognized compare status: {status!r}"


def _site_files(comparison: dict[str, Any], result: "RepoStatus") -> int | None:
    """How many changed files the published site is actually built from.

    None when that cannot be answered -- a workflow-built site assembles its
    inputs in ways only the workflow knows, and guessing there would turn an
    honest "unknown" into a confident wrong number.
    """
    files = comparison.get("files")
    if files is None or not result.site_paths_known:
        return None
    if not result.source_path:
        # The whole repository is served, so every changed file is site content.
        return len(files)
    prefix = result.source_path + "/"
    return sum(1 for f in files if str(f.get("filename", "")).startswith(prefix))


def check_repo(
    client: GitHubClient,
    org: str,
    repo_data: dict[str, Any],
    deployment_limit: int,
    check_live: bool = True,
) -> RepoStatus:
    repo = repo_data["name"]
    branch = repo_data.get("default_branch") or "main"
    result = RepoStatus(
        repo=repo,
        default_branch=branch,
        manifest_member=bool(repo_data.get("_manifest_member")),
        pages_enabled=bool(repo_data.get("has_pages")),
    )
    if not result.pages_enabled:
        result.freshness = "NO_PAGES"
        result.detail = "GitHub reports Pages is not enabled"
        return result

    try:
        # The /pages endpoint gives the served path and the build type. Without
        # it the site URL is a guess and the compare cannot be narrowed.
        try:
            pages = client.json(
                f"/repos/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}/pages"
            )
            result.build_type = pages.get("build_type")
            result.site_url = pages.get("html_url") or result.site_url
            source = pages.get("source") or {}
            path = (source.get("path") or "").strip("/")
            if result.build_type == "legacy":
                # "/" means the whole repository is served, which narrows nothing.
                result.source_path = path or ""
                result.site_paths_known = True
        except ApiError:
            pass

        branch_data = client.json(
            f"/repos/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}"
            f"/branches/{urllib.parse.quote(branch, safe='')}"
        )
        result.main_sha = branch_data["commit"]["sha"]

        query = urllib.parse.urlencode(
            {"environment": "github-pages", "per_page": deployment_limit}
        )
        deployments = client.json(
            f"/repos/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}/deployments?{query}"
        )
        if not deployments:
            result.detail = "Pages is enabled but no github-pages deployment was found"
            result.freshness = "UNKNOWN"
            return result

        successful: tuple[dict[str, Any], dict[str, Any]] | None = None
        for index, deployment in enumerate(deployments):
            status = _status_for_deployment(client, org, repo, deployment["id"])
            state = status.get("state") if status else "unknown"
            if index == 0:
                result.latest_attempt_state = state
            if state == "success":
                successful = deployment, status or {}
                break

        if successful is None:
            result.deployment_state = result.latest_attempt_state
            result.detail = (
                f"no successful deployment among the newest {len(deployments)} attempt(s)"
            )
            result.freshness = "UNKNOWN"
            return result

        deployment, status = successful
        result.deployment_state = status.get("state")
        result.published_sha = deployment.get("sha")
        result.published_at = status.get("updated_at") or deployment.get("updated_at")
        result.site_url = status.get("environment_url") or (
            f"https://{org.casefold()}.github.io/{repo}/"
        )

        if result.published_sha == result.main_sha:
            result.freshness = "CURRENT"
            result.commits_behind = 0
        elif result.published_sha and result.main_sha:
            compare = client.json(
                f"/repos/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}"
                f"/compare/{result.published_sha}...{result.main_sha}"
            )
            result.freshness, result.commits_behind, result.detail = _classify_comparison(
                compare
            )
            if result.freshness == "STALE":
                touched = _site_files(compare, result)
                result.site_files_changed = touched
                if touched == 0 and result.site_paths_known:
                    result.freshness = "CURRENT_CONTENT"
                    result.detail = (
                        f"{result.commits_behind} commit(s) behind, none touching "
                        f"{result.source_path + '/' if result.source_path else 'the served tree'}"
                    )
                elif touched and result.site_paths_known:
                    result.detail = (
                        f"{result.commits_behind} commit(s) behind, {touched} "
                        f"changing files the site is served from"
                    )

        if result.latest_attempt_state in ("queued", "in_progress") and result.freshness in (
            "STALE",
            "CURRENT_CONTENT",
        ):
            result.freshness = "DEPLOYING"
            result.detail = (
                f"a deployment is {result.latest_attempt_state}; the newest commit "
                f"is publishing now"
            )

        if check_live and result.site_url:
            result.live_http, result.live_url, live_error = client.live(result.site_url)
            if live_error:
                result.detail = "; ".join(filter(None, [result.detail, live_error]))
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        result.error = str(exc)[:300]
    return result


def collect(
    client: GitHubClient,
    org: str = DEFAULT_ORG,
    repo_limit: int = DEFAULT_REPO_LIMIT,
    deployment_limit: int = DEFAULT_DEPLOYMENT_LIMIT,
    check_live: bool = True,
) -> dict[str, Any]:
    repos, truncated = discover_repos(client, org, repo_limit)
    members = manifest_repo_names()
    for repo in repos:
        repo["_manifest_member"] = repo["name"].casefold() in members
    results = [
        check_repo(client, org, repo, deployment_limit, check_live)
        for repo in repos
    ]
    return {
        "org": org,
        "repo_limit": repo_limit,
        "repo_listing_truncated": truncated,
        "repos_discovered": len(repos),
        "manifest_members": sorted(members),
        "publishing_non_members": sorted(
            repo["name"] for repo in repos
            if not repo["_manifest_member"] and repo.get("has_pages")
        ),
        "results": [asdict(result) for result in results],
    }


def result_is_healthy(result: dict[str, Any], check_live: bool = True) -> bool:
    if result["error"] or result["freshness"] not in ("CURRENT", "CURRENT_CONTENT"):
        return False
    if result["latest_attempt_state"] not in ("success", "queued", "in_progress"):
        return False
    if check_live and not (
        result["live_http"] is not None and 200 <= result["live_http"] < 400
    ):
        return False
    return True


def report_is_healthy(data: dict[str, Any], check_live: bool = True) -> bool:
    return bool(data["results"]) and not data["repo_listing_truncated"] and all(
        result_is_healthy(result, check_live) for result in data["results"]
    )


def render(data: dict[str, Any], check_live: bool = True) -> str:
    results = data["results"]
    lines = [
        f"GitHub Pages freshness across {data['org']} Mechs",
        "",
        f"{'REPO':<23} {'LIVE':<5} {'DEPLOY':<12} {'SITE VS MAIN':<22} {'PUBLISHED':<10} URL",
    ]
    for result in results:
        if result["live_http"] is not None:
            live = str(result["live_http"])
        elif check_live:
            live = "ERR"
        else:
            live = "SKIP"
        deploy = result["latest_attempt_state"] or "-"
        freshness = result["freshness"]
        behind = result["commits_behind"]
        touched = result["site_files_changed"]
        if freshness == "CURRENT_CONTENT":
            freshness = f"current ({behind} behind)"
        elif freshness == "STALE" and touched:
            freshness = f"STALE ({touched} file(s))"
        elif behind:
            freshness += f" ({behind})"
        sha = (result["published_sha"] or "-")[:8]
        url = result["live_url"] or result["site_url"] or "-"
        lines.append(
            f"{result['repo']:<23} {live:<5} {deploy:<12} {freshness:<22} {sha:<10} {url}"
        )

    lines.extend(["", "Coverage"])
    outside = data.get("publishing_non_members") or []
    if outside:
        lines.append(
            f"  publishing but NOT fleet-manifest members: {', '.join(outside)} "
            f"-- membership is the manifest's to declare (see the Mech standard, "
            f"Tier 1.12)"
        )
    enabled = sum(result["pages_enabled"] for result in results)
    current = sum(
        result["freshness"] in ("CURRENT", "CURRENT_CONTENT") for result in results
    )
    healthy = sum(result_is_healthy(result, check_live) for result in results)
    lines.append(
        f"  discovered {data['repos_discovered']} Mech repos; "
        f"Pages enabled={enabled}; site content current={current}; healthy={healthy}"
    )
    if data["repo_listing_truncated"]:
        lines.append(
            f"  WARNING: discovery exceeded --repo-limit ({data['repo_limit']}); "
            "entire Mech repos may be missing"
        )
    for result in results:
        notes = []
        if result["error"]:
            notes.append(f"ERROR: {result['error']}")
        if result["detail"]:
            notes.append(result["detail"])
        if result["latest_attempt_state"] not in (None, "success", "queued", "in_progress"):
            notes.append(f"latest deployment attempt is {result['latest_attempt_state']}")
        if result["freshness"] == "STALE" and not result["site_paths_known"]:
            notes.append(
                "built by a workflow, so the change set could not be narrowed to "
                "site sources -- treat the commit count as an upper bound"
            )
        if notes:
            lines.append(f"  {result['repo']}: " + "; ".join(notes))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default=DEFAULT_ORG)
    parser.add_argument("--repo-limit", type=int, default=DEFAULT_REPO_LIMIT)
    parser.add_argument(
        "--deployment-limit", type=int, default=DEFAULT_DEPLOYMENT_LIMIT
    )
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--no-live-check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repo_limit < 1 or not 1 <= args.deployment_limit <= 100 or args.timeout <= 0:
        print("limits and timeout must be positive; --deployment-limit cannot exceed 100", file=sys.stderr)
        return 2
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    client = GitHubClient(token=token, timeout=args.timeout)
    try:
        data = collect(
            client,
            org=args.org,
            repo_limit=args.repo_limit,
            deployment_limit=args.deployment_limit,
            check_live=not args.no_live_check,
        )
    except ApiError as exc:
        print(f"ERROR: fleet discovery failed: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(render(data, check_live=not args.no_live_check))
    return 0 if report_is_healthy(data, check_live=not args.no_live_check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
