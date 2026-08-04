"""Tests for the shared QC dashboard generator.

The load-bearing property here is that the dashboard is a pure function of
the corpus: regenerating an unchanged corpus must produce no diff, so that
"is the committed dashboard stale?" can be answered by regenerating and
diffing. See TraitMech#193.

Note that a plain generate-twice-and-compare is a *weak* check of that:
with the timestamp rendered to whole seconds, two back-to-back runs of the
old clock-reading code landed in the same second and compared equal ~95% of
the time. The real guard is test_generation_never_reads_the_clock, which
makes any clock read raise.
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kg_microbe_qc import generator  # noqa: E402
from kg_microbe_qc.generator import (  # noqa: E402
    _corpus_timestamp,
    _parse_timestamp,
    generate_dashboard,
)


def _write_corpus(root: Path, records: dict[str, dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, body in records.items():
        (root / f"{name}.yaml").write_text(yaml.safe_dump(body, sort_keys=True))


def _write_config(tmp_path: Path, yaml_dir: Path, **extra) -> Path:
    cfg = {
        "repo_name": "TestMech",
        "yaml_dir": str(yaml_dir),
        "slots": [{"path": "name", "threshold": 0.9, "required": True}],
    }
    cfg.update(extra)
    path = tmp_path / "qc_config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def _hist(*timestamps: str) -> list[dict]:
    return [{"action": "edit", "curator": "t", "timestamp": t}
            for t in timestamps]


def _ts(records, paths=("curation_history.timestamp",)):
    """_corpus_timestamp's date only, for the many tests that ignore counts."""
    return _corpus_timestamp(records, list(paths))[0]


# --------------------------------------------------------------------------
# _parse_timestamp
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("2026-06-05T00:00:00Z", "2026-06-05T00:00:00+00:00"),
    ("2026-06-05T00:00:00z", "2026-06-05T00:00:00+00:00"),
    ("2026-06-05T00:00:00+00:00", "2026-06-05T00:00:00+00:00"),
    # naive is read as UTC, not as local time
    ("2026-06-05T00:00:00", "2026-06-05T00:00:00+00:00"),
    ("  2026-06-05T00:00:00Z  ", "2026-06-05T00:00:00+00:00"),
    # sub-second precision is preserved through parsing
    ("2026-01-27T06:35:58.329113Z", "2026-01-27T06:35:58.329113+00:00"),
    # non-UTC offsets are normalised, not truncated
    ("2026-06-05T12:00:00+02:00", "2026-06-05T10:00:00+00:00"),
    ("2026-06-05", "2026-06-05T00:00:00+00:00"),
])
def test_parse_timestamp_accepts_the_forms_the_fleet_actually_writes(
    value, expected
):
    assert _parse_timestamp(value).isoformat() == expected


def test_parse_timestamp_accepts_pyyaml_native_datetimes():
    """An unquoted YAML scalar is loaded as datetime/date, not str.

    Also pins the isinstance branch order: datetime subclasses date, so
    checking date first would truncate every datetime to midnight.
    """
    loaded = yaml.safe_load("t: 2026-06-05T01:02:03Z")["t"]
    assert isinstance(loaded, _dt.datetime)
    assert _parse_timestamp(loaded).isoformat() == "2026-06-05T01:02:03+00:00"

    loaded_date = yaml.safe_load("t: 2026-06-05")["t"]
    assert isinstance(loaded_date, _dt.date)
    assert _parse_timestamp(loaded_date).isoformat() == "2026-06-05T00:00:00+00:00"


@pytest.mark.parametrize("value", [
    None, "", "not-a-date", "2026-13-45T99:99:99Z", 12345, [], {},
    "yesterday",
])
def test_parse_timestamp_returns_none_rather_than_raising(value):
    assert _parse_timestamp(value) is None


# --------------------------------------------------------------------------
# _corpus_timestamp
# --------------------------------------------------------------------------

def test_corpus_timestamp_is_the_maximum_across_all_records():
    records = [
        {"curation_history": _hist("2026-01-01T00:00:00+00:00")},
        {"curation_history": _hist("2026-05-05T09:30:00+00:00",
                                   "2026-03-03T00:00:00+00:00")},
        {"curation_history": _hist("2026-02-02T00:00:00+00:00")},
    ]
    assert _ts(records) == "2026-05-05T09:30:00+00:00"


def test_corpus_timestamp_compares_instants_not_strings():
    """+02:00 noon precedes 11:00Z; a lexical max would pick the wrong one."""
    records = [
        {"curation_history": _hist("2026-01-01T12:00:00+02:00")},  # 10:00Z
        {"curation_history": _hist("2026-01-01T11:00:00Z")},       # 11:00Z
    ]
    assert _ts(records) == "2026-01-01T11:00:00+00:00"


def test_corpus_timestamp_is_none_when_no_record_carries_one():
    records = [{"name": "a"}, {"name": "b", "curation_history": []}]
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) == (None, 0)


def test_corpus_timestamp_ignores_unparseable_entries_but_keeps_good_ones():
    records = [
        {"curation_history": _hist("garbage")},
        {"curation_history": _hist("2026-04-04T00:00:00+00:00")},
        {"curation_history": [{"action": "edit"}]},  # no timestamp key
    ]
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) == (
        "2026-04-04T00:00:00+00:00", 1
    )


def test_corpus_timestamp_honours_a_configured_path():
    records = [{"provenance": {"modified": "2026-07-07T00:00:00+00:00"}}]
    assert _ts(records, ["provenance.modified"]) == "2026-07-07T00:00:00+00:00"


def test_a_scalar_timestamp_paths_is_not_iterated_per_character():
    """`timestamp_paths: provenance.modified` (no dash) is an easy YAML slip.

    A str satisfies Iterable[str], so without normalisation it would walk
    'p', 'r', 'o', ... match nothing, and report a provenance-free corpus --
    a misconfiguration indistinguishable from real missing data.
    """
    records = [{"provenance": {"modified": "2026-07-07T00:00:00+00:00"}}]
    assert _corpus_timestamp(records, "provenance.modified") == (
        "2026-07-07T00:00:00+00:00", 1
    )


def test_corpus_timestamp_reports_how_many_records_it_drew_on():
    """CommunityMech has curation_history on 2 of 311 records, so its date
    is pinned until one of those two is touched. The count is what makes
    that visible rather than silently implied."""
    records = [{"name": f"r{i}"} for i in range(9)]
    records.append({"curation_history": _hist("2026-07-02T00:00:00+00:00")})
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) == (
        "2026-07-02T00:00:00+00:00", 1
    )


def test_multiple_entries_in_one_record_count_that_record_once():
    records = [{"curation_history": _hist("2026-01-01T00:00:00+00:00",
                                          "2026-02-02T00:00:00+00:00")}]
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) == (
        "2026-02-02T00:00:00+00:00", 1
    )


# --------------------------------------------------------------------------
# generate_dashboard — the end-to-end determinism property
# --------------------------------------------------------------------------

def test_generation_never_reads_the_clock(tmp_path):
    """The actual guard for TraitMech#193, deterministic rather than lucky.

    Swaps the module's datetime for one whose now()/utcnow() raise, so any
    reintroduced clock read fails every run instead of only when two runs
    straddle a second boundary. Timestamps here are strings, so the shim's
    datetime is never used for isinstance dispatch.
    """
    class _NoClock(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("generate_dashboard read the wall clock")

        @classmethod
        def utcnow(cls):
            raise AssertionError("generate_dashboard read the wall clock")

    corpus = tmp_path / "corpus"
    _write_corpus(corpus, {
        "a": {"name": "A", "curation_history": _hist("2026-05-05T09:30:00+00:00")},
    })
    config = _write_config(tmp_path, corpus)

    shim = types.SimpleNamespace(
        datetime=_NoClock, date=_dt.date, timezone=_dt.timezone,
        timedelta=_dt.timedelta,
    )
    original = generator._dt
    generator._dt = shim
    try:
        stats = generate_dashboard(config_path=config, output_dir=tmp_path / "out")
    finally:
        generator._dt = original

    assert stats.timestamp == "2026-05-05T09:30:00+00:00"


def test_regenerating_an_unchanged_corpus_produces_no_diff(tmp_path):
    """Catches nondeterminism beyond the clock: dict/glob ordering, chart
    rendering, embedded tool metadata."""
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, {
        "a": {"name": "A", "curation_history": _hist("2026-05-05T09:30:00+00:00")},
        "b": {"name": "B", "curation_history": _hist("2026-01-01T00:00:00+00:00")},
    })
    config = _write_config(tmp_path, corpus)

    first, second = tmp_path / "out1", tmp_path / "out2"
    generate_dashboard(config_path=config, output_dir=first)
    generate_dashboard(config_path=config, output_dir=second)

    assert (first / "index.html").read_bytes() == (second / "index.html").read_bytes()
    assert (first / "coverage.png").read_bytes() == (second / "coverage.png").read_bytes()


def test_chart_png_does_not_embed_the_matplotlib_version(tmp_path):
    """The Mechs pip-install matplotlib unpinned. With the version stamped
    into the PNG, a regenerate-and-diff staleness check would trip on a
    matplotlib upgrade rather than on a corpus change."""
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, {
        "a": {"name": "A", "curation_history": _hist("2026-05-05T09:30:00+00:00")},
    })
    generate_dashboard(
        config_path=_write_config(tmp_path, corpus), output_dir=tmp_path / "out"
    )
    png = (tmp_path / "out" / "coverage.png").read_bytes()
    assert b"Matplotlib version" not in png
    assert b"Software" not in png


def test_dashboard_timestamp_tracks_the_corpus_not_the_clock(tmp_path):
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, {
        "a": {"name": "A", "curation_history": _hist("2020-02-02T03:04:05+00:00")},
    })
    stats = generate_dashboard(
        config_path=_write_config(tmp_path, corpus), output_dir=tmp_path / "out"
    )
    assert stats.timestamp == "2020-02-02T03:04:05+00:00"

    html = (tmp_path / "out" / "index.html").read_text()
    assert "2020-02-02T03:04:05+00:00" in html
    # the corpus is dated 2020, so today's year must appear nowhere
    assert str(_dt.datetime.now(_dt.timezone.utc).year) not in html


def test_editing_the_corpus_does_move_the_timestamp(tmp_path):
    """Guard against the degenerate fix of hardcoding/removing the date."""
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, {
        "a": {"name": "A", "curation_history": _hist("2026-05-05T09:30:00+00:00")},
    })
    config = _write_config(tmp_path, corpus)
    before = generate_dashboard(config_path=config, output_dir=tmp_path / "o1")

    _write_corpus(corpus, {
        "b": {"name": "B", "curation_history": _hist("2026-09-09T00:00:00+00:00")},
    })
    after = generate_dashboard(config_path=config, output_dir=tmp_path / "o2")

    assert before.timestamp == "2026-05-05T09:30:00+00:00"
    assert after.timestamp == "2026-09-09T00:00:00+00:00"


def test_corpus_without_provenance_renders_unknown_not_todays_date(tmp_path):
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, {"a": {"name": "A"}, "b": {"name": "B"}})
    stats = generate_dashboard(
        config_path=_write_config(tmp_path, corpus), output_dir=tmp_path / "out"
    )
    assert stats.timestamp is None
    assert stats.timestamp_sources == 0

    html = (tmp_path / "out" / "index.html").read_text()
    assert "Latest curation unknown" in html
    # no ISO-8601 instant anywhere in the page
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", html)


def test_page_states_how_thin_the_timestamp_base_is(tmp_path):
    """A date from 1 of 6 records must not read like a date from 6 of 6."""
    corpus = tmp_path / "corpus"
    records = {f"r{i}": {"name": f"R{i}"} for i in range(5)}
    records["dated"] = {"name": "D",
                        "curation_history": _hist("2026-07-02T00:00:00+00:00")}
    _write_corpus(corpus, records)
    stats = generate_dashboard(
        config_path=_write_config(tmp_path, corpus), output_dir=tmp_path / "out"
    )
    assert (stats.timestamp_sources, stats.record_count) == (1, 6)
    html = (tmp_path / "out" / "index.html").read_text()
    assert "Latest curation 2026-07-02T00:00:00+00:00" in html
    assert "from 1 of" in html and "6 records" in html


def test_timestamp_paths_config_key_is_honoured_end_to_end(tmp_path):
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, {
        "a": {"name": "A",
              "curation_history": _hist("2026-01-01T00:00:00+00:00"),
              "provenance": {"modified": "2026-08-08T00:00:00+00:00"}},
    })
    config = _write_config(
        tmp_path, corpus, timestamp_paths=["provenance.modified"]
    )
    stats = generate_dashboard(config_path=config, output_dir=tmp_path / "out")
    assert stats.timestamp == "2026-08-08T00:00:00+00:00"
