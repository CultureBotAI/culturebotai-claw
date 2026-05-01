"""kg_microbe_browser — shared HTML/browser helpers for the mech repos.

Currently exports a Mermaid-graph builder usable from any per-record
HTML template (CultureMech media composition, MIM ingredient
relationships, CommunityMech community membership).

Phase 5 of the dismech-pattern port; see
docs/proposals/phase5_mkdocs_material_and_browser_parity.md
"""
from kg_microbe_browser.graph import (
    build_community_membership_graph,
    build_ingredient_composition_graph,
)

__all__ = [
    "build_community_membership_graph",
    "build_ingredient_composition_graph",
]
