"""Correct-by-analogy proposals (#129 item 2).

The rule is deliberately narrow. #129 is explicit that this is not a
conflict-resolution engine: for a case like MediaIngredientMech#225, where one
substance carries two different CHEBI IDs, the tool's job is to surface the
disagreement with both records' evidence, not to pick a winner.

So exactly one shape is proposed -- an ontology-grounded record beside a
registry or placeholder fallback for the same substance -- and everything else
is reported untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_consistency import (
    build_proposals,
    is_fallback,
    is_ontology_grounded,
    render_markdown,
)


def write(root: Path, stem: str, *, identifier: str, term: str,
          ontology_id: str = "", quality: str = "", source: str = "") -> Path:
    lines = [f"identifier: {identifier}", f"preferred_term: {term}"]
    if ontology_id or quality or source:
        lines.append("ontology_mapping:")
        if ontology_id:
            lines.append(f"  ontology_id: {ontology_id}")
        if quality:
            lines.append(f"  mapping_quality: {quality}")
        if source:
            lines.append(f"  ontology_source: {source}")
    path = root / f"{stem}.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "ingredients"
    root.mkdir()
    return root


# --------------------------------------------------------------------------
# The one shape that is proposed
# --------------------------------------------------------------------------


def test_a_fallback_beside_a_grounded_twin_gets_a_proposal(corpus):
    """The real case: a CAS fallback whose own note says to promote to CHEBI
    "if/when CHEBI adds the term", beside a twin that is already CHEBI."""
    write(corpus, "a", identifier="CHEBI:74863", term="Methyl Beta-D-xylopyranoside",
          ontology_id="CHEBI:74863", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="cas:612-05-5", term="methyl-beta-D-xylopyranoside",
          ontology_id="cas:612-05-5", quality="FALLBACK_REGISTRY", source="CAS")

    report = build_proposals(corpus)

    assert len(report["proposals"]) == 1
    proposal = report["proposals"][0]
    assert proposal["current"] == "cas:612-05-5"
    assert proposal["proposed"] == "CHEBI:74863"
    assert proposal["analogous_identifier"] == "CHEBI:74863"
    assert "An ontology term exists" in proposal["justification"]


def test_a_proposal_cites_the_record_that_justifies_it(corpus):
    """A proposal without its analogue is an assertion; with it, a curator can
    check the reasoning."""
    write(corpus, "a", identifier="CHEBI:1", term="thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="cas:2", term="Thing",
          ontology_id="cas:2", quality="FALLBACK_REGISTRY", source="CAS")

    proposal = build_proposals(corpus)["proposals"][0]

    assert Path(proposal["analogous_record"]).name == "a.yaml"
    assert Path(proposal["record"]).name == "b.yaml"


# --------------------------------------------------------------------------
# Everything else is surfaced, never resolved
# --------------------------------------------------------------------------


def test_two_ontology_groundings_are_surfaced_without_a_proposal(corpus):
    """MediaIngredientMech#225's shape. There is no basis in the data for
    choosing between CHEBI:16789 and CHEBI:62318, and inventing one is what
    #129 warns against."""
    write(corpus, "a", identifier="CHEBI:16789", term="D-lyxose",
          ontology_id="CHEBI:16789", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="CHEBI:62318", term="D-Lyxose",
          ontology_id="CHEBI:62318", quality="EXACT_MATCH", source="CHEBI")

    report = build_proposals(corpus)

    assert report["proposals"] == []
    assert len(report["surfaced_without_proposal"]) == 1


def test_two_fallbacks_yield_no_proposal(corpus):
    """Neither has the answer, so there is nothing to copy."""
    write(corpus, "a", identifier="cas:303-07-1", term="2,6-dihydroxybenzoic acid",
          ontology_id="cas:303-07-1", quality="FALLBACK_REGISTRY", source="CAS")
    write(corpus, "b", identifier="cas:0303-07-1", term="2-6-dihydroxybenzoic acid",
          ontology_id="cas:0303-07-1", quality="FALLBACK_REGISTRY", source="CAS")

    report = build_proposals(corpus)

    assert report["proposals"] == []
    assert len(report["surfaced_without_proposal"]) == 1


def test_agreeing_records_produce_nothing(corpus):
    write(corpus, "a", identifier="CHEBI:1", term="thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="CHEBI:1", term="Thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")

    report = build_proposals(corpus)

    assert report["proposals"] == []
    assert report["surfaced_without_proposal"] == []


def test_more_than_one_grounded_record_blocks_a_proposal(corpus):
    """With two candidate answers there is no single analogue to cite."""
    write(corpus, "a", identifier="CHEBI:1", term="thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="CHEBI:2", term="Thing",
          ontology_id="CHEBI:2", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "c", identifier="cas:3", term="THING",
          ontology_id="cas:3", quality="FALLBACK_REGISTRY", source="CAS")

    assert build_proposals(corpus)["proposals"] == []


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quality", ["FALLBACK_REGISTRY", "PLACEHOLDER", "CAS_RN_LOOKUP"]
)
def test_measured_fallback_qualities_are_recognised(corpus, quality):
    """Values measured against the real corpus, not assumed."""
    from kg_microbe_consistency import load_record

    path = write(corpus, "a", identifier="x:1", term="t",
                 ontology_id="x:1", quality=quality)

    assert is_fallback(load_record(path)) is True


@pytest.mark.parametrize("quality", ["EXACT_MATCH", "SYNONYM_MATCH"])
def test_identity_qualities_count_as_grounded(corpus, quality):
    """SYNONYM_MATCH belongs here: a synonym match is an exact identity, not a
    close one."""
    from kg_microbe_consistency import load_record

    path = write(corpus, "a", identifier="CHEBI:1", term="t",
                 ontology_id="CHEBI:1", quality=quality, source="CHEBI")

    assert is_ontology_grounded(load_record(path)) is True


@pytest.mark.parametrize("quality", ["CLOSE_MATCH", "NARROW_MATCH", "BROAD_MATCH"])
def test_non_identity_qualities_are_not_treated_as_grounded(corpus, quality):
    """A narrower or broader term is not this substance's identity, so it is
    not an answer another record should copy."""
    from kg_microbe_consistency import load_record

    path = write(corpus, "a", identifier="CHEBI:1", term="t",
                 ontology_id="CHEBI:1", quality=quality, source="CHEBI")

    assert is_ontology_grounded(load_record(path)) is False


def test_a_minted_identifier_is_a_fallback(corpus):
    from kg_microbe_consistency import load_record

    path = write(corpus, "a", identifier="kgmicrobe.ingredient:x", term="t",
                 ontology_id="kgmicrobe.ingredient:x", quality="EXACT_MATCH")

    assert is_fallback(load_record(path)) is True


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def test_the_report_states_that_nothing_was_applied(corpus):
    write(corpus, "a", identifier="CHEBI:1", term="thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="cas:2", term="Thing",
          ontology_id="cas:2", quality="FALLBACK_REGISTRY", source="CAS")

    text = render_markdown(build_proposals(corpus))

    assert "Nothing here has been applied" in text
    assert "needs a curator's decision" in text


def test_building_proposals_writes_nothing(corpus):
    a = write(corpus, "a", identifier="CHEBI:1", term="thing",
              ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    b = write(corpus, "b", identifier="cas:2", term="Thing",
              ontology_id="cas:2", quality="FALLBACK_REGISTRY", source="CAS")
    before = {p: p.read_bytes() for p in (a, b)}

    build_proposals(corpus)

    assert {p: p.read_bytes() for p in (a, b)} == before


# --------------------------------------------------------------------------
# #190: one traversal answers both questions
# --------------------------------------------------------------------------


def test_propose_reads_the_corpus_once(corpus, monkeypatch):
    """`scan_groups` was extracted so the scan and the proposals could not
    disagree about what "the same substance" means. Traversing twice
    reintroduces exactly that possibility at the only place both are used."""
    from kg_microbe_consistency import __main__ as cli
    from kg_microbe_consistency import scanner

    write(corpus, "a", identifier="CHEBI:1", term="thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="cas:2", term="Thing",
          ontology_id="cas:2", quality="FALLBACK_REGISTRY", source="CAS")

    calls = []
    original = scanner.load_corpus
    monkeypatch.setattr(
        scanner, "load_corpus",
        lambda *a, **k: (calls.append(1), original(*a, **k))[1],
    )

    assert cli.main(["--corpus", str(corpus), "--propose"]) == 0
    assert len(calls) == 1, f"corpus loaded {len(calls)} times"


def test_propose_and_scan_agree_on_the_same_grouping(corpus):
    """Both paths must see one set of groups, not two independently built ones."""
    from kg_microbe_consistency import build_report, proposals_from_groups, scan_groups

    write(corpus, "a", identifier="CHEBI:1", term="thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="cas:2", term="Thing",
          ontology_id="cas:2", quality="FALLBACK_REGISTRY", source="CAS")

    records, skipped, groups = scan_groups(corpus)
    report = build_report(corpus, records, skipped, groups)
    proposed, surfaced = proposals_from_groups(groups)

    assert report["groups_disagreeing"] == len(proposed) + len(surfaced)


def test_fail_on_findings_still_applies_under_propose(corpus):
    """The exit-code logic runs once at the end; --propose must not bypass it."""
    from kg_microbe_consistency import __main__ as cli

    write(corpus, "a", identifier="CHEBI:1", term="thing",
          ontology_id="CHEBI:1", quality="EXACT_MATCH", source="CHEBI")
    write(corpus, "b", identifier="cas:2", term="Thing",
          ontology_id="cas:2", quality="FALLBACK_REGISTRY", source="CAS")

    assert cli.main(["--corpus", str(corpus), "--propose"]) == 0
    assert cli.main(
        ["--corpus", str(corpus), "--propose", "--fail-on-findings"]
    ) == 1
