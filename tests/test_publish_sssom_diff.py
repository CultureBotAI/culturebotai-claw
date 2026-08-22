"""Row-set diff behind the publish-sssom truncation guard (MediaIngredientMech#416).

The guard used to compare row counts, which reports churn as one net number: on
2026-08-21 a 155-out/102-in difference -- 88 of which were the same records under
a re-spelled subject -- surfaced only as "-53", indistinguishable from a
truncation. These tests pin the distinction the count could not make.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "publish_sssom", Path(__file__).resolve().parents[1] / "scripts" / "publish_sssom.py"
)
publish_sssom = importlib.util.module_from_spec(_SPEC)
# Register before exec: @dataclass resolves annotations via
# sys.modules[cls.__module__], which is None for an unregistered module.
sys.modules[_SPEC.name] = publish_sssom
_SPEC.loader.exec_module(publish_sssom)

diff_rows = publish_sssom.diff_rows
_spelling_key = publish_sssom._spelling_key


def row(subject, obj, predicate="skos:exactMatch"):
    return {"subject_id": subject, "object_id": obj, "predicate_id": predicate}


def test_identical_row_sets_produce_an_empty_diff():
    rows = [row("MIM:Glucose", "CHEBI:17234"), row("MIM:Edta_Stock", "CHEBI:4735")]

    diff = diff_rows(rows, list(rows))

    assert diff.is_empty
    assert diff.unchanged == 2


def test_a_genuinely_removed_row_is_reported_as_removed():
    prev = [row("MIM:Glucose", "CHEBI:17234"), row("MIM:Dropped", "CHEBI:99999")]
    new = [row("MIM:Glucose", "CHEBI:17234")]

    diff = diff_rows(prev, new)

    assert diff.removed == [("MIM:Dropped", "CHEBI:99999")]
    assert diff.added == []
    assert diff.respelled == []


def test_a_new_row_is_reported_as_added():
    prev = [row("MIM:Glucose", "CHEBI:17234")]
    new = [row("MIM:Glucose", "CHEBI:17234"), row("MIM:Fresh", "CHEBI:12345")]

    diff = diff_rows(prev, new)

    assert diff.added == [("MIM:Fresh", "CHEBI:12345")]
    assert diff.removed == []


@pytest.mark.parametrize(
    ("published", "rebuilt"),
    [
        # Letter case -- the capitalize() scar from MediaIngredientMech#147.
        ("MIM:EDTA_Stock", "MIM:Edta_Stock"),
        ("MIM:ATCC_Wolfes_mineral_mix", "MIM:ATCC_Wolfes_Mineral_Mix"),
        ("MIM:BG-11_Trace_Metals_Solution", "MIM:Bg-11_Trace_Metals_Solution"),
        # ~HEX escaping -- the published side carries literal parens, which
        # MIM's own _CURIE_RE rejects.
        ("MIM:(R)-lactate", "MIM:~28R~29-lactate"),
        ("MIM:Calcium(2)", "MIM:Calcium~282~29"),
        ("MIM:Tryptoneyeastbeef_(tyb)", "MIM:Tryptoneyeastbeef_~28tyb~29"),
    ],
)
def test_subject_respellings_are_not_removals(published, rebuilt):
    diff = diff_rows([row(published, "CHEBI:17234")], [row(rebuilt, "CHEBI:17234")])

    assert diff.removed == [], "a re-spelled subject must not read as a truncation"
    assert diff.added == []
    assert diff.respelled == [(published, rebuilt, "CHEBI:17234")]


@pytest.mark.parametrize(
    ("published", "rebuilt"),
    [
        # An older naming rule *stripped* the parens instead of escaping them,
        # so the stem itself differs -- not recoverable by normalisation.
        ("MIM:Synthetic_Sea_Salts_sss", "MIM:Synthetic_Sea_Salts_~28sss~29"),
        ("MIM:Sodium", "MIM:Sodium~28~29"),
        # A genuine relabel (MediaIngredientMech#236).
        ("MIM:2-phenylethylamine", "MIM:Phenethylamine_Hydrochloride"),
    ],
)
def test_a_changed_stem_is_not_silently_paired_as_a_respelling(published, rebuilt):
    """Only case and `~HEX` escaping are treated as spelling.

    Anything else -- a stripped character, a relabel -- is reported for a human
    to confirm. Pairing them automatically would need a lossy normalisation that
    could collapse two genuinely distinct records onto one key, and a guard that
    guesses is the failure mode this whole change exists to remove.
    """
    diff = diff_rows([row(published, "CHEBI:17234")], [row(rebuilt, "CHEBI:17234")])

    assert diff.respelled == []
    assert diff.removed == [(published, "CHEBI:17234")]
    assert diff.added == [(rebuilt, "CHEBI:17234")]


def test_a_respelling_onto_a_different_object_is_not_a_respelling():
    """Same record, different target, is a real mapping change -- gate it."""
    diff = diff_rows(
        [row("MIM:EDTA_Stock", "CHEBI:4735")],
        [row("MIM:Edta_Stock", "CHEBI:64755")],
    )

    assert diff.respelled == []
    assert diff.removed == [("MIM:EDTA_Stock", "CHEBI:4735")]
    assert diff.added == [("MIM:Edta_Stock", "CHEBI:64755")]


def test_predicate_flip_on_a_shared_key_is_reported_and_not_counted_unchanged():
    diff = diff_rows(
        [row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch")],
        [row("MIM:Glucose", "CHEBI:17234", "skos:narrowMatch")],
    )

    assert diff.flipped == [
        ("MIM:Glucose", "CHEBI:17234", "skos:exactMatch", "skos:narrowMatch")
    ]
    assert diff.unchanged == 0
    assert diff.removed == []


def test_churn_is_separated_rather_than_netted_out():
    """The shape the count guard could not see: rows out AND rows in."""
    prev = [
        row("MIM:EDTA_Stock", "CHEBI:4735"),          # re-spelled below
        row("MIM:(R)-lactate", "CHEBI:16004"),        # re-spelled below
        row("MIM:Retired", "kgmicrobe.compound:retired"),  # genuinely gone
    ]
    new = [
        row("MIM:Edta_Stock", "CHEBI:4735"),
        row("MIM:~28R~29-lactate", "CHEBI:16004"),
        row("MIM:Brand_New", "CHEBI:12345"),
    ]

    diff = diff_rows(prev, new)

    # A count guard sees 3 -> 3 and waves this through; a naive set diff sees
    # 3 out / 3 in and blocks. Only one row actually left the mapping set.
    assert len(diff.respelled) == 2
    assert diff.removed == [("MIM:Retired", "kgmicrobe.compound:retired")]
    assert diff.added == [("MIM:Brand_New", "CHEBI:12345")]


def test_spelling_key_is_idempotent_on_an_already_escaped_subject():
    """`~` is safe, so normalising an escaped subject twice is a fixed point."""
    once = _spelling_key("MIM:~28R~29-lactate")

    assert _spelling_key(once) == once


def test_spelling_key_does_not_collapse_distinct_records():
    assert _spelling_key("MIM:Glucose") != _spelling_key("MIM:Galactose")


def test_spelling_key_tolerates_a_subject_without_a_prefix():
    assert _spelling_key("bare_subject") == "bare_subject"


def test_duplicate_subject_object_pairs_are_counted_not_swallowed():
    """Keying on (subject, object) drops repeats -- the diff must admit it."""
    prev = [
        row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch"),
        row("MIM:Glucose", "CHEBI:17234", "skos:closeMatch"),
    ]
    new = [row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch")]

    diff = diff_rows(prev, new)

    assert diff.collapsed_prev == 1
    assert diff.collapsed_new == 0


def test_no_duplicates_reports_no_collapse():
    diff = diff_rows([row("MIM:Glucose", "CHEBI:17234")], [row("MIM:Glucose", "CHEBI:17234")])

    assert diff.collapsed_prev == 0
    assert diff.collapsed_new == 0


def test_respelling_choice_is_deterministic_across_orderings():
    """Two added rows can share a spelling key; the pairing must not vary."""
    prev = [row("MIM:FOO_BAR", "CHEBI:1")]
    variants = [row("MIM:Foo_Bar", "CHEBI:1"), row("MIM:foo_bar", "CHEBI:1")]

    forward = diff_rows(prev, list(variants))
    reversed_ = diff_rows(prev, list(reversed(variants)))

    assert forward.respelled == reversed_.respelled
    assert forward.added == reversed_.added


def test_read_rows_skips_the_yaml_preamble(tmp_path):
    path = tmp_path / "m.sssom.tsv"
    path.write_text(
        "# curie_map:\n"
        '#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"\n'
        "subject_id\tpredicate_id\tobject_id\n"
        "MIM:Glucose\tskos:exactMatch\tCHEBI:17234\n"
    )

    rows = publish_sssom._read_rows(path)

    assert rows == [
        {
            "subject_id": "MIM:Glucose",
            "predicate_id": "skos:exactMatch",
            "object_id": "CHEBI:17234",
        }
    ]


def test_read_rows_on_a_missing_file_is_empty_not_an_error(tmp_path):
    assert publish_sssom._read_rows(tmp_path / "absent.tsv") == []
