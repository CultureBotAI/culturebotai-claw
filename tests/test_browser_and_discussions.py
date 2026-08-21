"""Tests for the packaged browser helpers and discussion export."""

import json

import yaml

from kg_microbe_browser.graph import (
    build_community_membership_graph,
    build_ingredient_composition_graph,
)
from kg_microbe_discussions.export import build_records, write_browser


def test_community_graph_renders_roles_and_sanitizes_ids():
    graph = build_community_membership_graph(
        {
            "id": "community:1",
            "name": 'Quoted "community"',
            "taxonomy": [
                {
                    "taxon_term": {
                        "term": {"id": "NCBITaxon:2", "label": "Bacteria"}
                    },
                    "functional_role": ["producer", "consumer"],
                }
            ],
        }
    )

    assert "community_1" in graph
    assert "NCBITaxon_2" in graph
    assert "producer,consumer" in graph
    assert "Quoted 'community'" in graph
    assert build_community_membership_graph({"id": "empty"}) == ""


def test_ingredient_graph_deduplicates_chebi_and_reports_truncation():
    graph = build_ingredient_composition_graph(
        {
            "id": "medium:1",
            "ingredients": [
                {"preferred_term": "glucose", "term": {"id": "CHEBI:17234"}},
                {"preferred_term": "sugar", "term": {"id": "CHEBI:17234"}},
            ],
        },
        max_ingredients=1,
    )

    assert graph.count('CHEBI_17234["CHEBI:17234"]') == 1
    assert 'more["...1 more"]' in graph
    assert build_ingredient_composition_graph({"id": "empty"}) == ""


def test_discussion_export_builds_metrics_and_static_browser(tmp_path):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    (records_dir / "valid.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "record:1",
                "name": "Record one",
                "discussions": [
                    {
                        "discussion_id": "gap-1",
                        "kind": "KNOWLEDGE_GAP",
                        "prompt": "What is missing?",
                        "evidence": [{"reference": "PMID:1"}],
                        "proposed_experiments": [{"name": "experiment"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (records_dir / "invalid.yaml").write_text("[", encoding="utf-8")
    cfg = {
        "record_glob": "records/*.yaml",
        "page_url_template": "pages/{stem}.html#{discussion_id}",
    }

    records, metrics = build_records(tmp_path, cfg)

    assert metrics == {
        "total_discussions": 1,
        "total_knowledge_gaps": 1,
        "total_source_entries": 1,
        "kinds": ["KNOWLEDGE_GAP"],
    }
    assert records[0]["evidence_refs"] == ["PMID:1"]
    assert records[0]["page_url"] == "pages/valid.html#gap-1"

    out_dir = tmp_path / "browser"
    write_browser(records, metrics, "Example", out_dir)
    assert (out_dir / "index.html").is_file()
    data = (out_dir / "data.js").read_text(encoding="utf-8")
    assert json.dumps("Example") in data
    assert "gap-1" in data
