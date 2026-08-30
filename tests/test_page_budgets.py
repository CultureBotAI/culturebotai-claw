"""Page-size and file-count budgets, once, for any Mech (#132 Phase 6, item 1).

The criterion is that common site behaviour and budgets are "tested once
centrally". Only ProteinTraitsMech has budgets at all -- `audit_pages_size.py`
against `conf/pages_budgets.json`, enforced in its Pages workflow -- and the
others generate a site with nothing watching its size.

What did not generalize from that script is the layout it measures:
`data/records.*.json` and `data/detail/*.json` are written into the code, so no
other repository can use it unedited. Here a Mech names its groups as globs.

What mattered most to carry over is the smallest part of it. That script fails
when it finds no browse shards or no detail buckets -- two lines that look like
a footnote and are the only thing between it and a budget that cannot fail,
because a site that generated nothing is under every size limit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_pages import (
    BudgetError,
    GroupBudget,
    SiteBudgets,
    audit,
    load_budgets,
    measure,
)

ROOT = Path(__file__).resolve().parents[1]


def _site(tmp_path: Path, files: dict[str, int]) -> Path:
    site = tmp_path / "_site"
    for name, size in files.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    site.mkdir(parents=True, exist_ok=True)
    return site


def _budgets(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "budgets.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# The check that keeps every other check honest
# --------------------------------------------------------------------------


def test_an_empty_site_fails_before_any_size_limit(tmp_path):
    """A site that generated nothing is under every size budget. Without this,
    a broken build passes the gate that exists to catch it."""
    site = _site(tmp_path, {})

    _, failures = audit(site, SiteBudgets(site_total_bytes=1000, min_files=1))

    assert failures
    assert "passes every size budget" in failures[0]


def test_a_missing_site_directory_is_a_failure_not_a_pass(tmp_path):
    _, failures = audit(tmp_path / "never-built", SiteBudgets(site_total_bytes=10))

    assert failures == [f"{tmp_path / 'never-built'} is not a directory; nothing was generated"]


def test_a_group_that_matched_nothing_is_a_failure(tmp_path):
    """The generalization of "no browse record shards found"."""
    site = _site(tmp_path, {"index.html": 10})
    budgets = SiteBudgets(
        groups=(GroupBudget("browse", "data/records.*.json", min_files=1),)
    )

    _, failures = audit(site, budgets)

    assert any("expected at least 1" in f for f in failures)


# --------------------------------------------------------------------------
# Measuring
# --------------------------------------------------------------------------


def test_totals_and_counts_cover_the_whole_site(tmp_path):
    site = _site(tmp_path, {"a.html": 10, "sub/b.json": 20})

    metrics = measure(site, SiteBudgets())

    assert metrics["site_total_bytes"] == 30
    assert metrics["generated_file_count"] == 2


def test_a_group_reports_its_files_total_and_largest(tmp_path):
    site = _site(
        tmp_path,
        {"data/records.1.json": 100, "data/records.2.json": 250, "other.html": 5},
    )
    budgets = SiteBudgets(groups=(GroupBudget("browse", "data/records.*.json"),))

    metrics = measure(site, budgets)

    assert metrics["browse_files"] == 2
    assert metrics["browse_total_bytes"] == 350
    assert metrics["browse_largest_bytes"] == 250


def test_a_group_matching_a_directory_ignores_it(tmp_path):
    site = _site(tmp_path, {"data/detail/a.json": 10})
    budgets = SiteBudgets(groups=(GroupBudget("detail", "data/*"),))

    assert measure(site, budgets)["detail_files"] == 0


# --------------------------------------------------------------------------
# Limits
# --------------------------------------------------------------------------


def test_a_limit_that_is_exceeded_reports_both_numbers(tmp_path):
    site = _site(tmp_path, {"a.html": 100})

    _, failures = audit(site, SiteBudgets(site_total_bytes=50))

    assert failures == ["site_total_bytes: 100 > 50"]


def test_a_limit_that_is_met_exactly_passes(tmp_path):
    """A budget is a ceiling. Failing at exactly the limit would make every
    number one less than it reads."""
    site = _site(tmp_path, {"a.html": 50})

    _, failures = audit(site, SiteBudgets(site_total_bytes=50))

    assert failures == []


def test_an_undeclared_limit_is_not_enforced(tmp_path):
    site = _site(tmp_path, {"a.html": 10_000_000})

    _, failures = audit(site, SiteBudgets(min_files=1))

    assert failures == []


def test_group_limits_are_enforced_separately(tmp_path):
    site = _site(tmp_path, {"d/a.json": 100, "d/b.json": 900})
    budgets = SiteBudgets(
        groups=(GroupBudget("g", "d/*.json", total_bytes=500, largest_bytes=500),)
    )

    _, failures = audit(site, budgets)

    assert failures == ["g_total_bytes: 1,000 > 500", "g_largest_bytes: 900 > 500"]


# --------------------------------------------------------------------------
# Reading the declaration
# --------------------------------------------------------------------------


def test_a_budget_file_is_read(tmp_path):
    path = _budgets(
        tmp_path,
        {
            "site_total_bytes": 100,
            "generated_file_count": 5,
            "groups": {"g": {"glob": "d/*", "total_bytes": 10, "min_files": 2}},
        },
    )

    budgets = load_budgets(path)

    assert budgets.site_total_bytes == 100
    assert budgets.groups[0] == GroupBudget("g", "d/*", 10, None, 2)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"typo_bytes": 1}, "unknown keys"),
        ({"groups": {"g": {}}}, "must name a glob"),
        ({"groups": {"g": {"glob": "d/*", "typo": 1}}}, "unknown keys"),
        ({"site_total_bytes": "big"}, "must be an integer"),
        ({"site_total_bytes": -1}, "must not be negative"),
        ({"site_total_bytes": True}, "must be an integer"),
    ],
)
def test_an_unusable_budget_declaration_is_refused(tmp_path, body, message):
    """A budget nothing reads is a limit nobody is holding to, and a typo in a
    metric name is exactly how one stops being enforced."""
    with pytest.raises(BudgetError, match=message):
        load_budgets(_budgets(tmp_path, body))


def test_a_missing_or_malformed_file_says_which(tmp_path):
    with pytest.raises(BudgetError, match="cannot read budgets"):
        load_budgets(tmp_path / "absent.json")

    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(BudgetError, match="not valid JSON"):
        load_budgets(path)


def test_the_legacy_flat_keys_are_refused_with_the_group_form(tmp_path):
    """ProteinTraitsMech's own file writes the group into the metric name --
    `largest_browse_shard_bytes` -- which is why no other repository could use
    its schema. Recognising those keys is not accepting them; two ways to say
    one thing is the duplication this phase removes. It is so the migration
    reads as mechanical."""
    path = _budgets(
        tmp_path,
        {
            "browse_index_total_bytes": 1,
            "largest_browse_shard_bytes": 2,
            "detail_total_bytes": 3,
            "largest_detail_bucket_bytes": 4,
        },
    )

    with pytest.raises(BudgetError) as raised:
        load_budgets(path)

    message = str(raised.value)
    assert '"groups"' in message
    assert '"browse_index"' in message and '"detail"' in message


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------


def test_only_the_mech_with_budgets_declares_them():
    """Four Mechs generate a site and declare none. Saying so with a reason is
    what makes the gap visible rather than assumed."""
    manifest = load_fleet_manifest()
    enabled = set(manifest.with_capability("page_budgets"))

    assert enabled == {"proteintraitsmech"}
    for key, mech in manifest.mechs.items():
        capability = mech.capabilities["page_budgets"]
        if key in enabled:
            assert capability.settings["site_path"]
            assert capability.settings["budgets_path"]
        else:
            assert capability.reason, f"{key} disables it without a reason"


def test_a_mech_without_budgets_reports_the_reason(capsys):
    from kg_microbe_pages.__main__ import main

    assert main(["audit", "--mech", "culturemech"]) == 0
    assert "declares no page budgets" in capsys.readouterr().out
