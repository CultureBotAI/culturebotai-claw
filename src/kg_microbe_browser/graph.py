"""Mermaid flowchart builders.

Each function takes a parsed YAML record and returns a Mermaid block
ready to embed in an HTML template (or an mkdocs page with the
mermaid2 plugin enabled).

Mermaid IDs are sanitized — Mermaid only accepts `[A-Za-z0-9_]` for
node names, so CURIEs like `CHEBI:17234` become `CHEBI_17234`. The
displayed label keeps the colon.
"""
from __future__ import annotations

import re

_MERMAID_ID_RE = re.compile(r"[^A-Za-z0-9_]")


def _id(curie: str) -> str:
    """Sanitize a CURIE for use as a Mermaid node id."""
    return _MERMAID_ID_RE.sub("_", (curie or "ROOT")) or "node"


def _label(text: str) -> str:
    """Mermaid label-safe quoting. Doubles quote chars and trims length."""
    if not text:
        return ""
    s = str(text).replace('"', "'").replace("\n", " ")
    if len(s) > 70:
        s = s[:67] + "..."
    return s


def build_community_membership_graph(community: dict) -> str:
    """Mermaid flowchart: community → member taxa (+ functional roles).

    Renders only when there is taxonomy data; otherwise returns empty.
    """
    cid = community.get("id") or "community"
    cname = community.get("name") or cid
    taxa = community.get("taxonomy") or []
    if not taxa:
        return ""

    lines = ["```mermaid", "flowchart LR"]
    root = _id(cid)
    lines.append(f'    {root}["{_label(cname)}"]')
    for entry in taxa:
        term = (entry.get("taxon_term") or {}).get("term") or {}
        tid = term.get("id")
        if not tid:
            continue
        node = _id(tid)
        label = term.get("label") or tid
        edge_label = entry.get("functional_role") or ""
        if isinstance(edge_label, list):
            edge_label = ",".join(edge_label)
        if edge_label:
            lines.append(
                f'    {root} -->|"{_label(edge_label)}"| {node}["{_label(label)}"]'
            )
        else:
            lines.append(f'    {root} --> {node}["{_label(label)}"]')
    lines.append("```")
    return "\n".join(lines)


def build_ingredient_composition_graph(medium: dict,
                                       max_ingredients: int = 30) -> str:
    """Mermaid flowchart: medium → ingredients → CHEBI (when mapped).

    Caps at max_ingredients to avoid runaway diagrams for complex media.
    """
    mid = medium.get("id") or "medium"
    mname = medium.get("name") or mid
    ingredients = medium.get("ingredients") or []
    if not ingredients:
        return ""

    lines = ["```mermaid", "flowchart LR"]
    root = _id(mid)
    lines.append(f'    {root}["{_label(mname)}"]')
    seen_chebi: set[str] = set()
    for i, ing in enumerate(ingredients[:max_ingredients]):
        name = ing.get("preferred_term") or "?"
        ing_id = _id(f"ing{i}_{name}")
        lines.append(f'    {ing_id}["{_label(name)}"]')
        lines.append(f"    {root} --> {ing_id}")
        term = ing.get("term") or {}
        cid = term.get("id")
        if cid and cid.startswith("CHEBI:"):
            cid_node = _id(cid)
            if cid not in seen_chebi:
                seen_chebi.add(cid)
                lines.append(f'    {cid_node}["{cid}"]')
            lines.append(f'    {ing_id} -.-> {cid_node}')
    if len(ingredients) > max_ingredients:
        more = len(ingredients) - max_ingredients
        lines.append(f'    {root} --> more["...{more} more"]')
    lines.append("```")
    return "\n".join(lines)
