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
        "repo_limit": 300,
        "pr_limit": 200,
        "repo_listing_truncated": False,
        "pr_listing_truncated": [],
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


def test_repo_discovery_truncation_warns_that_whole_repos_may_be_missing():
    """The two limits fail differently and the warning must say which knob to
    turn: repo truncation drops ENTIRE REPOS, which is the worse failure."""
    out = render(_data(repo_listing_truncated=True, repo_limit=5),
                 include_drafts=True)
    assert "WARNING" in out
    assert "--repo-limit (5)" in out
    assert "ENTIRE REPOS" in out
    assert "--pr-limit" not in out


def test_pr_listing_truncation_names_the_affected_repos():
    out = render(_data(pr_listing_truncated=["CultureMech", "TraitMech"],
                       pr_limit=30), include_drafts=True)
    assert "--pr-limit (30)" in out
    assert "CultureMech, TraitMech" in out
    assert "--repo-limit" not in out


def test_the_two_truncation_warnings_are_independent():
    both = render(_data(repo_listing_truncated=True,
                        pr_listing_truncated=["TraitMech"]), include_drafts=True)
    assert "--repo-limit" in both and "--pr-limit" in both


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


# --------------------------------------------------------------------------
# truncation is visible at the cell level too
# --------------------------------------------------------------------------

def test_a_truncated_title_is_marked_not_silently_cut():
    """A cut title with no marker reads as a complete one -- the same
    looks-complete-but-is-not failure this report exists to avoid."""
    from fleet_pr_status import TITLE_WIDTH, _title
    long = "x" * (TITLE_WIDTH + 40)
    out = _title(long)
    assert len(out) == TITLE_WIDTH
    assert out.endswith("…")


def test_a_short_title_is_left_alone():
    from fleet_pr_status import _title
    assert _title("Fix the thing") == "Fix the thing"


def test_titles_are_flattened_so_a_newline_cannot_break_the_table():
    from fleet_pr_status import _title
    assert _title("Fix\nthe   thing") == "Fix the thing"


# --------------------------------------------------------------------------
# collect() — the detection logic, not just its rendering
#
# These exist because a mutation that stopped RECORDING pr truncation passed
# every test above: render() was covered against hand-built data, while the
# code that builds that data was not exercised at all. Stubbing `_gh` closes
# the gap without touching the network.
# --------------------------------------------------------------------------

import json as _json  # noqa: E402

import fleet_pr_status as fps  # noqa: E402


def _fake_gh(repos: list[str], prs_by_repo: dict[str, int]):
    def _gh(args, timeout=60):
        if args[0] == "repo":
            return _json.dumps([{"name": n} for n in repos])
        repo = args[args.index("--repo") + 1].split("/")[1]
        n = prs_by_repo.get(repo, 0)
        return _json.dumps([
            {"number": i, "title": f"t{i}", "isDraft": False,
             "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
             "additions": 1, "deletions": 0, "changedFiles": 1}
            for i in range(1, n + 1)
        ])
    return _gh


def test_collect_records_pr_truncation_per_repo(monkeypatch):
    monkeypatch.setattr(
        fps, "_gh",
        _fake_gh(["TraitMech", "CultureMech"], {"TraitMech": 3, "CultureMech": 1}),
    )
    data = fps.collect("Org", repo_limit=50, pr_limit=3)
    assert data["pr_listing_truncated"] == ["TraitMech"]
    assert data["repo_listing_truncated"] is False


def test_collect_records_repo_truncation_when_discovery_fills_the_limit(monkeypatch):
    monkeypatch.setattr(fps, "_gh", _fake_gh(["TraitMech", "CultureMech"], {}))
    data = fps.collect("Org", repo_limit=2, pr_limit=50)
    assert data["repo_listing_truncated"] is True


def test_collect_records_nothing_truncated_on_a_roomy_run(monkeypatch):
    monkeypatch.setattr(fps, "_gh", _fake_gh(["TraitMech"], {"TraitMech": 2}))
    data = fps.collect("Org", repo_limit=50, pr_limit=50)
    assert data["repo_listing_truncated"] is False
    assert data["pr_listing_truncated"] == []
    assert len(data["prs"]["TraitMech"]) == 2


def test_collect_captures_a_failing_repo_instead_of_dropping_it(monkeypatch):
    def _gh(args, timeout=60):
        if args[0] == "repo":
            return _json.dumps([{"name": "TraitMech"}, {"name": "CultureMech"}])
        if "CultureMech" in args[args.index("--repo") + 1]:
            raise fps.GhError("HTTP 502")
        return _json.dumps([])
    monkeypatch.setattr(fps, "_gh", _gh)
    data = fps.collect("Org", repo_limit=50, pr_limit=50)
    assert "CultureMech" in data["errors"]
    assert "CultureMech" not in data["prs"]
    assert "TraitMech" in data["prs"]


def test_collect_filters_non_fleet_repos_out_of_discovery(monkeypatch):
    monkeypatch.setattr(
        fps, "_gh", _fake_gh(["TraitMech", "PFASCommunityAgents", "kg-microbe"], {}),
    )
    data = fps.collect("Org", repo_limit=50, pr_limit=50)
    assert data["repos_queried"] == ["TraitMech"]


# --------------------------------------------------------------------------
# the datestamped TSV snapshot
# --------------------------------------------------------------------------

import csv as _csv  # noqa: E402

from fleet_pr_status import (  # noqa: E402
    TSV_COLUMNS,
    snapshot_is_complete,
    tsv_path,
    tsv_rows,
    write_tsv,
)

SNAP = "2026-08-04T06:43:15+00:00"


def _read(path):
    with open(path) as f:
        return list(_csv.DictReader(f, delimiter="\t"))


def test_tsv_is_datestamped_from_the_snapshot_not_the_clock(tmp_path):
    """The filename must come from the passed timestamp, so a caller can
    reproduce a snapshot's name without waiting for the right day."""
    p = write_tsv(_data(), tmp_path, SNAP)
    assert p.name == "fleet_pr_status_2026-08-04.tsv"


def test_an_incomplete_snapshot_is_marked_partial_in_the_FILENAME(tmp_path):
    """The console warning does not survive; a month later the file is all
    anyone has, so incompleteness has to travel with it."""
    for bad in ({"errors": {"TraitMech": "502"}},
                {"repo_listing_truncated": True},
                {"pr_listing_truncated": ["CultureMech"]}):
        p = write_tsv(_data(**bad), tmp_path, SNAP)
        assert p.name.endswith(".partial.tsv"), bad
    assert write_tsv(_data(), tmp_path, SNAP).name == "fleet_pr_status_2026-08-04.tsv"


def test_snapshot_is_complete_reflects_all_three_failure_modes():
    assert snapshot_is_complete(_data()) is True
    assert snapshot_is_complete(_data(errors={"x": "y"})) is False
    assert snapshot_is_complete(_data(repo_listing_truncated=True)) is False
    assert snapshot_is_complete(_data(pr_listing_truncated=["x"])) is False


def test_tsv_keeps_drafts_even_when_the_table_hides_them(tmp_path):
    """The table is a view; the TSV is the record. Dropping rows from a data
    export is the silent-omission failure this script exists to avoid."""
    data = _data(prs={"culturebotai-claw": [_pr(1, isDraft=True), _pr(2)],
                      "TraitMech": []})
    rows = _read(write_tsv(data, tmp_path, SNAP))
    assert len(rows) == 2
    assert sorted(r["is_draft"] for r in rows) == ["false", "true"]
    # meanwhile the rendered table, with drafts off, shows only one
    assert "fleet: 1" in render(data, include_drafts=False)


def test_tsv_header_matches_the_declared_columns_exactly(tmp_path):
    p = write_tsv(_data(), tmp_path, SNAP)
    with open(p) as f:
        header = f.readline().rstrip("\n").split("\t")
    assert header == list(TSV_COLUMNS)


def test_every_row_carries_the_snapshot_timestamp(tmp_path):
    rows = _read(write_tsv(_data(), tmp_path, SNAP))
    assert rows and all(r["snapshot_utc"] == SNAP for r in rows)


def test_titles_are_flattened_so_a_tab_or_newline_cannot_break_the_tsv(tmp_path):
    data = _data(prs={"culturebotai-claw": [_pr(1, title="a\tb\nc   d")],
                      "TraitMech": []})
    rows = _read(write_tsv(data, tmp_path, SNAP))
    assert rows[0]["title"] == "a b c d"
    assert len(rows) == 1


def test_a_failed_repo_contributes_no_rows_but_the_file_is_marked(tmp_path):
    data = _data(prs={"culturebotai-claw": [_pr(1)]},
                 errors={"TraitMech": "HTTP 502"})
    p = write_tsv(data, tmp_path, SNAP)
    assert p.name.endswith(".partial.tsv")
    assert len(_read(p)) == 1


def test_rerunning_the_same_date_overwrites_rather_than_appending(tmp_path):
    write_tsv(_data(), tmp_path, SNAP)
    p = write_tsv(_data(), tmp_path, SNAP)
    assert len(_read(p)) == 1


def test_tsv_rows_are_ordered_by_the_fixed_repo_order(tmp_path):
    data = _data(repos_queried=["culturebotai-claw", "TraitMech"],
                 prs={"culturebotai-claw": [_pr(5)], "TraitMech": [_pr(9)]})
    rows = tsv_rows(data, SNAP)
    assert [r["repo"] for r in rows] == ["culturebotai-claw", "TraitMech"]


def test_tsv_path_is_pure_and_does_not_touch_disk(tmp_path):
    p = tsv_path(tmp_path, SNAP, complete=True)
    assert not p.exists()
    assert p.parent == tmp_path


def test_a_quoted_title_survives_a_NAIVE_tab_split(tmp_path):
    """TSV's whole appeal is that `cut -f5` works. Under csv's default quoting
    a title containing a double quote is wrapped and its quotes doubled --
    correct to a csv reader, mangled to every naive consumer."""
    title = 'Answer to "what is open?"'
    data = _data(prs={"culturebotai-claw": [_pr(1, title=title)], "TraitMech": []})
    p = write_tsv(data, tmp_path, SNAP)
    raw = p.read_text().splitlines()[1]
    assert raw.split("\t")[4] == title
    assert len(raw.split("\t")) == len(TSV_COLUMNS)


def test_a_tab_in_any_field_cannot_shift_the_columns(tmp_path):
    """Not just titles: a branch name or author with a tab would silently
    add a column and misalign every field after it."""
    data = _data(prs={"culturebotai-claw": [
        _pr(1, title="a\tb", headRefName="feat\tx")], "TraitMech": []})
    p = write_tsv(data, tmp_path, SNAP)
    raw = p.read_text().splitlines()[1]
    assert len(raw.split("\t")) == len(TSV_COLUMNS)
    assert raw.split("\t")[4] == "a b"
    assert raw.split("\t")[12] == "feat x"


def test_the_file_contains_no_quoting_at_all(tmp_path):
    data = _data(prs={"culturebotai-claw": [_pr(1, title='has "quotes" in it')],
                      "TraitMech": []})
    body = write_tsv(data, tmp_path, SNAP).read_text().splitlines()[1]
    assert not body.startswith('"')
    assert '""' not in body
