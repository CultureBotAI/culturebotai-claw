"""Guards for the fleet branch catalogue, aimed at where it can mislead.

A clean run is not where this misleads anyone. Three failure shapes are, and
each has a precedent in this fleet:

* **A total without its breakdown.** 50 branches sounds like 50 open threads
  and was 3 open PRs plus 47 merged leftovers. This is the same denominator
  trap `fleet_pr_status` and `github-pages-status` were built around.
* **AHEAD read alone.** The fleet squash-merges, so a merged branch reports
  `ahead>0` forever -- 33 of 47 did. Treating that as unfinished work would
  report a fully-landed fleet as carrying hundreds of open commits.
* **An inverted comparison.** `ref(X).compare(headRef: Y)` is symmetric in
  shape and not in meaning; swapping base and head yields plausible numbers
  for every branch and correct ones for none.

Every fixture below is built so the two sides *differ*: ahead is never equal
to behind, the repo that fails is never the repo with no branches, and the
disposition fixtures each contain a state that a wrong precedence would pick.
A fixture built from the situation that already holds passes either way, which
is the failure mode #286 names.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fleet_branch_status", ROOT / "scripts" / "fleet_branch_status.py"
)
assert SPEC and SPEC.loader
fbs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fbs)

NOW = _dt.datetime(2026, 9, 9, tzinfo=_dt.timezone.utc)


# --------------------------------------------------------------------------
# disposition
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "states,expected",
    [
        ([], "no-pr"),
        ([{"state": "OPEN"}], "open-pr"),
        ([{"state": "CLOSED"}], "closed-pr"),
        ([{"state": "MERGED"}], "merged"),
        # Precedence, each with a competing state present so a wrong order picks
        # the other one.
        ([{"state": "CLOSED"}, {"state": "MERGED"}], "merged"),
        ([{"state": "OPEN"}, {"state": "MERGED"}], "merged"),
        ([{"state": "CLOSED"}, {"state": "OPEN"}], "open-pr"),
    ],
)
def test_disposition_precedence(states, expected):
    assert fbs.disposition(states) == expected


def test_a_merged_branch_reopened_and_closed_still_reads_merged():
    """Reporting it as `closed-pr` would send someone to redo landed work."""
    assert fbs.disposition(
        [{"state": "MERGED"}, {"state": "CLOSED"}, {"state": "CLOSED"}]
    ) == "merged"


# --------------------------------------------------------------------------
# the comparison direction
# --------------------------------------------------------------------------


def test_the_compare_query_bases_on_the_default_branch():
    """`ref(default).compare(headRef: branch)` is the only arrangement whose
    aheadBy is the branch's own commits; the reverse reads as the default
    branch's."""
    query = fbs._compare_query("main", ["feature/x"])
    assert '"refs/heads/main"' in query
    assert 'compare(headRef:"feature/x")' in query
    assert '"refs/heads/feature/x"' not in query


def test_ahead_and_behind_are_not_swapped(monkeypatch):
    """Driven by 4 and 24, which are unequal, so a swap changes the answer.
    Matches `GET /compare/main...branch` for a real branch, checked by hand."""
    payload = {
        "data": {"repository": {"ref": {
            "a0": {"aheadBy": 4, "behindBy": 24},
        }}}
    }
    monkeypatch.setattr(fbs, "_gh", lambda args, timeout=60: json.dumps(payload))
    measured = fbs.compare_to_default("O/R", "main", ["feature/x"])
    assert measured == {"feature/x": {"ahead": 4, "behind": 24}}


def test_each_branch_gets_its_own_alias(monkeypatch):
    """One alias per branch, mapped back by index. A shared alias would give
    every branch the first branch's numbers."""
    payload = {
        "data": {"repository": {"ref": {
            "a0": {"aheadBy": 1, "behindBy": 10},
            "a1": {"aheadBy": 2, "behindBy": 20},
        }}}
    }
    monkeypatch.setattr(fbs, "_gh", lambda args, timeout=60: json.dumps(payload))
    measured = fbs.compare_to_default("O/R", "main", ["first", "second"])
    assert measured["first"] == {"ahead": 1, "behind": 10}
    assert measured["second"] == {"ahead": 2, "behind": 20}


def test_no_branches_makes_no_api_call(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("compare_to_default called with no branches")

    monkeypatch.setattr(fbs, "_gh", explode)
    assert fbs.compare_to_default("O/R", "main", []) == {}


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------


def _ref(name, *, committed="2026-09-01T00:00:00Z", prs=(), oid="abcdef1234"):
    return {
        "name": name,
        "target": {"oid": oid, "committedDate": committed,
                   "author": {"name": "someone"}},
        "associatedPullRequests": {"nodes": list(prs)},
    }


def _fake_gh(refs_by_repo, *, fail=(), compare=None):
    """Stub `_gh`, dispatching on which query it was handed."""

    def run(args, timeout=60):
        query = next(a for a in args if a.startswith("query="))
        name = next(a for a in args if a.startswith("name="))[len("name="):]
        if name in fail:
            raise fbs.GhError(f"boom in {name}")
        if "compare(headRef" in query:
            return json.dumps({"data": {"repository": {"ref": compare or {}}}})
        return json.dumps({"data": {"repository": {
            "defaultBranchRef": {"name": "main"},
            "refs": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                     "nodes": refs_by_repo.get(name, [])},
        }}})

    return run


def _manifest_repo_names():
    identities = fbs.fleet_repository_identities()
    return [identity.rsplit("/", 1)[-1] for identity in identities]


def test_collect_covers_exactly_the_manifest_fleet(monkeypatch):
    """Membership is the manifest's to decide; a repo that drops out here is
    a repo whose branches nothing reports."""
    monkeypatch.setattr(fbs, "_gh", _fake_gh({}))
    data = fbs.collect(ref_limit=100, compare=False, now=NOW)

    manifest = load_fleet_manifest()
    expected = ["culturebotai-claw"] + [
        mech.github.rsplit("/", 1)[-1] for mech in manifest.mechs.values()
    ]
    assert data["repos_queried"] == expected
    assert len(expected) == len(manifest.mechs) + 1


def test_the_default_branch_is_not_catalogued_as_a_branch(monkeypatch):
    """It is the thing everything else is measured against, and listing it
    would inflate every count by one per repo."""
    names = _manifest_repo_names()
    monkeypatch.setattr(fbs, "_gh", _fake_gh({
        names[0]: [_ref("main"), _ref("feature/x")],
    }))
    data = fbs.collect(ref_limit=100, compare=False, now=NOW)
    assert [row["branch"] for row in data["branches"][names[0]]] == ["feature/x"]


def test_a_repository_that_fails_is_named_and_not_silently_dropped(monkeypatch):
    """The failure this whole script exists to prevent: a repo that errored
    reads identically to a repo with nothing in it."""
    names = _manifest_repo_names()
    failing, healthy = names[1], names[0]
    monkeypatch.setattr(fbs, "_gh", _fake_gh(
        {healthy: [_ref("feature/x")]}, fail={failing},
    ))
    data = fbs.collect(ref_limit=100, compare=False, now=NOW)

    assert failing in data["errors"]
    assert failing not in data["branches"]
    assert failing in data["repos_queried"]
    assert not fbs.snapshot_is_complete(data)


def test_reaching_the_ref_limit_is_recorded(monkeypatch):
    names = _manifest_repo_names()
    monkeypatch.setattr(fbs, "_gh", _fake_gh({
        names[0]: [_ref(f"feature/{i}") for i in range(5)],
    }))
    data = fbs.collect(ref_limit=3, compare=False, now=NOW)

    assert names[0] in data["ref_listing_truncated"]
    assert not fbs.snapshot_is_complete(data)


def test_a_failed_comparison_leaves_ahead_unknown_rather_than_zero(monkeypatch):
    """`None` and `0` mean opposite things: one is "not measured", the other
    is "contains nothing new". Defaulting to 0 would mark branches deletable
    that were never checked."""
    names = _manifest_repo_names()

    def run(args, timeout=60):
        query = next(a for a in args if a.startswith("query="))
        if "compare(headRef" in query:
            raise fbs.GhError("compare exploded")
        name = next(a for a in args if a.startswith("name="))[len("name="):]
        return json.dumps({"data": {"repository": {
            "defaultBranchRef": {"name": "main"},
            "refs": {"pageInfo": {"hasNextPage": False},
                     "nodes": [_ref("feature/x")] if name == names[0] else []},
        }}})

    monkeypatch.setattr(fbs, "_gh", run)
    data = fbs.collect(ref_limit=100, compare=True, now=NOW)

    assert data["branches"][names[0]][0]["ahead"] is None
    assert names[0] in data["compare_failed"]
    assert not fbs.snapshot_is_complete(data)


def test_age_is_computed_from_the_last_commit(monkeypatch):
    names = _manifest_repo_names()
    monkeypatch.setattr(fbs, "_gh", _fake_gh({
        names[0]: [_ref("feature/x", committed="2026-09-01T00:00:00Z")],
    }))
    data = fbs.collect(ref_limit=100, compare=False, now=NOW)
    assert data["branches"][names[0]][0]["age_days"] == 8


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


def _data(branches_by_repo, **overrides):
    names = _manifest_repo_names()
    data = {
        "repository_identities": {n: f"CultureBotAI/{n}" for n in names},
        "repos_queried": names,
        "ref_limit": 500,
        "compared": True,
        "ref_listing_truncated": [],
        "compare_failed": [],
        "default_branch": {n: "main" for n in names},
        "branches": {n: branches_by_repo.get(n, []) for n in names},
        "errors": {},
    }
    data.update(overrides)
    return data


def _row(branch, disposition="no-pr", ahead=1, behind=2, age=5):
    return {
        "branch": branch, "disposition": disposition, "ahead": ahead,
        "behind": behind, "age_days": age, "author": "someone",
        "sha": "abcdef12", "last_commit_utc": "2026-09-04T00:00:00Z",
        "pull_requests": [], "url": f"https://example.invalid/{branch}",
    }


def test_the_total_is_never_printed_without_the_breakdown():
    """50 branches read as 50 open threads and were 3 open plus 47 merged."""
    names = _manifest_repo_names()
    out = fbs.render(_data({names[0]: [
        _row("a", "merged"), _row("b", "open-pr"), _row("c", "no-pr"),
    ]}), stale_days=60)
    assert "3" in out.splitlines()[0]
    assert "merged=1" in out and "open-pr=1" in out and "no-pr=1" in out


def test_a_repo_with_no_branches_still_appears_in_coverage():
    """Otherwise "checked, nothing there" is indistinguishable from
    "not checked"."""
    names = _manifest_repo_names()
    out = fbs.render(_data({names[0]: [_row("a")]}), stale_days=60)
    assert f"{names[1]}=0" in out


def test_a_failed_repo_is_marked_failed_not_zero():
    names = _manifest_repo_names()
    out = fbs.render(
        _data({}, errors={names[1]: "boom"}), stale_days=60
    )
    assert f"{names[1]}=FAILED" in out
    assert "INCOMPLETE" in out


def test_truncation_names_the_repo_and_the_flag():
    names = _manifest_repo_names()
    out = fbs.render(
        _data({names[0]: [_row("a")]}, ref_listing_truncated=[names[0]]),
        stale_days=60,
    )
    assert names[0] in out and "--ref-limit" in out
    assert "INCOMPLETE" in out


def test_merged_branches_are_reported_as_deletable_with_the_squash_caveat():
    """33 of 47 merged branches read AHEAD>0. Without the caveat the number
    reads as unfinished work."""
    names = _manifest_repo_names()
    out = fbs.render(_data({names[0]: [
        _row("a", "merged", ahead=5), _row("b", "merged", ahead=0),
    ]}), stale_days=60)
    assert "2 branch(es) have a merged PR and can be deleted" in out
    assert "squash-merge artifact" in out
    assert "(1 still read AHEAD>0" in out


def test_a_merged_branch_is_not_listed_as_an_unmerged_contained_branch():
    """The contained line is about branches whose work might be lost; a merged
    branch is deletable for a different reason and would double-count."""
    names = _manifest_repo_names()
    out = fbs.render(
        _data({names[0]: [_row("a", "merged", ahead=0)]}), stale_days=60
    )
    assert "unmerged branch(es) hold no commits" not in out


def test_an_unmerged_contained_branch_is_called_out():
    names = _manifest_repo_names()
    out = fbs.render(
        _data({names[0]: [_row("keeper", "no-pr", ahead=0)]}), stale_days=60
    )
    assert "1 unmerged branch(es) hold no commits" in out
    assert "keeper" in out


def test_no_compare_says_that_nothing_is_known_to_be_deletable():
    names = _manifest_repo_names()
    out = fbs.render(
        _data({names[0]: [_row("a", ahead=None, behind=None)]}, compared=False),
        stale_days=60,
    )
    assert "--no-compare" in out
    assert "?" in out


def test_a_stale_no_pr_branch_is_called_out_and_a_fresh_one_is_not():
    """Driven by one branch either side of the threshold, so an off-by-one or
    an inverted comparison changes the answer."""
    names = _manifest_repo_names()
    out = fbs.render(_data({names[0]: [
        _row("old", "no-pr", age=90), _row("fresh", "no-pr", age=3),
    ]}), stale_days=60)
    assert "old" in out.split("Coverage")[1]
    assert "fresh" not in out.split("Coverage")[1]


def test_a_stale_merged_branch_is_not_reported_as_invisible_work():
    """The stale line is about work nobody can see; a merged branch is not
    that, and including it would bury the real ones."""
    names = _manifest_repo_names()
    out = fbs.render(
        _data({names[0]: [_row("landed", "merged", age=400)]}), stale_days=60
    )
    assert "no PR and no commit" not in out


# --------------------------------------------------------------------------
# the TSV record
# --------------------------------------------------------------------------


def test_the_tsv_keeps_every_disposition():
    """The table is a view; the TSV is the record. A snapshot that omits rows
    is the failure this script exists to avoid."""
    names = _manifest_repo_names()
    data = _data({names[0]: [
        _row("a", "merged"), _row("b", "open-pr"), _row("c", "closed-pr"),
    ]})
    rows = fbs.tsv_rows(data, "2026-09-09T00:00:00+00:00")
    assert {row["disposition"] for row in rows} == {"merged", "open-pr", "closed-pr"}


def test_the_tsv_has_no_tab_or_newline_in_any_cell():
    """Written unquoted, so a delimiter inside a field would silently shift
    every later column."""
    names = _manifest_repo_names()
    row = _row("a")
    row["author"] = "Some\tOne\nElse"
    rows = fbs.tsv_rows(_data({names[0]: [row]}), "2026-09-09T00:00:00+00:00")
    assert rows[0]["author"] == "Some One Else"


def test_an_unmeasured_comparison_is_written_as_empty_not_zero():
    names = _manifest_repo_names()
    rows = fbs.tsv_rows(
        _data({names[0]: [_row("a", ahead=None, behind=None)]}),
        "2026-09-09T00:00:00+00:00",
    )
    assert rows[0]["ahead"] == "" and rows[0]["behind"] == ""


def test_an_incomplete_snapshot_says_so_in_its_filename(tmp_path):
    """The console warning does not survive; a month later the file is all
    anyone has."""
    complete = fbs.tsv_path(tmp_path, "2026-09-09T00:00:00+00:00", True)
    partial = fbs.tsv_path(tmp_path, "2026-09-09T00:00:00+00:00", False)
    assert complete.name == "fleet_branch_status_2026-09-09.tsv"
    assert partial.name == "fleet_branch_status_2026-09-09.partial.tsv"


def test_the_tsv_columns_are_fixed_and_the_writer_agrees(tmp_path):
    names = _manifest_repo_names()
    data = _data({names[0]: [_row("a")]})
    path = fbs.write_tsv(data, tmp_path, "2026-09-09T00:00:00+00:00")
    header = path.read_text(encoding="utf-8").splitlines()[0].split("\t")
    assert tuple(header) == fbs.TSV_COLUMNS


# --------------------------------------------------------------------------
# exit codes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--ref-limit", "0"], ["--stale-days", "-1"]])
def test_bad_usage_exits_two(argv, capsys):
    assert fbs.main(argv) == 2


def test_a_complete_run_exits_zero_and_an_incomplete_one_exits_one(
    monkeypatch, tmp_path
):
    """Automation must never get a success status for a report the script
    itself labels incomplete."""
    names = _manifest_repo_names()
    monkeypatch.setattr(fbs.shutil, "which", lambda _name: "/usr/bin/gh")

    monkeypatch.setattr(fbs, "_gh", _fake_gh({names[0]: [_ref("feature/x")]}))
    assert fbs.main(["--no-compare", "--tsv-dir", str(tmp_path)]) == 0

    monkeypatch.setattr(
        fbs, "_gh", _fake_gh({names[0]: [_ref("feature/x")]}, fail={names[1]})
    )
    assert fbs.main(["--no-compare", "--tsv-dir", str(tmp_path)]) == 1
