"""Shared loader for kg-microbe's unified entity mapping artifact.

kg-microbe replaced the old wide dictionary
`mappings/unified_chemical_mappings.tsv.gz` (columns: id, canonical_name,
formula, synonyms, xrefs, sources) with an SSSOM file
`mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz` (columns:
subject_id, subject_label, predicate_id, object_id, object_label,
object_source, mapping_justification, source, mapping_date, confidence,
comment, object_formula, object_category).

The two are not a rename: the entity is now the *object* of a mapping row and
the surface forms kg-microbe recognizes are the *subject labels* spread across
many rows. This module re-derives the old per-entity view so the existing
reconciliation scripts keep working:

    canonical_name  <- object_label
    formula         <- object_formula
    synonyms        <- set of subject_label over *exactMatch* rows sharing
                       object_id
    xrefs           <- set of subject_id over rows sharing object_id
                       (this is where MIM:<id> cross-references now live)
    sources         <- pipe-joined `source` values
"""

from __future__ import annotations

import gzip
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# kg-microbe is not a Mech, so the manifest does not describe it and
# `require_mech_roots` does not cover it. The env-then-sibling shape is the
# same one `sync_kgm_dependencies.py` uses. Note that `load_kgm_entity_index`
# below returns {} for a missing file rather than refusing -- each caller
# checks `.exists()` itself and raises with the regeneration command, so a
# wrong root surfaces there, not here.
KGM_ROOT = Path(os.environ.get("KGMICROBE_ROOT", REPO_ROOT.parent / "kg-microbe"))
KGM_UNIFIED_SSSOM = (
    KGM_ROOT / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
)

# Mirrors KgMicrobeDict: an entity accumulating more surface forms than this is
# a row-merge pollution victim, not a real synonym set.
POLLUTION_THRESHOLD = 500

_CURIE_RE = re.compile(r"^[A-Z][A-Za-z0-9_.]*:[A-Za-z0-9_\-]+$")


def _iter_sssom(path: Path):
    """Yield dict rows from a (possibly gzipped) SSSOM TSV, skipping # metadata."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        header: list[str] | None = None
        for raw in f:
            if raw.startswith("#"):
                continue
            parts = raw.rstrip("\n").split("\t")
            if header is None:
                header = parts
                continue
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            yield dict(zip(header, parts))


def load_kgm_entity_index(
    path: Path | None = None, prefix: str = "CHEBI:"
) -> dict[str, dict]:
    """Return <prefix> entity ID -> {canonical_name, formula, synonyms, xrefs, sources}.

    Shape-compatible with the old `load_kgm_dict()` so callers need no change
    beyond the import.
    """
    path = path or KGM_UNIFIED_SSSOM
    by_id: dict[str, dict] = {}
    if not path.exists():
        return by_id

    for row in _iter_sssom(path):
        oid = (row.get("object_id") or "").strip()
        if not oid.startswith(prefix):
            continue

        entry = by_id.get(oid)
        if entry is None:
            entry = by_id[oid] = {
                "canonical_name": "",
                "formula": "",
                "synonyms": set(),
                "xrefs": set(),
                "sources": set(),
            }

        if not entry["canonical_name"]:
            olabel = (row.get("object_label") or "").strip()
            # A few rows carry the CURIE itself as the label; that is not a name.
            entry["canonical_name"] = "" if olabel == oid else olabel
        if not entry["formula"]:
            entry["formula"] = (row.get("object_formula") or "").strip()

        # Only identity rows can contribute synonyms.  The unified mapping also
        # carries close/narrow/broad matches whose subject labels are useful for
        # discovery, but are explicitly *not* names for the object.  Treating all
        # of them as synonyms discarded the SSSOM predicate and let unrelated
        # labels leak into MIM's published ``other`` column (MIM #464/#470).
        slabel = (row.get("subject_label") or "").strip()
        predicate = (row.get("predicate_id") or "").strip()
        if (
            predicate == "skos:exactMatch"
            and slabel
            and slabel != oid
            and not _CURIE_RE.match(slabel)
        ):
            entry["synonyms"].add(slabel)

        sid = (row.get("subject_id") or "").strip()
        if sid:
            entry["xrefs"].add(sid)

        for s in (row.get("source") or "").split("|"):
            if s.strip():
                entry["sources"].add(s.strip())

    for entry in by_id.values():
        entry["sources"] = "|".join(sorted(entry["sources"]))
        if len(entry["synonyms"]) > POLLUTION_THRESHOLD:
            entry["synonyms"] = set()
            entry["_polluted"] = True

    return by_id


def load_kgm_source_index(path: Path | None = None) -> dict[str, str]:
    """CHEBI:X -> pipe-separated kg-microbe `source` string."""
    return {
        cid: e["sources"]
        for cid, e in load_kgm_entity_index(path).items()
        if e["sources"]
    }


def load_kgm_labels(path: Path | None = None) -> dict[str, tuple[str, list[str]]]:
    """CHEBI:X -> (canonical_name, [synonyms...])."""
    return {
        cid: (e["canonical_name"], sorted(e["synonyms"]))
        for cid, e in load_kgm_entity_index(path).items()
    }


def load_kgm_compound_placeholders(path: Path | None = None) -> list[dict]:
    """Load kgmicrobe.compound:* placeholder entities (no-CHEBI surface forms).

    In the SSSOM these appear as *subjects*, so one row is one placeholder.
    """
    path = path or KGM_UNIFIED_SSSOM
    rows: list[dict] = []
    if not path.exists():
        return rows

    seen: set[str] = set()
    for row in _iter_sssom(path):
        sid = (row.get("subject_id") or "").strip()
        if not sid.startswith("kgmicrobe.compound:") or sid in seen:
            continue
        seen.add(sid)
        # subject_label is frequently blank in this artifact; the CURIE local
        # part is a slug of the original surface form, so de-slugify as fallback.
        label = (row.get("subject_label") or "").strip()
        if not label:
            label = sid.split(":", 1)[1].replace("_", " ").strip()
        rows.append({
            "source_id": sid,
            "preferred_term": label,
            "occurrences": 0,
            "sources": (row.get("source") or "").strip(),
            "origin": "kgmicrobe.compound",
        })
    return rows
