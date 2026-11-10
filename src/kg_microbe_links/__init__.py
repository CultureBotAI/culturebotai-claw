"""Cross-Mech links: do the identifiers one Mech's records cite resolve in the Mech that owns them?

The first link kind is taxa: every `NCBITaxon` CURIE a record carries, judged
against what TaxonMech holds. See `kg_microbe_links.taxa`.
"""

from kg_microbe_links.taxa import (
    TaxonIndex,
    TaxonLinksError,
    Verdict,
    collect,
    resolve_all,
)

__all__ = ["TaxonIndex", "TaxonLinksError", "Verdict", "collect", "resolve_all"]
