"""Contracts for the cross-record consistency scanner (#129, first step).

The defect class this catches is a record that is internally self-consistent
but wrong, where a matching record elsewhere already has the right answer. The
existing checks structurally cannot see it: id/label correspondence compares a
CURIE to its own ontology label, and the QC dashboard measures completeness.
Neither compares two records.

The scanner reports; it never proposes or writes. Several real disagreements
are legitimate distinctions -- a specific enantiomer versus its parent -- so
deciding is a curator's job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_consistency import (
    COMPARED_FIELDS,
    ScannerError,
    normalize_name,
    scan,
)


def write(root: Path, stem: str, **fields) -> Path:
    mapping = {
        key: fields.pop(key)
        for key in ("ontology_id", "mapping_predicate")
        if key in fields
    }
    lines = [f"identifier: {fields.pop('identifier', 'UNMAPPED_0001')}"]
    lines.append(f"preferred_term: {fields.pop('preferred_term', stem)}")
    for key, value in fields.items():
        if key == "synonyms":
            lines.append("synonyms:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    if mapping:
        lines.append("ontology_mapping:")
        lines.extend(f"  {k}: {v}" for k, v in mapping.items())
    path = root / f"{stem}.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "ingredients"
    root.mkdir()
    return root


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def test_two_spellings_of_one_name_are_matched(corpus):
    """`2,6-dihydroxybenzoic acid` and `2-6-dihydroxybenzoic acid` are the same
    substance; only punctuation differs. Real instance from the MIM corpus."""
    write(corpus, "a", preferred_term="2,6-dihydroxybenzoic acid",
          identifier="cas:303-07-1", ontology_id="cas:303-07-1")
    write(corpus, "b", preferred_term="2-6-dihydroxybenzoic acid",
          identifier="cas:0303-07-1", ontology_id="cas:0303-07-1")

    report = scan(corpus)

    assert report["groups_disagreeing"] == 1
    assert report["findings"][0]["matched_on"] == "identical normalized name"


def test_distinct_stereoisomers_are_not_matched(corpus):
    """D- and L- forms are different substances. Collapsing them would produce
    a false finding on exactly the distinction MIM's mapping rules protect."""
    write(corpus, "d", preferred_term="D-lyxose", ontology_id="CHEBI:16789")
    write(corpus, "l", preferred_term="L-lyxose", ontology_id="CHEBI:62318")

    assert scan(corpus)["groups_disagreeing"] == 0


def test_a_shared_synonym_matches_records_with_different_names(corpus):
    write(corpus, "a", preferred_term="sodium chloride",
          synonyms=["table salt"], ontology_id="CHEBI:26710")
    write(corpus, "b", preferred_term="NaCl",
          synonyms=["table salt"], ontology_id="CHEBI:99999")

    report = scan(corpus)

    assert report["groups_disagreeing"] == 1
    assert report["findings"][0]["matched_on"] == "shared synonym"


def test_a_record_is_not_grouped_with_itself(corpus):
    write(corpus, "only", preferred_term="glucose", ontology_id="CHEBI:17234")

    assert scan(corpus)["groups_matched"] == 0


# --------------------------------------------------------------------------
# Disagreement
# --------------------------------------------------------------------------


def test_agreeing_records_are_not_reported(corpus):
    """Two records for one substance that agree are a duplicate, not a
    disagreement; the deduplicator owns that."""
    write(corpus, "a", preferred_term="glucose", ontology_id="CHEBI:17234")
    write(corpus, "b", preferred_term="Glucose", ontology_id="CHEBI:17234")

    report = scan(corpus)

    assert report["groups_matched"] == 1
    assert report["groups_disagreeing"] == 0


def test_an_absent_value_is_a_gap_not_a_contradiction(corpus):
    """Reporting gaps would bury the contradictions this exists to surface --
    and completeness is what the QC dashboard already measures."""
    write(corpus, "a", preferred_term="glucose", ontology_id="CHEBI:17234")
    write(corpus, "b", preferred_term="Glucose")

    assert scan(corpus)["groups_disagreeing"] == 0


def test_the_compared_field_set_is_pinned():
    """Parametrizing over COMPARED_FIELDS cannot notice a field being removed
    from it -- the test case disappears with the field and the suite stays
    green. The set is asserted explicitly so a removal is a decision.
    """
    assert set(COMPARED_FIELDS) == {
        "ontology_id",
        "mapping_predicate",
        "ingredient_type",
    }


@pytest.mark.parametrize("field_name", COMPARED_FIELDS)
def test_every_compared_field_is_actually_compared(corpus, field_name):
    """A field in COMPARED_FIELDS that nothing reads would be a silent gap."""
    values = {"ontology_id": ("CHEBI:1", "CHEBI:2"),
              "mapping_predicate": ("skos:exactMatch", "skos:closeMatch"),
              "ingredient_type": ("SINGLE_INGREDIENT", "NAMED_MEDIUM")}[field_name]
    write(corpus, "a", preferred_term="thing", **{field_name: values[0]})
    write(corpus, "b", preferred_term="Thing", **{field_name: values[1]})

    report = scan(corpus)

    assert report["groups_disagreeing"] == 1
    assert report["findings"][0]["disagreements"][0]["field"] == field_name


def test_a_disagreement_names_every_record_holding_each_value(corpus):
    """A curator has to see which record says what, or the report is unusable."""
    write(corpus, "a", preferred_term="thing", ontology_id="CHEBI:1")
    write(corpus, "b", preferred_term="Thing", ontology_id="CHEBI:2")

    values = scan(corpus)["findings"][0]["disagreements"][0]["values"]

    assert set(values) == {"CHEBI:1", "CHEBI:2"}
    assert all(len(paths) == 1 for paths in values.values())


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------


def test_a_record_without_an_identifier_is_skipped(corpus):
    (corpus / "bad.yaml").write_text("preferred_term: nameless\n", encoding="utf-8")
    write(corpus, "a", preferred_term="glucose", ontology_id="CHEBI:17234")

    assert scan(corpus)["records_scanned"] == 1


def test_unparseable_yaml_is_skipped_rather_than_fatal(corpus):
    (corpus / "broken.yaml").write_text("key: [unclosed\n", encoding="utf-8")
    write(corpus, "a", preferred_term="glucose", ontology_id="CHEBI:17234")

    assert scan(corpus)["records_scanned"] == 1


def test_a_missing_corpus_directory_is_refused(tmp_path):
    with pytest.raises(ScannerError, match="does not exist"):
        scan(tmp_path / "absent")


def test_normalization_matches_the_deduplicator_shape():
    """A second normalization would group differently from the tool that
    already merges duplicates."""
    assert normalize_name("  D-Lyxose  ") == "d_lyxose"
    assert normalize_name("2,6-dihydroxybenzoic acid") == "2_6_dihydroxybenzoic_acid"
    assert normalize_name("") == ""


def test_the_scanner_writes_nothing(corpus):
    """Read-only by construction: #129 requires every correction to be surfaced
    for human confirmation, never applied."""
    a = write(corpus, "a", preferred_term="thing", ontology_id="CHEBI:1")
    b = write(corpus, "b", preferred_term="Thing", ontology_id="CHEBI:2")
    before = {p: p.read_bytes() for p in (a, b)}

    scan(corpus)

    assert {p: p.read_bytes() for p in (a, b)} == before


# --------------------------------------------------------------------------
# #182: a new pairing must not be suppressed because its members are known
# --------------------------------------------------------------------------


def test_a_shared_synonym_pairing_survives_both_records_being_grouped(corpus):
    """#182: the one disagreement in the corpus was the one not reported.

    A and B agree under one name; C and D agree under another; A and C share a
    synonym and disagree. Suppressing by membership dropped exactly that.
    """
    write(corpus, "a", identifier="MIM:A", preferred_term="thing",
          synonyms=["shared"], ontology_id="CHEBI:1")
    write(corpus, "b", identifier="MIM:B", preferred_term="Thing",
          ontology_id="CHEBI:1")
    write(corpus, "c", identifier="MIM:C", preferred_term="other",
          synonyms=["shared"], ontology_id="CHEBI:9")
    write(corpus, "d", identifier="MIM:D", preferred_term="Other",
          ontology_id="CHEBI:9")

    report = scan(corpus)

    assert report["groups_disagreeing"] == 1
    finding = report["findings"][0]
    assert finding["matched_on"] == "shared synonym"
    assert {r["identifier"] for r in finding["records"]} == {"MIM:A", "MIM:C"}


def test_the_same_record_set_is_not_reported_twice(corpus):
    """Two records matching by BOTH name and synonym are one relationship."""
    write(corpus, "a", preferred_term="thing", synonyms=["thing"],
          ontology_id="CHEBI:1")
    write(corpus, "b", preferred_term="Thing", synonyms=["thing"],
          ontology_id="CHEBI:2")

    report = scan(corpus)

    assert report["groups_matched"] == 1
    assert report["groups_disagreeing"] == 1


def test_a_record_may_belong_to_more_than_one_relationship(corpus):
    """Each relationship is a separate question, so a record appearing in two
    is information rather than duplication."""
    write(corpus, "a", preferred_term="thing", synonyms=["alias"],
          ontology_id="CHEBI:1")
    write(corpus, "b", preferred_term="Thing", ontology_id="CHEBI:2")
    write(corpus, "c", preferred_term="other", synonyms=["alias"],
          ontology_id="CHEBI:3")

    report = scan(corpus)

    assert report["groups_disagreeing"] == 2
