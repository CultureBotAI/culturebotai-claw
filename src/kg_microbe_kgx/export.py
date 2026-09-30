"""`kg-microbe-kgx export` -- one Mech's causal graphs as a KGX graph (#276).

The corpus is read through the Mech's ``causal_graph_coverage`` declaration and
``kg_microbe_graph.coverage.graph_parts``: the same shape, globs and reader
that the coverage report uses, so the graph that is measured is the graph that
is exported. Categories and predicates come from ``kg_microbe_kgx.maps``, and
what could not be mapped is exported as ``NamedThing`` / ``related_to`` with
the Mech's own value kept and counted, never guessed.

The output is checked with this package's own contract before the command
succeeds, so a written graph is a checked graph.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from kg_microbe_corpus import EMPTY_DOCUMENT, iter_records, list_records
from kg_microbe_graph.coverage import CoverageConfig, MalformedGraph, graph_parts
from kg_microbe_kgx import maps
from kg_microbe_kgx.contract import KgxProfile, check_graph

NODE_COLUMNS = (
    "id", "category", "name", "description", "provided_by", "original_category",
    "grounded",
)
EDGE_COLUMNS = (
    "id", "subject", "predicate", "object", "primary_knowledge_source",
    "knowledge_level", "agent_type", "publications", "supporting_text",
    "original_predicate", "provided_by",
)
_CURIE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*:\S+$")
_PUBLICATION = re.compile(r"^(PMID|DOI|PMC|PMCID):\S+$", re.IGNORECASE)
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_EDGE_NAMESPACE = uuid.UUID("5b3c6a1e-3f7a-4c2e-9d1b-6f0a2e7c4b11")
_REFERENCE_KEYS = ("reference", "reference_id", "pmid", "doi", "source")
_TEXT_KEYS = ("snippet", "quote", "supporting_text")


class ExportError(RuntimeError):
    """The export cannot run as declared."""


@dataclass(frozen=True)
class ExportSettings:
    mech: str
    coverage: CoverageConfig
    infores: str
    node_namespace: str
    category_map: Mapping[str, str] = field(default_factory=dict)
    predicate_map: Mapping[str, str] = field(default_factory=dict)
    extra_prefixes: tuple[str, ...] = ()
    node_label_field: str = "label"
    node_description_field: str = "description"
    edge_predicate_id_field: str = "predicate_id"

    @classmethod
    def from_manifest(cls, mech: str, declaration: Any) -> ExportSettings:
        coverage = declaration.capabilities.get("causal_graph_coverage")
        if coverage is None or not coverage.is_enabled:
            raise ExportError(
                f"{mech}: causal_graph_coverage is not enabled, so there is no declared "
                f"graph shape to export"
            )
        kgx = declaration.capabilities.get("kgx_export")
        settings = dict(getattr(kgx, "settings", None) or {})
        category_map = maps.parse_pairs(settings.get("category_map"), "category_map")
        predicate_map = maps.parse_pairs(settings.get("predicate_map"), "predicate_map")
        unknown = sorted(
            {v for v in category_map.values() if v not in maps.categories()}
            | {v for v in predicate_map.values() if v not in maps.predicates()}
        )
        if unknown:
            raise ExportError(
                f"{mech}: not Biolink {maps.BIOLINK_VERSION} terms: {', '.join(unknown)}"
            )
        return cls(
            mech=mech,
            coverage=CoverageConfig.from_settings(coverage.settings),
            infores=str(settings.get("infores") or f"infores:{mech}"),
            node_namespace=str(settings.get("node_namespace") or mech),
            category_map=category_map,
            predicate_map=predicate_map,
            extra_prefixes=tuple(settings.get("extra_prefixes", ())),
            node_label_field=str(settings.get("node_label_field") or "label"),
        )


@dataclass
class ExportStats:
    records: int = 0
    records_with_graph: int = 0
    malformed: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    nodes: int = 0
    edges: int = 0
    minted_nodes: int = 0
    merged_nodes: int = 0
    category_conflicts: int = 0
    dangling_edges: int = 0
    edges_with_publications: int = 0
    category_sources: Counter[str] = field(default_factory=Counter)
    predicate_sources: Counter[str] = field(default_factory=Counter)
    unmapped_categories: Counter[str] = field(default_factory=Counter)
    unmapped_predicates: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        mapped = self.edges - self.predicate_sources.get("fallback", 0)
        return {
            "records": self.records,
            "records_with_graph": self.records_with_graph,
            "malformed": self.malformed,
            "unreadable": self.unreadable,
            "nodes": self.nodes,
            "edges": self.edges,
            "minted_nodes": self.minted_nodes,
            "merged_nodes": self.merged_nodes,
            "category_conflicts": self.category_conflicts,
            "dangling_edges_skipped": self.dangling_edges,
            "edges_with_publications": self.edges_with_publications,
            "predicates_mapped_fraction": round(mapped / self.edges, 4) if self.edges else None,
            "category_sources": dict(sorted(self.category_sources.items())),
            "predicate_sources": dict(sorted(self.predicate_sources.items())),
            "unmapped_categories": dict(self.unmapped_categories.most_common(25)),
            "unmapped_predicates": dict(self.unmapped_predicates.most_common(25)),
        }


def _clean(value: Any) -> str:
    """One TSV field: no tab, no line break, no bare carriage return (#275)."""
    if value is None:
        return ""
    return re.sub(r"[\t\r\n]+", " ", str(value)).strip()


def _multi(values: Sequence[str]) -> str:
    """KGX's `|`-delimited multivalue, with `|` inside a value kept as `/`."""
    return "|".join(_clean(v).replace("|", "/") for v in values if _clean(v))


def _mint(settings: ExportSettings, record_key: str, graph_id: str, node_id: str) -> str:
    parts = (record_key, graph_id, node_id)
    return f"{settings.node_namespace}:" + ".".join(_UNSAFE.sub("_", p).strip("_") for p in parts)


def _evidence(raw: Mapping[str, Any], field_name: str | None) -> tuple[list[str], list[str]]:
    items = raw.get(field_name) if field_name else None
    if isinstance(items, dict):
        items = [items]
    publications, texts = [], []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        for key in _REFERENCE_KEYS:
            value = item.get(key)
            if isinstance(value, str) and _PUBLICATION.match(value.strip()):
                prefix, local = value.strip().split(":", 1)
                prefix = {"PMCID": "PMC"}.get(prefix.upper(), prefix.upper())
                publications.append(f"{prefix}:{local}")
        for key in _TEXT_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
    return sorted(set(publications)), texts


def export(root: Path, globs: Sequence[str], settings: ExportSettings,
           *, sample: int | None = None) -> tuple[list[list[str]], list[list[str]], ExportStats]:
    """Read the corpus and return KGX node rows, edge rows and statistics."""
    stats = ExportStats()
    nodes: dict[str, list[str]] = {}
    edges: list[list[str]] = []
    shape = settings.coverage.shape
    paths = list_records(root, globs)
    if sample is not None:
        paths = paths[:sample]

    for path, record in iter_records(root, (), paths_by_glob={"": list(paths)},
                                     distinguish_empty=True):
        relative = path.relative_to(root).as_posix()
        if record is EMPTY_DOCUMENT:
            continue
        if record is None:
            stats.unreadable.append(relative)
            continue
        if not isinstance(record, dict):
            stats.malformed.append(f"{relative}: the record is not a mapping")
            continue
        try:
            parts = graph_parts(record, settings.coverage)
        except MalformedGraph as exc:
            stats.malformed.append(f"{relative}: {exc}")
            continue
        stats.records += 1
        if any(part.edges for part in parts):
            stats.records_with_graph += 1
        record_key = relative.rsplit(".", 1)[0]

        for part in parts:
            local: dict[str, str] = {}
            for node, grounding, raw in part.nodes:
                if grounding and _CURIE.match(grounding):
                    kgx_id, grounded = grounding, True
                elif _CURIE.match(node.id):
                    kgx_id, grounded = node.id, True
                else:
                    kgx_id, grounded = _mint(settings, record_key, part.graph_id, node.id), False
                    stats.minted_nodes += 1
                local[node.id] = kgx_id
                category = maps.resolve_category(node.type, kgx_id, settings.category_map)
                raw = raw or {}
                name = raw.get(settings.node_label_field) or raw.get("name") or ""
                row = [
                    kgx_id, category.value, _clean(name),
                    _clean(raw.get(settings.node_description_field)), settings.infores,
                    _clean(category.original) if category.source == "fallback" else "",
                    "true" if grounded else "false",
                ]
                if kgx_id in nodes:
                    stats.merged_nodes += 1
                    if nodes[kgx_id][1] != category.value:
                        stats.category_conflicts += 1
                    continue
                nodes[kgx_id] = row
                stats.category_sources[category.source] += 1
                if category.source == "fallback":
                    stats.unmapped_categories[category.original or "<unset>"] += 1

            for index, (edge, _evidenced, raw) in enumerate(part.edges):
                subject, obj = local.get(edge.subject), local.get(edge.object)
                if subject is None or obj is None:
                    stats.dangling_edges += 1
                    continue
                predicate_id = raw.get(settings.edge_predicate_id_field)
                resolution = maps.resolve_predicate(
                    str(predicate_id) if predicate_id else None, edge.predicate,
                    settings.predicate_map, settings.extra_prefixes,
                )
                stats.predicate_sources[resolution.source] += 1
                if resolution.source == "fallback":
                    stats.unmapped_predicates[_clean(resolution.original) or "<unset>"] += 1
                publications, texts = _evidence(raw, shape.edge_evidence_field)
                if publications:
                    stats.edges_with_publications += 1
                edge_id = uuid.uuid5(
                    _EDGE_NAMESPACE, f"{settings.mech}/{relative}/{part.graph_id}/{index}"
                )
                edges.append([
                    f"urn:uuid:{edge_id}", subject, resolution.value, obj,
                    settings.infores, "knowledge_assertion", "manual_agent",
                    _multi(publications), _multi(texts),
                    _clean(resolution.original) if resolution.original else "",
                    settings.infores,
                ])
    stats.nodes, stats.edges = len(nodes), len(edges)
    return list(nodes.values()), edges, stats


def _write(path: Path, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """Plain tab-joined lines: every field is already free of tabs and line
    breaks (`_clean`), so no quoting is needed and none is added -- a quote
    character inside a value stays a literal character."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in (columns, *rows):
            handle.write("\t".join(row) + "\n")


def write_export(root: Path, globs: Sequence[str], settings: ExportSettings, out: Path,
                 *, sample: int | None = None, provenance: Mapping[str, Any] | None = None
                 ) -> tuple[dict[str, Any], list]:
    """Export, write nodes.tsv / edges.tsv / manifest.json, and check the result."""
    node_rows, edge_rows, stats = export(root, globs, settings, sample=sample)
    if not stats.records:
        raise ExportError(f"{settings.mech}: no readable records at {', '.join(globs)} under {root}")
    out.mkdir(parents=True, exist_ok=True)
    nodes_path, edges_path = out / "nodes.tsv", out / "edges.tsv"
    _write(nodes_path, NODE_COLUMNS, node_rows)
    _write(edges_path, EDGE_COLUMNS, edge_rows)
    findings = check_graph(nodes_path, edges_path, KgxProfile(extra_prefixes=settings.extra_prefixes))
    manifest = {
        "mech": settings.mech,
        "infores": settings.infores,
        "biolink_version": maps.BIOLINK_VERSION,
        "graph_shape": settings.coverage.shape.kind,
        "sampled": sample is not None,
        **dict(provenance or {}),
        "statistics": stats.as_dict(),
        "contract_findings": sorted({f.code for f in findings}),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                       encoding="utf-8")
    return manifest, findings
