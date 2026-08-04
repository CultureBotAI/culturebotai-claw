"""Tests for the fleet PR status report.

The report's value is entirely in its denominator: a count is only useful if
you can tell "nothing is open there" from "we did not look". So these tests
concentrate on the failure and truncation paths rather than the happy one --
a report that quietly drops an unreachable repo is worse than no report,
because it reads as authoritative.

Everything here runs offline; `collect()` is the only part that touches `gh`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fleet_pr_status import (  # noqa: E402
    FLEET_PATTERN,
    PREFERRED_ORDER,
    _mergeable,
    order_repos,
    render,
)


def _pr(number: int, **kw) -> dict:
    base = {
        "number": number, "title": f"PR {number}", "isDraft": False,
        "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
        "additions": 1, "deletions": 0, "changedFiles": 1,
    }
    base.update(kw)
    return base


def _data(**kw) -> dict:
    base = {
        "org": "CultureBotAI",
        "repos_queried": ["culturebotai-claw", "TraitMech"],
        "unexpected_repos": [],
        "org_repo_count": 38,
        "limit": 200,
        "truncation_risk": False,
        "prs": {"culturebotai-claw": [_pr(1)], "TraitMech": []},
        "errors": {},
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# fleet membership
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "culturebotai-claw", "CultureMech", "MediaIngredientMech",
    "CommunityMech", "TraitMech", "proteintraitsmech",
])
def test_every_known_fleet_repo_matches(name):
    assert FLEET_PATTERN.search(name)


@pytest.mark.parametrize("name", [
    "MicroGrowAgents", "PFASCommunityAgents", "kg-microbe", "CultureBotHT",
    "MicroMediaParam", "bsdbng", "wizard-claw",
])
def test_non_fleet_repos_do_not_match(name):
    """`claw` alone must not match -- only the exact repo name does."""
    assert not FLEET_PATTERN.search(name)


def test_a_new_mech_is_picked_up_and_flagged_rather_than_absorbed():
    """A sixth Mech must appear in the report AND be called out, not silently
    folded in as though it had always been there."""
    ordered, extra = order_repos(list(PREFERRED_ORDER) + ["EnzymeMech"])
    assert "EnzymeMech" in ordered
    assert extra == ["EnzymeMech"]
    out = render(_data(repos_queried=ordered, unexpected_repos=extra,
                       prs={r: [] for r in ordered}), include_drafts=True)
    assert "NEW repos not in the known fleet list: EnzymeMech" in out


def test_repo_order_is_stable_regardless_of_discovery_order():
    a, _ = order_repos(["TraitMech", "culturebotai-claw", "CultureMech"])
    b, _ = order_repos(["CultureMech", "TraitMech", "culturebotai-claw"])
    assert a == b == ["culturebotai-claw", "CultureMech", "TraitMech"]


# --------------------------------------------------------------------------
# mergeable rendering
# --------------------------------------------------------------------------

def test_unknown_mergeable_is_not_reported_as_a_conflict():
    """GitHub computes mergeability lazily; a freshly-pushed PR reports
    UNKNOWN. Rendering that as CONFLICTS sends people chasing nothing."""
    assert _mergeable({"mergeable": "UNKNOWN"}) == "?"
    assert _mergeable({}) == "?"
    assert _mergeable({"mergeable": None}) == "?"
    assert _mergeable({"mergeable": "CONFLICTING"}) == "CONFLICTS"
    assert _mergeable({"mergeable": "MERGEABLE"}) == "ok"


# --------------------------------------------------------------------------
# the denominator -- the whole point of the report
# --------------------------------------------------------------------------

def test_an_unqueryable_repo_is_named_and_the_total_marked_a_lower_bound():
    out = render(
        _data(repos_queried=["culturebotai-claw", "TraitMech"],
              prs={"culturebotai-claw": [_pr(1)]},
              errors={"TraitMech": "HTTP 502"}),
        include_drafts=True,
    )
    assert "ERROR TraitMech: NOT QUERIED — HTTP 502" in out
    assert "lower bound" in out
    # and the repo must not be silently reported as having zero
    assert "TraitMech=0" not in out


def test_hitting_the_limit_is_warned_about_not_swallowed():
    out = render(_data(truncation_risk=True, limit=30), include_drafts=True)
    assert "WARNING" in out and "--limit (30)" in out


def test_clean_run_makes_no_warning_noise():
    out = render(_data(), include_drafts=True)
    assert "WARNING" not in out
    assert "ERROR" not in out
    assert "lower bound" not in out


def test_every_queried_repo_appears_in_coverage_including_empty_ones():
    """A repo with zero open PRs must still be listed, so the reader can see
    it was checked rather than skipped."""
    out = render(_data(), include_drafts=True)
    assert "TraitMech=0" in out
    assert "culturebotai-claw=1" in out
    assert "queried 2 repos" in out


# --------------------------------------------------------------------------
# drafts and counting
# --------------------------------------------------------------------------

def test_drafts_are_counted_by_default_and_labelled():
    data = _data(prs={"culturebotai-claw": [_pr(1, isDraft=True)], "TraitMech": []})
    out = render(data, include_drafts=True)
    assert "Open PRs across the CultureBotAI fleet: 1" in out
    assert "draft" in out


def test_hiding_drafts_says_how_many_were_hidden():
    """Silently dropping them would make the total unexplainable."""
    data = _data(prs={"culturebotai-claw": [_pr(1, isDraft=True), _pr(2)],
                      "TraitMech": []})
    out = render(data, include_drafts=False)
    assert "fleet: 1" in out
    assert "1 draft PR(s) hidden" in out


def test_zero_open_prs_is_stated_explicitly():
    out = render(_data(prs={"culturebotai-claw": [], "TraitMech": []}),
                 include_drafts=True)
    assert "fleet: 0" in out
    assert "(none)" in out


def test_total_matches_the_rows_rendered():
    data = _data(prs={"culturebotai-claw": [_pr(3), _pr(2)],
                      "TraitMech": [_pr(9)]})
    out = render(data, include_drafts=True)
    assert "fleet: 3" in out
    assert len([ln for ln in out.splitlines() if ln.startswith(("culturebotai-claw ", "TraitMech "))]) == 3
