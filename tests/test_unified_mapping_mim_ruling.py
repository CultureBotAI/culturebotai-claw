"""UNIFIED_INGREDIENT_MAPPING must not republish an id that outranks MIM's ruling.

MediaIngredientMech#138: kg-microbe picks a row's primary with
``best_primary([chebi_id, culturemech_term_id, mim_id, kg_microbe_node_id, cas_rn])``
and equal-tier candidates tie on column order. The builder put CultureMech's
term first in ``chebi_id`` and copied it verbatim into ``culturemech_term_id``,
so every MIM correction to ``mim_id`` lost to the stale id it was correcting,
on every rebuild. 20 rows / 283 occurrences on the 2026-09-06 baseline, all
MIM's more specific identity losing -- Ca-pantothenate the salt vs pantothenate,
cobalamin's oxidation state, DTT, borax decahydrate.
"""

import importlib.util
import sys
import textwrap
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location(
    "build_unified_ingredient_mapping", _SCRIPTS / "build_unified_ingredient_mapping.py",
)
b = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = b
_SPEC.loader.exec_module(b)


def _mim(mim_id, status="MAPPED", chebi=None):
    return {
        "mim_id": mim_id, "preferred_term": "x",
        "chebi_id": chebi if chebi is not None else (mim_id if mim_id.startswith("CHEBI:") else ""),
        "cas_rn": "", "kg_microbe_node_id": mim_id, "mapping_status": status, "synonyms": [],
    }


def test_same_prefix_disagreement_publishes_mims_id_and_withholds_the_stale_one():
    """The #138 case: Ca-pantothenate, CultureMech says pantothenate, MIM the salt."""
    chebi, cm = b._published_ids("CHEBI:29032", _mim("CHEBI:31345"))
    assert chebi == "CHEBI:31345"
    assert cm == ""


def test_agreement_keeps_both():
    """Nothing to withhold when CultureMech already carries MIM's answer."""
    assert b._published_ids("CHEBI:30753", _mim("CHEBI:30753")) == ("CHEBI:30753", "CHEBI:30753")


def test_different_prefix_disagreement_is_left_to_the_consumers_tier_ranking():
    """FOODON vs CHEBI is decided by tier, not column order; blanking would only lose provenance."""
    chebi, cm = b._published_ids("FOODON:1", _mim("CHEBI:9"))
    assert chebi == "CHEBI:9"
    assert cm == "FOODON:1"


def test_unmapped_record_withholds_a_raw_id_that_would_win_by_default():
    """Calf brains: MIM refuses UBERON:0000955; with no corrected candidate, a raw one wins outright."""
    assert b._published_ids("UBERON:0000955", _mim("UNMAPPED_0170", status="UNMAPPED")) == ("", "")


def test_rejected_tombstone_carrying_the_winners_id_counts_as_a_ruling():
    """Ca-pantothenate: the label was merged, its tombstone holds the salt's id (#358).

    The builder already publishes that id as mim_id, so it must also win the
    tie -- otherwise the 137-occurrence flagship case of #138 stays broken.
    """
    chebi, cm = b._published_ids("CHEBI:29032", _mim("CHEBI:31345", status="REJECTED"))
    assert chebi == "CHEBI:31345"
    assert cm == ""


def test_no_mim_record_is_unchanged():
    """CultureMech's term is the only opinion, so it is published as before."""
    assert b._published_ids("CHEBI:5", None) == ("CHEBI:5", "CHEBI:5")


def test_non_chebi_mim_identity_falls_back_to_culturemechs_chebi():
    """MIM ruled cas:, so chebi_id has no MIM value to prefer and keeps the legacy fallback."""
    chebi, cm = b._published_ids("CHEBI:7", _mim("cas:1-2-3", chebi=""))
    assert chebi == "CHEBI:7"
    assert cm == "CHEBI:7"


def test_rows_are_wired_through(monkeypatch):
    """build_unified_rows uses the helper for both columns, not just one."""
    rec = _mim("CHEBI:31345")
    rows = b.build_unified_rows(
        {"Ca-pantothenate": {"term_id": "CHEBI:29032", "count": 3, "example_media": []}},
        {b._normalize("Ca-pantothenate"): rec}, {}, {},
    )
    assert rows[0]["chebi_id"] == "CHEBI:31345"
    assert rows[0]["culturemech_term_id"] == ""
    assert rows[0]["mim_id"] == "CHEBI:31345"


def test_load_mim_index_excludes_rejected_labels(tmp_path):
    """REJECTED_LABEL tombstones are provenance, not exported synonyms or lookup names."""
    mapped = tmp_path / "data" / "ingredients" / "mapped"
    mapped.mkdir(parents=True)
    (mapped / "Free.yaml").write_text(textwrap.dedent("""\
        identifier: CHEBI:17561
        preferred_term: L-Cysteine
        ontology_mapping:
          ontology_id: CHEBI:17561
          ontology_label: L-cysteine
        mapping_status: MAPPED
        synonyms:
        - synonym_text: Cysteine-HCl∙H2O
          synonym_type: REJECTED_LABEL
          source: kg_microbe
    """))
    (mapped / "Hydrate.yaml").write_text(textwrap.dedent("""\
        identifier: CHEBI:91248
        preferred_term: L-Cysteine HCl x H2O
        ontology_mapping:
          ontology_id: CHEBI:91248
          ontology_label: L-cysteine hydrochloride hydrate
        mapping_status: MAPPED
        synonyms:
        - synonym_text: Cysteine-HCl∙H2O
          synonym_type: HYDRATE_FORM
          source: kg_microbe
    """))

    name_index, _, _ = b.load_mim_index(tmp_path)

    assert "Cysteine-HCl∙H2O" not in name_index[b._normalize("L-Cysteine")]["synonyms"]
    assert (
        name_index[b._normalize("Cysteine-HCl∙H2O")]["mim_id"]
        == "CHEBI:91248"
    )


def test_write_tsv_uses_lf_line_endings(tmp_path):
    """Generated snapshots must not trip git's whitespace checker."""
    row = dict.fromkeys(b.COLUMNS, "")
    row["ingredient_name"] = "L-Cysteine"
    row["occurrence_count"] = 1
    output = tmp_path / "unified.tsv"

    b.write_tsv([row], output)

    raw = output.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2
