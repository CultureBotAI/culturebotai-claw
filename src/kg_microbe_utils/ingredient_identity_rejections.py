"""Reviewed proposal exclusions; this module neither resolves nor assigns IDs.

MIM #1004 and Claw #699 distinguish DL-carnitine hydrochloride from the
carnitinamide chloride at CHEBI:48601 despite that term's conflicting CAS xref.
The bounded evidence is retained in docs/reviews/carnitine-cas-policy-699/.
"""
from __future__ import annotations

DECISION = "https://github.com/CultureBotAI/MediaIngredientMech/issues/1004"
SOURCES = (
    "https://api-evsrest.nci.nih.gov/api/v1/concept/ncit/C216679?include=full",
    "https://pubchem.ncbi.nlm.nih.gov/compound/5970",
    "https://www.ebi.ac.uk/chebi/backend/api/public/compound/48601/",
)
_REVIEWED_NAMES = frozenset({"carnitine hydrochloride", "carnitine (dl) hydrochloride"})


def rejection_reason(*, ontology_id: str, cas: str | None = None,
                     name: str | None = None) -> str | None:
    """Reject only the reviewed CAS/term pair or the two reviewed salt names.

    CURIE prefix case and outer whitespace are representation boundaries; names
    additionally collapse whitespace and case. No punctuation, stereo qualifier,
    substring, synonym, or inferred source field is used to broaden the scope.
    """
    if ontology_id.strip().upper() != "CHEBI:48601":
        return None
    number = (cas or "").strip()
    if number.lower().startswith("cas:"):
        number = number[4:]
    reviewed_cas = number == "461-05-2"
    reviewed_name = " ".join((name or "").casefold().split()) in _REVIEWED_NAMES
    if not (reviewed_cas or reviewed_name):
        return None
    basis = "CAS 461-05-2" if reviewed_cas else "the reviewed hydrochloride name"
    return (
        f"Rejected CHEBI:48601 for {basis}: carnitinamide chloride is a distinct "
        f"amide, not the reviewed carnitine hydrochloride. Decision: {DECISION}; "
        f"primary evidence: {'; '.join(SOURCES)}. No replacement ID inferred."
    )
