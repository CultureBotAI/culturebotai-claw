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
    """
    prior_key = ("MIM:A", "skos:closeMatch", "CHEBI:1")
    prior_stamps = {prior_key: "OAK+OLS:chebi|SYNONYM_ENRICH|2026-07-07"}

    by_subject_object = {}
    for (subj, _pred, obj), stamp in prior_stamps.items():
        by_subject_object.setdefault((subj, obj), stamp)

    # The row as the builder now emits it: same subject and object, corrected
    # predicate. The exact key misses; the (subject, object) key must not.
    assert prior_stamps.get(("MIM:A", "skos:exactMatch", "CHEBI:1")) is None
    assert by_subject_object[("MIM:A", "CHEBI:1")] == (
        "OAK+OLS:chebi|SYNONYM_ENRICH|2026-07-07")


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
