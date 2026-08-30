"""Structural integrity of a causal graph (#132 Phase 6, item 2).

TraitMech and ProteinTraitsMech each audit inline causal graphs, and each
wrote its own. Both find dangling
edges; only TraitMech looks at connectivity. A graph that splits into two
halves, or a node no edge references, passes ProteinTraitsMech's audit today.

Those are properties of a graph rather than of either schema, so they belong
here. What stays downstream is everything needing the schema: enum membership,
evidence, CURIE shapes, and node-type consistency.

Checked against both corpora before being trusted. On TraitMech's 353 graphs
this reproduces its own auditor exactly -- 2 DUPLICATE_GROUNDING, 205
FRAGMENTED_GRAPH, 1201 unreachable nodes. On 5,218 of ProteinTraitsMech's it
reports nothing, which is the right answer for well-formed graphs and the
evidence that it is not simply flagging everything.
"""

from __future__ import annotations

import pytest

from kg_microbe_graph import Edge, Graph, Node, audit, components


def _graph(nodes, edges, graph_id="g"):
    return Graph(
        graph_id,
        tuple(Node(n, t) for n, t in nodes),
        tuple(Edge(s, o) for s, o in edges),
    )


def _codes(graph, **kwargs):
    return [f.code for f in audit(graph, **kwargs)]


# --------------------------------------------------------------------------
# Edges and nodes
# --------------------------------------------------------------------------


def test_a_well_formed_graph_has_nothing_to_report():
    graph = _graph([("a", "TRAIT"), ("b", None)], [("a", "b")])

    assert audit(graph, anchor_types=("TRAIT",)) == []


def test_an_edge_naming_a_node_that_does_not_exist_is_dangling():
    graph = _graph([("a", None)], [("a", "ghost")])

    findings = audit(graph)

    assert [f.code for f in findings] == ["DANGLING_EDGE"]
    assert "object 'ghost'" in findings[0].detail


def test_both_endpoints_are_checked():
    graph = _graph([("a", None)], [("ghost", "other")])

    assert _codes(graph).count("DANGLING_EDGE") == 2


def test_a_duplicate_node_id_is_reported():
    """An edge naming it cannot say which node it means."""
    graph = _graph([("a", None), ("a", None), ("b", None)], [("a", "b")])

    assert "DUPLICATE_NODE_ID" in _codes(graph)


def test_a_node_no_edge_references_is_an_orphan():
    graph = _graph([("a", None), ("b", None), ("lonely", None)], [("a", "b")])

    findings = [f for f in audit(graph) if f.code == "ORPHAN_NODE"]

    assert len(findings) == 1
    assert "'lonely'" in findings[0].detail


def test_a_single_node_graph_has_no_orphan():
    """Nothing to connect to. Reporting it would fail every minimal graph."""
    assert _codes(_graph([("only", None)], [])) == []


def test_an_empty_graph_is_reported_and_nothing_else_is_attempted():
    assert _codes(_graph([], [])) == ["EMPTY_GRAPH"]


def test_a_node_referenced_only_as_an_object_is_not_an_orphan():
    """Orphanhood is undirected: an effect with no outgoing edge is connected."""
    graph = _graph([("cause", None), ("effect", None)], [("cause", "effect")])

    assert "ORPHAN_NODE" not in _codes(graph)


# --------------------------------------------------------------------------
# Connectivity
# --------------------------------------------------------------------------


def test_a_graph_in_two_pieces_is_fragmented():
    graph = _graph(
        [("a", None), ("b", None), ("c", None), ("d", None)],
        [("a", "b"), ("c", "d")],
    )

    findings = [f for f in audit(graph) if f.code == "FRAGMENTED_GRAPH"]

    assert len(findings) == 1
    assert "2 disconnected components" in findings[0].detail


def test_components_are_reported_largest_first_then_lexically():
    """The lone node sorts FIRST, so discovery order and report order differ.

    Written the other way round first -- a lone `z` beside `a,b,c` -- where the
    natural walk already produces the sorted answer, and a mutation returning
    the components unsorted passed.
    """
    graph = _graph(
        [("a", None), ("m", None), ("n", None), ("o", None)],
        [("m", "n"), ("n", "o")],
    )

    assert components(graph) == [frozenset({"m", "n", "o"}), frozenset({"a"})]


def test_a_dangling_edge_does_not_join_two_components():
    """Letting it merge them would hide a fragmentation behind a typo."""
    graph = _graph(
        [("a", None), ("b", None)], [("a", "typo"), ("typo", "b")]
    )

    assert "FRAGMENTED_GRAPH" in _codes(graph)


# --------------------------------------------------------------------------
# Anchors
# --------------------------------------------------------------------------


def test_a_graph_with_no_anchor_node_is_reported():
    graph = _graph([("a", "OTHER"), ("b", "OTHER")], [("a", "b")])

    assert "NO_ANCHOR_NODE" in _codes(graph, anchor_types=("TRAIT",))


def test_a_node_unreachable_from_the_anchor_is_reported():
    graph = _graph(
        [("t", "TRAIT"), ("near", None), ("far", None), ("also_far", None)],
        [("t", "near"), ("far", "also_far")],
    )

    findings = [f for f in audit(graph, anchor_types=("TRAIT",))
                if f.code == "UNREACHABLE_FROM_ANCHOR"]

    assert sorted(f.detail.split("'")[1] for f in findings) == ["also_far", "far"]


def test_reachability_is_undirected():
    """A mechanism written effect-to-cause is the same mechanism. Treating one
    direction as unreachable would report modelling style as a defect."""
    graph = _graph([("t", "TRAIT"), ("cause", None)], [("cause", "t")])

    assert "UNREACHABLE_FROM_ANCHOR" not in _codes(graph, anchor_types=("TRAIT",))


def test_without_a_declared_anchor_neither_anchor_check_runs():
    """ProteinTraitsMech's node types are CHEMICAL, PROTEIN, MOLECULAR_FUNCTION
    and so on -- no single type says what the record is about. Inventing one
    would report every graph as anchorless."""
    graph = _graph([("a", "CHEMICAL"), ("b", "PROTEIN")], [("a", "b")])

    assert _codes(graph) == []


def test_more_than_one_type_may_anchor():
    graph = _graph([("a", "TRAIT"), ("b", "CAPACITY")], [("a", "b")])

    assert _codes(graph, anchor_types=("TRAIT", "CAPACITY")) == []


# --------------------------------------------------------------------------
# Groundings
# --------------------------------------------------------------------------


def test_two_nodes_sharing_a_grounding_are_one_concept_modelled_twice():
    graph = _graph([("a", None), ("b", None)], [("a", "b")])

    findings = [
        f
        for f in audit(graph, groundings={"a": "METPO:1", "b": "METPO:1"})
        if f.code == "DUPLICATE_GROUNDING"
    ]

    assert len(findings) == 1
    assert "METPO:1" in findings[0].detail


def test_distinct_groundings_are_fine():
    graph = _graph([("a", None), ("b", None)], [("a", "b")])

    assert audit(graph, groundings={"a": "METPO:1", "b": "METPO:2"}) == []


def test_a_grounding_on_a_node_that_does_not_exist_is_ignored():
    """The dangling-node problem is reported by DANGLING_EDGE; counting its
    grounding here would report the same defect twice under another name."""
    graph = _graph([("a", None), ("b", None)], [("a", "b")])

    assert audit(graph, groundings={"ghost": "METPO:1", "a": "METPO:1"}) == []


# --------------------------------------------------------------------------
# Report shape
# --------------------------------------------------------------------------


def test_findings_name_their_graph():
    graph = _graph([("a", None)], [("a", "ghost")], graph_id="mechanism-1")

    assert audit(graph)[0].graph == "mechanism-1"
    assert str(audit(graph)[0]).startswith("[mechanism-1] DANGLING_EDGE:")


@pytest.mark.parametrize("run", range(3))
def test_the_same_graph_gives_the_same_findings_in_the_same_order(run):
    graph = _graph(
        [("z", None), ("a", None), ("m", None), ("t", "TRAIT")], [("a", "m")]
    )

    first = [str(f) for f in audit(graph, anchor_types=("TRAIT",))]
    second = [str(f) for f in audit(graph, anchor_types=("TRAIT",))]

    assert first == second
