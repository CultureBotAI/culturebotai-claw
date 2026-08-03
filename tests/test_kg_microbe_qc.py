"""Tests for the shared QC dashboard generator.

The load-bearing property here is that the dashboard is a pure function of
the corpus: regenerating an unchanged corpus must produce no diff, so that
"is the committed dashboard stale?" can be answered by regenerating and
diffing. See TraitMech#193.
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
    """An unquoted YAML scalar is loaded as datetime/date, not str."""
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
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) == (
        "2026-05-05T09:30:00+00:00"
    )


def test_corpus_timestamp_compares_instants_not_strings():
    """+02:00 noon precedes 11:00Z; a lexical max would pick the wrong one."""
    records = [
        {"curation_history": _hist("2026-01-01T12:00:00+02:00")},  # 10:00Z
        {"curation_history": _hist("2026-01-01T11:00:00Z")},       # 11:00Z
    ]
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) == (
        "2026-01-01T11:00:00+00:00"
    )


def test_corpus_timestamp_is_none_when_no_record_carries_one():
    """CommunityMech's corpus is largely provenance-free; must not guess."""
    records = [{"name": "a"}, {"name": "b", "curation_history": []}]
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) is None


def test_corpus_timestamp_ignores_unparseable_entries_but_keeps_good_ones():
    records = [
        {"curation_history": _hist("garbage")},
        {"curation_history": _hist("2026-04-04T00:00:00+00:00")},
        {"curation_history": [{"action": "edit"}]},  # no timestamp key
    ]
    assert _corpus_timestamp(records, ["curation_history.timestamp"]) == (
        "2026-04-04T00:00:00+00:00"
    )


def test_corpus_timestamp_honours_a_configured_path():
    records = [{"provenance": {"modified": "2026-07-07T00:00:00+00:00"}}]
    assert _corpus_timestamp(records, ["provenance.modified"]) == (
        "2026-07-07T00:00:00+00:00"
    )


# --------------------------------------------------------------------------
# generate_dashboard — the end-to-end determinism property
# --------------------------------------------------------------------------

def test_regenerating_an_unchanged_corpus_produces_no_diff(tmp_path):
    """The property TraitMech#193 asks for: rerun => byte-identical output."""
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


def test_dashboard_timestamp_tracks_the_corpus_not_the_clock(tmp_path):
    """The strong form: the rendered date is the corpus max, and the run
    happens 'now', so a clock read would show today instead."""
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
    this_year = str(_dt.datetime.now(_dt.timezone.utc).year)
    assert not re.search(rf"Generated {this_year}", html)


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

    html = (tmp_path / "out" / "index.html").read_text()
    assert "Corpus date unknown" in html
    # no ISO-8601 instant anywhere in the page
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", html)


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
