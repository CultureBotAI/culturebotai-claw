"""Predicate and curator-scope guards for MIM SSSOM synonym enrichment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
    assert "Accepted local alias" in published
    assert "Accepted upstream alias" in published
