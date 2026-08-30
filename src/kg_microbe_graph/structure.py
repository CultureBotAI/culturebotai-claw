"""Structural integrity of a causal graph (#132 Phase 6, item 2).

TraitMech and ProteinTraitsMech each audit inline causal graphs, and each
wrote its own. What they check overlaps
only partly, and the gap runs one way:

  TraitMech          dangling edges, orphan nodes, duplicate groundings,
                     fragmentation, reachability from a TRAIT node, node-type
                     consistency
  ProteinTraitsMech  dangling edges, unique graph and node ids, required
                     labels and types, enum membership, evidence, CURIE shapes

Both find dangling edges, and only TraitMech looks at connectivity at all. A
graph that splits into two halves, or a node no edge references, passes
ProteinTraitsMech's audit today. Those are properties of a graph, not of either
schema, so they belong here -- and consolidating gives one Mech checks it does
not have rather than merely removing a copy.

What stays downstream is everything that needs the schema: which enum a node
type must belong to, whether an edge carries evidence, what a CURIE may look
like, and which node type anchors reachability. The last is an input here,
because "reachable from a TRAIT node" is TraitMech's question and the shape of
it -- reachable from an anchor -- is everyone's.

Directionality is deliberate. Fragmentation and orphans are undirected
questions: a node connected only by an incoming edge is not an orphan.
Reachability is asked undirected too, because a mechanism written
cause-to-effect and one written effect-to-cause are the same mechanism, and
treating one as unreachable would report modelling style as a defect.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

__all__ = [
    "Edge",
    "Finding",
    "Graph",
    "Node",
    "audit",
    "components",
]


@dataclass(frozen=True)
class Node:
    id: str
    type: str | None = None


@dataclass(frozen=True)
class Edge:
    subject: str
    object: str
    predicate: str | None = None


@dataclass(frozen=True)
class Graph:
    id: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


@dataclass(frozen=True)
class Finding:
    code: str
    graph: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.graph}] {self.code}: {self.detail}"


def components(graph: Graph) -> list[frozenset[str]]:
    """Connected components over declared nodes, treating edges as undirected.

    An edge naming a node that does not exist is reported separately and does
    not join anything: letting it merge components would hide a fragmentation
    behind a typo.
    """
    declared = {node.id for node in graph.nodes}
    adjacent: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.subject in declared and edge.object in declared:
            adjacent[edge.subject].add(edge.object)
            adjacent[edge.object].add(edge.subject)

    seen: set[str] = set()
    found: list[frozenset[str]] = []
    for start in sorted(declared):
        if start in seen:
            continue
        stack, group = [start], set()
        while stack:
            current = stack.pop()
            if current in group:
                continue
            group.add(current)
            stack.extend(adjacent[current] - group)
        seen |= group
        found.append(frozenset(group))
    # Largest first, then lexically, so a report is stable and the main body of
    # the graph leads.
    return sorted(found, key=lambda g: (-len(g), sorted(g)))


def _reachable(graph: Graph, sources: Iterable[str]) -> set[str]:
    declared = {node.id for node in graph.nodes}
    adjacent: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.subject in declared and edge.object in declared:
            adjacent[edge.subject].add(edge.object)
            adjacent[edge.object].add(edge.subject)
    stack = [s for s in sources if s in declared]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacent[current] - seen)
    return seen


def audit(
    graph: Graph,
    *,
    anchor_types: Sequence[str] = (),
    groundings: Mapping[str, str] | None = None,
) -> list[Finding]:
    """Every structural defect in one graph, worst first.

    `anchor_types` names the node types a graph must contain and be reachable
    from -- TraitMech's TRAIT. Empty means the graph has no anchor and those
    two checks do not apply, rather than silently passing a graph with no
    anchor at all.
    """
    findings: list[Finding] = []
    declared: dict[str, int] = defaultdict(int)
    for node in graph.nodes:
        declared[node.id] += 1

    for node_id, count in sorted(declared.items()):
        if count > 1:
            findings.append(
                Finding(
                    "DUPLICATE_NODE_ID",
                    graph.id,
                    f"{node_id!r} is declared {count} times; an edge naming it "
                    f"cannot say which",
                )
            )

    if not graph.nodes:
        findings.append(Finding("EMPTY_GRAPH", graph.id, "no nodes"))
        return findings

    for edge in graph.edges:
        for role, endpoint in (("subject", edge.subject), ("object", edge.object)):
            if endpoint not in declared:
                findings.append(
                    Finding(
                        "DANGLING_EDGE",
                        graph.id,
                        f"edge {role} {endpoint!r} is not a node in this graph",
                    )
                )

    referenced = {
        endpoint
        for edge in graph.edges
        for endpoint in (edge.subject, edge.object)
        if endpoint in declared
    }
    # A single-node graph has nothing to connect to, so its one node is not an
    # orphan. Reporting it would make every minimal graph fail.
    if len(declared) > 1:
        for node_id in sorted(set(declared) - referenced):
            findings.append(
                Finding(
                    "ORPHAN_NODE",
                    graph.id,
                    f"{node_id!r} is declared but no edge references it",
                )
            )

    parts = components(graph)
    if len(parts) > 1:
        sizes = ", ".join(str(len(part)) for part in parts)
        findings.append(
            Finding(
                "FRAGMENTED_GRAPH",
                graph.id,
                f"splits into {len(parts)} disconnected components ({sizes} "
                f"nodes)",
            )
        )

    if anchor_types:
        anchors = [n.id for n in graph.nodes if n.type in set(anchor_types)]
        if not anchors:
            findings.append(
                Finding(
                    "NO_ANCHOR_NODE",
                    graph.id,
                    f"no node typed {' or '.join(sorted(set(anchor_types)))}, so "
                    f"there is nothing to anchor reachability to",
                )
            )
        else:
            unreachable = sorted(set(declared) - _reachable(graph, anchors))
            for node_id in unreachable:
                findings.append(
                    Finding(
                        "UNREACHABLE_FROM_ANCHOR",
                        graph.id,
                        f"{node_id!r} cannot be reached from any "
                        f"{'/'.join(sorted(set(anchor_types)))} node",
                    )
                )

    if groundings:
        by_grounding: dict[str, list[str]] = defaultdict(list)
        for node_id, grounding in groundings.items():
            if grounding and node_id in declared:
                by_grounding[grounding].append(node_id)
        for grounding, ids in sorted(by_grounding.items()):
            if len(ids) > 1:
                findings.append(
                    Finding(
                        "DUPLICATE_GROUNDING",
                        graph.id,
                        f"{', '.join(sorted(ids))} all carry {grounding!r} -- "
                        f"one concept modelled twice",
                    )
                )

    return findings
