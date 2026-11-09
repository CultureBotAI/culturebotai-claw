"""Pure MIM owned-name export policy (MIM #669, Claw #701).

Callers own the complete mapped-record snapshot, source references, validation
and publication. SUPPRESS is an export decision; it neither rejects a source
synonym nor establishes that two records denote the same substance.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

POLICY_VERSION = "owned-name-policy-v1"
SIDECAR_COLUMNS = (
    "subject_id", "token_key", "token", "owner_subject_ids", "disposition",
    "input_surfaces", "source_refs", "evidence_refs",
)


@dataclass(frozen=True)
class AliasCandidate:
    """One pipe-free `other` token and its caller-supplied provenance."""

    text: str
    input_surface: str
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Suppression:
    """One observed exclusion; rendering combines repeated pair encounters."""

    subject_id: str
    token: str
    owner_subject_ids: frozenset[str]
    input_surface: str
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]


def _subject(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A nonempty subject ID is required")
    return value.strip()


def _token(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Alias token must be a string")
    if "|" in value:
        raise ValueError("Split pipe-delimited aliases into attributed tokens first")
    return value.strip()


def build_owner_index(
    records: Mapping[str, Mapping[str, object]],
) -> dict[str, frozenset[str]]:
    """Mirror native Rule K ownership without reads, caches or target filtering.

    Subject keys are the caller's forward-escaped filenames. An explicit
    representative takes precedence even when empty, null or unresolved.
    Only an absent representative permits the legacy identifier fallback.
    """
    entries = tuple(records.items())
    for subject, data in entries:
        if _subject(subject) != subject:
            raise ValueError("Snapshot subject IDs must already be stripped")
        if not isinstance(data, Mapping):
            raise ValueError(f"Record {subject} is not a mapping")

    def rejected(data: Mapping[str, object]) -> bool:
        return str(data.get("mapping_status") or "").strip().upper() == "REJECTED"

    live_by_identifier: dict[str, set[str]] = {}
    for subject, data in entries:
        identifier = str(data.get("identifier") or "").strip()
        if identifier and not rejected(data):
            live_by_identifier.setdefault(identifier, set()).add(subject)

    owners: dict[str, set[str]] = {}
    for subject, data in entries:
        term = str(data.get("preferred_term") or "").strip()
        if not term:
            continue
        if rejected(data):
            target = data.get("representative") if "representative" in data else data.get("identifier")
            credited = live_by_identifier.get(str(target or "").strip())
            owners.setdefault(term.casefold(), set()).update(credited or {subject})
        else:
            owners.setdefault(term.casefold(), set()).add(subject)
    return {term: frozenset(subjects) for term, subjects in owners.items()}


def filter_owned_aliases(
    subject_id: str,
    candidates: Iterable[AliasCandidate],
    owners: Mapping[str, frozenset[str]],
) -> tuple[tuple[AliasCandidate, ...], tuple[Suppression, ...]]:
    """Keep unowned or subject-owned tokens; preserve allowed input order.

    Upstream synonym eligibility and downstream deduplication/capping remain
    caller responsibilities. Blank candidates are left for that existing path,
    and cannot create an exclusion. No canonical baseline exempts a collision.
    """
    subject = _subject(subject_id)
    kept: list[AliasCandidate] = []
    suppressed: list[Suppression] = []
    for candidate in candidates:
        token = _token(candidate.text)
        holders = owners.get(token.casefold()) if token else None
        if not holders or subject in holders:
            kept.append(candidate)
            continue
        suppressed.append(Suppression(
            subject, token, frozenset(holders), candidate.input_surface,
            candidate.source_refs, candidate.evidence_refs,
        ))
    return tuple(kept), tuple(suppressed)


def _references(values: tuple[str, ...], field: str) -> set[str]:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"Suppression requires nonempty {field}")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"Suppression {field} must contain nonempty strings")
    return set(values)


def render_suppressed_aliases(events: Iterable[Suppression]) -> bytes:
    """Render deterministic, provenance-complete, one-row-per-pair TSV bytes.

    Owners, origins and references are unions across encounters. The displayed
    spelling is the minimum observed trimmed spelling, never an invented label.
    The manifest that binds these references and bytes belongs to the caller.
    """
    grouped: dict[tuple[str, str], dict[str, set[str]]] = {}
    for event in events:
        subject = _subject(event.subject_id)
        token = _token(event.token)
        if not token:
            raise ValueError("Suppression requires a nonempty token")
        holders = event.owner_subject_ids
        if not isinstance(holders, frozenset) or not holders:
            raise ValueError("Suppression requires a nonempty owner set")
        if any(_subject(owner) != owner for owner in holders):
            raise ValueError("Suppression owner IDs must already be stripped")
        if subject in holders:
            raise ValueError("Cannot suppress a token credited to the subject")
        surface = event.input_surface
        if not isinstance(surface, str) or not surface.strip():
            raise ValueError("Suppression requires an input surface")
        source_refs = _references(event.source_refs, "source_refs")
        evidence_refs = _references(event.evidence_refs, "evidence_refs")
        group = grouped.setdefault((subject, token.casefold()), {
            "tokens": set(), "owner_subject_ids": set(), "input_surfaces": set(),
            "source_refs": set(), "evidence_refs": set(),
        })
        group["tokens"].add(token)
        group["owner_subject_ids"].update(holders)
        group["input_surfaces"].add(surface)
        group["source_refs"].update(source_refs)
        group["evidence_refs"].update(evidence_refs)

    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=SIDECAR_COLUMNS,
                            delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for (subject, key), group in sorted(grouped.items()):
        row = {
            "subject_id": subject, "token_key": key,
            "token": min(group["tokens"]), "disposition": "SUPPRESS",
        }
        for field in ("owner_subject_ids", "input_surfaces", "source_refs", "evidence_refs"):
            row[field] = json.dumps(sorted(group[field]), ensure_ascii=False, separators=(",", ":"))
        writer.writerow(row)
    return out.getvalue().encode("utf-8")

# Controlled same-path cached-module source drift before builder import.
def filter_owned_aliases(subject_id, candidates, owners):
    return tuple(candidates), ()
