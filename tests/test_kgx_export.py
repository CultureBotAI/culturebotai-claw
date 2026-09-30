"""`kg-microbe-kgx export`: a Mech's declared graphs as checked KGX (#276, #539).

Offline, against fixture corpora in each graph shape. Every case is driven by
an input where the rule under test changes the output (#286): a grounded node
beside an ungrounded one, a Biolink `predicate_id` beside an RO one beside a
bare phrase, one grounding in two records.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from kg_microbe_graph.coverage import CoverageConfig
from kg_microbe_kgx import maps
from kg_microbe_kgx.contract import check_graph
from kg_microbe_kgx.export import ExportError, ExportSettings, write_export

GLOBS = ["data/**/*.yaml"]


def _corpus(tmp_path: Path, records: dict[str, dict]) -> Path:
    root = tmp_path / "repo"
    for name, record in records.items():
        path = root / "data" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(record), encoding="utf-8")
    return root


def _settings(mech: str = "m", **overrides) -> ExportSettings:
    coverage = overrides.pop("coverage", {"graph_shape": "graph_list"})
    overrides.setdefault("node_namespace", mech)
    return ExportSettings(
        mech=mech,
        coverage=CoverageConfig.from_settings(coverage),
        infores=f"infores:{mech}",
        **overrides,
    )


def _graph_record(edges: list[dict], nodes: list[dict] | None = None) -> dict:
    return {
        "id": "r",
        "causal_graphs": [{
            "graph_id": "g1",
            "nodes": nodes or [
                {"node_id": "n1", "node_type": "CHEMICAL", "grounding": "CHEBI:15377",
                 "label": "water"},
                {"node_id": "n2", "node_type": "BIOLOGICAL_PROCESS", "label": "respiration"},
            ],
            "edges": edges,
        }],
    }


def _edge(**extra) -> dict:
    return {"subject": "n1", "object": "n2", "predicate": "participates in",
            "evidence": [{"reference": "PMID:123", "snippet": "water is used"}], **extra}


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _export(tmp_path: Path, records: dict[str, dict], settings: ExportSettings | None = None):
    root = _corpus(tmp_path, records)
    out = tmp_path / "out"
    manifest, findings = write_export(root, GLOBS, settings or _settings(), out)
    return manifest, findings, _rows(out / "nodes.tsv"), _rows(out / "edges.tsv"), out


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


def test_a_grounded_node_is_its_grounding_and_an_ungrounded_one_is_minted(tmp_path):
    _, findings, nodes, _, _ = _export(tmp_path, {"a/r.yaml": _graph_record([_edge()])})
    by_name = {row["name"]: row for row in nodes}
    assert by_name["water"]["id"] == "CHEBI:15377"
    assert by_name["water"]["grounded"] == "true"
    assert by_name["respiration"]["id"] == "m:data_a_r.g1.n2"
    assert by_name["respiration"]["grounded"] == "false"
    assert findings == []


def test_the_same_grounding_in_two_records_is_one_node(tmp_path):
    manifest, _, nodes, edges, _ = _export(tmp_path, {
        "a.yaml": _graph_record([_edge()]),
        "b.yaml": _graph_record([_edge()]),
    })
    assert [row["id"] for row in nodes].count("CHEBI:15377") == 1
    assert len(edges) == 2
    assert manifest["statistics"]["merged_nodes"] == 1


def test_category_comes_from_type_then_prefix_then_fallback(tmp_path):
    record = _graph_record([_edge()], nodes=[
        # RHEA's prefix says MolecularActivity; the declared type says chemical.
        {"node_id": "n1", "node_type": "CHEMICAL", "grounding": "RHEA:10000", "label": "a"},
        {"node_id": "n2", "node_type": "UNLISTED", "grounding": "CHEBI:1", "label": "b"},
        {"node_id": "n3", "node_type": "UNLISTED", "label": "c"},
    ])
    manifest, _, nodes, _, _ = _export(tmp_path, {"r.yaml": record})
    by_name = {row["name"]: row for row in nodes}
    assert by_name["a"]["category"] == "biolink:ChemicalEntity"  # type beats prefix
    assert by_name["b"]["category"] == "biolink:ChemicalEntity"  # prefix
    assert by_name["c"]["category"] == "biolink:NamedThing"
    assert by_name["c"]["original_category"] == "UNLISTED"
    assert manifest["statistics"]["category_sources"] == {"fallback": 1, "node_type": 1, "prefix": 1}


def test_a_mech_category_map_overrides_the_shared_one(tmp_path):
    settings = _settings(category_map={"CHEMICAL": "biolink:SmallMolecule"})
    _, _, nodes, _, _ = _export(tmp_path, {"r.yaml": _graph_record([_edge()])}, settings)
    assert {row["name"]: row["category"] for row in nodes}["water"] == "biolink:SmallMolecule"


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "predicate", "source"),
    [
        ({"predicate_id": "biolink:enables"}, "biolink:enables", "biolink_id"),
        ({"predicate_id": "BFO:0000050"}, "biolink:part_of", "mapped_id"),
        ({}, "biolink:participates_in", "phrase"),
        ({"predicate": "fuels"}, "biolink:related_to", "fallback"),
    ],
)
def test_predicate_resolution_order(tmp_path, extra, predicate, source):
    manifest, _, _, edges, _ = _export(tmp_path, {"r.yaml": _graph_record([_edge(**extra)])})
    assert edges[0]["predicate"] == predicate
    assert manifest["statistics"]["predicate_sources"] == {source: 1}
    if source == "fallback":
        assert edges[0]["original_predicate"] == "fuels"


def test_a_declared_prefix_keeps_its_predicate(tmp_path):
    settings = _settings(extra_prefixes=("METPO",))
    edge = _edge(predicate_id="METPO:2007700")
    manifest, findings, _, edges, _ = _export(tmp_path, {"r.yaml": _graph_record([edge])}, settings)
    assert edges[0]["predicate"] == "METPO:2007700"
    assert manifest["statistics"]["predicate_sources"] == {"declared_prefix": 1}
    assert findings == []


def test_evidence_becomes_publications_and_supporting_text(tmp_path):
    edge = _edge(evidence=[{"reference": "doi:10.1/x", "snippet": "a|b"},
                           {"reference": "https://example.org", "snippet": "c"}])
    _, _, _, edges, _ = _export(tmp_path, {"r.yaml": _graph_record([edge])})
    assert edges[0]["publications"] == "DOI:10.1/x"  # URLs are not publications
    assert edges[0]["supporting_text"] == "a/b|c"


def test_an_edge_to_an_undeclared_node_is_skipped_and_counted(tmp_path):
    manifest, findings, _, edges, _ = _export(
        tmp_path, {"r.yaml": _graph_record([_edge(), _edge(object="n9")])}
    )
    assert len(edges) == 1
    assert manifest["statistics"]["dangling_edges_skipped"] == 1
    assert findings == []


def test_edges_claim_no_provenance_the_mech_did_not_declare(tmp_path):
    """Seeded and curated edges must not both read as a curator's assertion (#542)."""
    record = {"r.yaml": _graph_record([_edge()])}
    default = _export(tmp_path / "a", record)[3][0]
    declared = _export(tmp_path / "b", record, _settings(
        knowledge_level="knowledge_assertion", agent_type="manual_agent"))[3][0]
    assert (default["knowledge_level"], default["agent_type"]) == ("not_provided", "not_provided")
    assert (declared["knowledge_level"], declared["agent_type"]) == (
        "knowledge_assertion", "manual_agent")


@pytest.mark.parametrize("setting", ["knowledge_level", "agent_type"])
def test_a_provenance_value_outside_biolink_is_refused(setting):
    class Capability:
        def __init__(self, enabled, settings):
            self.is_enabled, self.settings = enabled, settings

    class Declaration:
        capabilities = {
            "causal_graph_coverage": Capability(True, {"graph_shape": "graph_list"}),
            "kgx_export": Capability(False, {setting: "curated"}),
        }

    with pytest.raises(ExportError, match="not a Biolink value"):
        ExportSettings.from_manifest("m", Declaration())


def test_edge_ids_are_stable_across_exports(tmp_path):
    record = {"r.yaml": _graph_record([_edge()])}
    first = _export(tmp_path / "a", record)[3][0]["id"]
    second = _export(tmp_path / "b", record)[3][0]["id"]
    assert first == second and first.startswith("urn:uuid:")


def test_a_field_with_a_tab_newline_or_quote_stays_one_field(tmp_path):
    record = _graph_record([_edge()], nodes=[
        {"node_id": "n1", "node_type": "CHEMICAL", "grounding": "CHEBI:1",
         "label": 'say "hi"\tthere\nnow'},
        {"node_id": "n2", "node_type": "CHEMICAL", "grounding": "CHEBI:2", "label": "b"},
    ])
    _, findings, nodes, _, out = _export(tmp_path, {"r.yaml": record})
    assert {row["id"]: row["name"] for row in nodes}["CHEBI:1"] == 'say "hi" there now'
    assert findings == []
    assert check_graph(out / "nodes.tsv", out / "edges.tsv") == []


# --------------------------------------------------------------------------
# Shapes, manifest, refusals
# --------------------------------------------------------------------------


def test_a_record_graph_exports_through_the_same_reader(tmp_path):
    coverage = {
        "graph_shape": "record_graph", "node_list_fields": ["participants", "reactions"],
        "node_id_field": "id", "edges_field": "mechanistic_edges",
        "edge_subject_field": "subject", "edge_object_field": "object",
        "edge_predicate_field": "predicate", "edge_evidence_field": "evidence",
    }
    record = {
        "id": "MetaCyc:PWY-1",
        "participants": [{"id": "CHEBI:1", "label": "a"}],
        "reactions": [{"id": "RHEA:10", "label": "r"}],
        "mechanistic_edges": [{"id": "e1", "subject": "RHEA:10", "predicate": "produces",
                               "object": "CHEBI:1",
                               "evidence": [{"reference_id": "PMID:1", "quote": "q"}]}],
    }
    settings = _settings(coverage=coverage)
    _, findings, nodes, edges, _ = _export(tmp_path, {"p.yaml": record}, settings)
    assert {row["id"]: row["category"] for row in nodes} == {
        "CHEBI:1": "biolink:ChemicalEntity", "RHEA:10": "biolink:MolecularActivity",
    }
    assert edges[0]["predicate"] == "biolink:produces"
    assert edges[0]["publications"] == "PMID:1"
    assert findings == []


def test_the_manifest_records_what_was_mapped(tmp_path):
    _, _, _, _, out = _export(tmp_path, {"r.yaml": _graph_record([_edge(), _edge(predicate="fuels")])})
    manifest = json.loads((out / "manifest.json").read_text())
    stats = manifest["statistics"]
    assert manifest["biolink_version"] == maps.BIOLINK_VERSION
    assert stats["predicates_mapped_fraction"] == 0.5
    assert stats["unmapped_predicates"] == {"fuels": 1}


def test_a_corpus_with_no_records_is_an_error_not_an_empty_graph(tmp_path):
    (tmp_path / "repo" / "data").mkdir(parents=True)
    with pytest.raises(ExportError, match="no readable records"):
        write_export(tmp_path / "repo", GLOBS, _settings(), tmp_path / "out")


def test_a_map_target_that_is_not_biolink_is_refused():
    class Capability:
        def __init__(self, enabled, settings):
            self.is_enabled, self.settings = enabled, settings

    class Declaration:
        capabilities = {
            "causal_graph_coverage": Capability(True, {"graph_shape": "graph_list"}),
            "kgx_export": Capability(False, {"category_map": ["CHEMICAL=biolink:Chemical"]}),
        }

    with pytest.raises(ExportError, match="not Biolink"):
        ExportSettings.from_manifest("m", Declaration())


def test_without_a_declared_graph_shape_there_is_nothing_to_export():
    class Declaration:
        capabilities: dict = {}

    with pytest.raises(ExportError, match="causal_graph_coverage is not enabled"):
        ExportSettings.from_manifest("m", Declaration())


# --------------------------------------------------------------------------
# The maps themselves
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "known"),
    [
        (maps.NODE_TYPE_CATEGORIES, maps.categories),
        (maps.PREFIX_CATEGORIES, maps.categories),
        (maps.PHRASE_PREDICATES, maps.predicates),
    ],
    ids=["node-types", "prefixes", "phrases"],
)
def test_every_shared_map_target_is_a_term_of_the_pinned_biolink(table, known):
    missing = sorted({target for target in table.values() if target not in known()})
    assert not missing, f"not Biolink {maps.BIOLINK_VERSION}: {missing}"


def test_the_snapshot_is_the_model_it_names():
    """Counts measured against biolink-model 4.3.6 (#275 counted 327 class CURIEs
    by a different rule; the snapshot includes the model's root class)."""
    snapshot = maps.snapshot()
    assert snapshot["version"] == maps.BIOLINK_VERSION
    assert len(snapshot["categories"]) == 328
    assert "biolink:related_to" in snapshot["predicates"]


def test_output_that_fails_the_contract_is_reported_not_passed(tmp_path):
    """The exporter checks what it wrote. A namespace that is not a CURIE prefix
    makes every minted id invalid, and that must surface as findings."""
    settings = _settings(node_namespace="1bad")
    manifest, findings, _, _, _ = _export(tmp_path, {"r.yaml": _graph_record([_edge()])}, settings)
    assert findings
    assert manifest["contract_findings"]



# --------------------------------------------------------------------------
# Against the real corpora (skips without a checkout)
# --------------------------------------------------------------------------

from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mech", load_fleet_manifest().with_capability("causal_graph_coverage"))
def test_every_declared_graph_exports_contract_clean(mech, tmp_path):
    """A sample of each Mech's real records, so a shape or map the fixtures
    miss shows up as a contract finding rather than in a release."""
    try:
        root = resolve_mech_root(mech, claw_root=ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a {mech} checkout: {exc}")
    declaration = load_fleet_manifest().mechs[mech]
    settings = ExportSettings.from_manifest(mech, declaration)
    manifest, findings = write_export(root, declaration.record_globs, settings,
                                      tmp_path / mech, sample=200)
    assert findings == [], f"{mech}: {sorted({f.code for f in findings})}"
    assert manifest["statistics"]["records"] > 0
