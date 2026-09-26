"""How much of a Mech's corpus carries a causal graph, and what those graphs are.

"Fraction of records with a causal graph" has one naive answer -- records whose
graph slot is non-empty, over every record -- and the fleet measured on
2026-09-25 shows why that answer misleads in both directions:

  - CellStructureMech reads 547/548 by that count, yet 450 of those records
    carry only NONMECHANISTIC topology graphs; 97 carry a mechanism.
  - TraitMech reads 523/767, and its denominator includes 50 deprecated records
    and 101 relation carriers its own playbook says never take a graph.
  - CommunityMech holds its graph in `ecological_interactions[].downstream`,
    not a `causal_graphs` slot, so a slot count reports nothing at all.

So this reports three things the naive count fuses, and declines to decide two
things it cannot decide from the data.

**Applicability is declared, never inferred.** A record leaves the denominator
only by matching an `exempt_when` rule the Mech's manifest declaration names.
The tempting structural rules are wrong somewhere in the fleet: 27 of
HabitatMech's 32 graphs sit on parent classes, and habitats are exactly the
records HabitatMech graphs; 65 of CellStructureMech's 66 is-a parents carry a
graph. An automatic "parents and habitats need no graph" rule would erase most
of the coverage those Mechs have. Every rule is reported with the number of
records it matched, zero included, so a rule that has stopped matching anything
is visible rather than silently harmless.

**A graph with no edge is not coverage.** CommunityMech has 52 records whose
interaction nodes have no downstream edge. They are counted as `edgeless_only`
-- present, but asserting no causal link -- not as graphs.

**A graph's own disposition is a separate count.** Where a Mech records one
(`scope_status`), `with_mechanistic_graph` is the subset of `with_graph` whose
scope is one the Mech names as mechanistic. NONMECHANISTIC is neither coverage
nor exemption here because it means different things in different Mechs --
"a mechanism does not apply" for TraitMech's reviewed records, "deferred" for
its proposed ones, "a topology graph instead" in CellStructureMech -- and a
single rule would be right for one and wrong for the others. Both numbers are
reported; `strata` shows where they diverge.

**Several graphs per record are counted, not collapsed.** The graphs-per-record
histogram and, for each declared `graph_facets` field, the combination of
values each record carries (CellStructureMech ASSEMBLY+FUNCTION, one
NaturalProductMech record's nine BIOACTIVITY graphs) say whether records carry
the several graphs they need. A record whose identifier is grounded in *another*
record's graph is counted separately among the graphless: its mechanism may be
modelled elsewhere, which a per-record count cannot see.

Structure comes from `kg_microbe_graph.audit`, reported per finding code both as
findings and as graphs, because node-level codes (ORPHAN_NODE) and graph-level
codes (FRAGMENTED_GRAPH) otherwise read as comparable when they are not.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from kg_microbe_corpus import iter_records, resolve_value
from kg_microbe_corpus.loader import soundness
from kg_microbe_graph.structure import Edge, Graph, Node, audit

__all__ = [
    "CAPABILITY",
    "CoverageConfig",
    "CoverageConfigError",
    "CoverageError",
    "CoverageReport",
    "ExemptionRule",
    "GraphShape",
    "SHAPES",
    "collect",
]

CAPABILITY = "causal_graph_coverage"

GRAPH_LIST = "graph_list"
NODE_NESTED_EDGES = "node_nested_edges"
SHAPES = frozenset({GRAPH_LIST, NODE_NESTED_EDGES})

UNSET = "<unset>"
DIRECTORY_STRATUM = "@directory"
MAX_TOP_PREDICATES = 10
EDGE_BUCKETS = ((0, 0, "0"), (1, 1, "1"), (2, 4, "2-4"), (5, 9, "5-9"), (10, 19, "10-19"))

_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CoverageError(RuntimeError):
    """The corpus could not be read as declared."""


class CoverageConfigError(ValueError):
    """A `causal_graph_coverage` declaration cannot be applied as written."""


class _Malformed(Exception):
    """A record whose graph slot does not have the declared shape."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExemptionRule:
    """One declared reason a record needs no causal graph.

    Three forms, and nothing else, so a typo is an error rather than a rule
    that quietly matches nothing:

        field.path=A|B   the value at the path (or any element, when it is a
                         list) equals one of the alternatives
        field.path~REGEX the value matches the regular expression (re.search)
        path:GLOB        the record's path matches GLOB, with the same
                         semantics as the manifest's record_globs

    A dotted path follows `kg_microbe_corpus.resolve_value`, so a field means
    the same thing here as in the corpus report.
    """

    text: str
    kind: str
    field: str | None = None
    values: frozenset[str] = frozenset()
    pattern: re.Pattern[str] | None = None
    glob: str | None = None

    @classmethod
    def parse(cls, text: str) -> ExemptionRule:
        if text.startswith("path:"):
            glob = text[len("path:") :].strip()
            if not glob or glob.startswith("/") or ".." in Path(glob).parts:
                raise CoverageConfigError(
                    f"exempt_when {text!r}: a path rule needs a relative glob "
                    f"inside the repository"
                )
            return cls(text=text, kind="path", glob=glob)

        positions = [i for i in (text.find("="), text.find("~")) if i > 0]
        if not positions:
            raise CoverageConfigError(
                f"exempt_when {text!r}: expected field=VALUE[|VALUE...], "
                f"field~REGEX, or path:GLOB"
            )
        split = min(positions)
        name, operator, rest = text[:split].strip(), text[split], text[split + 1 :]
        if not _FIELD.match(name):
            raise CoverageConfigError(
                f"exempt_when {text!r}: {name!r} is not a dotted field path"
            )
        if operator == "~":
            try:
                pattern = re.compile(rest)
            except re.error as exc:
                raise CoverageConfigError(
                    f"exempt_when {text!r}: invalid regular expression: {exc}"
                ) from exc
            if not rest:
                raise CoverageConfigError(f"exempt_when {text!r}: empty pattern")
            return cls(text=text, kind="matches", field=name, pattern=pattern)

        values = [value.strip() for value in rest.split("|")]
        if not values or any(not value for value in values):
            raise CoverageConfigError(
                f"exempt_when {text!r}: every alternative must be non-empty"
            )
        return cls(text=text, kind="equals", field=name, values=frozenset(values))

    def matches(self, record: Mapping[str, Any], relative: str, globbed: set[str]) -> bool:
        if self.kind == "path":
            return relative in globbed
        assert self.field is not None
        value = resolve_value(record, self.field)
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if candidate is None or isinstance(candidate, (dict, list)):
                continue
            text = _scalar(candidate)
            if self.kind == "equals" and text in self.values:
                return True
            if self.kind == "matches" and self.pattern is not None and self.pattern.search(text):
                return True
        return False


@dataclass(frozen=True)
class GraphShape:
    """Where a record keeps its causal graph, and what the parts are called.

    `graph_list`: the record holds a list of graphs, each with its own nodes
    and edges -- TraitMech's shape, which CellStructureMech, HabitatMech and the
    others copied "so tooling can be shared", hence the defaults.

    `node_nested_edges`: the record *is* one graph. Its nodes are a list, and
    each node lists its own outgoing edges -- CommunityMech's
    `ecological_interactions[].downstream[].target`. The subject of such an
    edge is the node it sits under, so there is no subject field, and nothing
    is defaulted: a field that is not declared is reported as not measured,
    never as zero.
    """

    kind: str
    graphs_field: str | None
    graph_id_field: str | None
    nodes_field: str
    edges_field: str
    node_id_field: str
    node_type_field: str | None
    node_grounding_field: str | None
    edge_subject_field: str | None
    edge_object_field: str
    edge_predicate_field: str | None
    edge_evidence_field: str | None


_GRAPH_LIST_DEFAULTS = {
    "graphs_field": "causal_graphs",
    "graph_id_field": "graph_id",
    "nodes_field": "nodes",
    "edges_field": "edges",
    "node_id_field": "node_id",
    "node_type_field": "node_type",
    "node_grounding_field": "grounding",
    "edge_subject_field": "subject",
    "edge_object_field": "object",
    "edge_predicate_field": "predicate",
    "edge_evidence_field": "evidence",
}
_NESTED_REQUIRED = ("nodes_field", "edges_field", "node_id_field", "edge_object_field")
_NESTED_FORBIDDEN = ("graphs_field", "graph_id_field", "edge_subject_field")
_SHAPE_FIELDS = tuple(_GRAPH_LIST_DEFAULTS)


@dataclass(frozen=True)
class CoverageConfig:
    shape: GraphShape
    record_id_field: str | None = None
    scope_field: str | None = None
    mechanistic_scopes: frozenset[str] | None = None
    graph_facets: tuple[str, ...] = ()
    anchor_node_types: tuple[str, ...] = ()
    duplicate_grounding_check: bool = False
    exempt_when: tuple[ExemptionRule, ...] = ()
    strata: tuple[str, ...] = ()

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> CoverageConfig:
        """Build a configuration from a manifest declaration, or say why not.

        The manifest loader checks each setting's type. What it cannot check is
        whether the settings make sense together -- a scope list with no scope
        field, a subject field on a shape whose edges have none -- so that is
        checked here, and a test applies it to every enabled declaration.
        """
        kind = settings.get("graph_shape")
        if kind not in SHAPES:
            raise CoverageConfigError(
                f"graph_shape must be one of {', '.join(sorted(SHAPES))} (got {kind!r})"
            )

        declared = {name: settings.get(name) for name in _SHAPE_FIELDS}
        for name, value in declared.items():
            if value is not None and not _KEY.match(str(value)):
                raise CoverageConfigError(
                    f"{name} {value!r} must be a single key, not a path"
                )
        if kind == GRAPH_LIST:
            resolved = {
                name: declared[name] or default
                for name, default in _GRAPH_LIST_DEFAULTS.items()
            }
        else:
            missing = [name for name in _NESTED_REQUIRED if not declared[name]]
            if missing:
                raise CoverageConfigError(
                    f"{NODE_NESTED_EDGES} needs {', '.join(missing)}: nothing is "
                    f"defaulted for this shape"
                )
            forbidden = [name for name in _NESTED_FORBIDDEN if declared[name]]
            if forbidden:
                raise CoverageConfigError(
                    f"{NODE_NESTED_EDGES} has no {', '.join(forbidden)}: the record "
                    f"is the graph and an edge's subject is the node it sits under"
                )
            resolved = dict(declared)
        shape = GraphShape(kind=kind, **resolved)

        scope_field = settings.get("scope_field")
        mechanistic = settings.get("mechanistic_scopes")
        facets = tuple(settings.get("graph_facets", ()))
        if kind == NODE_NESTED_EDGES and (scope_field or facets):
            raise CoverageConfigError(
                f"{NODE_NESTED_EDGES} graphs are the record itself; scope_field and "
                f"graph_facets describe a graph object this shape does not have"
            )
        if mechanistic is not None and not scope_field:
            raise CoverageConfigError(
                "mechanistic_scopes names values of a scope_field, and none is declared"
            )
        for name in (scope_field, *facets):
            if name is not None and not _KEY.match(name):
                raise CoverageConfigError(f"{name!r} must be a single graph key")

        check = bool(settings.get("duplicate_grounding_check", False))
        if check and not shape.node_grounding_field:
            raise CoverageConfigError(
                "duplicate_grounding_check needs node_grounding_field"
            )

        record_id_field = settings.get("record_id_field")
        if record_id_field is not None and not _FIELD.match(record_id_field):
            raise CoverageConfigError(f"record_id_field {record_id_field!r} is not a path")

        strata = tuple(settings.get("strata", ()))
        for stratum in strata:
            if stratum != DIRECTORY_STRATUM and not _FIELD.match(stratum):
                raise CoverageConfigError(
                    f"stratum {stratum!r} must be a dotted field path or "
                    f"{DIRECTORY_STRATUM}"
                )

        rules = tuple(ExemptionRule.parse(text) for text in settings.get("exempt_when", ()))
        return cls(
            shape=shape,
            record_id_field=record_id_field,
            scope_field=scope_field,
            mechanistic_scopes=frozenset(mechanistic) if mechanistic is not None else None,
            graph_facets=facets,
            anchor_node_types=tuple(settings.get("anchor_node_types", ())),
            duplicate_grounding_check=check,
            exempt_when=rules,
            strata=strata,
        )

    def definition(self) -> dict[str, Any]:
        """What was measured, echoed into the report so it reads on its own."""
        shape = self.shape
        return {
            "graph_shape": shape.kind,
            "graph_slot": shape.graphs_field or shape.nodes_field,
            "edges": (
                f"{shape.nodes_field}[].{shape.edges_field}[].{shape.edge_object_field}"
                if shape.kind == NODE_NESTED_EDGES
                else f"{shape.graphs_field}[].{shape.edges_field}"
            ),
            "scope_field": self.scope_field,
            "mechanistic_scopes": (
                sorted(self.mechanistic_scopes) if self.mechanistic_scopes is not None else None
            ),
            "exempt_when": [rule.text for rule in self.exempt_when],
            "anchor_node_types": list(self.anchor_node_types),
            "duplicate_grounding_check": self.duplicate_grounding_check,
        }


# --------------------------------------------------------------------------
# Reading one record's graphs
# --------------------------------------------------------------------------


@dataclass
class _Parsed:
    graph_id: str
    graph: Graph
    groundings: dict[str, str]
    scope: str | None
    facets: dict[str, str]
    node_types: Counter[str]
    predicates: Counter[str]
    edges_with_evidence: int
    nodes_grounded: int


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _key(value: Any) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return UNSET
    if isinstance(value, list):
        return "+".join(sorted(_key(item) for item in value))
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return _scalar(value)


def _populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def _identifier(value: Any, what: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or value == "":
        raise _Malformed(f"{what} has no usable identifier")
    return str(value)


def _list(value: Any, what: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _Malformed(f"{what} is a {type(value).__name__}, not a list")
    return value


def _node(raw: Any, shape: GraphShape, what: str) -> tuple[Node, str | None]:
    if not isinstance(raw, dict):
        raise _Malformed(f"{what} is not a mapping")
    node_id = _identifier(raw.get(shape.node_id_field), what)
    node_type = raw.get(shape.node_type_field) if shape.node_type_field else None
    grounding = raw.get(shape.node_grounding_field) if shape.node_grounding_field else None
    return (
        Node(node_id, str(node_type) if node_type is not None else None),
        str(grounding) if _populated(grounding) else None,
    )


def _edge(raw: Any, subject: Any, shape: GraphShape, what: str) -> tuple[Edge, bool]:
    if not isinstance(raw, dict):
        raise _Malformed(f"{what} is not a mapping")
    if shape.edge_subject_field is not None:
        subject = raw.get(shape.edge_subject_field)
    predicate = raw.get(shape.edge_predicate_field) if shape.edge_predicate_field else None
    edge = Edge(
        _identifier(subject, f"{what} subject"),
        _identifier(raw.get(shape.edge_object_field), f"{what} object"),
        str(predicate) if _populated(predicate) else None,
    )
    evidenced = bool(shape.edge_evidence_field) and _populated(
        raw.get(shape.edge_evidence_field)
    )
    return edge, evidenced


def _assemble(
    graph_id: str,
    nodes: list[tuple[Node, str | None]],
    edges: list[tuple[Edge, bool]],
    scope: str | None,
    facets: dict[str, str],
) -> _Parsed:
    return _Parsed(
        graph_id=graph_id,
        graph=Graph(graph_id, tuple(n for n, _ in nodes), tuple(e for e, _ in edges)),
        groundings={n.id: g for n, g in nodes if g},
        scope=scope,
        facets=facets,
        node_types=Counter(n.type or UNSET for n, _ in nodes),
        predicates=Counter(e.predicate or UNSET for e, _ in edges),
        edges_with_evidence=sum(1 for _, evidenced in edges if evidenced),
        nodes_grounded=sum(1 for _, g in nodes if g),
    )


def _graphs(record: Mapping[str, Any], config: CoverageConfig) -> list[_Parsed]:
    shape = config.shape
    if shape.kind == NODE_NESTED_EDGES:
        raw_nodes = _list(record.get(shape.nodes_field), shape.nodes_field)
        if not raw_nodes:
            return []
        nodes, edges = [], []
        for i, raw in enumerate(raw_nodes):
            what = f"{shape.nodes_field}[{i}]"
            node = _node(raw, shape, what)
            nodes.append(node)
            for j, raw_edge in enumerate(_list(raw.get(shape.edges_field), f"{what}.{shape.edges_field}")):
                edges.append(_edge(raw_edge, node[0].id, shape, f"{what}.{shape.edges_field}[{j}]"))
        return [_assemble(shape.nodes_field, nodes, edges, None, {})]

    assert shape.graphs_field is not None and shape.graph_id_field is not None
    parsed = []
    for i, raw in enumerate(_list(record.get(shape.graphs_field), shape.graphs_field)):
        what = f"{shape.graphs_field}[{i}]"
        if not isinstance(raw, dict):
            raise _Malformed(f"{what} is not a mapping")
        graph_id = raw.get(shape.graph_id_field)
        graph_id = str(graph_id) if _populated(graph_id) else f"#{i}"
        nodes = [
            _node(n, shape, f"{what}.{shape.nodes_field}[{j}]")
            for j, n in enumerate(_list(raw.get(shape.nodes_field), f"{what}.{shape.nodes_field}"))
        ]
        edges = [
            _edge(e, None, shape, f"{what}.{shape.edges_field}[{j}]")
            for j, e in enumerate(_list(raw.get(shape.edges_field), f"{what}.{shape.edges_field}"))
        ]
        scope = _key(raw.get(config.scope_field)) if config.scope_field else None
        facets = {facet: _key(raw.get(facet)) for facet in config.graph_facets}
        parsed.append(_assemble(graph_id, nodes, edges, scope, facets))
    return parsed


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

BUCKETS = ("with_graph", "edgeless_only", "no_graph")


def _counts(mechanistic: bool) -> dict[str, int]:
    base = {"records": 0, "exempt": 0, "eligible": 0, **{b: 0 for b in BUCKETS}}
    if mechanistic:
        base["with_mechanistic_graph"] = 0
    return base


def _spread(values: Sequence[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def _edge_bucket(count: int) -> str:
    for low, high, label in EDGE_BUCKETS:
        if low <= count <= high:
            return label
    return "20+"


def _fraction(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


@dataclass
class CoverageReport:
    mech: str
    config: CoverageConfig
    sampled: bool = False
    records: int = 0
    unreadable: list[str] = field(default_factory=list)
    malformed: list[str] = field(default_factory=list)
    exempt_by_rule: dict[str, int] = field(default_factory=dict)
    exempt_with_graph: int = 0
    buckets: Counter[str] = field(default_factory=Counter)
    with_mechanistic_graph: int = 0
    referenced_elsewhere: int = 0
    strata: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    graphs_per_record: Counter[int] = field(default_factory=Counter)
    nodes_per_graph: list[int] = field(default_factory=list)
    edges_per_graph: list[int] = field(default_factory=list)
    edges_with_evidence: int = 0
    nodes_grounded: int = 0
    node_types: Counter[str] = field(default_factory=Counter)
    predicates: Counter[str] = field(default_factory=Counter)
    scopes: Counter[str] = field(default_factory=Counter)
    facet_graphs: dict[str, Counter[str]] = field(default_factory=dict)
    facet_combinations: dict[str, Counter[str]] = field(default_factory=dict)
    findings: Counter[str] = field(default_factory=Counter)
    finding_graphs: Counter[str] = field(default_factory=Counter)
    finding_scopes: dict[str, Counter[str]] = field(default_factory=dict)
    graphs_with_findings: int = 0
    parser: tuple[str, str] | None = None

    @property
    def exempt(self) -> int:
        return sum(self.exempt_by_rule.values())

    @property
    def eligible(self) -> int:
        return self.records - self.exempt

    def parser_note(self) -> str:
        if self.parser is None:
            return "parser not recorded: this report did not read a corpus"
        name, why = self.parser
        return f"parsed with {name}: {why}"

    def as_dict(self) -> dict[str, Any]:
        """Deterministic JSON: sorted keys, no timestamps, no absolute paths."""
        config = self.config
        shape = config.shape
        mechanistic = config.mechanistic_scopes is not None
        with_graph = self.buckets["with_graph"]
        return {
            "mech": self.mech,
            "sampled": self.sampled,
            "definition": config.definition(),
            "records": self.records,
            "unreadable": sorted(self.unreadable),
            "malformed": sorted(self.malformed),
            "exempt": {
                "records": self.exempt,
                "with_graph": self.exempt_with_graph,
                "by_rule": {rule.text: self.exempt_by_rule.get(rule.text, 0)
                            for rule in config.exempt_when},
            },
            "coverage": {
                "eligible": self.eligible,
                **{bucket: self.buckets[bucket] for bucket in BUCKETS},
                "with_mechanistic_graph": self.with_mechanistic_graph if mechanistic else None,
                "fraction_with_graph": _fraction(with_graph, self.eligible),
                "fraction_mechanistic": (
                    _fraction(self.with_mechanistic_graph, self.eligible) if mechanistic else None
                ),
                "graphless_but_referenced_elsewhere": (
                    self.referenced_elsewhere
                    if config.record_id_field and shape.node_grounding_field
                    else None
                ),
            },
            "strata": {
                name: dict(sorted(values.items())) for name, values in sorted(self.strata.items())
            },
            "graphs": {
                "total": len(self.nodes_per_graph),
                "per_record": {
                    str(count): records
                    for count, records in sorted(self.graphs_per_record.items())
                },
                "nodes": sum(self.nodes_per_graph),
                "edges": sum(self.edges_per_graph),
                "nodes_per_graph": _spread(self.nodes_per_graph),
                "edges_per_graph": _spread(self.edges_per_graph),
                "edge_count_histogram": dict(
                    sorted(Counter(_edge_bucket(n) for n in self.edges_per_graph).items())
                ),
                "edges_with_evidence": (
                    self.edges_with_evidence if shape.edge_evidence_field else None
                ),
                "nodes_grounded": (
                    self.nodes_grounded if shape.node_grounding_field else None
                ),
                "node_types": dict(sorted(self.node_types.items())),
                "predicates": {
                    "distinct": len(self.predicates),
                    "top": [
                        list(pair)
                        for pair in sorted(
                            self.predicates.items(), key=lambda item: (-item[1], item[0])
                        )[:MAX_TOP_PREDICATES]
                    ],
                },
                "scopes": dict(sorted(self.scopes.items())) if config.scope_field else None,
                "facets": {
                    facet: {
                        "graphs": dict(sorted(self.facet_graphs.get(facet, Counter()).items())),
                        "record_combinations": dict(
                            sorted(self.facet_combinations.get(facet, Counter()).items())
                        ),
                    }
                    for facet in config.graph_facets
                },
            },
            "structure": {
                "graphs_with_findings": self.graphs_with_findings,
                "findings": {
                    code: {"findings": self.findings[code], "graphs": self.finding_graphs[code]}
                    for code in sorted(self.findings)
                },
                "graphs_by_scope": (
                    {
                        code: dict(sorted(scopes.items()))
                        for code, scopes in sorted(self.finding_scopes.items())
                    }
                    if config.scope_field
                    else None
                ),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"


def _stratum_value(record: Mapping[str, Any], stratum: str, relative: str) -> str:
    if stratum == DIRECTORY_STRATUM:
        return Path(relative).parent.as_posix()
    return _key(resolve_value(record, stratum))


def collect(
    mech: str,
    root: Path,
    globs: Sequence[str],
    config: CoverageConfig,
    *,
    sample: int | None = None,
) -> CoverageReport:
    """Walk one Mech's corpus and report its causal-graph coverage."""
    root = Path(root)
    if not root.is_dir():
        raise CoverageError(f"{mech}: {root} is not a directory")
    if not globs:
        raise CoverageError(
            f"{mech}: no record globs declared; the manifest says which files are the corpus"
        )

    sound, why = soundness()
    report = CoverageReport(
        mech=mech,
        config=config,
        sampled=sample is not None,
        parser=("CSafeLoader" if sound else "SafeLoader", why),
    )
    mechanistic_scopes = config.mechanistic_scopes
    globbed = {
        rule.text: {
            path.relative_to(root).as_posix()
            for path in root.glob(rule.glob)
            if path.is_file()
        }
        for rule in config.exempt_when
        if rule.kind == "path" and rule.glob is not None
    }
    # Groundings seen in edge-bearing graphs, to ask afterwards whether a
    # graphless record is modelled inside someone else's. A record with no
    # edge-bearing graph cannot be the one referencing itself.
    referenced: set[str] = set()
    graphless_ids: list[str] = []

    for path, record in iter_records(root, globs, sample=sample):
        relative = path.relative_to(root).as_posix()
        if record is None:
            report.unreadable.append(relative)
            continue
        if not isinstance(record, dict):
            report.malformed.append(f"{relative}: the record is not a mapping")
            continue
        try:
            graphs = _graphs(record, config)
        except _Malformed as exc:
            report.malformed.append(f"{relative}: {exc}")
            continue

        report.records += 1
        report.graphs_per_record[len(graphs)] += 1
        edge_bearing = [g for g in graphs if g.graph.edges]
        mechanistic = [
            g for g in edge_bearing
            if mechanistic_scopes is None or g.scope in mechanistic_scopes
        ]
        bucket = "with_graph" if edge_bearing else ("edgeless_only" if graphs else "no_graph")

        rule = next(
            (r for r in config.exempt_when
             if r.matches(record, relative, globbed.get(r.text, set()))),
            None,
        )
        if rule is not None:
            report.exempt_by_rule[rule.text] = report.exempt_by_rule.get(rule.text, 0) + 1
            if edge_bearing:
                report.exempt_with_graph += 1
        else:
            report.buckets[bucket] += 1
            if mechanistic_scopes is not None and mechanistic:
                report.with_mechanistic_graph += 1
            if not edge_bearing and config.record_id_field:
                own = resolve_value(record, config.record_id_field)
                if _populated(own) and not isinstance(own, (dict, list)):
                    graphless_ids.append(_scalar(own))

        for stratum in config.strata:
            counts = report.strata.setdefault(stratum, {}).setdefault(
                _stratum_value(record, stratum, relative),
                _counts(mechanistic_scopes is not None),
            )
            counts["records"] += 1
            if rule is not None:
                counts["exempt"] += 1
                continue
            counts["eligible"] += 1
            counts[bucket] += 1
            if mechanistic_scopes is not None and mechanistic:
                counts["with_mechanistic_graph"] += 1

        seen_ids: Counter[str] = Counter(g.graph_id for g in graphs)
        for graph_id, count in seen_ids.items():
            if count > 1:
                report.findings["DUPLICATE_GRAPH_ID"] += count - 1
                report.finding_graphs["DUPLICATE_GRAPH_ID"] += count

        for facet in config.graph_facets:
            values = {g.facets[facet] for g in graphs}
            report.facet_graphs.setdefault(facet, Counter()).update(
                g.facets[facet] for g in graphs
            )
            if values:
                report.facet_combinations.setdefault(facet, Counter())[
                    "+".join(sorted(values))
                ] += 1

        for parsed in graphs:
            _measure(report, parsed, config, relative)
            if parsed.graph.edges:
                referenced.update(parsed.groundings.values())

    report.referenced_elsewhere = sum(1 for own in graphless_ids if own in referenced)
    return report


def _measure(report: CoverageReport, parsed: _Parsed, config: CoverageConfig, relative: str) -> None:
    graph = parsed.graph
    report.nodes_per_graph.append(len(graph.nodes))
    report.edges_per_graph.append(len(graph.edges))
    report.edges_with_evidence += parsed.edges_with_evidence
    report.nodes_grounded += parsed.nodes_grounded
    report.node_types.update(parsed.node_types)
    report.predicates.update(parsed.predicates)
    if config.scope_field:
        report.scopes[parsed.scope or UNSET] += 1

    # The graph id carries the record path, so a finding names where it is;
    # CellStructureMech reuses a graph_id across two records.
    findings = audit(
        Graph(f"{relative}#{parsed.graph_id}", graph.nodes, graph.edges),
        anchor_types=config.anchor_node_types,
        groundings=parsed.groundings if config.duplicate_grounding_check else None,
    )
    if not findings:
        return
    report.graphs_with_findings += 1
    codes = Counter(finding.code for finding in findings)
    for code, count in codes.items():
        report.findings[code] += count
        report.finding_graphs[code] += 1
        if config.scope_field:
            report.finding_scopes.setdefault(code, Counter())[parsed.scope or UNSET] += 1
