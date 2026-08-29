"""Correct-by-analogy proposals over the disagreements the scanner reports.

Item 2 of #129. Where the scanner says two records for one substance disagree,
this asks a narrower question: does one of them clearly have the answer the
other is waiting for?

The rule is deliberately narrow, because #129 is explicit that this is not a
conflict-resolution engine. Only one shape is proposed:

    one record is grounded in an ontology, its twin sits on a registry or
    placeholder fallback for the same substance

That case is unambiguous, and the corpus states it in its own words. A real
`cas:612-05-5` record carries the note "no CHEBI entry exists ... Curator can
promote to a CHEBI primary if/when CHEBI adds the term", while its twin is
already `CHEBI:74863`. The precondition the record itself named is satisfied,
and the evidence is the sibling record.

Two records grounded in DIFFERENT ontology terms are reported and never
proposed on. There is no basis in the data for picking a winner between
CHEBI:16789 and CHEBI:62318 for D-lyxose, and inventing one is what #129 warns
against.

Nothing here writes to a corpus. A proposal is a document for a curator.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .scanner import Group, Record, scan_groups

# Mapping qualities that mean "no ontology term was available", measured
# against the real corpus rather than assumed. A record in one of these states
# is a placeholder for a grounding, not a competing grounding.
FALLBACK_QUALITIES: frozenset[str] = frozenset(
    {"FALLBACK_REGISTRY", "PLACEHOLDER", "CAS_RN_LOOKUP"}
)

# Sources that are registries or minted stand-ins rather than ontologies.
FALLBACK_SOURCES: frozenset[str] = frozenset({"CAS"})
MINTED_PREFIXES: tuple[str, ...] = ("kgmicrobe.",)

# Qualities that assert the term IS the substance. SYNONYM_MATCH belongs here:
# a synonym match is an exact identity, not a close one.
IDENTITY_QUALITIES: frozenset[str] = frozenset({"EXACT_MATCH", "SYNONYM_MATCH"})


def is_fallback(record: Record) -> bool:
    """Whether this record is standing in for a grounding it does not have."""
    quality = record.fields.get("mapping_quality", "")
    source = record.fields.get("ontology_source", "")
    identifier = record.fields.get("ontology_id", "")
    return (
        quality in FALLBACK_QUALITIES
        or source in FALLBACK_SOURCES
        or identifier.startswith(MINTED_PREFIXES)
    )


def is_ontology_grounded(record: Record) -> bool:
    """Whether this record asserts an ontology term as the substance's identity."""
    if is_fallback(record):
        return False
    return record.fields.get("mapping_quality", "") in IDENTITY_QUALITIES


@dataclass(frozen=True)
class Proposal:
    """A correction one record's state suggests for another, with its evidence."""

    subject: Record
    analogue: Record
    field_name: str
    current: str
    proposed: str
    justification: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "record": str(self.subject.path),
            "identifier": self.subject.identifier,
            "field": self.field_name,
            "current": self.current,
            "proposed": self.proposed,
            "analogous_record": str(self.analogue.path),
            "analogous_identifier": self.analogue.identifier,
            "justification": self.justification,
        }


def propose_for_group(group: Group) -> list[Proposal]:
    """Proposals this group supports, which is often none.

    Requires exactly one ontology-grounded record. Two grounded records
    disagreeing is the surface-only case, and a group of fallbacks has no
    answer to copy from.
    """
    grounded = [r for r in group.records if is_ontology_grounded(r)]
    fallbacks = [r for r in group.records if is_fallback(r)]
    if len(grounded) != 1 or not fallbacks:
        return []

    analogue = grounded[0]
    target = analogue.fields.get("ontology_id", "")
    if not target:
        return []

    proposals: list[Proposal] = []
    for record in fallbacks:
        current = record.fields.get("ontology_id", "")
        if current == target:
            continue
        proposals.append(
            Proposal(
                subject=record,
                analogue=analogue,
                field_name="ontology_id",
                current=current,
                proposed=target,
                justification=(
                    f"{record.preferred_term!r} is on a "
                    f"{record.fields.get('mapping_quality') or 'fallback'} "
                    f"grounding ({current or 'none'}), while "
                    f"{analogue.preferred_term!r} — matched to it by "
                    f"{group.reason} — is grounded as "
                    f"{analogue.fields.get('mapping_quality')} to {target}. "
                    f"An ontology term exists for this substance."
                ),
            )
        )
    return proposals


def unmodelled_qualities(groups: Sequence[Group]) -> set[str]:
    """Mapping qualities in these groups that the proposal rule does not know.

    The rule keys on MediaIngredientMech's vocabulary. CultureMech's is
    entirely different -- `(none)`, `LLM_ASSISTED`, `MANUAL` -- so no record
    there classifies as grounded or as a fallback and nothing is ever proposed.
    Declining is right; declining silently is the failure shape recorded in
    #161 and again in the scanner's skip count (#192).
    """
    known = FALLBACK_QUALITIES | IDENTITY_QUALITIES
    seen = {
        record.fields.get("mapping_quality", "")
        for group in groups
        for record in group.records
    }
    return {quality for quality in seen if quality and quality not in known}


def proposals_from_groups(
    groups: Sequence[Group],
) -> tuple[list[Proposal], list[Group]]:
    """Split disagreeing groups into proposals and surface-only findings.

    Takes groups rather than a path so one traversal can answer both the scan
    and the proposal question. Re-scanning would be the second definition of
    "the same substance" that `scan_groups` exists to prevent (#190).
    """
    proposed: list[Proposal] = []
    surfaced: list[Group] = []
    for group in groups:
        if not group.disagreements:
            continue
        group_proposals = propose_for_group(group)
        if group_proposals:
            proposed.extend(group_proposals)
        else:
            surfaced.append(group)
    return proposed, surfaced


def build_proposals(root: Path, glob: str = "**/*.yaml") -> dict[str, Any]:
    """Scan `root` and return proposals plus the groups deliberately left alone."""
    records, skipped, groups = scan_groups(root, glob)
    proposed, surfaced = proposals_from_groups(groups)
    return {
        "root": str(root),
        "records_scanned": len(records),
        "files_skipped": skipped,
        "proposals": [p.as_dict() for p in proposed],
        "surfaced_without_proposal": [g.as_dict() for g in surfaced],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """A curator-facing document. Proposals are requests, not decisions."""
    lines = ["# Correct-by-analogy proposals\n"]
    lines.append(
        f"Scanned {report['records_scanned']} records. "
        f"{len(report['proposals'])} proposal(s); "
        f"{len(report['surfaced_without_proposal'])} disagreement(s) surfaced "
        f"without one.\n"
    )
    lines.append(
        "> Every proposal below needs a curator's decision. Nothing here has "
        "been applied.\n"
    )
    if report["proposals"]:
        lines.append("## Proposals\n")
        for item in report["proposals"]:
            lines.append(f"### `{item['identifier']}` — {Path(item['record']).name}")
            lines.append(f"- **{item['field']}**: `{item['current'] or 'none'}` "
                         f"→ `{item['proposed']}`")
            lines.append(f"- Analogous record: `{item['analogous_identifier']}` "
                         f"({Path(item['analogous_record']).name})")
            lines.append(f"- {item['justification']}\n")
    if report["surfaced_without_proposal"]:
        lines.append("## Surfaced without a proposal\n")
        lines.append(
            "Both records assert an ontology grounding, or neither does. There "
            "is no basis in the data for choosing between them, so these are "
            "reported for a curator rather than resolved.\n"
        )
        for group in report["surfaced_without_proposal"]:
            names = ", ".join(f"`{r['identifier']}`" for r in group["records"])
            lines.append(f"- **{group['key']}** ({group['matched_on']}): {names}")
    return "\n".join(lines) + "\n"
