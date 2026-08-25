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
    _mergeable,
    fleet_repository_identities,
    render,
)

from kg_microbe_fleet import load_fleet_manifest  # noqa: E402


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
        "repository_identities": {
            "culturebotai-claw": "CultureBotAI/culturebotai-claw",
            "TraitMech": "CultureBotAI/TraitMech",
        },
        "pr_limit": 200,
        "pr_listing_truncated": [],
        "prs": {"culturebotai-claw": [_pr(1)], "TraitMech": []},
        "errors": {},
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# fleet membership
# --------------------------------------------------------------------------

def test_the_sweep_queries_exactly_the_manifest_fleet():
    """Every Mech in the manifest is swept, and nothing else is."""

    manifest = load_fleet_manifest()
    identities = fleet_repository_identities(manifest)

    for mech in manifest.mechs.values():
        assert mech.github in identities, f"{mech.key} is not swept"
    # claw itself plus exactly the manifest Mechs -- no more.
    assert len(identities) == len(manifest.keys) + 1


def test_an_org_repo_not_in_the_manifest_is_not_swept():
    assert "CultureBotAI/HabitatMech" not in fleet_repository_identities()


def test_adding_a_mech_to_the_manifest_adds_it_to_the_sweep():
    """Membership is now declared, not discovered.

    The previous implementation pattern-matched the GitHub org and flagged
    repositories it had not seen before. Deriving the list from the manifest
    means a Mech is swept as soon as it is declared -- but also that a
    repository created in the org and never added to the manifest is invisible
    here. That trade is deliberate: the manifest is the fleet's definition.
    """

    manifest = load_fleet_manifest()
    before = fleet_repository_identities(manifest)

    class _Extended:
        mechs = {
            **manifest.mechs,
            "enzymemech": type(
                "M", (), {"github": "CultureBotAI/EnzymeMech"}
            )(),
        }
        keys = tuple(manifest.keys) + ("enzymemech",)

    after = fleet_repository_identities(_Extended())

    assert "CultureBotAI/EnzymeMech" not in before
    assert "CultureBotAI/EnzymeMech" in after


def test_repo_order_is_stable_and_follows_manifest_order():
    manifest = load_fleet_manifest()

    first = fleet_repository_identities(manifest)
    second = fleet_repository_identities(manifest)

    assert first == second
    assert [identity for identity in first[1:]] == [
        mech.github for mech in manifest.mechs.values()
    ]


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


def test_pr_listing_truncation_names_the_affected_repos():
    out = render(_data(pr_listing_truncated=["CultureMech", "TraitMech"],
                       pr_limit=30), include_drafts=True)
    assert "--pr-limit (30)" in out
    assert "CultureMech, TraitMech" in out
    assert "--repo-limit" not in out


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


def _fake_gh(prs_by_repo: dict[str, int]):
    def _gh(args, timeout=60):
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
        _fake_gh({"TraitMech": 3, "CultureMech": 1}),
    )
    data = fps.collect(pr_limit=3)
    assert data["pr_listing_truncated"] == ["TraitMech"]


def test_collect_records_nothing_truncated_on_a_roomy_run(monkeypatch):
    monkeypatch.setattr(fps, "_gh", _fake_gh({"TraitMech": 2}))
    data = fps.collect(pr_limit=50)
    assert data["pr_listing_truncated"] == []
    assert len(data["prs"]["TraitMech"]) == 2


def test_collect_captures_a_failing_repo_instead_of_dropping_it(monkeypatch):
    def _gh(args, timeout=60):
        if "CultureMech" in args[args.index("--repo") + 1]:
            raise fps.GhError("HTTP 502")
        return _json.dumps([])
    monkeypatch.setattr(fps, "_gh", _gh)
    data = fps.collect(pr_limit=50)
    assert "CultureMech" in data["errors"]
    assert "CultureMech" not in data["prs"]
    assert "TraitMech" in data["prs"]


# --------------------------------------------------------------------------
# the datestamped TSV snapshot
# --------------------------------------------------------------------------

import csv as _csv  # noqa: E402

from fleet_pr_status import (  # noqa: E402
    TSV_COLUMNS,
    main,
    snapshot_is_complete,
    tsv_path,
    tsv_rows,
    write_tsv,
)

SNAP = "2026-08-04T06:43:15+00:00"


def _read(path):
    with open(path) as f:
        return list(_csv.DictReader(f, delimiter="\t"))


def test_nonpositive_pr_limit_is_rejected_before_any_gh_call(capsys):
    assert main(["--pr-limit", "0", "--no-tsv"]) == 2
    assert "must be a positive integer" in capsys.readouterr().err


def test_main_returns_nonzero_for_a_truncated_snapshot(monkeypatch, capsys):
    monkeypatch.setattr(fps.shutil, "which", lambda command: "/usr/bin/gh")
    monkeypatch.setattr(
        fps,
        "collect",
        lambda pr_limit: _data(pr_listing_truncated=["TraitMech"]),
    )

    assert main(["--no-tsv"]) == 1
    assert "WARNING" in capsys.readouterr().out


def test_tsv_is_datestamped_from_the_snapshot_not_the_clock(tmp_path):
    """The filename must come from the passed timestamp, so a caller can
    reproduce a snapshot's name without waiting for the right day."""
    p = write_tsv(_data(), tmp_path, SNAP)
    assert p.name == "fleet_pr_status_2026-08-04.tsv"


def test_an_incomplete_snapshot_is_marked_partial_in_the_FILENAME(tmp_path):
    """The console warning does not survive; a month later the file is all
    anyone has, so incompleteness has to travel with it."""
    for bad in ({"errors": {"TraitMech": "502"}},
                {"pr_listing_truncated": ["CultureMech"]}):
        p = write_tsv(_data(**bad), tmp_path, SNAP)
        assert p.name.endswith(".partial.tsv"), bad
    assert write_tsv(_data(), tmp_path, SNAP).name == "fleet_pr_status_2026-08-04.tsv"


def test_snapshot_is_complete_reflects_both_failure_modes():
    assert snapshot_is_complete(_data()) is True
    assert snapshot_is_complete(_data(errors={"x": "y"})) is False
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


@pytest.mark.parametrize(
    ("title", "safe_title"),
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("  +cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("\t-2+3", "'-2+3"),
        ("\n@SUM(1,2)", "'@SUM(1,2)"),
    ],
)
def test_formula_titles_are_neutralized_after_tsv_flattening(
    tmp_path, title, safe_title
):
    data = _data(
        prs={"culturebotai-claw": [_pr(1, title=title)], "TraitMech": []}
    )
    path = write_tsv(data, tmp_path, SNAP)

    assert _read(path)[0]["title"] == safe_title
    raw_cells = path.read_text().splitlines()[1].split("\t")
    assert raw_cells[4] == safe_title
    assert len(raw_cells) == len(TSV_COLUMNS)


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


def test_rerun_removes_the_stale_opposite_completeness_marker(tmp_path):
    complete = write_tsv(_data(), tmp_path, SNAP)
    partial = write_tsv(
        _data(errors={"TraitMech": "temporarily unavailable"}), tmp_path, SNAP
    )
    assert partial.exists()
    assert not complete.exists()

    complete = write_tsv(_data(), tmp_path, SNAP)
    assert complete.exists()
    assert not partial.exists()


def test_snapshot_transition_is_serialized_under_one_persistent_lock(
    tmp_path, monkeypatch
):
    """Replace and opposite-marker deletion must be one locked transition."""
    complete = tsv_path(tmp_path, SNAP, complete=True)
    partial = tsv_path(tmp_path, SNAP, complete=False)
    partial.write_text("stale partial snapshot")
    lock_path = fps._snapshot_lock_path(tmp_path, SNAP)
    events = []
    lock_held = False
    real_flock = fps.fcntl.flock
    real_replace = fps.os.replace
    real_unlink = fps.Path.unlink

    def tracking_flock(fd, operation):
        nonlocal lock_held
        if operation == fps.fcntl.LOCK_EX:
            assert not lock_held
            lock_held = True
            events.append("lock")
        elif operation == fps.fcntl.LOCK_UN:
            assert lock_held
            events.append("unlock")
            lock_held = False
        return real_flock(fd, operation)

    def tracking_replace(source, destination):
        assert lock_held
        events.append("replace")
        return real_replace(source, destination)

    def tracking_unlink(path, *args, **kwargs):
        assert path != lock_path, "the stable lock file must never be unlinked"
        if path in {complete, partial}:
            assert lock_held
            events.append("delete-counterpart")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(fps.fcntl, "flock", tracking_flock)
    monkeypatch.setattr(fps.os, "replace", tracking_replace)
    monkeypatch.setattr(fps.Path, "unlink", tracking_unlink)

    assert write_tsv(_data(), tmp_path, SNAP) == complete
    assert events == ["lock", "replace", "delete-counterpart", "unlock"]
    assert lock_path.exists()
    assert lock_path.stat().st_mode & 0o777 == 0o600

    # A partial writer for the same date must reuse the exact same lock path.
    events.clear()
    assert write_tsv(
        _data(errors={"TraitMech": "temporarily unavailable"}), tmp_path, SNAP
    ) == partial
    assert events == ["lock", "replace", "delete-counterpart", "unlock"]
    assert lock_path.exists()


def test_snapshot_lock_rejects_a_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("do not follow", encoding="utf-8")
    lock_path = fps._snapshot_lock_path(tmp_path, SNAP)
    lock_path.symlink_to(outside)

    with pytest.raises(OSError):
        write_tsv(_data(), tmp_path, SNAP)

    assert outside.read_text(encoding="utf-8") == "do not follow"


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
