"""The shared SSSOM contract, rule by rule and against the fleet's real files.

Every rule was measured on the six SSSOM files three Mechs publish before it was
written, and the negative cases carry as much weight as the positives: the first
version reported 7,410 findings, of which 7,402 were CultureMech's deliberate
"nothing matched" rows. A check that buries eight real findings under thousands
of correct ones is a check people learn to ignore.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_sssom import (
    CORE_COLUMNS,
    SsssomProfile,
    check_file,
    check_mapping,
    read_mapping,
    summarise,
)

HEADER = "\t".join(CORE_COLUMNS)
PREAMBLE = (
    "# curie_map:\n"
    '#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"\n'
    '#   skos: "http://www.w3.org/2004/02/skos/core#"\n'
    '#   semapv: "https://w3id.org/semapv/vocab/"\n'
    '#   sssom: "https://w3id.org/sssom/"\n'
)


def row(**over: str) -> str:
    values = {
        "subject_id": "CHEBI:1",
        "subject_label": "a",
        "predicate_id": "skos:exactMatch",
        "object_id": "CHEBI:2",
        "object_label": "b",
        "mapping_justification": "semapv:ManualMappingCuration",
        "confidence": "0.9",
        "comment": "",
    }
    values.update(over)
    return "\t".join(values[c] for c in CORE_COLUMNS)


def doc(*rows: str, preamble: str = PREAMBLE, header: str = HEADER) -> str:
    return preamble + header + "\n" + "\n".join(rows) + "\n"


def codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_a_well_formed_mapping_reports_nothing():
    assert check_mapping(read_mapping(doc(row()))) == []


# -- the shared core --------------------------------------------------------


def test_the_core_is_what_every_mech_already_writes():
    """Not an invention. Measured across MediaIngredientMech's canonical
    ingredient mapping, its research proposal, three CultureMech ChEBI exports
    and TraitMech's METPO proposal -- these eight are in all six."""
    assert CORE_COLUMNS == (
        "subject_id",
        "subject_label",
        "predicate_id",
        "object_id",
        "object_label",
        "mapping_justification",
        "confidence",
        "comment",
    )


def test_a_missing_core_column_is_reported():
    header = "\t".join(c for c in CORE_COLUMNS if c != "confidence")
    text = PREAMBLE + header + "\nCHEBI:1\ta\tskos:exactMatch\tCHEBI:2\tb\tsemapv:X\t\n"
    findings = check_mapping(read_mapping(text))
    assert "MISSING_CORE_COLUMN" in codes(findings)
    assert "confidence" in str(findings[0])


def test_a_repeated_column_is_reported():
    header = HEADER + "\tcomment"
    assert "DUPLICATE_COLUMN" in codes(
        check_mapping(read_mapping(doc(row() + "\tx", header=header)))
    )


# -- extensions -------------------------------------------------------------


def test_a_column_that_is_not_an_sssom_slot_must_be_declared():
    """SSSOM permits extensions, so the only way an undeclared one can be caught
    is by declaring the rest. `source` and `validation_method` are the live
    example: MediaIngredientMech writes both and neither is an SSSOM slot, so a
    consumer cannot tell whether `source` means mapping_source or subject_source."""
    text = doc(row() + "\tMIM:curator", header=HEADER + "\tsource")
    findings = check_mapping(read_mapping(text))
    assert codes(findings) == ["UNDECLARED_EXTENSION"]
    assert "source" in str(findings[0])

    declared = SsssomProfile(extensions=("source",))
    assert check_mapping(read_mapping(text), declared) == []


def test_a_real_sssom_slot_needs_no_declaration():
    """`other` and `mapping_source` look like the odd ones out and are standard;
    the slot list is read from the installed schema rather than typed here, so
    the check cannot be wrong about which is which."""
    for slot in ("other", "mapping_source", "mapping_tool", "object_source"):
        text = doc(row() + "\tx", header=HEADER + f"\t{slot}")
        assert check_mapping(read_mapping(text)) == [], slot


# -- the curie_map ----------------------------------------------------------


def test_a_file_with_no_preamble_cannot_be_resolved():
    """TraitMech's METPO proposals carry no preamble, so a reader cannot expand
    METPO:0000001 without knowing the convention out of band."""
    findings = check_mapping(read_mapping(doc(row(), preamble="")))
    assert "NO_CURIE_MAP" in codes(findings)


def test_a_prefix_used_but_not_declared_is_reported():
    """CultureMech's ChEBI exports use ENVO, FOODON and UBERON without declaring
    them; those CURIEs cannot be resolved from the file alone."""
    findings = check_mapping(read_mapping(doc(row(object_id="ENVO:1"))))
    assert "PREFIX_NOT_IN_CURIE_MAP" in codes(findings)
    assert "ENVO" in str(findings[0])


def test_a_declared_prefix_that_is_never_used_is_not_a_finding():
    """Untidy, not wrong. A file that uses prefixes it never declares is
    unreadable; one that declares prefixes it never uses is merely generous."""
    assert check_mapping(read_mapping(doc(row()))) == []


def test_an_iri_needs_no_prefix():
    text = doc(row(object_id="http://purl.obolibrary.org/obo/CHEBI_2"))
    assert check_mapping(read_mapping(text)) == []


# -- rows that say nothing matched ------------------------------------------


def test_an_unmapped_row_may_have_no_object():
    """CultureMech writes 3,664 of these with `semapv:Unmapped`. Reporting them
    as empty identifiers is what made the first version of this check useless."""
    text = doc(row(predicate_id="semapv:Unmapped", object_id="", object_label="",
                   confidence="0.0"))
    assert check_mapping(read_mapping(text)) == []


def test_the_sssom_spelling_of_no_match_is_also_accepted():
    text = doc(row(object_id="sssom:NoTermFound", object_label=""))
    assert check_mapping(read_mapping(text)) == []


def test_an_unmapped_row_that_carries_an_object_contradicts_itself():
    text = doc(row(predicate_id="semapv:Unmapped", object_id="CHEBI:2"))
    findings = check_mapping(read_mapping(text))
    assert "UNMAPPED_ROW_HAS_AN_OBJECT" in codes(findings)


def test_a_mapped_row_still_needs_an_object():
    text = doc(row(object_id="", object_label=""))
    assert "EMPTY_IDENTIFIER" in codes(check_mapping(read_mapping(text)))


# -- per-row rules ----------------------------------------------------------


def test_a_confidence_that_is_a_word_is_reported():
    """TraitMech's proposals use high/medium where SSSOM defines a 0..1 double."""
    findings = check_mapping(read_mapping(doc(row(confidence="high"))))
    assert codes(findings) == ["CONFIDENCE_NOT_A_NUMBER"]


@pytest.mark.parametrize("value", ["1.5", "-0.1"])
def test_a_confidence_outside_zero_to_one_is_reported(value):
    assert "CONFIDENCE_OUT_OF_RANGE" in codes(
        check_mapping(read_mapping(doc(row(confidence=value))))
    )


@pytest.mark.parametrize("value", ["0", "1", "0.0", "1.0", ""])
def test_the_endpoints_and_an_absent_confidence_are_fine(value):
    assert check_mapping(read_mapping(doc(row(confidence=value)))) == []


def test_an_identifier_that_is_not_a_curie_is_reported():
    findings = check_mapping(read_mapping(doc(row(object_id="just some text"))))
    assert "NOT_A_CURIE" in codes(findings)


def test_a_ragged_row_is_reported_once():
    text = PREAMBLE + HEADER + "\nCHEBI:1\ta\tskos:exactMatch\n"
    assert "RAGGED_ROW" in codes(check_mapping(read_mapping(text)))


def test_the_same_mapping_twice_is_reported():
    findings = check_mapping(read_mapping(doc(row(), row())))
    assert codes(findings) == ["DUPLICATE_MAPPING"]
    assert "row 1" in str(findings[0])


def test_the_same_triple_with_different_evidence_is_not_a_duplicate():
    """SSSOM records independent evidence for one mapping as separate rows
    differing in mapping_justification. CultureMech has 1,819 such pairs across
    two files -- every one legitimate, and not one an identical row. Keying the
    duplicate rule on the triple alone reported all of them, which is how a
    check becomes noise."""
    first = row(mapping_justification="semapv:LexicalMatching")
    second = row(mapping_justification="semapv:ManualMappingCuration")
    assert check_mapping(read_mapping(doc(first, second))) == []


def test_only_an_identical_row_is_a_duplicate():
    assert codes(check_mapping(read_mapping(doc(row(), row())))) == ["DUPLICATE_MAPPING"]


def test_the_same_subject_mapped_to_two_objects_is_not_a_duplicate():
    """One term legitimately maps to several; only an identical triple repeats."""
    assert check_mapping(read_mapping(doc(row(), row(object_id="CHEBI:3")))) == []


def test_an_empty_file_says_so_rather_than_passing():
    assert codes(check_mapping(read_mapping("# curie_map:\n"))) == ["EMPTY_FILE"]


# -- against the fleet's real files ------------------------------------------

MANIFEST = load_fleet_manifest()
CLAW_ROOT = Path(__file__).resolve().parents[1]

#: What each Mech publishes, and the state it is in. A ledger rather than a
#: skip, so it fails in both directions and can only shrink: when a Mech
#: declares its extensions or adds a curie_map, the test says so.
CORPUS = {
    "mediaingredientmech": (
        "mappings/ingredient_mappings.sssom.tsv",
        {"UNDECLARED_EXTENSION": 1},
    ),
    "mediaingredientmech#proposal": (
        "mappings/microbedecoder_residual_research_proposed.sssom.tsv",
        {"UNDECLARED_EXTENSION": 1},
    ),
    "culturemech": (
        "output/culturemech_chebi_mappings_exact.sssom.tsv",
        {"UNDECLARED_EXTENSION": 1, "PREFIX_NOT_IN_CURIE_MAP": 1},
    ),
    "culturemech#re_enriched": (
        "output/culturemech_chebi_mappings_re_enriched.sssom.tsv",
        {"UNDECLARED_EXTENSION": 1, "PREFIX_NOT_IN_CURIE_MAP": 1},
    ),
    "culturemech#unmapped": ("output/unmapped_after_exact.sssom.tsv", {}),
    "traitmech": (
        "proposals/metpo_traitmech_v11/metpo_proposal_mappings.sssom.tsv",
        {"NO_CURIE_MAP": 1, "CONFIDENCE_NOT_A_NUMBER": 5},
    ),
}


@pytest.mark.parametrize(("key", "spec"), sorted(CORPUS.items()))
def test_the_real_files_report_exactly_what_was_measured(key, spec):
    """The measured baseline, kept. Eight findings across five files; anything
    else means the corpus moved or the rule did, and both are worth knowing."""
    relative, expected = spec
    mech = key.split("#")[0]
    try:
        root = resolve_mech_root(mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a {mech} checkout: {exc}")
    path = root / relative
    if not path.is_file():
        pytest.skip(f"{mech} has no {relative} here")
    assert summarise(check_file(path)) == expected


def test_culturemechs_unmapped_export_is_clean():
    """3,746 rows with no object, and not one finding. This file is the reason
    the "nothing matched" rule exists -- it was 3,746 false positives before."""
    try:
        root = resolve_mech_root("culturemech", claw_root=CLAW_ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a culturemech checkout: {exc}")
    path = root / "output/unmapped_after_exact.sssom.tsv"
    if not path.is_file():
        pytest.skip("no unmapped export here")
    mapping = read_mapping(path.read_text(encoding="utf-8", errors="replace"))
    assert len(mapping.rows) > 3000
    assert sum(1 for r in mapping.rows if not (r.get("object_id") or "").strip()) == len(
        mapping.rows
    )
    assert check_file(path) == []
