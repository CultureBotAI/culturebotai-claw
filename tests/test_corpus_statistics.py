"""One comparable corpus report for every Mech (#132 Phase 6, item 4).

The Mechs that have statistics scripts do not compute the same things:
CultureMech has three of them, MediaIngredientMech two, ProteinTraitsMech one. Put side
by side they answer different questions, so there is nothing to compare, which
is what the phase's acceptance criterion asks for.

ProteinTraitsMech's is the most developed and shows what is general and what is
not: walking a corpus and emitting deterministic JSON is; `trait_axis` and
`mapping_status`, compiled into it as regexes, are that Mech's own schema. So
the fields are declared per Mech in the manifest and everything else lives once
in `kg_microbe_corpus`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kg_microbe_corpus import CorpusError, collect, iter_records, resolve_value
from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root

ROOT = Path(__file__).resolve().parents[1]


def _corpus(tmp_path: Path, records: dict[str, object]) -> Path:
    root = tmp_path / "repo"
    for name, content in records.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            content if isinstance(content, str) else yaml.safe_dump(content),
            encoding="utf-8",
        )
    return root


# --------------------------------------------------------------------------
# Reading the corpus
# --------------------------------------------------------------------------


def test_records_and_bytes_are_counted(tmp_path):
    root = _corpus(tmp_path, {"d/a.yaml": {"x": 1}, "d/b.yaml": {"x": 2}})

    report = collect("m", root, ["d/*.yaml"])

    assert report.records == 2
    assert report.bytes == sum(p.stat().st_size for p in (root / "d").iterdir())


def test_a_file_matching_two_globs_is_counted_once(tmp_path):
    """Otherwise the record total exceeds the number of files, and two Mechs'
    reports stop being comparable for a reason nothing states."""
    root = _corpus(tmp_path, {"d/a.yaml": {"x": 1}})

    report = collect("m", root, ["d/*.yaml", "**/*.yaml"])

    assert report.records == 1
    assert report.by_glob == {"d/*.yaml": 1, "**/*.yaml": 0}


def test_an_unparseable_record_is_named_and_excluded(tmp_path):
    """One broken record must not hide the statistics for the rest, and a
    report that stayed silent would understate the corpus without saying so."""
    root = _corpus(tmp_path, {"d/a.yaml": {"x": 1}, "d/b.yaml": "{unclosed"})

    report = collect("m", root, ["d/*.yaml"])

    assert report.records == 1
    assert report.unreadable == ["d/b.yaml"]


def test_the_corpus_must_exist(tmp_path):
    with pytest.raises(CorpusError, match="is not a directory"):
        collect("m", tmp_path / "absent", ["*.yaml"])


def test_no_globs_is_refused_rather_than_reporting_an_empty_corpus(tmp_path):
    """Zero records and "no globs declared" look identical in a report and mean
    entirely different things."""
    with pytest.raises(CorpusError, match="no record globs"):
        collect("m", _corpus(tmp_path, {"a.yaml": {}}), [])


def test_records_are_read_in_a_stable_order(tmp_path):
    root = _corpus(tmp_path, {f"d/{n}.yaml": {"x": n} for n in "cabd"})

    order = [p.name for p, _ in iter_records(root, ["d/*.yaml"])]

    assert order == sorted(order), "a sample must be the same sample everywhere"


def test_a_sample_takes_the_first_n_in_that_order(tmp_path):
    root = _corpus(tmp_path, {f"d/{n}.yaml": {"x": n} for n in "abcde"})

    report = collect("m", root, ["d/*.yaml"], sample=2)

    assert report.records == 2
    assert report.sampled is True


# --------------------------------------------------------------------------
# Fields
# --------------------------------------------------------------------------


def test_a_field_is_reported_as_populated_missing_and_distinct(tmp_path):
    root = _corpus(
        tmp_path,
        {
            "d/a.yaml": {"kind": "A"},
            "d/b.yaml": {"kind": "A"},
            "d/c.yaml": {"kind": "B"},
            "d/d.yaml": {"other": 1},
        },
    )

    stats = collect("m", root, ["d/*.yaml"], ["kind"]).fields["kind"]

    assert (stats.populated, stats.missing, stats.distinct) == (3, 1, 2)
    assert stats.top_values == (("A", 2), ("B", 1))


@pytest.mark.parametrize("empty", [None, "", [], {}])
def test_an_empty_value_counts_as_missing(tmp_path, empty):
    """A field present but blank is not populated; counting it would overstate
    coverage, which is the one thing this report is for."""
    root = _corpus(tmp_path, {"d/a.yaml": {"kind": empty}})

    assert collect("m", root, ["d/*.yaml"], ["kind"]).fields["kind"].missing == 1


def test_zero_is_populated(tmp_path):
    """`0` and `False` are values. Treating them as absent is the classic
    truthiness bug in a coverage counter."""
    root = _corpus(tmp_path, {"d/a.yaml": {"n": 0}, "d/b.yaml": {"n": False}})

    assert collect("m", root, ["d/*.yaml"], ["n"]).fields["n"].populated == 2


def test_ties_are_broken_by_value_so_the_report_is_deterministic(tmp_path):
    root = _corpus(
        tmp_path, {"d/a.yaml": {"k": "b"}, "d/b.yaml": {"k": "a"}, "d/c.yaml": {"k": "c"}}
    )

    stats = collect("m", root, ["d/*.yaml"], ["k"]).fields["k"]

    assert stats.top_values == (("a", 1), ("b", 1), ("c", 1))


def test_a_dotted_field_is_followed(tmp_path):
    root = _corpus(tmp_path, {"d/a.yaml": {"mapping": {"quality": "EXACT"}}})

    stats = collect("m", root, ["d/*.yaml"], ["mapping.quality"]).fields["mapping.quality"]

    assert stats.top_values == (("EXACT", 1),)


def test_a_dotted_field_finds_the_first_list_element_that_has_it(tmp_path):
    """One Mech's `ontology_mapping` is a mapping and another's is a list of
    them. Following either is what lets one declared name mean one thing."""
    record = {"ontology_mapping": [{"other": 1}, {"quality": "EXACT"}]}

    assert resolve_value(record, "ontology_mapping.quality") == "EXACT"


@pytest.mark.parametrize(
    "record", [{"a": "scalar"}, {"a": [1, 2]}, {}, {"a": None}]
)
def test_an_unreachable_path_resolves_to_none_rather_than_raising(record):
    assert resolve_value(record, "a.b.c") is None


def test_a_record_that_is_not_a_mapping_does_not_crash_the_walk(tmp_path):
    """A YAML list where a record was expected parses fine and has no fields."""
    root = _corpus(tmp_path, {"d/a.yaml": "- one\n- two\n"})

    report = collect("m", root, ["d/*.yaml"], ["kind"])

    assert report.records == 1
    assert report.fields["kind"].missing == 1


# --------------------------------------------------------------------------
# The report itself
# --------------------------------------------------------------------------


def test_the_report_is_deterministic_json(tmp_path):
    """A report that changes when nothing changed cannot be diffed between
    releases, which is most of what makes one worth keeping."""
    root = _corpus(tmp_path, {"d/b.yaml": {"k": "x"}, "d/a.yaml": {"k": "y"}})

    first = collect("m", root, ["d/*.yaml"], ["k"]).to_json()
    second = collect("m", root, ["d/*.yaml"], ["k"]).to_json()

    assert first == second
    assert json.loads(first)["mech"] == "m"


def test_the_report_carries_no_absolute_paths(tmp_path):
    root = _corpus(tmp_path, {"d/a.yaml": "{unclosed"})

    text = collect("m", root, ["d/*.yaml"]).to_json()

    assert str(root) not in text, "a report keyed to one machine cannot be compared"


# --------------------------------------------------------------------------
# Against the real corpora
# --------------------------------------------------------------------------


def _declared() -> list[tuple[str, tuple[str, ...]]]:
    manifest = load_fleet_manifest()
    return [
        (key, mech.capabilities["corpus_statistics"].settings.get("fields", ()))
        for key, mech in manifest.mechs.items()
        if mech.capabilities["corpus_statistics"].is_enabled
    ]


def test_every_mech_declares_the_fields_its_report_tabulates():
    declared = _declared()

    assert len(declared) == 6
    for key, fields in declared:
        assert fields, f"{key} enables corpus_statistics without naming fields"


@pytest.mark.parametrize(("mech", "fields"), _declared(), ids=lambda v: v if isinstance(v, str) else "")
def test_a_declared_field_is_one_the_corpus_actually_carries(mech, fields):
    """A field no record has reports "0 populated, N missing", which reads as a
    data problem rather than a wrong declaration. Every one of these was
    checked against its own corpus; one guess -- TraitMech's
    `ontology_mapping.mapping_quality` -- was wrong and is why this test exists.
    """
    try:
        root = resolve_mech_root(mech, claw_root=ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a {mech} checkout: {exc}")

    manifest = load_fleet_manifest()
    report = collect(
        mech, root, list(manifest.mechs[mech].record_globs), fields, sample=400
    )
    if not report.records:
        pytest.skip(f"{mech} has no records at its declared globs here")

    empty = [name for name, stats in report.fields.items() if not stats.populated]
    assert not empty, (
        f"{mech} declares {empty}, which no sampled record carries; either the "
        f"declaration is wrong or the corpus is"
    )


def test_the_corpus_is_globbed_once(tmp_path, monkeypatch):
    """#231. `collect` needs the glob listing to attribute each file, and
    `iter_records` needs it to walk. Computing it twice cost ~13 s on
    ProteinTraitsMech's 429,271 records -- invisible on the corpora the other
    tests use, which are three orders of magnitude smaller."""
    from kg_microbe_corpus import statistics

    root = _corpus(tmp_path, {"d/a.yaml": {"x": 1}, "d/b.yaml": {"x": 2}})
    calls = {"n": 0}
    real = statistics._paths_by_glob

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(statistics, "_paths_by_glob", counted)
    statistics.collect("m", root, ["d/*.yaml"], ["x"])

    assert calls["n"] == 1
