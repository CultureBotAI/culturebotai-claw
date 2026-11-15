"""Finite, explicitly reviewed external assertions on one permanent MIM owner.

This pure contract is also executed from captured source bytes by Claw. It does
not discover terms, infer ancestors, approve evidence, or modify owner identity.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

FIELD = "additional_ontology_mappings"
MARKER = "additional_ontology_mapping="
PREDICATES = {"skos:exactMatch", "skos:closeMatch", "skos:broadMatch", "skos:narrowMatch"}
SOURCES = {
    "CHEBI": "CHEBI",
    "FOODON": "FOODON",
    "ENVO": "ENVO",
    "UBERON": "UBERON",
    "NCIT": "NCIT",
    "mesh": "MESH",
    "BTO": "BTO",
    "MICRO": "MICRO",
}
FIELDS = {
    "subject_id",
    "ontology_id",
    "ontology_label",
    "ontology_source",
    "predicate_id",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "review_note",
    "evidence",
    "llm_assisted",
    "mapping_justification",
}
EVIDENCE_FIELDS = {
    "evidence_source",
    "evidence_type",
    "source",
    "confidence_score",
    "notes",
    "cas_rn",
    "pmid",
    "doi",
    "snippet",
    "supports",
    "explanation",
}


def require(condition, message):
    if not condition:
        raise ValueError("Additional ontology mapping: " + message)


def assertions(record):
    """Validate cross-field meaning; closed LinkML validation also checks shape.

    WITHHOLD preserves a reviewed proposal without licensing its publication as
    supported. A contradictory evidence list cannot be marked SUPPORTED.
    """
    values = record.get(FIELD, [])
    require(isinstance(values, list), "assertions must be a list")
    if not values:
        return values
    primary = record.get("ontology_mapping") or {}
    require(
        isinstance(primary, dict) and isinstance(record.get("identifier"), str),
        "valid primary mapping and identifier required",
    )
    require(
        primary.get("ontology_id") is None or isinstance(primary["ontology_id"], str),
        "primary target must be a CURIE string",
    )
    seen = {primary.get("ontology_id"), record.get("identifier")}
    for item in values:
        require(
            isinstance(item, dict) and set(item) == FIELDS, "complete assertion fields required"
        )
        for name in FIELDS - {"evidence", "llm_assisted"}:
            require(
                isinstance(item[name], str)
                and bool(item[name].strip())
                and item[name] == item[name].strip()
                and not any(c in item[name] for c in "\n\r\t"),
                "nonblank scalar required: " + name,
            )
        require(type(item["llm_assisted"]) is bool, "explicit LLM assistance attribution required")
        require(
            re.fullmatch(r"semapv:[A-Za-z][A-Za-z0-9_]*", item["mapping_justification"])
            is not None,
            "explicit mapping justification CURIE required",
        )
        require(
            re.fullmatch(r"MIM:[0-9]{7}", item["subject_id"]) is not None
            and item["subject_id"] != "MIM:0000000"
            and item["subject_id"] == record.get("mim_id"),
            "permanent owner differs",
        )
        target = item["ontology_id"]
        require(
            re.fullmatch(r"[A-Za-z]+:[A-Za-z0-9][A-Za-z0-9._~-]*", target) is not None,
            "external ontology CURIE required",
        )
        require(
            SOURCES.get(target.split(":", 1)[0]) == item["ontology_source"],
            "ontology prefix/source differs or is unsupported",
        )
        require(target not in seen, "duplicate or conflicting target; primary stays separate")
        seen.add(target)
        require(item["predicate_id"] in PREDICATES, "unsupported predicate; no subclass projection")
        require(item["review_status"] in {"SUPPORTED", "WITHHOLD"}, "review disposition required")
        try:
            reviewed = datetime.fromisoformat(item["reviewed_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Additional ontology mapping: invalid review timestamp") from exc
        require(reviewed.utcoffset() is not None, "review timestamp needs timezone")
        evidence = item["evidence"]
        require(isinstance(evidence, list) and bool(evidence), "scoped evidence required")
        for entry in evidence:
            require(
                isinstance(entry, dict) and set(entry) <= EVIDENCE_FIELDS,
                "evidence must use maintained MappingEvidence fields",
            )
            for name in ("evidence_type", "source", "explanation", "supports"):
                require(
                    isinstance(entry.get(name), str)
                    and bool(entry[name].strip())
                    and not any(c in entry[name] for c in "\t\r\n"),
                    "evidence needs " + name,
                )
            require(
                entry["supports"] in {"SUPPORT", "PARTIAL", "REFUTE", "NO_EVIDENCE"},
                "invalid evidence support",
            )
        if item["review_status"] == "SUPPORTED":
            require(
                record.get("mapping_status") == "MAPPED" and bool(primary.get("ontology_id")),
                "supported extra needs eligible primary grounding",
            )
            supports = {entry["supports"] for entry in evidence}
            require(
                "SUPPORT" in supports and "REFUTE" not in supports,
                "supported assertion needs uncontradicted supporting evidence",
            )
            if item["predicate_id"] == "skos:exactMatch":
                require(
                    primary.get("mapping_quality") in {"EXACT_MATCH", "SYNONYM_MATCH"},
                    "exact extra cannot excuse an inexact primary grounding",
                )
    return values


def assertion_comment(item):
    """Preserve the entire reviewed assertion without a new SSSOM column."""
    return MARKER + json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def row_assertion(record, row):
    """Bind an extra row to its full current assertion, including withheld status."""
    values = assertions(record)
    item = next((value for value in values if value["ontology_id"] == row["object_id"]), None)
    if item is None:
        require(MARKER not in row.get("comment", ""), "row assertion has no current owner claim")
        return None
    require(
        row["subject_id"] == item["subject_id"]
        and row["predicate_id"] == item["predicate_id"]
        and row["object_label"] == item["ontology_label"]
        and row.get("mapping_justification") == item["mapping_justification"]
        and row.get("mapping_date") == item["reviewed_at"][:10]
        and embedded_assertion(row) == item
        and assertion_comment(item) in row.get("comment", ""),
        "row target, predicate, label or evidence differs from current assertion",
    )
    expected_sources = {"MIM:" + entry["source"] for entry in item["evidence"]}
    expected_sources.add("MIM:curator=" + item["reviewed_by"])
    require(
        expected_sources <= set(row.get("source", "").split("|")),
        "row assertion attribution differs",
    )
    require(not row.get("other"), "additional assertions must not activate aliases")
    return item


def embedded_assertion(row):
    """Read the last current assertion after any preserved historical comments."""
    comment = row.get("comment", "")
    if MARKER not in comment:
        return None
    offset, item = 0, None
    while (position := comment.find(MARKER, offset)) != -1:
        start = position + len(MARKER)
        try:
            item, length = json.JSONDecoder().raw_decode(comment[start:])
        except (ValueError, TypeError) as exc:
            raise ValueError("Additional ontology mapping: malformed embedded assertion") from exc
        offset = start + length
    require(isinstance(item, dict) and set(item) == FIELDS, "incomplete embedded assertion")
    require(
        item["subject_id"] == row["subject_id"]
        and item["ontology_id"] == row["object_id"]
        and item["predicate_id"] == row["predicate_id"],
        "embedded assertion triple differs",
    )
    return item
