"""Predicate and curator-scope guards for MIM SSSOM synonym enrichment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


kgm = _load("kgm_unified_mappings", SCRIPTS / "kgm_unified_mappings.py")
builder = _load("build_mim_ingredient_sssom", SCRIPTS / "build_mim_ingredient_sssom.py")


def test_loader_does_not_promote_non_identity_rows_to_synonyms(tmp_path):
    path = tmp_path / "unified.sssom.tsv"
    path.write_text(
        "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\t"
        "object_formula\tsource\n"
        "kgm.name:exact\tExact alias\tskos:exactMatch\tCHEBI:1\tTarget\tH2O\texact\n"
        "kgm.name:close\tUnrelated close label\tskos:closeMatch\tCHEBI:1\tTarget\tH2O\tclose\n"
        "kgm.name:narrow\tNarrow child\tskos:narrowMatch\tCHEBI:1\tTarget\tH2O\tnarrow\n"
    )

    entry = kgm.load_kgm_entity_index(path)["CHEBI:1"]

    assert entry["synonyms"] == {"Exact alias"}
    assert entry["xrefs"] == {
        "kgm.name:exact",
        "kgm.name:close",
        "kgm.name:narrow",
    }
    assert entry["sources"] == "close|exact|narrow"


def test_builder_honors_mim_rejected_label_for_every_input_source(tmp_path):
    record = tmp_path / "Reviewed.yaml"
    record.write_text(
        yaml.safe_dump(
            {
                "identifier": "CHEBI:1",
                "preferred_term": "Reviewed material",
                "mapping_status": "MAPPED",
                "ontology_mapping": {
                    "ontology_id": "CHEBI:1",
                    "ontology_label": "Target",
                    "ontology_source": "CHEBI",
                    "mapping_quality": "EXACT_MATCH",
                },
                "synonyms": [
                    {
                        "synonym_text": "Upstream bad label",
                        "synonym_type": "REJECTED_LABEL",
                        "source": "curator review",
                    },
                    {
                        "synonym_text": "Accepted local alias",
                        "synonym_type": "EXACT_SYNONYM",
                        "source": "curator review",
                    },
                    {
                        "synonym_text": "(for solid medium)",
                        "synonym_type": "RAW_TEXT",
                        "source": "curator review",
                    },
                    {
                        "synonym_text": "Original amount: X",
                        "synonym_type": "RAW_TEXT",
                        "source": "curator review",
                    },
                    {
                        "synonym_text": "MOPS buffer (SIGMA)",
                        "synonym_type": "RAW_TEXT",
                        "source": "curator review",
                    },
                ],
            },
            sort_keys=False,
        )
    )

    rows = builder._row_from_yaml(
        record,
        residual={},
        kgm_sources={},
        kgm_labels={
            "CHEBI:1": (
                "Target",
                ["UPSTREAM BAD LABEL", "Accepted upstream alias"],
            )
        },
        canonical_labels={"CHEBI:1": "Target"},
    )
    published = set(rows[0]["other"].split("|"))

    assert "Upstream bad label" not in published
    assert "UPSTREAM BAD LABEL" not in published
    assert "(for solid medium)" not in published
    assert "Original amount: X" not in published
    assert "Accepted local alias" in published
    assert "Accepted upstream alias" in published
    assert "MOPS buffer (SIGMA)" in published


def _write_scoped_record(tmp_path, *, identifier, ontology_id, quality):
    record = tmp_path / "Scoped.yaml"
    record.write_text(
        yaml.safe_dump(
            {
                "identifier": identifier,
                "preferred_term": "Reviewed subject",
                "mapping_status": "MAPPED",
                "ontology_mapping": {
                    "ontology_id": ontology_id,
                    "ontology_label": "Stored target alias",
                    "mapping_quality": quality,
                },
                "synonyms": [
                    {
                        "synonym_text": "Curated subject alias",
                        "synonym_type": "EXACT_SYNONYM",
                        "source": "curator review",
                    },
                    {
                        "synonym_text": "Reviewed overlap alias",
                        "synonym_type": "RAW_TEXT",
                        "source": "curator review",
                    },
                    {
                        "synonym_text": "Rejected alias",
                        "synonym_type": "REJECTED_LABEL",
                        "source": "curator review",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return record


@pytest.mark.parametrize(
    ("quality", "predicate"),
    [
        ("CLOSE_MATCH", "skos:closeMatch"),
        ("NARROW_MATCH", "skos:broadMatch"),
        ("CLOSE_MATCH", "skos:narrowMatch"),
    ],
)
def test_nonexact_row_does_not_inherit_target_aliases(
    tmp_path, monkeypatch, quality, predicate,
):
    """KG aliases describe the object, not a non-identical MIM subject (#680)."""
    record = _write_scoped_record(
        tmp_path,
        identifier="kgmicrobe.compound:scoped",
        ontology_id="CHEBI:1",
        quality=quality,
    )
    residual = {}
    if predicate == "skos:narrowMatch":
        # Production CONSIDER_SPECIFIC decisions are now annotation-only.
        # Inject a predicate-routing fixture to exercise the third supported
        # nonidentity predicate through the real row builder, without changing
        # its synonym logic or pretending current curation emits this case.
        monkeypatch.setitem(
            builder._PREDICATE_BY_CATEGORY, "TEST_NARROW", predicate,
        )
        residual[record.name] = {"category": "TEST_NARROW"}

    rows = builder._row_from_yaml(
        record,
        residual=residual,
        kgm_sources={},
        kgm_labels={
            "CHEBI:1": (
                "KG target name",
                ["KG target synonym", "Reviewed overlap alias", "REJECTED ALIAS"],
            ),
        },
        canonical_labels={"CHEBI:1": "Canonical target"},
    )
    target = next(row for row in rows if row["object_id"] == "CHEBI:1")
    registry = next(
        row for row in rows if row["object_id"] == "kgmicrobe.compound:scoped"
    )

    assert target["predicate_id"] == predicate
    assert target["object_label"] == "Canonical target"
    assert set(target["other"].split("|")) == {
        "Curated subject alias", "Reviewed overlap alias",
    }
    assert registry["predicate_id"] == "skos:exactMatch"


def test_nonexact_nonchebi_row_does_not_publish_previous_object_label(tmp_path):
    """ENVO canonicalization alone must not make its old label a subject name."""
    record = _write_scoped_record(
        tmp_path,
        identifier="kgmicrobe.ingredient:scoped",
        ontology_id="ENVO:00002149",
        quality="CLOSE_MATCH",
    )
    rows = builder._row_from_yaml(
        record,
        residual={},
        kgm_sources={},
        kgm_labels={},
        canonical_labels={"ENVO:00002149": "Canonical target"},
    )
    target = next(row for row in rows if row["object_id"] == "ENVO:00002149")

    assert target["predicate_id"] == "skos:closeMatch"
    assert target["object_label"] == "Canonical target"
    assert set(target["other"].split("|")) == {
        "Curated subject alias", "Reviewed overlap alias",
    }


@pytest.mark.parametrize(
    ("quality", "category"),
    [("EXACT_MATCH", None), ("CLOSE_MATCH", "SYMMETRIC"), ("NARROW_MATCH", None)],
)
def test_final_identity_predicate_keeps_permitted_target_aliases(
    tmp_path, quality, category,
):
    """Use the final identity predicate, after quality and residual overrides."""
    record = _write_scoped_record(
        tmp_path, identifier="CHEBI:1", ontology_id="CHEBI:1", quality=quality,
    )
    residual = {record.name: {"category": category}} if category else {}
    rows = builder._row_from_yaml(
        record,
        residual=residual,
        kgm_sources={},
        kgm_labels={
            "CHEBI:1": (
                "KG target name",
                ["KG target synonym", "Reviewed overlap alias", "REJECTED ALIAS"],
            ),
        },
        canonical_labels={"CHEBI:1": "Canonical target"},
    )

    assert len(rows) == 1
    assert rows[0]["predicate_id"] == "skos:exactMatch"
    assert rows[0]["object_label"] == "Canonical target"
    assert set(rows[0]["other"].split("|")) == {
        "Stored target alias", "KG target name", "KG target synonym",
        "Curated subject alias", "Reviewed overlap alias",
    }
