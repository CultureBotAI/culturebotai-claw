"""Biolink categories and predicates for the fleet KGX exporter (#539).

Every target below is a term of the pinned Biolink snapshot
(``data/biolink_4_3_6.json``, written by ``scripts/snapshot_biolink.py``), and
``resolve_category`` / ``resolve_predicate`` report *how* each value was
resolved, so an export can say what fraction it mapped rather than guess:

- a category comes from the node's type, then its grounding's prefix, then
  ``biolink:NamedThing`` with the original kept;
- a predicate comes from the edge's ``predicate_id`` when it is already
  Biolink, then from Biolink's own exact/narrow mappings of that CURIE (so an
  RO term needs no table here), then from the free-text phrase, then
  ``biolink:related_to`` with the original kept.

A Mech overrides or extends any of this through its ``kgx_export`` settings
(``category_map``, ``predicate_map``), written ``KEY=biolink:Term``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Iterable, Mapping

BIOLINK_VERSION = "4.3.6"
FALLBACK_CATEGORY = "biolink:NamedThing"
FALLBACK_PREDICATE = "biolink:related_to"
# Biolink 4.3.6 KnowledgeLevelEnum and AgentTypeEnum. An edge says only what
# its Mech declares; the default is `not_provided`, never a guess (#542).
KNOWLEDGE_LEVELS = frozenset({
    "knowledge_assertion", "logical_entailment", "not_provided", "observation",
    "prediction", "statistical_association",
})
AGENT_TYPES = frozenset({
    "automated_agent", "computational_model", "data_analysis_pipeline",
    "image_processing_agent", "manual_agent", "manual_validation_of_automated_agent",
    "not_provided", "text_mining_agent",
})

# Node types the Mechs share because the graph_list Mechs copied TraitMech's
# schema; measured across the fleet on 2026-09-30. Types with no honest single
# Biolink class (RESIDUE, MOTIF, STATE, CAPACITY, EXPERIMENTAL_FACTOR, ...) are
# deliberately absent: they export as NamedThing with the original kept.
NODE_TYPE_CATEGORIES: dict[str, str] = {
    "CHEMICAL": "biolink:ChemicalEntity",
    "COMPOUND": "biolink:ChemicalEntity",
    "LIGAND": "biolink:ChemicalEntity",
    "PRECURSOR": "biolink:ChemicalEntity",
    "MOLECULAR_FUNCTION": "biolink:MolecularActivity",
    "BIOLOGICAL_PROCESS": "biolink:BiologicalProcess",
    "PROCESS": "biolink:BiologicalProcess",
    "TRANSPORT_PROCESS": "biolink:BiologicalProcess",
    "PATHWAY": "biolink:Pathway",
    "PROTEIN": "biolink:Protein",
    "ENZYME": "biolink:Protein",
    "GENE_OR_PROTEIN": "biolink:GeneOrGeneProduct",
    "PROTEIN_COMPLEX": "biolink:MacromolecularComplex",
    "DOMAIN": "biolink:ProteinDomain",
    "NUCLEIC_ACID": "biolink:NucleicAcidEntity",
    "RNA": "biolink:RNAProduct",
    "CELLULAR_LOCALIZATION": "biolink:CellularComponent",
    "ORGANELLE": "biolink:CellularComponent",
    "STRUCTURE": "biolink:CellularComponent",
    "CELL_STRUCTURE": "biolink:CellularComponent",
    "PHENOTYPE": "biolink:PhenotypicFeature",
    "TRAIT": "biolink:PhenotypicFeature",
    "QUALITY": "biolink:Attribute",
    "ENVIRONMENTAL_FACTOR": "biolink:EnvironmentalFeature",
    "HABITAT": "biolink:EnvironmentalFeature",
    "TAXON": "biolink:OrganismTaxon",
}

# CURIE prefixes whose meaning does not depend on context. GO is absent: a GO
# term is a process, a function or a component, and only the node type says.
PREFIX_CATEGORIES: dict[str, str] = {
    "CHEBI": "biolink:ChemicalEntity",
    "PUBCHEM.COMPOUND": "biolink:ChemicalEntity",
    "NPATLAS": "biolink:ChemicalEntity",
    "RHEA": "biolink:MolecularActivity",
    "EC": "biolink:MolecularActivity",
    "UNIPROTKB": "biolink:Protein",
    "SGD": "biolink:Gene",
    "NCBITAXON": "biolink:OrganismTaxon",
    "GTDB": "biolink:OrganismTaxon",
    "ENVO": "biolink:EnvironmentalFeature",
    "PR": "biolink:Protein",
}

# Free-text phrasings that recur across Mechs, lower-cased and space-normalised.
PHRASE_PREDICATES: dict[str, str] = {
    "part of": "biolink:part_of",
    "is part of": "biolink:part_of",
    "is subunit of": "biolink:part_of",
    "has part": "biolink:has_part",
    "contains": "biolink:has_part",
    "has input": "biolink:has_input",
    "has output": "biolink:has_output",
    "molecularly interacts with": "biolink:physically_interacts_with",
    "binds": "biolink:binds",
    "interacts with": "biolink:interacts_with",
    "enables": "biolink:enables",
    "capable of": "biolink:capable_of",
    "precedes": "biolink:precedes",
    "produces": "biolink:produces",
    "consumes": "biolink:consumes",
    "contributes to": "biolink:contributes_to",
    "is a": "biolink:subclass_of",
    "catalyzes": "biolink:catalyzes",
    "causes": "biolink:causes",
    "regulates": "biolink:regulates",
    "affects": "biolink:affects",
    "associated with": "biolink:associated_with",
    "localizes to": "biolink:located_in",
    "located in": "biolink:located_in",
    "participates in": "biolink:participates_in",
    "has participant": "biolink:has_participant",
    "derives from": "biolink:derives_from",
    "occurs in": "biolink:occurs_in",
}


@dataclass(frozen=True)
class Resolution:
    value: str
    source: str  # which rule decided it, for the export manifest
    original: str | None  # the Mech's own value when it was not kept as is


@lru_cache(maxsize=None)
def snapshot(version: str = BIOLINK_VERSION) -> dict:
    name = f"biolink_{version.replace('.', '_')}.json"
    return json.loads(resources.files("kg_microbe_kgx").joinpath("data", name).read_text())


@lru_cache(maxsize=None)
def _mapped_predicates(version: str = BIOLINK_VERSION) -> dict[str, str]:
    """CURIE -> Biolink predicate, from the model's own exact/narrow mappings.

    A CURIE that Biolink maps from two predicates is ambiguous and left out.
    """
    seen: dict[str, set[str]] = {}
    for predicate, mapped in snapshot(version)["predicates"].items():
        for curie in mapped:
            seen.setdefault(curie.upper(), set()).add(predicate)
    return {curie: next(iter(p)) for curie, p in seen.items() if len(p) == 1}


def categories(version: str = BIOLINK_VERSION) -> frozenset[str]:
    return frozenset(snapshot(version)["categories"])


def predicates(version: str = BIOLINK_VERSION) -> frozenset[str]:
    return frozenset(snapshot(version)["predicates"])


def parse_pairs(values: Iterable[object] | None, what: str) -> dict[str, str]:
    """``["KEY=biolink:Term", ...]`` from a manifest string_list."""
    pairs: dict[str, str] = {}
    for item in values or ():
        key, sep, target = str(item).partition("=")
        if not sep or not key.strip() or not target.strip():
            raise ValueError(f"{what} entry {item!r} is not KEY=biolink:Term")
        pairs[key.strip()] = target.strip()
    return pairs


def _phrase(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip().lower()


def resolve_category(
    node_type: str | None,
    identifier: str,
    overrides: Mapping[str, str] | None = None,
) -> Resolution:
    overrides = overrides or {}
    if node_type and node_type in overrides:
        return Resolution(overrides[node_type], "mech_map", node_type)
    if node_type and node_type in NODE_TYPE_CATEGORIES:
        return Resolution(NODE_TYPE_CATEGORIES[node_type], "node_type", node_type)
    prefix = identifier.split(":", 1)[0].upper() if ":" in identifier else ""
    if prefix in PREFIX_CATEGORIES:
        return Resolution(PREFIX_CATEGORIES[prefix], "prefix", node_type)
    return Resolution(FALLBACK_CATEGORY, "fallback", node_type)


def resolve_predicate(
    predicate_id: str | None,
    phrase: str | None,
    overrides: Mapping[str, str] | None = None,
    extra_prefixes: tuple[str, ...] = (),
) -> Resolution:
    overrides = {_phrase(k): v for k, v in (overrides or {}).items()}
    known = predicates()
    original = predicate_id or phrase
    if predicate_id:
        if predicate_id in known:
            return Resolution(predicate_id, "biolink_id", None)
        mapped = _mapped_predicates().get(predicate_id.upper())
        if mapped:
            return Resolution(mapped, "mapped_id", predicate_id)
        prefix = predicate_id.split(":", 1)[0]
        if prefix in extra_prefixes:
            return Resolution(predicate_id, "declared_prefix", None)
    if phrase:
        key = _phrase(phrase)
        if key in overrides:
            return Resolution(overrides[key], "mech_map", phrase)
        if key in PHRASE_PREDICATES:
            return Resolution(PHRASE_PREDICATES[key], "phrase", phrase)
    return Resolution(FALLBACK_PREDICATE, "fallback", original)
