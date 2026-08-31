"""Offline tests for fleet GitHub Pages freshness reporting."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fleet_pages_status import (  # noqa: E402
    FLEET_PATTERN,
    _classify_comparison,
    check_repo,
    discover_repos,
    render,
    report_is_healthy,
)


class FakeClient:
    def __init__(self, responses, live=(200, "https://example.test/", None)):
        self.responses = responses
        self.live_response = live
        self.paths = []

    def json(self, path):
        self.paths.append(path)
        for needle, response in self.responses:
            if needle in path:
                return response
        raise AssertionError(f"unexpected path: {path}")

    def live(self, url):
        return self.live_response


def _repo(name="TraitMech", has_pages=True):
    return {"name": name, "default_branch": "main", "has_pages": has_pages}


def _responses(
    main="b" * 40,
    deployments=None,
    states=None,
    compare=None,
    build_type="legacy",
    source_path="/docs",
):
    deployments = deployments or [
        {"id": 2, "sha": main, "updated_at": "2026-08-29T01:00:00Z"}
    ]
    states = states or {2: "success"}
    responses = [
        (
            "/pages",
            {
                "build_type": build_type,
                "html_url": "https://example.test/",
                "source": {"branch": "main", "path": source_path},
            },
        ),
        ("/branches/main", {"commit": {"sha": main}}),
    ]
    responses.append(("/deployments?", deployments))
    for deployment_id, state in states.items():
        responses.append(
            (
                f"/deployments/{deployment_id}/statuses",
                [
                    {
                        "state": state,
                        "updated_at": "2026-08-29T02:00:00Z",
                        "environment_url": "https://example.test/",
                    }
                ],
            )
        )
    if compare is not None:
        responses.append(("/compare/", compare))
    return responses


def test_fleet_membership_is_every_name_ending_in_mech_only():
    for name in ("CultureMech", "proteintraitsmech", "NewMech"):
        assert FLEET_PATTERN.search(name)
    for name in ("culturebotai-claw", "kg-microbe", "MicroGrowAgents"):
        assert not FLEET_PATTERN.search(name)


def test_discovery_filters_orders_and_detects_truncation():
    repos = [_repo("NewMech"), _repo("TraitMech"), _repo("kg-microbe")]
    client = FakeClient([("/orgs/", repos)])
    found, truncated = discover_repos(client, "Org", repo_limit=1)
    assert [repo["name"] for repo in found] == ["TraitMech"]
    assert truncated is True


def test_discovery_paginates_past_non_mech_repositories():
    class PageClient:
        def json(self, path):
            page = path.rsplit("page=", 1)[1]
            if page == "1":
                return [_repo(f"project-{number}") for number in range(100)]
            if page == "2":
                return [_repo("LateListedMech")]
            raise AssertionError(path)

    found, truncated = discover_repos(PageClient(), "Org", repo_limit=20)
    assert [repo["name"] for repo in found] == ["LateListedMech"]
    assert truncated is False


def test_exact_deployment_sha_is_current_and_live():
    main = "a" * 40
    result = check_repo(FakeClient(_responses(main=main)), "Org", _repo(), 20)
    assert result.freshness == "CURRENT"
    assert result.commits_behind == 0
    assert result.live_http == 200


def test_uses_prior_success_when_latest_attempt_failed():
    main = "b" * 40
    old = "a" * 40
    deployments = [
        {"id": 3, "sha": main, "updated_at": "2026-08-29T03:00:00Z"},
        {"id": 2, "sha": old, "updated_at": "2026-08-29T02:00:00Z"},
    ]
    responses = _responses(
        main=main,
        deployments=deployments,
        states={3: "failure", 2: "success"},
        compare={"status": "ahead", "ahead_by": 4},
    )
    result = check_repo(FakeClient(responses), "Org", _repo(), 20)
    assert result.latest_attempt_state == "failure"
    assert result.published_sha == old
    assert result.freshness == "STALE"
    assert result.commits_behind == 4


def test_comparison_classification_does_not_guess_divergence():
    assert _classify_comparison({"status": "ahead", "ahead_by": 3})[:2] == (
        "STALE",
        3,
    )
    assert _classify_comparison({"status": "behind", "behind_by": 2})[0] == (
        "DEPLOYED_AHEAD"
    )
    assert _classify_comparison({"status": "diverged"})[0] == "DIVERGED"


def test_pages_disabled_is_visible_without_api_followups():
    client = FakeClient([])
    result = check_repo(client, "Org", _repo(has_pages=False), 20)
    assert result.freshness == "NO_PAGES"
    assert client.paths == []


def test_no_successful_deployment_is_unknown_not_current():
    deployments = [{"id": 3, "sha": "b" * 40}]
    result = check_repo(
        FakeClient(_responses(deployments=deployments, states={3: "failure"})),
        "Org",
        _repo(),
        20,
    )
    assert result.freshness == "UNKNOWN"
    assert "no successful deployment" in result.detail


def _data(result, truncated=False):
    return {
        "org": "Org",
        "repo_limit": 300,
        "repo_listing_truncated": truncated,
        "repos_discovered": 1,
        "results": [result.__dict__],
    }


def test_health_requires_current_successful_and_reachable():
    result = check_repo(FakeClient(_responses()), "Org", _repo(), 20)
    assert report_is_healthy(_data(result)) is True
    result.live_http = 404
    assert report_is_healthy(_data(result)) is False
    result.live_http = 200
    result.latest_attempt_state = "failure"
    assert report_is_healthy(_data(result)) is False
    result.latest_attempt_state = "success"
    assert report_is_healthy(_data(result, truncated=True)) is False


def test_report_prints_denominator_and_findings():
    result = check_repo(FakeClient(_responses()), "Org", _repo(), 20)
    result.freshness = "STALE"
    result.commits_behind = 2
    result.detail = "main is 2 commit(s) ahead of the published site"
    text = render(_data(result))
    assert "STALE (2)" in text
    assert "discovered 1 Mech repos" in text
    assert "current=0" in text
    assert result.detail in text


# -- "current relative to main" means the site, not the commit count ---------


MAIN = "b" * 40
OLD = "a" * 40


def _behind(compare, **kw):
    """Responses where the site is published at an older commit than main."""
    return _responses(
        main=MAIN,
        deployments=[{"id": 2, "sha": OLD, "updated_at": "2026-08-29T02:00:00Z"}],
        states={2: "success"},
        compare=compare,
        **kw,
    )


def _compare(ahead, filenames):
    return {
        "status": "ahead",
        "ahead_by": ahead,
        "files": [{"filename": name} for name in filenames],
    }


def test_commits_that_miss_the_served_tree_are_not_staleness():
    """Measured across the fleet, every Mech was one commit behind and every one
    of those commits changed a justfile recipe, `.env.example` or a vendored
    script -- nothing the published site is built from. Reporting that as STALE
    trains a reader to ignore the column."""
    responses = _behind(
        _compare(1, ["justfile", ".env.example", "scripts/x.py"]), source_path="/docs"
    )
    result = check_repo(FakeClient(responses), "Org", _repo(), 20)
    assert result.freshness == "CURRENT_CONTENT"
    assert result.commits_behind == 1
    assert result.site_files_changed == 0
    assert "none touching docs/" in result.detail


def test_a_commit_touching_the_served_tree_is_staleness():
    responses = _behind(
        _compare(2, ["justfile", "docs/index.html"]), source_path="/docs"
    )
    result = check_repo(FakeClient(responses), "Org", _repo(), 20)
    assert result.freshness == "STALE"
    assert result.site_files_changed == 1
    assert "1 changing files the site is served from" in result.detail


def test_a_site_served_from_the_repository_root_counts_every_change():
    """`source.path` of "/" narrows nothing -- the whole tree is published, so
    every changed file is site content."""
    responses = _behind(_compare(1, ["justfile"]), source_path="/")
    result = check_repo(FakeClient(responses), "Org", _repo(), 20)
    assert result.source_path == ""
    assert result.freshness == "STALE"
    assert result.site_files_changed == 1


def test_a_workflow_built_site_says_it_could_not_narrow():
    """A workflow assembles its inputs in ways only the workflow knows.
    Guessing there would turn an honest unknown into a confident wrong number."""
    responses = _behind(_compare(3, ["docs/index.html"]), build_type="workflow")
    result = check_repo(FakeClient(responses), "Org", _repo(), 20)
    assert result.site_paths_known is False
    assert result.site_files_changed is None
    assert result.freshness == "STALE"
    assert result.commits_behind == 3

    line = render(
        {
            "org": "Org",
            "repo_limit": 300,
            "repo_listing_truncated": False,
            "repos_discovered": 1,
            "results": [__import__("dataclasses").asdict(result)],
        }
    )
    assert "could not be narrowed" in line
    assert "upper bound" in line


def test_a_deployment_in_flight_is_not_staleness():
    """queued/in_progress means the newest commit is publishing right now."""
    main = "b" * 40
    old = "a" * 40
    deployments = [
        {"id": 3, "sha": main, "updated_at": "2026-08-29T03:00:00Z"},
        {"id": 2, "sha": old, "updated_at": "2026-08-29T02:00:00Z"},
    ]
    responses = _responses(
        main=main,
        deployments=deployments,
        states={3: "queued", 2: "success"},
        compare=_compare(1, ["docs/index.html"]),
    )
    result = check_repo(FakeClient(responses), "Org", _repo(), 20)
    assert result.freshness == "DEPLOYING"
    assert "publishing now" in result.detail


def test_a_site_that_cannot_report_its_pages_config_still_reports():
    """The /pages call is best-effort: a repository that refuses it must still
    produce a freshness verdict rather than an error row."""

    class NoPages(FakeClient):
        def json(self, path):
            if path.endswith("/pages"):
                from fleet_pages_status import ApiError

                raise ApiError("HTTP 404: Not Found", 404)
            return super().json(path)

    responses = _behind(_compare(2, ["docs/index.html"]))
    result = check_repo(NoPages(responses), "Org", _repo(), 20)
    assert result.error is None
    assert result.freshness == "STALE"
    assert result.site_paths_known is False


def test_the_served_path_is_a_prefix_not_a_substring():
    """`src/docs/theme.css` contains "docs/" and is not in the served tree.
    A substring match would report a template edit as a live-site change, which
    is the same class of error as counting a docstring mention as code."""
    responses = _behind(
        _compare(1, ["src/culturemech/docs/theme.css", "site/docs/x.html"]),
        source_path="/docs",
    )
    result = check_repo(FakeClient(responses), "Org", _repo(), 20)
    assert result.site_files_changed == 0
    assert result.freshness == "CURRENT_CONTENT"
