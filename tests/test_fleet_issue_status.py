"""Tests for the fleet issue status report.

Same shape as the PR report's tests, for the same reason: the report is only
worth reading if "nothing open there" can be told from "we did not look", so
the failure and truncation paths get the coverage. Everything runs offline;
`collect()` reaches `gh` only through `_gh`, which is stubbed here.
"""
from __future__ import annotations

import csv as _csv
import json as _json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fleet_issue_status as fis  # noqa: E402
from fleet_issue_status import (  # noqa: E402
    TITLE_WIDTH,
    TSV_COLUMNS,
    _title,
    fleet_repository_identities,
    main,
    render,
    snapshot_is_complete,
    summarize,
    tsv_path,
    tsv_rows,
    write_tsv,
)

from kg_microbe_fleet import load_fleet_manifest  # noqa: E402

SNAP = "2026-09-13T10:00:00+00:00"
NOW = fis._parse_time(SNAP)


def _issue(number: int, **kw) -> dict:
    base = {
        "number": number, "title": f"Issue {number}", "labels": [],
        "assignees": [], "author": {"login": "someone"}, "milestone": None,
        "createdAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-10T00:00:00Z",
        "url": f"https://example.invalid/issues/{number}",
    }
    base.update(kw)
    return base


def _pr(number: int, **kw) -> dict:
    base = {"number": number, "isDraft": False, "mergeable": "MERGEABLE"}
    base.update(kw)
    return base


def _data(**kw) -> dict:
    base = {
        "org": "CultureBotAI",
        "repos_queried": ["culturebotai-claw", "TraitMech"],
        "repository_identities": {
            "culturebotai-claw": "CultureBotAI/culturebotai-claw",
            "TraitMech": "CultureBotAI/TraitMech",
        },
        "issue_limit": 500,
        "pr_limit": 200,
        "include_prs": True,
        "issue_listing_truncated": [],
        "pr_listing_truncated": [],
        "issues": {"culturebotai-claw": [_issue(1)], "TraitMech": []},
        "prs": {"culturebotai-claw": [_pr(7)], "TraitMech": []},
        "errors": {},
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# fleet membership
# --------------------------------------------------------------------------

def test_the_sweep_queries_exactly_the_manifest_fleet():
    manifest = load_fleet_manifest()
    identities = fleet_repository_identities(manifest)
    for mech in manifest.mechs.values():
        assert mech.github in identities, f"{mech.key} is not swept"
    assert len(identities) == len(manifest.keys) + 1
    assert identities[0] == fis.CONTROL_PLANE_REPOSITORY


def test_an_org_repo_not_in_the_manifest_is_not_swept():
    assert "CultureBotAI/CultureBotAI.github.io" not in fleet_repository_identities()


# --------------------------------------------------------------------------
# summaries are computed against the snapshot, not the wall clock
# --------------------------------------------------------------------------

def test_stale_and_oldest_are_measured_from_the_passed_now():
    issues = [
        _issue(1, createdAt="2026-01-01T00:00:00Z", updatedAt="2026-01-02T00:00:00Z"),
        _issue(2, createdAt="2026-09-10T00:00:00Z", updatedAt="2026-09-12T00:00:00Z"),
    ]
    late = fis._parse_time("2026-12-01T00:00:00+00:00")

    at_snapshot = summarize(issues, NOW, stale_days=60)
    much_later = summarize(issues, late, stale_days=60)

    assert at_snapshot["stale"] == 1
    assert much_later["stale"] == 2, "the same issues read later must age"
    assert at_snapshot["oldest_age_days"] == 255
    assert much_later["oldest_age_days"] == 334


def test_stale_boundary_is_inclusive_at_exactly_stale_days():
    exactly = _issue(1, updatedAt="2026-07-15T10:00:00Z")   # 60 days before SNAP
    one_less = _issue(2, updatedAt="2026-07-15T10:00:01Z")  # 59 days, 23:59:59
    assert summarize([exactly], NOW, 60)["stale"] == 1
    assert summarize([one_less], NOW, 60)["stale"] == 0


def test_unassigned_counts_only_issues_with_no_assignee():
    issues = [_issue(1), _issue(2, assignees=[{"login": "a"}])]
    assert summarize(issues, NOW, 60)["unassigned"] == 1


def test_an_empty_repo_summarises_to_zeros_and_no_oldest():
    assert summarize([], NOW, 60) == {
        "open": 0, "unassigned": 0, "stale": 0, "oldest_age_days": None,
    }


# --------------------------------------------------------------------------
# the denominator
# --------------------------------------------------------------------------

def test_an_unqueryable_repo_is_named_and_the_totals_marked_lower_bounds():
    out = render(
        _data(issues={"culturebotai-claw": [_issue(1)]},
              prs={"culturebotai-claw": []},
              errors={"TraitMech": "issues: HTTP 502"}),
        SNAP, 60,
    )
    assert "ERROR TraitMech: NOT QUERIED — issues: HTTP 502" in out
    assert "lower bounds" in out
    assert "TraitMech=0" not in out
    # and the table row says so rather than showing a plausible zero
    row = next(ln for ln in out.splitlines() if ln.startswith("TraitMech"))
    assert "NOT QUERIED" in row
    assert " 0 " not in row


def test_every_queried_repo_appears_in_coverage_including_empty_ones():
    out = render(_data(), SNAP, 60)
    assert "TraitMech=0" in out
    assert "culturebotai-claw=1" in out
    assert "queried 2 repos" in out


def test_issue_truncation_names_the_affected_repos_and_the_flag():
    out = render(_data(issue_listing_truncated=["CultureMech"], issue_limit=30), SNAP, 60)
    assert "--issue-limit (30)" in out
    assert "CultureMech" in out


def test_pr_truncation_is_reported_separately():
    out = render(_data(pr_listing_truncated=["TraitMech"], pr_limit=5), SNAP, 60)
    assert "--pr-limit (5)" in out


def test_clean_run_makes_no_warning_noise():
    out = render(_data(), SNAP, 60)
    assert "WARNING" not in out
    assert "ERROR" not in out
    assert "lower bound" not in out


def test_headline_totals_match_the_rows():
    data = _data(issues={"culturebotai-claw": [_issue(1), _issue(2)], "TraitMech": [_issue(3)]},
                 prs={"culturebotai-claw": [_pr(9), _pr(8, mergeable="CONFLICTING")],
                      "TraitMech": [_pr(4, isDraft=True)]})
    out = render(data, SNAP, 60)
    assert "fleet: 3; open PRs: 3" in out
    claw = next(ln for ln in out.splitlines() if ln.startswith("culturebotai-claw"))
    assert claw.split()[-3:] == ["2", "1", "0"]   # PRs, CONFLICTS, DRAFTS
    trait = next(ln for ln in out.splitlines() if ln.startswith("TraitMech"))
    assert trait.split()[-3:] == ["1", "0", "1"]


def test_no_prs_mode_drops_the_pr_columns_and_headline():
    out = render(_data(include_prs=False), SNAP, 60)
    assert "open PRs" not in out
    assert "CONFLICTS" not in out


def test_the_report_says_that_issue_counts_exclude_pull_requests():
    """GitHub's open_issues_count includes PRs; the report's number does not,
    and a reader comparing it to the repository badge needs to know why."""
    assert "exclude pull requests" in render(_data(), SNAP, 60)


# --------------------------------------------------------------------------
# collect() -- detection, not just rendering
# --------------------------------------------------------------------------

def _fake_gh(issues_by_repo: dict[str, int], prs_by_repo: dict[str, int] | None = None,
             fail: dict[str, str] | None = None):
    """Stand in for `gh issue list` / `gh pr list`, honouring --limit and
    returning newest-first as the real one does."""
    prs_by_repo = prs_by_repo or {}
    fail = fail or {}

    def _gh(args, timeout=60):
        kind = args[0]
        repo = args[args.index("--repo") + 1].split("/")[1]
        limit = int(args[args.index("--limit") + 1])
        if fail.get(f"{kind}:{repo}"):
            raise fis.GhError(fail[f"{kind}:{repo}"])
        total = (issues_by_repo if kind == "issue" else prs_by_repo).get(repo, 0)
        numbers = sorted(range(1, total + 1), reverse=True)[:limit]
        if kind == "issue":
            return _json.dumps([_issue(i) for i in numbers])
        return _json.dumps([_pr(i) for i in numbers])
    return _gh


def test_collect_records_issue_truncation_per_repo(monkeypatch):
    monkeypatch.setattr(fis, "_gh", _fake_gh({"TraitMech": 4, "CultureMech": 1}))
    data = fis.collect(issue_limit=3, pr_limit=50)
    assert data["issue_listing_truncated"] == ["TraitMech"]
    assert len(data["issues"]["TraitMech"]) == 3
    assert not snapshot_is_complete(data)


def test_exactly_the_limit_is_not_truncation(monkeypatch):
    monkeypatch.setattr(fis, "_gh", _fake_gh({"TraitMech": 3}))
    data = fis.collect(issue_limit=3, pr_limit=50)
    assert data["issue_listing_truncated"] == []
    assert snapshot_is_complete(data)


def test_the_probe_row_is_never_counted(monkeypatch):
    monkeypatch.setattr(fis, "_gh", _fake_gh({"TraitMech": 10}))
    data = fis.collect(issue_limit=3, pr_limit=50)
    assert [i["number"] for i in data["issues"]["TraitMech"]] == [10, 9, 8]


def test_pr_truncation_is_detected_independently(monkeypatch):
    monkeypatch.setattr(fis, "_gh", _fake_gh({"TraitMech": 1}, {"TraitMech": 3}))
    data = fis.collect(issue_limit=50, pr_limit=2)
    assert data["pr_listing_truncated"] == ["TraitMech"]
    assert data["issue_listing_truncated"] == []


def test_a_failing_issue_query_is_captured_and_the_repo_left_out_of_totals(monkeypatch):
    monkeypatch.setattr(
        fis, "_gh", _fake_gh({"TraitMech": 2}, fail={"issue:CultureMech": "HTTP 502"})
    )
    data = fis.collect(issue_limit=50, pr_limit=50)
    assert data["errors"]["CultureMech"] == "issues: HTTP 502"
    assert "CultureMech" not in data["issues"]
    assert "CultureMech" not in data["prs"]
    assert len(data["issues"]["TraitMech"]) == 2


def test_a_failing_pr_query_marks_the_whole_row_not_half_of_it(monkeypatch):
    """Issues fetched and PRs not: showing the issue count beside a blank PR
    column would read as "no PRs". The row is an error."""
    monkeypatch.setattr(
        fis, "_gh", _fake_gh({"TraitMech": 2}, fail={"pr:TraitMech": "timeout"})
    )
    data = fis.collect(issue_limit=50, pr_limit=50)
    assert data["errors"]["TraitMech"].startswith("prs: ")
    assert "TraitMech" not in data["issues"]


def test_no_prs_mode_never_calls_gh_pr(monkeypatch):
    calls = []

    def _gh(args, timeout=60):
        calls.append(args[0])
        if args[0] == "pr":
            raise AssertionError("pr list must not be queried with --no-prs")
        return _json.dumps([])
    monkeypatch.setattr(fis, "_gh", _gh)
    data = fis.collect(issue_limit=5, pr_limit=5, include_prs=False)
    assert set(calls) == {"issue"}
    assert data["include_prs"] is False


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def test_nonpositive_limits_are_rejected_before_any_gh_call(capsys):
    assert main(["--issue-limit", "0", "--no-tsv"]) == 2
    assert main(["--pr-limit", "-1", "--no-tsv"]) == 2
    assert main(["--stale-days", "-1", "--no-tsv"]) == 2


def test_main_returns_nonzero_for_an_incomplete_snapshot(monkeypatch, capsys):
    monkeypatch.setattr(fis.shutil, "which", lambda command: "/usr/bin/gh")
    monkeypatch.setattr(
        fis, "collect",
        lambda issue_limit, pr_limit, include_prs: _data(issue_listing_truncated=["TraitMech"]),
    )
    assert main(["--no-tsv"]) == 1
    assert "WARNING" in capsys.readouterr().out


def test_main_returns_zero_for_a_complete_snapshot(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(fis.shutil, "which", lambda command: "/usr/bin/gh")
    monkeypatch.setattr(fis, "collect", lambda issue_limit, pr_limit, include_prs: _data())
    assert main(["--tsv-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Snapshot:" in out
    assert list(tmp_path.glob("fleet_issue_status_*.tsv"))


# --------------------------------------------------------------------------
# the TSV
# --------------------------------------------------------------------------

def _read(path):
    with open(path) as f:
        return list(_csv.DictReader(f, delimiter="\t"))


def test_tsv_is_datestamped_from_the_snapshot_not_the_clock(tmp_path):
    assert write_tsv(_data(), tmp_path, SNAP).name == "fleet_issue_status_2026-09-13.tsv"


def test_an_incomplete_snapshot_is_marked_partial_in_the_filename(tmp_path):
    for bad in ({"errors": {"TraitMech": "issues: 502"}},
                {"issue_listing_truncated": ["CultureMech"]},
                {"pr_listing_truncated": ["CultureMech"]}):
        assert write_tsv(_data(**bad), tmp_path, SNAP).name.endswith(".partial.tsv"), bad


def test_rerun_removes_the_stale_opposite_completeness_marker(tmp_path):
    complete = write_tsv(_data(), tmp_path, SNAP)
    partial = write_tsv(_data(errors={"TraitMech": "issues: 502"}), tmp_path, SNAP)
    assert partial.exists() and not complete.exists()
    complete = write_tsv(_data(), tmp_path, SNAP)
    assert complete.exists() and not partial.exists()


def test_tsv_header_matches_the_declared_columns_exactly(tmp_path):
    p = write_tsv(_data(), tmp_path, SNAP)
    with open(p) as f:
        assert f.readline().rstrip("\n").split("\t") == list(TSV_COLUMNS)


def test_tsv_rows_carry_labels_assignees_and_ages(tmp_path):
    data = _data(issues={"culturebotai-claw": [_issue(
        1, labels=[{"name": "bug"}, {"name": "needs-human"}],
        assignees=[{"login": "a"}, {"login": "b"}],
        milestone={"title": "v2"},
        createdAt="2026-09-03T10:00:00Z", updatedAt="2026-09-11T10:00:00Z",
    )], "TraitMech": []})
    row = _read(write_tsv(data, tmp_path, SNAP))[0]
    assert row["labels"] == "bug,needs-human"
    assert row["assignees"] == "a,b"
    assert row["milestone"] == "v2"
    assert row["age_days"] == "10"
    assert row["days_since_update"] == "2"


def test_a_tab_or_newline_in_any_field_cannot_shift_the_columns(tmp_path):
    data = _data(issues={"culturebotai-claw": [_issue(
        1, title="a\tb\nc", labels=[{"name": "x\ty"}])], "TraitMech": []})
    raw = write_tsv(data, tmp_path, SNAP).read_text().splitlines()[1]
    cells = raw.split("\t")
    assert len(cells) == len(TSV_COLUMNS)
    assert cells[4] == "a b c"
    assert cells[5] == "x y"


@pytest.mark.parametrize("title", ["=SUM(A1)", "+1", "-2", "@x"])
def test_formula_titles_are_neutralized(tmp_path, title):
    data = _data(issues={"culturebotai-claw": [_issue(1, title=title)], "TraitMech": []})
    assert _read(write_tsv(data, tmp_path, SNAP))[0]["title"] == "'" + title


def test_the_file_contains_no_quoting_at_all(tmp_path):
    data = _data(issues={"culturebotai-claw": [_issue(1, title='has "quotes"')], "TraitMech": []})
    body = write_tsv(data, tmp_path, SNAP).read_text().splitlines()[1]
    assert not body.startswith('"') and '""' not in body


def test_tsv_rows_follow_the_fixed_repo_order():
    data = _data(issues={"culturebotai-claw": [_issue(5)], "TraitMech": [_issue(9)]})
    assert [r["repo"] for r in tsv_rows(data, SNAP)] == ["culturebotai-claw", "TraitMech"]


def test_tsv_path_is_pure(tmp_path):
    p = tsv_path(tmp_path, SNAP, complete=True)
    assert not p.exists() and p.parent == tmp_path


def test_a_truncated_title_is_marked_not_silently_cut():
    out = _title("x" * (TITLE_WIDTH + 40))
    assert len(out) == TITLE_WIDTH and out.endswith("…")
