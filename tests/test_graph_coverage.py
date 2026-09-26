"""Causal-graph coverage, comparable across the fleet (#132 Phase 6, item 2).

Every Mech with a graph model counted its own coverage, and each count was a
different question: TraitMech's dashboard divided by every record, deprecated
ones included; CellStructureMech's README counted topology graphs as
mechanisms; CommunityMech's graph was invisible to anything looking for a
`causal_graphs` slot. These tests pin the distinctions the shared report draws
instead -- each one against a fixture in which the two sides differ, because a
fixture built from the case that already holds passes whether or not the
distinction is implemented (#286).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kg_microbe_corpus import collect as corpus_report
from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_graph.coverage import (
    CAPABILITY,
    CoverageConfig,
    CoverageConfigError,
    CoverageError,
    ExemptionRule,
    collect,
)

ROOT = Path(__file__).resolve().parents[1]
GLOBS = ["data/**/*.yaml"]


def _corpus(tmp_path: Path, records: dict[str, object]) -> Path:
    root = tmp_path / "repo"
    for name, content in records.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            content if isinstance(content, str) else yaml.safe_dump(content),
            encoding="utf-8",
        )
    return root


def _config(**settings: object) -> CoverageConfig:
    return CoverageConfig.from_settings({"graph_shape": "graph_list", **settings})


def _graph(graph_id: str, edges: int, scope: str | None = None, **extra: object) -> dict:
    """A chain of `edges` edges over `edges + 1` nodes (one node when 0)."""
    nodes = [{"node_id": f"n{i}", "node_type": "X"} for i in range(max(edges + 1, 1))]
    graph: dict = {
        "graph_id": graph_id,
        "nodes": nodes,
        "edges": [
            {"subject": f"n{i}", "object": f"n{i + 1}", "predicate": "causes"}
            for i in range(edges)
        ],
        **extra,
    }
    if scope is not None:
        graph["scope_status"] = scope
    return graph


def _report(tmp_path: Path, records: dict[str, object], **settings: object) -> dict:
    root = _corpus(tmp_path, records)
    return collect("m", root, GLOBS, _config(**settings)).as_dict()


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_a_graph_list_defaults_to_the_shape_traitmech_set_and_others_copied():
    shape = _config().shape
    assert (shape.graphs_field, shape.nodes_field, shape.edges_field) == (
        "causal_graphs", "nodes", "edges",
    )
    assert (shape.edge_subject_field, shape.edge_object_field) == ("subject", "object")
    assert shape.node_grounding_field == "grounding"


def test_a_declared_field_overrides_its_default():
    assert _config(node_grounding_field="identifier").shape.node_grounding_field == "identifier"


def test_the_nested_shape_defaults_nothing():
    """A field that is not declared must read as not measured. Defaulting
    `edge_evidence_field` to `evidence` would report CommunityMech's 944 edges
    as unevidenced, when its edges have no evidence slot at all."""
    with pytest.raises(CoverageConfigError, match="nothing is defaulted"):
        CoverageConfig.from_settings(
            {"graph_shape": "node_nested_edges", "nodes_field": "interactions"}
        )
    config = CoverageConfig.from_settings({
        "graph_shape": "node_nested_edges", "nodes_field": "interactions",
        "edges_field": "downstream", "node_id_field": "name", "edge_object_field": "target",
    })
    assert config.shape.edge_evidence_field is None
    assert config.shape.node_grounding_field is None


@pytest.mark.parametrize(
    "extra",
    [{"graphs_field": "causal_graphs"}, {"edge_subject_field": "source"},
     {"scope_field": "scope"}, {"graph_facets": ["kind"]}],
)
def test_the_nested_shape_refuses_what_only_a_graph_object_has(extra):
    with pytest.raises(CoverageConfigError):
        CoverageConfig.from_settings({
            "graph_shape": "node_nested_edges", "nodes_field": "interactions",
            "edges_field": "downstream", "node_id_field": "name",
            "edge_object_field": "target", **extra,
        })


def test_mechanistic_scopes_need_a_scope_field_to_name_values_of():
    with pytest.raises(CoverageConfigError, match="no.*scope_field|none is declared"):
        _config(mechanistic_scopes=["MECHANISTIC"])
    assert _config(scope_field="scope_status", mechanistic_scopes=["MECHANISTIC"])


def test_a_duplicate_grounding_check_needs_somewhere_to_read_groundings():
    with pytest.raises(CoverageConfigError, match="node_grounding_field"):
        CoverageConfig.from_settings({
            "graph_shape": "node_nested_edges", "nodes_field": "interactions",
            "edges_field": "downstream", "node_id_field": "name",
            "edge_object_field": "target", "duplicate_grounding_check": True,
        })


@pytest.mark.parametrize(
    "settings",
    [{"graph_shape": "graphs"}, {"graph_shape": "graph_list", "nodes_field": "a.b"},
     {"graph_shape": "graph_list", "strata": ["bad path!"]},
     {"graph_shape": "graph_list", "record_id_field": "has space"}],
)
def test_a_declaration_that_cannot_be_applied_is_refused(settings):
    with pytest.raises(CoverageConfigError):
        CoverageConfig.from_settings(settings)


@pytest.mark.parametrize(
    ("text", "kind"),
    [("mapping_status=DEPRECATED", "equals"), ("a.b=X|Y", "equals"),
     ("identifier~^EC:.*-$", "matches"), ("path:data/x/*.yaml", "path")],
)
def test_an_exemption_rule_has_three_forms(text, kind):
    assert ExemptionRule.parse(text).kind == kind


def test_the_first_operator_splits_a_rule():
    """`=` inside a regex is part of the pattern, not a second operator."""
    rule = ExemptionRule.parse("label~a=b")
    assert (rule.kind, rule.field) == ("matches", "label")


@pytest.mark.parametrize(
    "text",
    ["DEPRECATED", "=DEPRECATED", "bad field=X", "status=A||B", "status=",
     "id~(", "id~", "path:", "path:/etc/*.yaml", "path:../other/*.yaml"],
)
def test_a_rule_that_cannot_mean_anything_is_an_error(text):
    """A typo must fail the declaration, not become a rule matching nothing."""
    with pytest.raises(CoverageConfigError):
        ExemptionRule.parse(text)


# --------------------------------------------------------------------------
# What counts as covered
# --------------------------------------------------------------------------


def test_a_graph_with_no_edge_is_not_coverage(tmp_path):
    report = _report(tmp_path, {
        "data/none.yaml": {"identifier": "A"},
        "data/edgeless.yaml": {"identifier": "B", "causal_graphs": [_graph("g", 0)]},
        "data/covered.yaml": {"identifier": "C", "causal_graphs": [_graph("g", 2)]},
    })
    coverage = report["coverage"]
    assert (coverage["no_graph"], coverage["edgeless_only"], coverage["with_graph"]) == (1, 1, 1)
    assert coverage["fraction_with_graph"] == round(1 / 3, 4)


def test_an_empty_graph_list_is_no_graph(tmp_path):
    report = _report(tmp_path, {"data/a.yaml": {"causal_graphs": []}})
    assert report["coverage"]["no_graph"] == 1


def test_a_nonmechanistic_graph_is_coverage_but_not_a_mechanism(tmp_path):
    report = _report(
        tmp_path,
        {
            "data/mech.yaml": {"causal_graphs": [_graph("g", 2, "MECHANISTIC")]},
            "data/non.yaml": {"causal_graphs": [_graph("g", 2, "NONMECHANISTIC")]},
            "data/unset.yaml": {"causal_graphs": [_graph("g", 2)]},
            "data/edgeless.yaml": {"causal_graphs": [_graph("g", 0, "MECHANISTIC")]},
        },
        scope_field="scope_status", mechanistic_scopes=["MECHANISTIC"],
    )
    coverage = report["coverage"]
    assert coverage["with_graph"] == 3
    # An edgeless graph cannot be a mechanism whatever its scope says.
    assert coverage["with_mechanistic_graph"] == 1
    assert coverage["edgeless_only"] == 1
    assert report["graphs"]["scopes"] == {
        "<unset>": 1, "MECHANISTIC": 2, "NONMECHANISTIC": 1,
    }


def test_one_mechanistic_graph_makes_a_record_mechanistic(tmp_path):
    report = _report(
        tmp_path,
        {"data/a.yaml": {"causal_graphs": [
            _graph("topology", 3, "NONMECHANISTIC"), _graph("assembly", 2, "MECHANISTIC"),
        ]}},
        scope_field="scope_status", mechanistic_scopes=["MECHANISTIC"],
    )
    assert report["coverage"]["with_mechanistic_graph"] == 1


def test_without_a_declared_scope_there_is_no_mechanistic_count(tmp_path):
    """HabitatMech's graphs carry no disposition. Reporting all 32 as
    "mechanistic" would assert something no field says."""
    report = _report(tmp_path, {"data/a.yaml": {"causal_graphs": [_graph("g", 2)]}})
    assert report["coverage"]["with_mechanistic_graph"] is None
    assert report["coverage"]["fraction_mechanistic"] is None
    assert report["graphs"]["scopes"] is None


# --------------------------------------------------------------------------
# Declared exemptions
# --------------------------------------------------------------------------


def test_an_exempt_record_leaves_the_denominator(tmp_path):
    records = {
        "data/live.yaml": {"mapping_status": "REVIEWED"},
        "data/retired.yaml": {"mapping_status": "DEPRECATED",
                              "causal_graphs": [_graph("g", 1)]},
    }
    exempted = _report(tmp_path / "a", records, exempt_when=["mapping_status=DEPRECATED"])
    counted = _report(tmp_path / "b", records)

    assert counted["coverage"]["eligible"] == 2
    assert exempted["coverage"]["eligible"] == 1
    assert exempted["coverage"]["fraction_with_graph"] == 0.0
    assert exempted["exempt"]["records"] == 1
    # It still carries a graph, and saying so is how a wrong rule shows up.
    assert exempted["exempt"]["with_graph"] == 1
    assert exempted["records"] == exempted["exempt"]["records"] + exempted["coverage"]["eligible"]


def test_the_first_matching_rule_is_credited(tmp_path):
    records = {"data/a.yaml": {"mapping_status": "DEPRECATED", "term_kind": "OBJECT_PROPERTY"}}
    rules = ["mapping_status=DEPRECATED", "term_kind=OBJECT_PROPERTY"]
    forward = _report(tmp_path / "f", records, exempt_when=rules)["exempt"]["by_rule"]
    backward = _report(tmp_path / "b", records, exempt_when=rules[::-1])["exempt"]["by_rule"]
    assert forward == {"mapping_status=DEPRECATED": 1, "term_kind=OBJECT_PROPERTY": 0}
    assert backward == {"term_kind=OBJECT_PROPERTY": 1, "mapping_status=DEPRECATED": 0}


def test_a_rule_that_matches_nothing_is_still_reported(tmp_path):
    """Most declared DEPRECATED rules match no record today. A zero is the
    report saying so; an absent key would look like no rule at all."""
    report = _report(tmp_path, {"data/a.yaml": {"mapping_status": "SEEDED"}},
                     exempt_when=["mapping_status=DEPRECATED"])
    assert report["exempt"]["by_rule"] == {"mapping_status=DEPRECATED": 0}


def test_alternatives_and_list_values_match_any_element(tmp_path):
    report = _report(
        tmp_path,
        {"data/a.yaml": {"term_kind": "DATATYPE_PROPERTY"},
         "data/b.yaml": {"tags": ["x", "grouping"]},
         "data/c.yaml": {"term_kind": "CLASS", "tags": ["x"]}},
        exempt_when=["term_kind=OBJECT_PROPERTY|DATATYPE_PROPERTY", "tags=grouping"],
    )
    assert report["exempt"]["records"] == 2


def test_a_dotted_rule_follows_the_same_path_as_the_corpus_report(tmp_path):
    report = _report(
        tmp_path,
        {"data/a.yaml": {"ontology_mapping": {"mapping_quality": "PLACEHOLDER"}},
         "data/b.yaml": {"ontology_mapping": {"mapping_quality": "EXACT"}}},
        exempt_when=["ontology_mapping.mapping_quality=PLACEHOLDER"],
    )
    assert report["exempt"]["records"] == 1


def test_a_regex_rule_searches_the_value(tmp_path):
    """Searched, not matched whole: an unanchored pattern finds a substring,
    and anchoring is the rule author's to write."""
    report = _report(
        tmp_path,
        {"data/a.yaml": {"identifier": "EC:1.1.1.-", "label": "x"},
         "data/b.yaml": {"identifier": "EC:1.1.1.1", "label": "a grouping term"},
         "data/c.yaml": {"identifier": "EC:1.1.1.2", "label": "leaf"}},
        exempt_when=["identifier~^EC:.*-$", "label~grouping"],
    )
    assert report["exempt"]["by_rule"] == {"identifier~^EC:.*-$": 1, "label~grouping": 1}


def test_scalars_compare_as_text(tmp_path):
    report = _report(
        tmp_path,
        {"data/a.yaml": {"abstract": True}, "data/b.yaml": {"abstract": False},
         "data/c.yaml": {"level": 1}},
        exempt_when=["abstract=true", "level=1"],
    )
    assert report["exempt"]["records"] == 2


def test_a_path_rule_uses_record_glob_semantics(tmp_path):
    """`*` does not cross a directory, as in the manifest's record_globs.
    fnmatch's `*` does, and would exempt the nested record too."""
    report = _report(
        tmp_path,
        {"data/metpo/a.yaml": {"identifier": "A"},
         "data/metpo/nested/b.yaml": {"identifier": "B"},
         "data/other/c.yaml": {"identifier": "C"}},
        exempt_when=["path:data/metpo/*.yaml"],
    )
    assert report["exempt"]["records"] == 1


# --------------------------------------------------------------------------
# Several graphs per record
# --------------------------------------------------------------------------


def test_graphs_per_record_and_the_combination_each_record_carries(tmp_path):
    report = _report(
        tmp_path,
        {"data/both.yaml": {"causal_graphs": [
            _graph("a", 2, graph_kind="ASSEMBLY"), _graph("f", 2, graph_kind="FUNCTION")]},
         "data/one.yaml": {"causal_graphs": [_graph("f", 2, graph_kind="FUNCTION")]},
         "data/none.yaml": {"identifier": "X"}},
        graph_facets=["graph_kind"],
    )
    assert report["graphs"]["per_record"] == {"0": 1, "1": 1, "2": 1}
    facet = report["graphs"]["facets"]["graph_kind"]
    assert facet["graphs"] == {"ASSEMBLY": 1, "FUNCTION": 2}
    assert facet["record_combinations"] == {"ASSEMBLY+FUNCTION": 1, "FUNCTION": 1}


def test_a_graphless_record_grounded_in_another_records_graph_is_counted(tmp_path):
    """TraitMech's acetoclastic methanogenesis has no graph of its own and is
    a node in methanogenesis's. A per-record count cannot see that."""
    graph = _graph("g", 1)
    graph["nodes"][1]["grounding"] = "T:2"
    edgeless = _graph("g", 0)
    edgeless["nodes"][0]["grounding"] = "T:3"
    records = {
        "data/parent.yaml": {"identifier": "T:1", "causal_graphs": [graph]},
        "data/modelled_elsewhere.yaml": {"identifier": "T:2"},
        "data/only_in_an_edgeless_graph.yaml": {"identifier": "T:3"},
        "data/other.yaml": {"identifier": "T:4", "causal_graphs": [edgeless]},
        "data/nowhere.yaml": {"identifier": "T:5"},
    }
    report = _report(tmp_path / "a", records, record_id_field="identifier")
    assert report["coverage"]["graphless_but_referenced_elsewhere"] == 1
    assert _report(tmp_path / "b", records)["coverage"][
        "graphless_but_referenced_elsewhere"
    ] is None


# --------------------------------------------------------------------------
# A record that is one graph
# --------------------------------------------------------------------------

NESTED = {
    "graph_shape": "node_nested_edges", "nodes_field": "ecological_interactions",
    "node_id_field": "name", "node_type_field": "interaction_type",
    "edges_field": "downstream", "edge_object_field": "target",
}


def test_a_record_can_be_one_graph_whose_nodes_list_their_edges(tmp_path):
    root = _corpus(tmp_path, {
        "data/chain.yaml": {"ecological_interactions": [
            {"name": "a", "interaction_type": "CROSS_FEEDING", "downstream": [{"target": "b"}]},
            {"name": "b", "downstream": [{"target": "c"}]},
            {"name": "c"}]},
        "data/unlinked.yaml": {"ecological_interactions": [{"name": "a"}, {"name": "b"}]},
        "data/empty.yaml": {"ecological_interactions": []},
        "data/absent.yaml": {"id": "x"},
        "data/typo.yaml": {"ecological_interactions": [
            {"name": "a", "downstream": [{"target": "missing"}]}]},
    })
    report = collect("m", root, GLOBS, CoverageConfig.from_settings(NESTED)).as_dict()
    coverage = report["coverage"]
    assert (coverage["with_graph"], coverage["edgeless_only"], coverage["no_graph"]) == (2, 1, 2)
    assert report["structure"]["findings"]["DANGLING_EDGE"] == {"findings": 1, "graphs": 1}
    assert report["graphs"]["node_types"] == {"<unset>": 5, "CROSS_FEEDING": 1}
    # Undeclared, so unmeasured -- not zero, and not "<unset>" (#477).
    assert report["graphs"]["edges_with_evidence"] is None
    assert report["graphs"]["nodes_grounded"] is None
    assert report["graphs"]["predicates"] is None


def test_directed_cycles_are_not_findings(tmp_path):
    """CommunityMech's syntrophic loops are cycles by design."""
    root = _corpus(tmp_path, {"data/loop.yaml": {"ecological_interactions": [
        {"name": "a", "downstream": [{"target": "b"}]},
        {"name": "b", "downstream": [{"target": "a"}]}]}})
    report = collect("m", root, GLOBS, CoverageConfig.from_settings(NESTED)).as_dict()
    assert report["structure"]["findings"] == {}


# --------------------------------------------------------------------------
# Graph statistics and structure
# --------------------------------------------------------------------------


def test_evidence_and_grounding_are_counted_where_present(tmp_path):
    graph = _graph("g", 2)
    graph["edges"][0]["evidence"] = [{"reference": "PMID:1"}]
    graph["edges"][1]["evidence"] = []
    graph["nodes"][0]["grounding"] = "GO:1"
    report = _report(tmp_path, {"data/a.yaml": {"causal_graphs": [graph]}})
    assert report["graphs"]["edges_with_evidence"] == 1
    assert report["graphs"]["nodes_grounded"] == 1


def test_node_and_edge_counts_are_spread_and_bucketed(tmp_path):
    report = _report(tmp_path, {"data/a.yaml": {"causal_graphs": [
        _graph("a", 1), _graph("b", 3), _graph("c", 25)]}})
    graphs = report["graphs"]
    assert graphs["edges_per_graph"] == {"min": 1, "median": 3, "max": 25}
    assert graphs["edge_count_histogram"] == {"1": 1, "2-4": 1, "20+": 1}
    assert graphs["total"] == 3 and graphs["edges"] == 29


def test_findings_are_counted_both_as_findings_and_as_graphs(tmp_path):
    """ORPHAN_NODE is per node and FRAGMENTED_GRAPH per graph; one number per
    code would make 71 findings on 27 graphs read like 71 bad graphs."""
    graph = _graph("g", 1)
    graph["nodes"] += [{"node_id": "lonely1"}, {"node_id": "lonely2"}]
    report = _report(tmp_path, {"data/a.yaml": {"causal_graphs": [graph]}})
    findings = report["structure"]["findings"]
    assert findings["ORPHAN_NODE"] == {"findings": 2, "graphs": 1}
    assert report["structure"]["graphs_with_findings"] == 1


def test_findings_are_split_by_scope(tmp_path):
    """TraitMech exempts NONMECHANISTIC graphs from connectivity (#598), and
    TraitMech#613 asks that the fragmentation it hides still be counted."""
    fragmented = {
        "graph_id": "g", "nodes": [{"node_id": x} for x in "abcd"],
        "edges": [{"subject": "a", "object": "b"}, {"subject": "c", "object": "d"}],
    }
    report = _report(
        tmp_path,
        {"data/m.yaml": {"causal_graphs": [dict(fragmented, scope_status="MECHANISTIC")]},
         "data/n.yaml": {"causal_graphs": [dict(fragmented, scope_status="NONMECHANISTIC")]}},
        scope_field="scope_status", mechanistic_scopes=["MECHANISTIC"],
    )
    assert report["structure"]["graphs_by_scope"]["FRAGMENTED_GRAPH"] == {
        "MECHANISTIC": 1, "NONMECHANISTIC": 1,
    }


def test_duplicate_groundings_are_checked_only_when_declared(tmp_path):
    graph = _graph("g", 1)
    graph["nodes"][0]["grounding"] = graph["nodes"][1]["grounding"] = "CHEBI:1"
    records = {"data/a.yaml": {"causal_graphs": [graph]}}
    checked = _report(tmp_path / "a", records, duplicate_grounding_check=True)
    unchecked = _report(tmp_path / "b", records)
    assert "DUPLICATE_GROUNDING" in checked["structure"]["findings"]
    assert "DUPLICATE_GROUNDING" not in unchecked["structure"]["findings"]


def test_the_declared_anchor_reaches_the_audit(tmp_path):
    records = {"data/a.yaml": {"causal_graphs": [_graph("g", 1)]}}
    anchored = _report(tmp_path / "a", records, anchor_node_types=["TRAIT"])
    unanchored = _report(tmp_path / "b", records)
    assert anchored["structure"]["findings"]["NO_ANCHOR_NODE"] == {"findings": 1, "graphs": 1}
    assert unanchored["structure"]["findings"] == {}


def test_a_graph_id_repeated_within_a_record_is_a_finding(tmp_path):
    """Two records may share a graph_id -- CellStructureMech does -- but one
    record may not, since an anchor `causal_graphs#<id>` could not say which."""
    report = _report(tmp_path, {
        "data/a.yaml": {"causal_graphs": [_graph("g", 1), _graph("g", 2)]},
        "data/b.yaml": {"causal_graphs": [_graph("h", 1)]},
        "data/c.yaml": {"causal_graphs": [_graph("h", 1)]},
    })
    structure = report["structure"]
    assert structure["findings"]["DUPLICATE_GRAPH_ID"] == {"findings": 2, "graphs": 2}
    # Counted on the same path as every other code, so the aggregate agrees (#475).
    assert structure["graphs_with_findings"] == 2


# --------------------------------------------------------------------------
# Reading the corpus
# --------------------------------------------------------------------------


def test_unreadable_and_malformed_records_are_named_and_excluded(tmp_path):
    no_id = _graph("g", 1)
    del no_id["nodes"][0]["node_id"]
    report = _report(tmp_path, {
        "data/good.yaml": {"causal_graphs": [_graph("g", 1)]},
        "data/broken.yaml": "causal_graphs: [unclosed\n",
        "data/list.yaml": "- a\n- b\n",
        "data/string.yaml": {"causal_graphs": "see elsewhere"},
        "data/no_node_id.yaml": {"causal_graphs": [no_id]},
    })
    assert report["records"] == 1
    assert report["unreadable"] == ["data/broken.yaml"]
    assert [entry.split(":")[0] for entry in report["malformed"]] == [
        "data/list.yaml", "data/no_node_id.yaml", "data/string.yaml",
    ]
    assert "not a list" in next(m for m in report["malformed"] if "string" in m)


def test_strata_break_every_count_down(tmp_path):
    report = _report(
        tmp_path,
        {"data/a/x.yaml": {"status": "REVIEWED", "causal_graphs": [_graph("g", 1)]},
         "data/a/y.yaml": {"status": "REVIEWED"},
         "data/b/z.yaml": {"status": "DEPRECATED"},
         "data/b/w.yaml": {}},
        exempt_when=["status=DEPRECATED"], strata=["status", "@directory"],
    )
    status = report["strata"]["status"]
    assert status["REVIEWED"] == {
        "records": 2, "exempt": 0, "eligible": 2,
        "with_graph": 1, "edgeless_only": 0, "no_graph": 1,
    }
    # An exempt record is in no eligible bucket, in a stratum as in the total.
    assert status["DEPRECATED"] == {
        "records": 1, "exempt": 1, "eligible": 0,
        "with_graph": 0, "edgeless_only": 0, "no_graph": 0,
    }
    assert status["<unset>"]["no_graph"] == 1
    assert set(report["strata"]["@directory"]) == {"data/a", "data/b"}


def test_the_report_is_deterministic_and_carries_no_absolute_paths(tmp_path):
    records = {f"data/{name}.yaml": {"causal_graphs": [_graph("g", i)]}
               for i, name in enumerate("cab")}
    root = _corpus(tmp_path, records)
    config = _config(strata=["@directory"])
    first = collect("m", root, GLOBS, config).to_json()
    assert first == collect("m", root, GLOBS, config).to_json()
    assert str(root) not in first
    json.loads(first)


def test_a_sample_reads_the_first_n_records(tmp_path):
    root = _corpus(tmp_path, {f"data/{i}.yaml": {"identifier": str(i)} for i in range(5)})
    report = collect("m", root, GLOBS, _config(), sample=2).as_dict()
    assert report["records"] == 2 and report["sampled"] is True


def test_the_corpus_must_exist_and_be_declared(tmp_path):
    with pytest.raises(CoverageError, match="not a directory"):
        collect("m", tmp_path / "absent", GLOBS, _config())
    with pytest.raises(CoverageError, match="no record globs"):
        collect("m", tmp_path, [], _config())


def test_a_root_with_no_records_at_the_globs_is_an_error_not_an_empty_corpus(tmp_path):
    """The wrong directory, or a Mech that moved its records, reads as 0 of 0
    -- which a fleet table would show as a completed read (#473)."""
    root = _corpus(tmp_path, {"elsewhere/a.yaml": {"causal_graphs": [_graph("g", 1)]}})
    with pytest.raises(CoverageError, match="no records at"):
        collect("m", root, GLOBS, _config())
    # A corpus whose every record is unreadable is not empty: it is named.
    broken = _corpus(tmp_path / "b", {"data/a.yaml": "x: [unclosed\n"})
    assert collect("m", broken, GLOBS, _config()).unreadable == ["data/a.yaml"]


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def test_a_mech_without_a_graph_model_reports_its_reason(capsys):
    from kg_microbe_graph.__main__ import main

    assert main(["coverage", "--mech", "culturemech"]) == 0
    assert "reports no causal-graph coverage: not_applicable" in capsys.readouterr().out


def test_root_reads_a_snapshot_under_the_mechs_own_declaration(tmp_path, capsys):
    from kg_microbe_graph.__main__ import main

    root = _corpus(tmp_path, {
        "data/traits/a.yaml": {"mapping_status": "REVIEWED",
                               "causal_graphs": [_graph("g", 1, "MECHANISTIC")]},
        "data/traits/b.yaml": {"mapping_status": "DEPRECATED"},
    })
    assert main(["coverage", "--mech", "traitmech", "--root", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["exempt"]["by_rule"]["mapping_status=DEPRECATED"] == 1
    assert report["coverage"]["with_mechanistic_graph"] == 1


def test_an_unreadable_record_makes_the_command_fail(tmp_path, capsys):
    from kg_microbe_graph.__main__ import main

    root = _corpus(tmp_path, {"data/traits/a.yaml": "identifier: [unclosed\n"})
    assert main(["coverage", "--mech", "traitmech", "--root", str(root)]) == 1
    assert json.loads(capsys.readouterr().out)["unreadable"] == ["data/traits/a.yaml"]


def test_a_fleet_run_names_what_it_could_not_read_and_fails(monkeypatch, capsys):
    import kg_microbe_graph.__main__ as cli

    def unavailable(key, **_):
        raise MechRootError(f"{key} is not configured")

    monkeypatch.setattr(cli, "resolve_mech_root", unavailable)
    assert cli.main(["coverage", "--all"]) == 1
    payload = json.loads(capsys.readouterr().out)
    manifest = load_fleet_manifest()
    enabled = set(manifest.with_capability(CAPABILITY))
    assert set(payload["unavailable"]) == enabled
    assert set(payload["not_enabled"]) == set(manifest.mechs) - enabled
    assert payload["reports"] == {}


def _fleet_root(tmp_path: Path) -> Path:
    """One directory holding a record at every enabled Mech's first glob."""
    manifest = load_fleet_manifest()
    records = {}
    for key in manifest.with_capability(CAPABILITY):
        glob = manifest.mechs[key].record_globs[0]
        records[glob.replace("**/", "").replace("*", key)] = {"identifier": key}
    return _corpus(tmp_path, records)


def test_a_fleet_summary_has_a_row_for_every_mech(monkeypatch, tmp_path, capsys):
    import kg_microbe_graph.__main__ as cli

    root = _fleet_root(tmp_path)
    monkeypatch.setattr(cli, "resolve_mech_root", lambda key, **_: root)
    assert cli.main(["coverage", "--all", "--summary"]) == 0
    lines = capsys.readouterr().out.splitlines()
    for key in load_fleet_manifest().mechs:
        assert any(line.startswith(key) for line in lines), key


def test_root_names_one_checkout(capsys):
    from kg_microbe_graph.__main__ import main

    with pytest.raises(SystemExit) as raised:
        main(["coverage", "--all", "--root", "."])
    assert raised.value.code == 2


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------


def test_every_mech_decides_whether_it_has_a_causal_graph_to_cover():
    """CultureMech and MIM have no graph model. Saying so with a reason is
    what separates "does not apply" from "forgot"."""
    manifest = load_fleet_manifest()
    assert set(manifest.with_capability(CAPABILITY)) == {
        "communitymech", "traitmech", "proteintraitsmech", "antibioticmech",
        "cellstructuremech", "habitatmech", "naturalproductmech", "taxonmech",
    }
    for key, mech in manifest.mechs.items():
        capability = mech.capabilities[CAPABILITY]
        if not capability.is_enabled:
            assert capability.reason, f"{key} opts out without a reason"


@pytest.mark.parametrize("mech", load_fleet_manifest().with_capability(CAPABILITY))
def test_every_enabled_declaration_is_one_the_tool_can_apply(mech):
    """The loader checks each setting's type; only this checks that they make
    sense together. It needs no checkout, so it runs in CI."""
    settings = load_fleet_manifest().mechs[mech].capabilities[CAPABILITY].settings
    CoverageConfig.from_settings(settings)


# --------------------------------------------------------------------------
# Against the real corpora
# --------------------------------------------------------------------------


def _root_or_skip(mech: str) -> Path:
    try:
        return resolve_mech_root(mech, claw_root=ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a {mech} checkout: {exc}")


@pytest.mark.parametrize("mech", load_fleet_manifest().with_capability(CAPABILITY))
def test_every_declared_field_is_one_the_corpus_carries(mech):
    """A misspelt exemption field matches nothing and reads as "no record is
    exempt"; a misspelt stratum reports everything as <unset>. Both look like
    data, so each declared field is checked against its own corpus."""
    root = _root_or_skip(mech)
    declaration = load_fleet_manifest().mechs[mech]
    config = CoverageConfig.from_settings(declaration.capabilities[CAPABILITY].settings)
    fields = [rule.field for rule in config.exempt_when if rule.field]
    fields += [s for s in config.strata if not s.startswith("@")]
    if config.record_id_field:
        fields.append(config.record_id_field)

    report = corpus_report(mech, root, list(declaration.record_globs), fields, sample=400)
    if not report.records:
        pytest.skip(f"{mech} has no records at its declared globs here")
    empty = [name for name, stats in report.fields.items() if not stats.populated]
    assert not empty, f"{mech} declares {empty}, which no sampled record carries"

    for rule in config.exempt_when:
        if rule.kind == "path":
            assert any(p.is_file() for p in root.glob(rule.glob or "")), (
                f"{mech} exempts {rule.text}, which matches no file"
            )


def _slot_ranges(schema_view, slot: str) -> set[str]:
    """Every range the schema gives `slot`, on any class that has it --
    through imports, attributes and slot_usage, which raw YAML cannot see.
    TraitMech declares no tree_root, so no single class can be assumed."""
    return {
        schema_view.induced_slot(slot, name).range
        for name in schema_view.all_classes()
        if slot in schema_view.class_slots(name)
    }


@pytest.mark.parametrize("mech", load_fleet_manifest().with_capability(CAPABILITY))
def test_an_exempted_value_is_one_the_schema_permits(mech):
    """Most DEPRECATED rules match no record today, so the corpus cannot say
    whether the value is spelt right. The schema can -- and a rule whose field
    the schema cannot resolve is a failure, not a silent skip (#478)."""
    from linkml_runtime.utils.schemaview import SchemaView

    root = _root_or_skip(mech)
    declaration = load_fleet_manifest().mechs[mech]
    config = CoverageConfig.from_settings(declaration.capabilities[CAPABILITY].settings)
    rules = [r for r in config.exempt_when if r.kind == "equals" and r.field]
    if not rules:
        pytest.skip(f"{mech} declares no field=value exemption")
    schema_view = SchemaView(str(root / declaration.schema_paths[0]))
    for rule in rules:
        assert rule.field is not None
        ranges = _slot_ranges(schema_view, rule.field.rsplit(".", 1)[-1])
        assert len(ranges) == 1, f"{mech}: {rule.field} resolves to ranges {ranges}"
        enum = schema_view.get_enum(ranges.pop())
        if enum is None:
            continue
        permitted = set(enum.permissible_values)
        assert rule.values <= permitted, (
            f"{mech} exempts {sorted(rule.values - permitted)} for {rule.field}, "
            f"which its schema does not permit"
        )


def _slots(schema_view, class_name: str) -> set[str]:
    return set(schema_view.class_slots(class_name))


def _range(schema_view, class_name: str, slot: str) -> str:
    return schema_view.induced_slot(slot, class_name).range


@pytest.mark.parametrize("mech", load_fleet_manifest().with_capability(CAPABILITY))
def test_every_declared_graph_field_is_one_the_schema_declares(mech):
    """A misspelt `graphs_field` finds no graphs and reports 0% coverage with
    exit 0; a misspelt scope_field zeroes the mechanistic headline. Both look
    like data. Checked against the schema, so it holds whether or not the
    corpus has graphs yet -- TaxonMech has none -- and costs no corpus scan
    (#492)."""
    from linkml_runtime.utils.schemaview import SchemaView

    root = _root_or_skip(mech)
    declaration = load_fleet_manifest().mechs[mech]
    config = CoverageConfig.from_settings(declaration.capabilities[CAPABILITY].settings)
    shape = config.shape
    schema_view = SchemaView(str(root / declaration.schema_paths[0]))

    slot = shape.graphs_field or shape.nodes_field
    records = [c for c in schema_view.all_classes() if slot in _slots(schema_view, c)]
    assert records, f"{mech}: no class in the schema has a {slot!r} slot"
    record_class = records[0]
    if config.record_id_field:
        assert config.record_id_field.split(".")[0] in _slots(schema_view, record_class)

    if shape.graphs_field:
        graph_class = _range(schema_view, record_class, shape.graphs_field)
        graph = {shape.graph_id_field, shape.nodes_field, shape.edges_field,
                 config.scope_field, *config.graph_facets} - {None}
        missing = graph - _slots(schema_view, graph_class)
        assert not missing, f"{mech}: {graph_class} has no {sorted(missing)}"
        node_class = _range(schema_view, graph_class, shape.nodes_field)
        edge_class = _range(schema_view, graph_class, shape.edges_field)
        node = {shape.node_id_field, shape.node_type_field, shape.node_grounding_field}
    else:
        node_class = _range(schema_view, record_class, shape.nodes_field)
        edge_class = _range(schema_view, node_class, shape.edges_field)
        node = {shape.node_id_field, shape.node_type_field, shape.edges_field}
    missing = (node - {None}) - _slots(schema_view, node_class)
    assert not missing, f"{mech}: {node_class} has no {sorted(missing)}"
    edge = {shape.edge_subject_field, shape.edge_object_field,
            shape.edge_predicate_field, shape.edge_evidence_field} - {None}
    missing = edge - _slots(schema_view, edge_class)
    assert not missing, f"{mech}: {edge_class} has no {sorted(missing)}"


# --------------------------------------------------------------------------
# Review follow-ups (#473-#478)
# --------------------------------------------------------------------------


def test_strata_carry_the_mechanistic_count(tmp_path):
    """TraitMech's mapping_status stratum exists to separate "does not apply"
    from "deferred" NONMECHANISTIC graphs; that needs the count per stratum."""
    report = _report(
        tmp_path,
        {"data/r.yaml": {"status": "REVIEWED", "causal_graphs": [_graph("g", 1, "MECHANISTIC")]},
         "data/p.yaml": {"status": "PROPOSED", "causal_graphs": [_graph("g", 1, "NONMECHANISTIC")]}},
        scope_field="scope_status", mechanistic_scopes=["MECHANISTIC"], strata=["status"],
    )
    status = report["strata"]["status"]
    assert status["REVIEWED"]["with_mechanistic_graph"] == 1
    assert status["PROPOSED"] == {
        "records": 1, "exempt": 0, "eligible": 1, "with_graph": 1,
        "edgeless_only": 0, "no_graph": 0, "with_mechanistic_graph": 0,
    }


def test_an_exempt_record_is_out_of_every_eligible_count_but_its_graphs_are_measured(tmp_path):
    graph = _graph("g", 1, "MECHANISTIC")
    graph["nodes"][1]["grounding"] = "T:9"
    report = _report(
        tmp_path,
        {"data/retired.yaml": {"identifier": "T:1", "status": "DEPRECATED",
                               "causal_graphs": [_graph("g", 2, "MECHANISTIC")]},
         "data/retired_graphless.yaml": {"identifier": "T:9", "status": "DEPRECATED"},
         "data/live.yaml": {"identifier": "T:2", "causal_graphs": [graph]}},
        scope_field="scope_status", mechanistic_scopes=["MECHANISTIC"],
        record_id_field="identifier", exempt_when=["status=DEPRECATED"],
    )
    coverage = report["coverage"]
    assert coverage["with_mechanistic_graph"] == 1
    # T:9 is grounded in live.yaml's graph, but it is exempt, not a gap.
    assert coverage["graphless_but_referenced_elsewhere"] == 0
    # Graph statistics describe every graph in the corpus, exempt or not.
    assert report["graphs"]["total"] == 2
    assert report["exempt"]["with_graph"] == 1


def test_a_combination_is_a_set_and_multiplicity_lives_in_per_record(tmp_path):
    report = _report(
        tmp_path,
        {"data/a.yaml": {"causal_graphs": [
            _graph("f1", 1, graph_kind="FUNCTION"), _graph("f2", 1, graph_kind="FUNCTION")]}},
        graph_facets=["graph_kind"],
    )
    facet = report["graphs"]["facets"]["graph_kind"]
    assert facet["record_combinations"] == {"FUNCTION": 1}
    assert facet["graphs"] == {"FUNCTION": 2}
    assert report["graphs"]["per_record"] == {"2": 1}


def test_a_dict_valued_stratum_with_dates_and_boolean_keys_is_a_key_not_a_crash(tmp_path):
    root = _corpus(tmp_path, {
        "data/a.yaml": "provenance: {date: 2024-01-01, on: x}\ncausal_graphs: []\n",
    })
    report = collect("m", root, GLOBS, _config(strata=["provenance"])).as_dict()
    (key,) = report["strata"]["provenance"]
    assert "2024-01-01" in key and "true" in key.lower()


def test_a_record_that_is_not_utf8_is_named_unreadable(tmp_path):
    root = _corpus(tmp_path, {"data/good.yaml": {"identifier": "A"}})
    (root / "data" / "latin1.yaml").write_bytes("label: caf\xe9\n".encode("latin-1"))
    report = collect("m", root, GLOBS, _config()).as_dict()
    assert report["unreadable"] == ["data/latin1.yaml"]
    assert report["records"] == 1


@pytest.mark.parametrize(
    ("edges", "bucket"),
    [(0, "0"), (1, "1"), (2, "2-4"), (4, "2-4"), (5, "5-9"), (9, "5-9"),
     (10, "10-19"), (19, "10-19"), (20, "20+")],
)
def test_edge_count_buckets_have_the_documented_boundaries(edges, bucket):
    from kg_microbe_graph.coverage import _edge_bucket

    assert _edge_bucket(edges) == bucket


@pytest.mark.parametrize(
    ("pattern", "directory"),
    [("data/traits/**/*.yaml", "data/traits"), ("kb/communities/*.yaml", "kb/communities"),
     ("records.yaml", "."), ("*.yaml", ".")],
)
def test_the_revision_check_is_limited_to_the_record_directories(pattern, directory):
    from kg_microbe_graph.__main__ import _glob_directory

    assert _glob_directory(pattern) == directory


def _git_init(path: Path) -> None:
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    for command in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t",
                                     "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(path), *command], check=True, capture_output=True)


def test_a_snapshot_inside_another_checkout_is_not_reported_as_that_checkout(tmp_path):
    """The skill extracts snapshots under claw's workspace; asking git there
    answered with claw's HEAD (#472)."""
    from kg_microbe_graph.__main__ import SNAPSHOT, _revision

    _git_init(tmp_path / "enclosing")
    snapshot = _corpus(tmp_path / "enclosing" / "workspace", {"data/a.yaml": {"x": 1}})
    assert _revision(snapshot, GLOBS) == SNAPSHOT
    assert _revision(tmp_path / "plain", GLOBS) == SNAPSHOT


def test_an_untracked_record_makes_a_checkout_uncommitted(tmp_path):
    from kg_microbe_graph.__main__ import _revision

    _git_init(tmp_path / "mech")
    clean = _revision(tmp_path / "mech", GLOBS)
    assert clean.startswith("HEAD ") and "uncommitted" not in clean
    (tmp_path / "mech" / "data").mkdir()
    (tmp_path / "mech" / "data" / "new.yaml").write_text("identifier: A\n")
    assert "uncommitted" in _revision(tmp_path / "mech", GLOBS)
    # Outside the record directories, a change is not the corpus's business.
    assert "uncommitted" not in _revision(tmp_path / "mech", ["kb/*.yaml"])


def test_the_revision_probe_takes_no_optional_locks(monkeypatch, tmp_path):
    import subprocess

    import kg_microbe_graph.__main__ as cli

    calls = []

    def record(command, **kwargs):
        calls.append((command, kwargs.get("env", {})))
        raise subprocess.CalledProcessError(128, command)

    monkeypatch.setattr(cli.subprocess, "run", record)
    cli._revision(tmp_path, GLOBS)
    command, env = calls[0]
    assert "--no-optional-locks" in command and env["GIT_OPTIONAL_LOCKS"] == "0"


def _traitmech_root(tmp_path: Path, records: dict[str, object]) -> Path:
    return _corpus(tmp_path, {f"data/traits/{name}": body for name, body in records.items()})


def test_a_malformed_record_makes_the_command_fail(tmp_path, capsys):
    from kg_microbe_graph.__main__ import main

    root = _traitmech_root(tmp_path, {"a.yaml": {"causal_graphs": "see elsewhere"}})
    assert main(["coverage", "--mech", "traitmech", "--root", str(root)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["malformed"]
    assert "excluded 0 unreadable, 0 empty and 1 malformed" in captured.err


def test_one_mech_that_cannot_be_read_is_a_usage_failure(monkeypatch, tmp_path):
    import kg_microbe_graph.__main__ as cli

    def unavailable(key, **_):
        raise MechRootError(f"{key} is not configured")

    monkeypatch.setattr(cli, "resolve_mech_root", unavailable)
    assert cli.main(["coverage", "--mech", "traitmech"]) == 2
    empty = _corpus(tmp_path, {"elsewhere/a.yaml": {"x": 1}})
    assert cli.main(["coverage", "--mech", "traitmech", "--root", str(empty)]) == 2


def test_a_fleet_mech_with_no_records_is_unavailable(monkeypatch, tmp_path, capsys):
    import kg_microbe_graph.__main__ as cli

    empty = _corpus(tmp_path, {"elsewhere/a.yaml": {"x": 1}})
    monkeypatch.setattr(cli, "resolve_mech_root", lambda key, **_: empty)
    assert cli.main(["coverage", "--all"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["unavailable"]) == set(load_fleet_manifest().with_capability(CAPABILITY))
    assert all("no records at" in why for why in payload["unavailable"].values())


def test_a_declaration_the_tool_cannot_apply_fails_the_command(monkeypatch):
    import kg_microbe_graph.__main__ as cli

    def refuse(settings):
        raise CoverageConfigError("nonsense")

    monkeypatch.setattr(cli.CoverageConfig, "from_settings", staticmethod(refuse))
    assert cli.main(["coverage", "--mech", "traitmech"]) == 2


def test_a_summary_row_carries_the_reports_numbers_and_marks_a_sample(tmp_path, capsys):
    from kg_microbe_graph.__main__ import main

    root = _traitmech_root(tmp_path, {
        "a.yaml": {"causal_graphs": [_graph("g", 1, "MECHANISTIC")]},
        "b.yaml": {"causal_graphs": [_graph("g", 1, "NONMECHANISTIC")]},
        "c.yaml": {"mapping_status": "DEPRECATED"},
        "d.yaml": {},
    })
    assert main(["coverage", "--mech", "traitmech", "--root", str(root), "--summary"]) == 0
    row = next(line for line in capsys.readouterr().out.splitlines()
               if line.startswith("traitmech"))
    # records exempt eligible w/graph % mechan. % edgeless graphs flagged
    assert row.split()[1:] == ["4", "1", "3", "2", "66.7%", "1", "33.3%", "0", "2", "2"]

    assert main(["coverage", "--mech", "traitmech", "--root", str(root),
                 "--summary", "--sample", "2"]) == 0
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.startswith("traitmech"))
    assert row.split()[1] == "2*"
    assert "sampled: the first 2 records only" in out


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_sample_must_read_at_least_one_record(value):
    from kg_microbe_graph.__main__ import main

    with pytest.raises(SystemExit) as raised:
        main(["coverage", "--mech", "traitmech", "--sample", value])
    assert raised.value.code == 2


# --------------------------------------------------------------------------
# Second review round (#480-#483)
# --------------------------------------------------------------------------


def _rich_corpus(tmp_path: Path) -> Path:
    """A corpus exercising every counter, so a part left out of a merge shows."""
    referencing = _graph("g", 1, "MECHANISTIC", graph_kind="ASSEMBLY")
    referencing["nodes"][1]["grounding"] = "T:3"
    referencing["nodes"][0]["grounding"] = "CHEBI:1"
    referencing["nodes"].append({"node_id": "lonely", "node_type": "X", "grounding": "CHEBI:1"})
    records: dict[str, object] = {
        "data/a/1.yaml": {"identifier": "T:1", "status": "REVIEWED", "causal_graphs": [
            referencing, _graph("h", 3, "NONMECHANISTIC", graph_kind="FUNCTION")]},
        "data/a/2.yaml": {"identifier": "T:2", "status": "DEPRECATED",
                          "causal_graphs": [_graph("g", 2, "MECHANISTIC")]},
        "data/b/3.yaml": {"identifier": "T:3", "status": "PROPOSED"},
        "data/b/4.yaml": {"identifier": "T:4", "causal_graphs": [
            _graph("g", 0), _graph("g", 1, graph_kind="FUNCTION")]},
        "data/b/5.yaml": {"identifier": "T:5", "causal_graphs": [_graph("e", 0)]},
        "data/c/broken.yaml": "x: [unclosed\n",
        "data/c/empty.yaml": "# nothing here\n",
        "data/c/list.yaml": "- a\n",
    }
    for i in range(6, 40):
        records[f"data/d/{i:02d}.yaml"] = {
            "identifier": f"T:{i}", "status": "REVIEWED" if i % 3 else "PROPOSED",
            "causal_graphs": [_graph("g", i % 7, "MECHANISTIC" if i % 2 else "NONMECHANISTIC",
                                     graph_kind="ASSEMBLY" if i % 4 else "FUNCTION")] if i % 5 else [],
        }
    return _corpus(tmp_path, records)


def test_a_parallel_walk_reports_exactly_what_one_process_does(tmp_path, monkeypatch):
    import kg_microbe_graph.coverage as coverage

    root = _rich_corpus(tmp_path)
    config = _config(
        scope_field="scope_status", mechanistic_scopes=["MECHANISTIC"],
        graph_facets=["graph_kind"], anchor_node_types=["X"], duplicate_grounding_check=True,
        record_id_field="identifier", exempt_when=["status=DEPRECATED"],
        strata=["status", "@directory"],
    )
    sequential = collect("m", root, GLOBS, config).to_json()
    monkeypatch.setattr(coverage, "PARALLEL_THRESHOLD", 0)
    parallel = collect("m", root, GLOBS, config, jobs=3).to_json()

    assert parallel == sequential
    report = json.loads(sequential)
    # The fixture must reach every part of the report, or equality proves little.
    assert report["exempt"]["records"] and report["strata"] and report["empty"]
    assert report["coverage"]["graphless_but_referenced_elsewhere"] == 1
    assert {"DUPLICATE_GRAPH_ID", "ORPHAN_NODE"} <= set(report["structure"]["findings"])
    assert report["graphs"]["facets"]["graph_kind"]["record_combinations"]


def test_an_empty_file_is_named_empty_not_unreadable(tmp_path):
    report = _report(tmp_path, {
        "data/good.yaml": {"identifier": "A"},
        "data/blank.yaml": "",
        "data/comments.yaml": "# placeholder\n",
        "data/broken.yaml": "x: [unclosed\n",
    })
    assert report["empty"] == ["data/blank.yaml", "data/comments.yaml"]
    assert report["unreadable"] == ["data/broken.yaml"]
    assert report["records"] == 1


def test_a_file_holding_nothing_still_fails_the_command(tmp_path, capsys):
    from kg_microbe_graph.__main__ import main

    root = _traitmech_root(tmp_path, {"a.yaml": {"mapping_status": "REVIEWED"}, "b.yaml": ""})
    assert main(["coverage", "--mech", "traitmech", "--root", str(root)]) == 1
    assert "data/traits/b.yaml: holds no document" in capsys.readouterr().err


def test_a_regex_with_surrounding_whitespace_is_refused():
    """`label~ grouping` would require a literal leading space (#483)."""
    with pytest.raises(CoverageConfigError, match="whitespace"):
        ExemptionRule.parse("label~ grouping")
    assert ExemptionRule.parse(r"label~\sgrouping").pattern is not None


def test_a_path_rule_that_names_only_directories_is_refused(tmp_path):
    root = _corpus(tmp_path, {"data/metpo/a.yaml": {"identifier": "A"}})
    with pytest.raises(CoverageConfigError, match="names directories"):
        collect("m", root, GLOBS, _config(exempt_when=["path:data/metpo"]))
    assert not issubclass(CoverageConfigError, CoverageError)


def test_a_declaration_only_the_corpus_refutes_is_still_a_declaration_error(
    monkeypatch, tmp_path, capsys
):
    """Exit 2, as for any declaration error -- not "unavailable", exit 1,
    beside checkouts that are merely unconfigured (#497)."""
    import kg_microbe_graph.__main__ as cli

    root = _corpus(tmp_path, {"data/traits/metpo/a.yaml": {"identifier": "A"}})
    real = cli.CoverageConfig.from_settings
    monkeypatch.setattr(cli.CoverageConfig, "from_settings", staticmethod(
        lambda settings: real({**settings, "exempt_when": ["path:data/traits/metpo"]})))
    monkeypatch.setattr(cli, "resolve_mech_root", lambda key, **_: root)
    assert cli.main(["coverage", "--mech", "traitmech", "--root", str(root)]) == 2
    assert cli.main(["coverage", "--all"]) == 2
    assert "declared incorrectly" in capsys.readouterr().err


@pytest.mark.parametrize("spelling", ["true", "True", "yes", "on"])
def test_a_boolean_matches_any_spelling_yaml_reads_as_true(tmp_path, spelling):
    report = _report(
        tmp_path,
        {"data/a.yaml": {"abstract": True}, "data/b.yaml": {"abstract": False}},
        exempt_when=[f"abstract={spelling}"],
    )
    assert report["exempt"]["records"] == 1


def test_a_dotted_rule_reaches_every_list_element_not_just_the_first(tmp_path):
    """The metagenome marker sits somewhere in a lineage, not first (#483)."""
    report = _report(
        tmp_path,
        {"data/metagenome.yaml": {"lineage": [
            {"taxon_id": "NCBITaxon:1"}, {"taxon_id": "NCBITaxon:408169"}]},
         "data/organism.yaml": {"lineage": [
            {"taxon_id": "NCBITaxon:1"}, {"taxon_id": "NCBITaxon:2"}]}},
        exempt_when=["lineage.taxon_id=NCBITaxon:408169"],
    )
    assert report["exempt"]["records"] == 1


# --------------------------------------------------------------------------
# Third review round (#486-#498)
# --------------------------------------------------------------------------


def _far_reference_corpus(tmp_path: Path) -> Path:
    """A referenced graphless record that sorts far from its referencer, so a
    chunked walk puts them in different parts."""
    root = _rich_corpus(tmp_path)
    referencer = yaml.safe_load((root / "data/a/1.yaml").read_text())
    referencer["causal_graphs"][0]["nodes"][0]["grounding"] = "T:far"
    (root / "data/a/1.yaml").write_text(yaml.safe_dump(referencer))
    (root / "data/z").mkdir()
    (root / "data/z/far.yaml").write_text("identifier: T:far\nstatus: PROPOSED\n")
    return root


@pytest.mark.parametrize("jobs", [2, 3, 7])
def test_a_reference_across_parts_of_a_parallel_walk_is_still_counted(tmp_path, monkeypatch, jobs):
    """ProteinTraitsMech has 5,841 graphless records grounded elsewhere; a
    per-part count would drop every pair a chunk boundary separates (#490)."""
    import kg_microbe_graph.coverage as coverage

    root = _far_reference_corpus(tmp_path)
    config = _config(record_id_field="identifier", exempt_when=["status=DEPRECATED"])
    sequential = collect("m", root, GLOBS, config).as_dict()
    assert sequential["coverage"]["graphless_but_referenced_elsewhere"] == 2
    monkeypatch.setattr(coverage, "PARALLEL_THRESHOLD", 0)
    assert collect("m", root, GLOBS, config, jobs=jobs).as_dict() == sequential


def _pool_spy(monkeypatch) -> list[int]:
    import kg_microbe_graph.coverage as coverage

    started: list[int] = []

    class Spy(coverage.ProcessPoolExecutor):
        def __init__(self, *args, **kwargs):
            started.append(kwargs.get("max_workers", 0))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(coverage, "ProcessPoolExecutor", Spy)
    return started


def test_the_pool_is_used_from_the_threshold_up(tmp_path, monkeypatch):
    """Equality alone passes if the pool never runs (#490)."""
    import kg_microbe_graph.coverage as coverage

    started = _pool_spy(monkeypatch)
    monkeypatch.setattr(coverage, "PARALLEL_THRESHOLD", 3)
    three = _corpus(tmp_path / "three", {f"data/{i}.yaml": {"identifier": str(i)} for i in range(3)})
    two = _corpus(tmp_path / "two", {f"data/{i}.yaml": {"identifier": str(i)} for i in range(2)})

    collect("m", two, GLOBS, _config(), jobs=2)
    assert started == []
    collect("m", three, GLOBS, _config(), jobs=2)
    assert started == [2]
    collect("m", three, GLOBS, _config(), jobs=1)
    assert started == [2]


def test_only_the_fields_that_are_not_sums_are_left_out_of_a_merge():
    from kg_microbe_graph.coverage import _NOT_MERGED

    assert _NOT_MERGED == {"mech", "config", "sampled", "parser", "referenced_elsewhere"}


def test_predicates_are_counted_and_ranked_most_frequent_first(tmp_path):
    graph = _graph("g", 3)
    graph["edges"][0]["predicate"] = "inhibits"
    report = _report(tmp_path, {"data/a.yaml": {"causal_graphs": [graph]}})
    assert report["graphs"]["predicates"] == {
        "distinct": 2, "top": [["causes", 2], ["inhibits", 1]],
    }


def test_undeclared_node_types_are_not_measured(tmp_path):
    root = _corpus(tmp_path, {"data/a.yaml": {"ecological_interactions": [
        {"name": "a", "interaction_type": "X", "downstream": [{"target": "b"}]}, {"name": "b"}]}})
    config = CoverageConfig.from_settings({k: v for k, v in NESTED.items() if k != "node_type_field"})
    assert collect("m", root, GLOBS, config).as_dict()["graphs"]["node_types"] is None


@pytest.mark.parametrize("text", ["label~ grouping", "label~grouping ", "label~\tgrouping"])
def test_a_regex_with_leading_or_trailing_whitespace_is_refused(text):
    with pytest.raises(CoverageConfigError, match="whitespace"):
        ExemptionRule.parse(text)


@pytest.mark.parametrize("spelling", ["false", "False", "no", "off"])
def test_a_false_boolean_matches_any_spelling(tmp_path, spelling):
    report = _report(
        tmp_path,
        {"data/a.yaml": {"abstract": True}, "data/b.yaml": {"abstract": False}},
        exempt_when=[f"abstract={spelling}"],
    )
    assert report["exempt"]["records"] == 1


@pytest.mark.parametrize("rule", ["abstract~^yes$", "abstract~(?i)^TRUE$", "abstract~on"])
def test_a_regex_rule_matches_a_boolean_by_any_spelling(tmp_path, rule):
    """`abstract: yes` is read as True; a regex that names `yes` must still
    see it (#496)."""
    report = _report(
        tmp_path,
        {"data/a.yaml": "abstract: yes\n", "data/b.yaml": "abstract: no\n"},
        exempt_when=[rule],
    )
    assert report["exempt"]["records"] == 1


def test_an_anchor_needs_node_types_to_anchor_on():
    with pytest.raises(CoverageConfigError, match="node_type_field"):
        CoverageConfig.from_settings({
            **{k: v for k, v in NESTED.items() if k != "node_type_field"},
            "anchor_node_types": ["X"],
        })


def test_an_impossible_date_is_one_unreadable_record_not_a_failed_run(tmp_path):
    report = _report(tmp_path, {
        "data/good.yaml": {"identifier": "A"},
        "data/bad_date.yaml": "identifier: B\nreviewed: 2025-06-31\n",
    })
    assert report["unreadable"] == ["data/bad_date.yaml"]
    assert report["records"] == 1


def test_a_recursive_alias_is_one_malformed_record_not_a_failed_run(tmp_path):
    report = _report(
        tmp_path,
        {"data/good.yaml": {"identifier": "A", "tags": ["x"]},
         "data/loop.yaml": "identifier: B\ntags: &t [x, *t]\n"},
        exempt_when=["tags=never"], strata=["tags"],
    )
    assert report["records"] == 1
    assert report["malformed"] == ["data/loop.yaml: a value refers to itself (recursive alias)"]
    assert set(report["strata"]["tags"]) == {"x"}


def test_a_bare_null_document_is_empty(tmp_path):
    report = _report(tmp_path, {"data/a.yaml": {"identifier": "A"}, "data/null.yaml": "~\n"})
    assert report["empty"] == ["data/null.yaml"]


def test_a_checkout_spelt_another_way_is_still_that_checkout(tmp_path):
    """Case-insensitive file systems (macOS) reach one checkout by several
    spellings; comparing path strings called it a snapshot (#493)."""
    from kg_microbe_graph.__main__ import SNAPSHOT, _revision

    _git_init(tmp_path / "mech")
    variant = tmp_path / "MECH"
    if not variant.exists():
        pytest.skip("case-sensitive file system: one spelling per directory")
    assert _revision(variant, GLOBS).startswith("HEAD ")
    (tmp_path / "mech" / "data").mkdir()
    assert _revision(tmp_path / "mech" / "data", GLOBS) == SNAPSHOT


def test_the_revision_probe_ignores_an_inherited_repository(monkeypatch, tmp_path):
    """Run from a git hook, GIT_DIR would name the hook's repository."""
    import subprocess

    import kg_microbe_graph.__main__ as cli

    calls = []

    def record(command, **kwargs):
        calls.append((command, kwargs.get("env", {})))
        raise subprocess.CalledProcessError(128, command)

    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere.git"))
    monkeypatch.setattr(cli.subprocess, "run", record)
    cli._revision(tmp_path, GLOBS)
    command, env = calls[0]
    assert "core.fsmonitor=false" in command
    assert "GIT_DIR" not in env


def test_many_excluded_files_are_named_up_to_a_limit(tmp_path):
    from kg_microbe_graph.__main__ import MAX_NAMED, _excluded

    root = _corpus(tmp_path, {"data/good.yaml": {"identifier": "A"},
                              **{f"data/b{i}.yaml": "" for i in range(MAX_NAMED + 2)}})
    line = _excluded("m", collect("m", root, GLOBS, _config()))
    assert line is not None and line.endswith("; and 2 more")
    assert line.count("holds no document") == MAX_NAMED


def test_a_summary_row_with_excluded_files_is_marked(tmp_path, capsys):
    from kg_microbe_graph.__main__ import main

    root = _traitmech_root(tmp_path, {"a.yaml": {"mapping_status": "REVIEWED"}, "b.yaml": ""})
    assert main(["coverage", "--mech", "traitmech", "--root", str(root), "--summary"]) == 1
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.startswith("traitmech"))
    assert row.split()[1] == "1!"
    assert "! traitmech: 1 file(s) excluded from every count" in out
