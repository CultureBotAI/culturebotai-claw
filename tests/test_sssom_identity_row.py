"""The identity row's predicate, and the stamp replay across it.

MediaIngredientMech#438: every mapped record emits one row whose `object_id`
IS the record's own `identifier`. A record whose identifier is `CHEBI:17634`
asserts "I am CHEBI:17634"; publishing that as `skos:closeMatch` says it is
merely similar to itself. 448 rows said that.

The builder hard-codes `exactMatch` on the dual-emission registry row, but that
block only fires when the identifier DIFFERS from the ontology_id. When they
are equal there is no second row -- the parent row is the identity row, and it
was taking the quality-derived predicate. All 448 came from that path.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# The builder imports its sibling `kgm_unified_mappings` by bare name, so the
# scripts dir has to be importable before exec_module.
sys.path.insert(0, str(_SCRIPTS))

_SPEC = importlib.util.spec_from_file_location(
    "build_mim_ingredient_sssom", _SCRIPTS / "build_mim_ingredient_sssom.py",
)
builder = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = builder
_SPEC.loader.exec_module(builder)


def write_record(tmp_path, stem, identifier, ontology_id, quality, label="Thing"):
    path = tmp_path / f"{stem}.yaml"
    path.write_text(
        f"identifier: {identifier}\n"
        f"preferred_term: {label}\n"
        f"mapping_status: MAPPED\n"
        f"ontology_mapping:\n"
        f"  ontology_id: {ontology_id}\n"
        f"  ontology_label: {label}\n"
        f"  mapping_quality: {quality}\n",
        encoding="utf-8",
    )
    return path


def rows_for(tmp_path, **kw):
    path = write_record(tmp_path, **kw)
    return builder._row_from_yaml(path, {}, {}, {}, {})


def identity_row(rows, identifier):
    return next(r for r in rows if r["object_id"] == identifier)


@pytest.mark.parametrize(
    "quality",
    ["FALLBACK_REGISTRY", "PLACEHOLDER", "CAS_RN_LOOKUP", "LEXICAL_MATCH",
     "CLOSE_MATCH", "SYNONYM_MATCH", "EXACT_MATCH"],
)
def test_identity_row_is_exact_match_whatever_the_quality(tmp_path, quality):
    """mapping_quality grades the ontology grounding, not self-identity.

    These seven values produced 448 `closeMatch`-to-self rows between them, and
    four of them yielded *both* predicates depending on other state.
    """
    rows = rows_for(tmp_path, stem="Thing", identifier="CHEBI:17634",
                    ontology_id="CHEBI:17634", quality=quality)

    assert identity_row(rows, "CHEBI:17634")["predicate_id"] == "skos:exactMatch"


def test_a_non_identity_parent_row_still_takes_the_quality_predicate(tmp_path):
    """The override must not leak onto rows pointing at a different term."""
    rows = rows_for(tmp_path, stem="Thing", identifier="cas:1234-56-7",
                    ontology_id="CHEBI:17634", quality="CLOSE_MATCH")

    parent = next(r for r in rows if r["object_id"] == "CHEBI:17634")
    assert parent["predicate_id"] == "skos:closeMatch"


def test_the_dual_emission_registry_row_is_still_emitted_and_exact(tmp_path):
    rows = rows_for(tmp_path, stem="Thing", identifier="cas:1234-56-7",
                    ontology_id="CHEBI:17634", quality="CLOSE_MATCH")

    assert identity_row(rows, "cas:1234-56-7")["predicate_id"] == "skos:exactMatch"


def test_identity_override_does_not_touch_confidence(tmp_path):
    """Deliberately predicate-only -- raising confidence would move 45 further
    rows that #438 is not about."""
    rows = rows_for(tmp_path, stem="Thing", identifier="CHEBI:1",
                    ontology_id="CHEBI:1", quality="CLOSE_MATCH")

    row = identity_row(rows, "CHEBI:1")
    assert row["predicate_id"] == "skos:exactMatch"
    assert row["confidence"] == "0.9", "quality-derived confidence is untouched"


def test_prior_stamps_load_keyed_on_subject_predicate_object(tmp_path):
    """The replay index the carry-over falls back from."""
    prior = tmp_path / "prior.sssom.tsv"
    prior.write_text(
        "# mapping_set_id: x\n"
        "subject_id\tpredicate_id\tobject_id\tvalidation_method\n"
        "MIM:A\tskos:closeMatch\tCHEBI:1\tOAK+OLS:chebi|SYNONYM_ENRICH|2026-07-07\n"
        "MIM:B\tskos:exactMatch\tCHEBI:2\t\n",
        encoding="utf-8",
    )

    stamps = builder._load_existing_validation_method(prior)

    assert stamps == {
        ("MIM:A", "skos:closeMatch", "CHEBI:1"):
            "OAK+OLS:chebi|SYNONYM_ENRICH|2026-07-07"
    }, "blank stamps are not indexed"


def test_a_stamp_survives_its_row_changing_predicate(tmp_path):
    """Correcting 448 identity rows would otherwise have dropped 389 verdicts.

    The stamps record findings about the *object* -- `SYNONYM_ENRICH`,
    `UNKNOWN_TERM` -- so strengthening closeMatch to exactMatch does not
    invalidate them, and this loader exists precisely so a rebuild does not
    wipe review state.

    Calls the builder's own `replay_stamp`. An earlier version of this test
    reimplemented the fallback inline, so a change to the real loop could not
    fail it.
    """
    prior_stamps = {
        ("MIM:A", "skos:closeMatch", "CHEBI:1"):
            "OAK+OLS:chebi|SYNONYM_ENRICH|2026-07-07",
    }
    index = builder.build_subject_object_index(prior_stamps)

    # The row as the builder now emits it: same subject and object, corrected
    # predicate. The exact key misses; the strengthened fallback must not.
    assert prior_stamps.get(("MIM:A", "skos:exactMatch", "CHEBI:1")) is None
    stamp, outcome = builder.replay_stamp(
        "MIM:A", "skos:exactMatch", "CHEBI:1", prior_stamps, index)

    assert outcome == "carried"
    assert stamp == "OAK+OLS:chebi|SYNONYM_ENRICH|2026-07-07"


def test_an_exact_key_hit_is_replayed_not_carried():
    """The unchanged-predicate path must not be miscounted as a carry-over."""
    prior_stamps = {("MIM:A", "skos:exactMatch", "CHEBI:1"): "v|CONFIRMED|d"}
    index = builder.build_subject_object_index(prior_stamps)

    stamp, outcome = builder.replay_stamp(
        "MIM:A", "skos:exactMatch", "CHEBI:1", prior_stamps, index)

    assert (stamp, outcome) == ("v|CONFIRMED|d", "replayed")


def test_a_weakened_predicate_resets_the_row_into_the_review_queue():
    """#126: this inherited the stamp unconditionally.

    A curator downgrading exactMatch to narrowMatch after a specificity review
    has withdrawn the endorsement; carrying it kept the row out of review.
    """
    prior_stamps = {("MIM:A", "skos:exactMatch", "CHEBI:1"): "v|CONFIRMED|d"}
    index = builder.build_subject_object_index(prior_stamps)

    stamp, outcome = builder.replay_stamp(
        "MIM:A", "skos:narrowMatch", "CHEBI:1", prior_stamps, index)

    assert stamp is None
    assert outcome == "reset"


def test_a_pair_with_two_prior_predicates_never_carries():
    """Ambiguous history cannot be compared for strength, so it must not carry.

    Does not occur in the corpus today -- 2885 rows, 2885 distinct
    subject+object pairs -- but the loader must not depend on that.
    """
    prior_stamps = {
        ("MIM:A", "skos:closeMatch", "CHEBI:1"): "v|CONFIRMED|d",
        ("MIM:A", "skos:narrowMatch", "CHEBI:1"): "v|OTHER|d",
    }
    index = builder.build_subject_object_index(prior_stamps)

    stamp, outcome = builder.replay_stamp(
        "MIM:A", "skos:exactMatch", "CHEBI:1", prior_stamps, index)

    assert stamp is None
    assert outcome == "reset"


def test_a_row_with_no_prior_stamp_is_absent_not_reset():
    """`absent` and `reset` must stay distinguishable: one is a row that was
    never reviewed, the other is a row whose review was deliberately dropped."""
    index = builder.build_subject_object_index({})

    stamp, outcome = builder.replay_stamp(
        "MIM:Z", "skos:exactMatch", "CHEBI:9", {}, index)

    assert (stamp, outcome) == (None, "absent")


def test_narrow_match_to_a_different_parent_stays_narrow(tmp_path):
    """NARROW_MATCH identity rows were already exactMatch and must stay so,
    while the asymmetric parent row keeps its narrowMatch."""
    rows = rows_for(tmp_path, stem="Thing", identifier="kgmicrobe.ingredient:thing",
                    ontology_id="CHEBI:17634", quality="NARROW_MATCH")

    assert next(r for r in rows
                if r["object_id"] == "CHEBI:17634")["predicate_id"] == "skos:narrowMatch"
    assert identity_row(rows, "kgmicrobe.ingredient:thing")["predicate_id"] == "skos:exactMatch"


def test_identity_row_drops_a_stale_symmetric_comment(tmp_path, monkeypatch):
    """A `SYMMETRIC:` rationale argues for a difference; an exactMatch row
    asserting identity must not carry one. 51 rows did after the predicate
    half of #438 landed."""
    path = write_record(tmp_path, stem="Thing", identifier="CHEBI:17634",
                        ontology_id="CHEBI:17634", quality="CLOSE_MATCH")
    residual = {path.name: {"category": "SYMMETRIC",
                            "rationale": "MIM is the more specific side"}}

    rows = builder._row_from_yaml(path, residual, {}, {}, {})

    row = identity_row(rows, "CHEBI:17634")
    assert row["predicate_id"] == "skos:exactMatch"
    assert "SYMMETRIC" not in (row["comment"] or "")


def test_a_non_identity_row_keeps_its_symmetric_comment(tmp_path):
    """The retirement is scoped to identity rows -- elsewhere the rationale
    still explains a real predicate choice."""
    path = write_record(tmp_path, stem="Thing", identifier="cas:1234-56-7",
                        ontology_id="CHEBI:17634", quality="CLOSE_MATCH")
    residual = {path.name: {"category": "SYMMETRIC",
                            "rationale": "MIM is the more specific side"}}

    rows = builder._row_from_yaml(path, residual, {}, {}, {})

    parent = next(r for r in rows if r["object_id"] == "CHEBI:17634")
    assert "SYMMETRIC" in (parent["comment"] or "")


# --------------------------------------------------------------------------
# #126: a stamp survives a STRENGTHENED predicate, not a weakened one
# --------------------------------------------------------------------------


def test_the_strength_table_covers_every_predicate_the_builder_emits():
    """An emittable predicate missing from the table would never strengthen,
    silently resetting stamps it should have carried."""
    import re

    source = (_SCRIPTS / "build_mim_ingredient_sssom.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'"(skos:[a-zA-Z]+)"', source))

    assert emitted, "found no predicates in the builder; the test is vacuous"
    assert emitted <= set(builder.PREDICATE_STRENGTH), (
        f"not in PREDICATE_STRENGTH: {sorted(emitted - set(builder.PREDICATE_STRENGTH))}"
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("skos:closeMatch", "skos:exactMatch"),
        ("skos:narrowMatch", "skos:exactMatch"),
        ("skos:broadMatch", "skos:exactMatch"),
        ("skos:narrowMatch", "skos:closeMatch"),
    ],
)
def test_a_strengthened_predicate_keeps_the_object_level_verdict(old, new):
    """The stamps assert things about the OBJECT -- that the term resolved, that
    its synonyms were enriched. Strengthening the relation cannot falsify that."""
    assert builder._strengthens(old, new) is True


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("skos:exactMatch", "skos:closeMatch"),
        ("skos:exactMatch", "skos:narrowMatch"),
        ("skos:closeMatch", "skos:narrowMatch"),
        ("skos:narrowMatch", "skos:broadMatch"),
        ("skos:broadMatch", "skos:narrowMatch"),
    ],
)
def test_a_weakened_or_sideways_predicate_drops_the_verdict(old, new):
    """Downgrading after a specificity review is someone changing their mind
    about the pair; inheriting the stamp would carry an endorsement just
    withdrawn. narrowMatch and broadMatch are directional subsumption, not
    degrees of identity, so neither strengthens the other."""
    assert builder._strengthens(old, new) is False


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("skos:exactMatch", "skos:mysteryMatch"),
        ("skos:mysteryMatch", "skos:exactMatch"),
        ("", "skos:exactMatch"),
    ],
)
def test_an_unrecognised_predicate_never_strengthens(old, new):
    """A vocabulary the table does not describe is a reason to re-review, not
    to inherit a verdict."""
    assert builder._strengthens(old, new) is False


def test_the_same_predicate_does_not_count_as_strengthening():
    """Equal predicates are the exact-key replay path and must never reach the
    fallback; if they did, counting them as carried would misreport."""
    for predicate in builder.PREDICATE_STRENGTH:
        assert builder._strengthens(predicate, predicate) is False
