#!/usr/bin/env python3
"""
Generate workspace/reports/kg_microbe_review.md — a row-level diff
of MIM's published SSSOM against kg-microbe's SSSOM-first consolidated
artifact on the chemical-mappings-mim-priority branch.

Why this script changed (2026-05-04)
------------------------------------
kg-microbe's consolidator collapses MIM:* subjects into entity-anchored
records: a MIM row ``MIM:Glucose skos:exactMatch CHEBI:17234`` is *not*
preserved in the unified SSSOM as a ``MIM:Glucose``-keyed row. Instead,
the consolidator emits many xref rows ``cas:50-99-7 → CHEBI:17234``,
``kegg.compound:C00031 → CHEBI:17234``, etc., and accumulates source
contributors (including ``mediaingredientmech_reviewed``) on the
``source`` column of those rows.

The previous classifier looked for ``subject_id == MIM:*`` matches in
kg-microbe's unified SSSOM and reported 1338 ``MISSING_IN_KGM`` —
nearly all of which were artefacts: the MIM mapping had landed via
xref-row propagation, just not under a ``MIM:*`` subject. The new
classifier anchors on ``object_id`` instead.

Output classes
--------------
  IN_SYNC                        kg-microbe has ≥1 row with this MIM-asserted
                                 object_id AND `mediaingredientmech_*` in source.
  IN_SYNC_SUBJECT_PRESERVED      Residual MIM:* subject preserved in kg-microbe
                                 (no xref collapse possible) and matches MIM's object.
  DIVERGED_OBJECT                Residual MIM:* subject preserved in kg-microbe but
                                 with a different object_id than MIM asserts.
  PROVENANCE_LOST                Object exists in kg-microbe SSSOM but no row
                                 carries `mediaingredientmech_*` source — consolidator
                                 dropped MIM provenance, or hasn't re-run yet.
  OBJECT_NOT_IN_KGM              MIM-asserted object_id is absent from kg-microbe
                                 entirely. True propagation backlog.
  REGISTRY_LANDED                MIM registry row (object = `kgmicrobe.{ingredient,compound}:*`)
                                 — that CURIE has its own subject row in kg-microbe.
  REGISTRY_NOT_LANDED            Same shape, but kg-microbe doesn't yet have a
                                 row for that registry CURIE (informational —
                                 happens when MIM mints a new registry CURIE
                                 with no canonical CHEBI anchor for kg-microbe
                                 to synthesise around).

Also scans kg-microbe's SSSOM for:
  STALE_IN_KGM         MIM:* subjects in kg-microbe that MIM no longer publishes.
  MIM_LEGACY_IN_KGM    Any `MediaIngredientMech:*` subjects remaining.
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ---------- paths ----------


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)
KGM_ROOT_PATH = Path(
    os.environ.get("KGMICROBE_ROOT", REPO_ROOT.parent / "kg-microbe")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
MIM_SSSOM = MIM_ROOT / "mappings/ingredient_mappings.sssom.tsv"
KGM_SSSOM_GZ = KGM_ROOT_PATH / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
KGM_LEGACY_TSV_GZ = KGM_ROOT_PATH / "mappings/unified_chemical_mappings.tsv.gz"
KGM_METATRAITS_DIR = KGM_ROOT_PATH / "kg_microbe/transform_utils/metatraits/mappings"
OUT = REPO_ROOT / "workspace/reports/kg_microbe_review.md"


# ---------- loaders ----------

def _parse_sssom_header_and_rows(lines):
    """Yield (header_list, row_dict) pairs; skip comment lines."""
    header = None
    for line in lines:
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if header is None:
            header = parts
            continue
        if len(parts) < len(header):
            parts += [""] * (len(header) - len(parts))
        yield header, dict(zip(header, parts))


def load_mim() -> list[dict]:
    """Return ALL MIM SSSOM rows (no dedup; one MIM subject can have many rows)."""
    rows: list[dict] = []
    with MIM_SSSOM.open() as f:
        for _, row in _parse_sssom_header_and_rows(f):
            rows.append(row)
    return rows


def load_kgm_indexes() -> dict:
    """Build the indexes the new classifier needs.

    Returns dict with keys:
      objects_with_mim       set[str] — object_ids in rows tagged `mediaingredientmech_*`
      all_objects            set[str] — every object_id seen
      mim_subject_rows       dict[str, list[dict]] — residual `MIM:*` subjects
      kgmicrobe_subjects     set[str] — kgmicrobe.{ingredient,compound}:* subject_ids
      legacy_rows            list[dict] — MediaIngredientMech:* subjects
      mim_subject_source     dict[str, set[str]] — source-tag set per MIM:* subject
    """
    objects_with_mim: set[str] = set()
    all_objects: set[str] = set()
    mim_subject_rows: dict[str, list[dict]] = defaultdict(list)
    kgmicrobe_subjects: set[str] = set()
    legacy_rows: list[dict] = []
    mim_subject_source: dict[str, set[str]] = defaultdict(set)

    with gzip.open(KGM_SSSOM_GZ, "rt", encoding="utf-8") as f:
        for _, row in _parse_sssom_header_and_rows(f):
            obj = (row.get("object_id") or "").strip()
            sid = (row.get("subject_id") or "").strip()
            src = (row.get("source") or "")
            src_lower = src.lower()
            has_mim = "mediaingredient" in src_lower

            if obj:
                all_objects.add(obj)
                if has_mim:
                    objects_with_mim.add(obj)

            if sid.startswith("MIM:"):
                mim_subject_rows[sid].append(row)
                for tag in src.split("|"):
                    tag = tag.strip()
                    if tag:
                        mim_subject_source[sid].add(tag)
            elif sid.startswith("MediaIngredientMech:"):
                legacy_rows.append(row)
            elif sid.startswith("kgmicrobe."):
                kgmicrobe_subjects.add(sid)

    return {
        "objects_with_mim": objects_with_mim,
        "all_objects": all_objects,
        "mim_subject_rows": dict(mim_subject_rows),
        "kgmicrobe_subjects": kgmicrobe_subjects,
        "legacy_rows": legacy_rows,
        "mim_subject_source": dict(mim_subject_source),
    }


def load_metatraits_chemical() -> tuple[list[dict], list[dict]]:
    """Load kg-microbe's metatraits chemical mappings — these are
    chemistry-relevant mapping files outside the unified SSSOM that
    should also be reflected in MIM.

    Returns (chemical_mappings_rows, special_chemical_mappings_rows).
    Both lists carry dict-shaped rows with at least `name` and `chebi`.
    """
    chem_path = KGM_METATRAITS_DIR / "chemical_mappings.tsv"
    special_path = KGM_METATRAITS_DIR / "special_chemical_mappings.tsv"

    def _load_sssom_shape(path):
        if not path.exists():
            return []
        out = []
        with path.open() as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < len(header):
                    parts += [""] * (len(header) - len(parts))
                row = dict(zip(header, parts))
                raw = (row.get("subject_label") or "").strip()
                name = raw.split(":", 1)[-1].strip() if ":" in raw else raw
                obj = (row.get("object_id") or "").strip()
                out.append({
                    "name": name,
                    "raw_subject_label": raw,
                    "chebi": obj,
                    "object_label": (row.get("object_label") or "").strip(),
                    "predicate": (row.get("predicate_id") or "").strip(),
                    "curator": (row.get("curator") or "").strip(),
                    "source_dataset": (row.get("source_dataset") or "").strip(),
                })
        return out

    def _load_special(path):
        if not path.exists():
            return []
        out = []
        with path.open() as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < len(header):
                    parts += [""] * (len(header) - len(parts))
                row = dict(zip(header, parts))
                out.append({
                    "name": (row.get("chemical_name") or "").strip(),
                    "trait_pattern": (row.get("trait_pattern") or "").strip(),
                    "chebi": (row.get("ontology_id") or "").strip(),
                    "object_label": (row.get("ontology_name") or "").strip(),
                    "category": (row.get("category") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                })
        return out

    return _load_sssom_shape(chem_path), _load_special(special_path)


def diff_metatraits_against_mim(rows: list[dict], mim_by_chebi: dict[str, list[dict]],
                                mim_label_index: dict[str, str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"IN_MIM_AGREE": [], "IN_MIM_DIVERGE": [], "MISSING_IN_MIM": []}
    for r in rows:
        chebi = r.get("chebi", "")
        name = (r.get("name") or "").lower().strip()
        if chebi in mim_by_chebi:
            out["IN_MIM_AGREE"].append(r)
            continue
        mim_chebi = mim_label_index.get(name, "")
        if mim_chebi and mim_chebi != chebi:
            r = dict(r)
            r["_mim_chebi"] = mim_chebi
            out["IN_MIM_DIVERGE"].append(r)
            continue
        out["MISSING_IN_MIM"].append(r)
    return out


def load_kgm_source_tags(mim_subject_source: dict[str, set[str]]) -> dict[str, int]:
    """Count distinct source tags across kg-microbe's residual `MIM:*` rows."""
    counts: Counter[str] = Counter()
    for tags in mim_subject_source.values():
        for tag in tags:
            counts[tag] += 1
    return dict(counts)


# ---------- diff ----------

_SYMMETRIC_PREDICATES = {"skos:exactMatch", "skos:closeMatch"}
_ASYMMETRIC_PREDICATES = {"skos:narrowMatch", "skos:broadMatch"}


def classify_row(mim_row: dict, kgm_idx: dict) -> tuple[str, str]:
    """Classify a single MIM SSSOM row against kg-microbe's unified SSSOM.

    See module docstring for class semantics.
    """
    sid = (mim_row.get("subject_id") or "").strip()
    obj = (mim_row.get("object_id") or "").strip()
    pred = (mim_row.get("predicate_id") or "").strip()

    if not obj:
        return "MIM_NO_OBJECT", "MIM row has empty object_id"

    # Asymmetric rows (skos:narrowMatch / broadMatch) are parent-of relations,
    # NOT identity/primary claims. The consolidator stores them in a separate
    # parent_relations list rather than as xrefs of the parent entity, so a
    # subject-level "is the parent CURIE among kg-microbe's xrefs of MIM:Foo?"
    # check would (correctly) say no — but that's not a divergence, it's the
    # expected design. Classify these on object presence: if kg-microbe knows
    # the parent ontology term at all, the asymmetric relation propagates
    # implicitly via xref/synonym propagation on that term.
    if pred in _ASYMMETRIC_PREDICATES:
        if obj in kgm_idx["all_objects"]:
            return "IN_SYNC", (
                f"asymmetric ({pred}); parent object_id present in kg-microbe"
            )
        return "OBJECT_NOT_IN_KGM", (
            f"asymmetric ({pred}); parent object absent from kg-microbe SSSOM"
        )

    # Symmetric rows: prefer subject-level diagnosis when MIM:* is preserved
    # as a subject in kg-microbe. Post-2026-05-04 consolidator fix, almost
    # every MIM:* subject is preserved (xrefs of the canonical entity).
    mim_subject_rows = kgm_idx["mim_subject_rows"]
    if pred in _SYMMETRIC_PREDICATES and sid in mim_subject_rows:
        kgm_objs = {(r.get("object_id") or "").strip() for r in mim_subject_rows[sid]}
        if obj in kgm_objs:
            return "IN_SYNC_SUBJECT_PRESERVED", "kg-microbe preserves MIM:* subject; objects match"
        kgm_objs_disp = ", ".join(sorted(o for o in kgm_objs if o)) or "(none)"
        return "DIVERGED_OBJECT", f"MIM={obj}; kg-microbe={{{kgm_objs_disp}}}"

    # Registry rows — MIM-internal pairing of subject ↔ kgmicrobe.* identity CURIE.
    # In kg-microbe's data model, kgmicrobe.* CURIEs are canonical entity *objects*
    # (subjects of canonical_name + synonym rows via kgm.name:*). Treat the CURIE
    # as landed if it appears in either subject_id or object_id position.
    if obj.startswith("kgmicrobe."):
        if obj in kgm_idx["kgmicrobe_subjects"] or obj in kgm_idx["all_objects"]:
            return "REGISTRY_LANDED", "kgmicrobe.* CURIE materialised in kg-microbe"
        return "REGISTRY_NOT_LANDED", (
            "kgmicrobe.* CURIE not present in kg-microbe (consolidator hasn't synthesised "
            "an entity record — typical when MIM mints a registry CURIE without a CHEBI anchor)"
        )

    # Fallback object-level diagnosis — covers symmetric rows whose MIM:* subject
    # didn't land as a residual subject in kg-microbe (rare).
    if obj in kgm_idx["objects_with_mim"]:
        return "IN_SYNC", "object_id present in kg-microbe with mediaingredientmech source"
    if obj in kgm_idx["all_objects"]:
        return "PROVENANCE_LOST", (
            "object_id present in kg-microbe but no row tags mediaingredientmech_* "
            "— consolidator dropped MIM provenance, or hasn't re-run since MIM update"
        )
    return "OBJECT_NOT_IN_KGM", "object_id absent from kg-microbe SSSOM (true backlog)"


# ---------- report ----------

# Class display order + suggested action text, used to render the summary table.
CLASS_ROWS: list[tuple[str, str]] = [
    ("IN_SYNC",
     "None — consolidator absorbed MIM via xref propagation"),
    ("IN_SYNC_SUBJECT_PRESERVED",
     "None — residual MIM:* subject preserved as-is, agrees with MIM"),
    ("DIVERGED_OBJECT",
     "Investigate — MIM and consolidator disagree on canonical object"),
    ("PROVENANCE_LOST",
     "Rerun consolidator (or audit consolidator's source-merge logic)"),
    ("OBJECT_NOT_IN_KGM",
     "True backlog — consolidator hasn't ingested this object"),
    ("REGISTRY_LANDED",
     "None — kgmicrobe.* registry CURIE materialised in kg-microbe"),
    ("REGISTRY_NOT_LANDED",
     "Informational — registry CURIE awaiting a canonical anchor"),
    ("MIM_NO_OBJECT",
     "Curator-side — MIM row has no object_id"),
]


def render(
    classified: list[tuple[str, dict, str]],
    stale: list[dict],
    legacy: list[dict],
    kgm_source_tags: dict[str, int],
    mim_total: int,
    kgm_mim_subject_total: int,
    metatraits_chem: dict | None = None,
    metatraits_special: dict | None = None,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts: dict[str, int] = defaultdict(int)
    for cls, _, _ in classified:
        counts[cls] += 1

    out: list[str] = []
    out.append("# kg-microbe Review (SSSOM-first, chemical-mappings-mim-priority)\n")
    out.append(f"_Generated {now} by `scripts/generate_kg_microbe_review.py`._\n\n")
    out.append(
        "Row-level diff of MIM's published SSSOM vs kg-microbe's "
        "consolidated SSSOM (`kgmicrobe_unified_entity_mappings.sssom.tsv.gz`) "
        "on the `chemical-mappings-mim-priority` branch.\n\n"
    )
    out.append(
        "**Classification anchors on `object_id`**, not `subject_id`. "
        "kg-microbe's consolidator collapses `MIM:*` subjects into "
        "entity-anchored xref rows tagging `mediaingredientmech_*` in the "
        "`source` column; the previous subject-anchored classifier mis-reported "
        "such consolidations as missing.\n\n"
    )

    out.append("## Scope\n")
    rel_mim = MIM_SSSOM.relative_to(MIM_SSSOM.parents[3])
    out.append(f"- MIM published SSSOM: **{mim_total}** rows (`{rel_mim}`)\n")
    out.append(
        f"- kg-microbe consolidated SSSOM: residual **{kgm_mim_subject_total}** "
        "rows still keyed at a `MIM:*` subject; the rest collapsed into "
        "entity-anchored xrefs.\n"
    )
    out.append(f"- Legacy `MediaIngredientMech:*` subjects in kg-microbe SSSOM: **{len(legacy)}**\n\n")

    out.append("## Diff summary\n")
    out.append("| Class | Rows | Suggested action |\n|---|---:|---|\n")
    for cls, action in CLASS_ROWS:
        n = counts.get(cls, 0)
        if n == 0:
            continue
        out.append(f"| `{cls}` | {n} | {action} |\n")
    out.append(f"| `STALE_IN_KGM` | {len(stale)} | "
               "Rerun consolidator — MIM dropped these |\n")
    out.append(f"| `MIM_LEGACY_IN_KGM` | {len(legacy)} | "
               "Should be zero on chemical-mappings-mim-priority |\n")
    out.append("\n")

    out.append("## kg-microbe source tag distribution (residual `MIM:*` rows)\n")
    out.append(
        "Distinct subjects per source tag across the small set of `MIM:*` "
        "subjects that kg-microbe couldn't collapse via xref propagation. "
        "Sanity check that `mediaingredientmech_reviewed` dominates.\n\n"
    )
    out.append("| Source tag | Subjects |\n|---|---:|\n")
    for tag, n in sorted(kgm_source_tags.items(), key=lambda x: -x[1])[:15]:
        out.append(f"| `{tag}` | {n} |\n")
    out.append("\n")

    # Per-class sample tables — only for classes that flag something actionable.
    def sample(cls: str, limit: int = 25) -> None:
        rows = [(m, note) for c, m, note in classified if c == cls][:limit]
        if not rows:
            return
        out.append(f"## {cls} (showing {len(rows)} of {counts[cls]})\n\n")
        out.append("| MIM subject | MIM predicate | MIM object | Note |\n")
        out.append("|---|---|---|---|\n")
        for m, note in rows:
            out.append(
                f"| `{m.get('subject_id', '')}` | "
                f"`{m.get('predicate_id', '')}` | "
                f"`{m.get('object_id', '')}` — {m.get('object_label', '')} | "
                f"{note} |\n"
            )
        out.append("\n")

    sample("DIVERGED_OBJECT")
    sample("PROVENANCE_LOST")
    sample("OBJECT_NOT_IN_KGM")
    sample("REGISTRY_NOT_LANDED", limit=15)

    if stale:
        out.append(f"## STALE_IN_KGM (showing {min(20, len(stale))} of {len(stale)})\n\n")
        out.append("| kg-microbe MIM subject | kg-microbe object |\n|---|---|\n")
        for s in stale[:20]:
            out.append(
                f"| `{s['subject_id']}` | `{s.get('object_id', '')}` — "
                f"{s.get('object_label', '')} |\n"
            )
        out.append("\n")

    if legacy:
        out.append(f"## MIM_LEGACY_IN_KGM (showing {min(10, len(legacy))} of {len(legacy)})\n\n")
        out.append(
            "Any `MediaIngredientMech:<id>` subject in kg-microbe's SSSOM "
            "should have been rewritten to `MIM:<slug>` on this branch. "
            "Remaining rows indicate the consolidator needs another pass.\n\n"
        )
        out.append("| kg-microbe subject | kg-microbe object |\n|---|---|\n")
        for l in legacy[:10]:
            out.append(
                f"| `{l['subject_id']}` | `{l.get('object_id', '')}` — "
                f"{l.get('object_label', '')} |\n"
            )
        out.append("\n")

    # Metatraits chemical mappings comparison
    if metatraits_chem is not None or metatraits_special is not None:
        out.append("## Metatraits chemical mappings (out-of-SSSOM)\n")
        out.append(
            "Coverage check for kg-microbe's `kg_microbe/transform_utils/"
            "metatraits/mappings/chemical_mappings.tsv` (trait → CHEBI for "
            "carbon/nitrogen substrates) and `special_chemical_mappings.tsv` "
            "(trait_pattern → ontology). These are chemistry-relevant "
            "mappings that live outside the unified SSSOM and should also "
            "be reflected in MIM.\n\n",
        )
        out.append("| File | Total | IN_MIM_AGREE | IN_MIM_DIVERGE | MISSING_IN_MIM |\n")
        out.append("|---|---:|---:|---:|---:|\n")
        if metatraits_chem is not None:
            t = sum(len(v) for v in metatraits_chem.values())
            out.append(
                f"| `chemical_mappings.tsv` | {t} | "
                f"{len(metatraits_chem.get('IN_MIM_AGREE', []))} | "
                f"{len(metatraits_chem.get('IN_MIM_DIVERGE', []))} | "
                f"{len(metatraits_chem.get('MISSING_IN_MIM', []))} |\n"
            )
        if metatraits_special is not None:
            t = sum(len(v) for v in metatraits_special.values())
            out.append(
                f"| `special_chemical_mappings.tsv` | {t} | "
                f"{len(metatraits_special.get('IN_MIM_AGREE', []))} | "
                f"{len(metatraits_special.get('IN_MIM_DIVERGE', []))} | "
                f"{len(metatraits_special.get('MISSING_IN_MIM', []))} |\n"
            )
        out.append("\n")
        for label, diff in (("chemical_mappings", metatraits_chem),
                            ("special_chemical_mappings", metatraits_special)):
            if diff is None:
                continue
            divs = diff.get("IN_MIM_DIVERGE", [])
            miss = diff.get("MISSING_IN_MIM", [])
            if divs:
                out.append(f"### {label} — DIVERGE ({len(divs)} rows)\n")
                out.append("| Name | kg-microbe CHEBI | MIM CHEBI |\n|---|---|---|\n")
                for r in divs[:10]:
                    out.append(
                        f"| {r.get('name', '')} | `{r.get('chebi', '')}` | "
                        f"`{r.get('_mim_chebi', '')}` |\n"
                    )
                out.append("\n")
            if miss:
                out.append(f"### {label} — MISSING_IN_MIM (first 10 of {len(miss)})\n")
                out.append("| Name | kg-microbe CHEBI | Source |\n|---|---|---|\n")
                for r in miss[:10]:
                    out.append(
                        f"| {r.get('name', '')} | `{r.get('chebi', '')}` | "
                        f"{label} |\n"
                    )
                out.append("\n")
        out.append(
            "**Out-of-scope (no chemistry overlap with MIM):** "
            "`enzyme_mappings.tsv`, `enzyme_name_to_go.tsv`, "
            "`pathway_mappings.tsv`, `phenotype_mappings.tsv`, "
            "`metpo_alias_mappings.tsv`. Not reviewed.\n\n"
        )

    out.append("## Recommended contribution scope\n")
    actionable = (
        counts.get("DIVERGED_OBJECT", 0)
        + counts.get("PROVENANCE_LOST", 0)
        + counts.get("OBJECT_NOT_IN_KGM", 0)
    )
    if actionable == 0 and len(stale) == 0 and len(legacy) == 0:
        out.append(
            "kg-microbe is fully in sync with MIM at the object-anchor level — "
            "no actionable backlog. Recurring tasks remain:\n\n"
        )
    else:
        out.append("Based on this diff, the actionable items are:\n\n")
        if counts.get("OBJECT_NOT_IN_KGM", 0):
            out.append(
                f"1. **Rerun kg-microbe consolidator** to absorb the "
                f"{counts['OBJECT_NOT_IN_KGM']} `OBJECT_NOT_IN_KGM` rows.\n"
            )
        if counts.get("PROVENANCE_LOST", 0):
            out.append(
                f"2. **Audit consolidator source-merge** — {counts['PROVENANCE_LOST']} "
                "rows where kg-microbe has the canonical object but no "
                "`mediaingredientmech_*` source tag. Either the consolidator "
                "stripped MIM provenance during a merge, or it hasn't re-run "
                "since the MIM SSSOM was published.\n"
            )
        if counts.get("DIVERGED_OBJECT", 0):
            out.append(
                f"3. **Reconcile {counts['DIVERGED_OBJECT']} `DIVERGED_OBJECT` rows** — "
                "MIM and the consolidator disagree on which canonical entity "
                "the MIM subject should resolve to. Typical: MICRO vs FOODON, "
                "minted `kgmicrobe.ingredient:*` vs ENVO parent.\n"
            )
        if len(stale):
            out.append(
                f"4. **Drop {len(stale)} STALE_IN_KGM rows** — MIM no longer "
                "publishes these subjects; consolidator carries them stale.\n"
            )
        if len(legacy):
            out.append(
                f"5. **Drop {len(legacy)} `MediaIngredientMech:*` legacy rows** — "
                "should be zero after the namespace migration.\n"
            )
    out.append(
        "- **Surface MIM curator provenance** — MIM SSSOM's `source` column "
        "embeds `MIM:curator=<name>` tags that flatten to "
        "`mediaingredientmech_reviewed[curator=...]` in kg-microbe; the "
        "distribution table above is a sanity check on that propagation.\n"
    )
    out.append(
        "- **Accept `complex_ingredients.tsv.gz`** — the FOODON/ENVO "
        "companion artifact covering rows that the CHEBI-scoped review "
        "would otherwise treat as `MIM_ONLY_NON_CHEBI` (now folded into "
        "`IN_SYNC` since the consolidator already absorbs them).\n"
    )
    out.append("\n---\n\n_Review complete._\n")

    return "".join(out)


# ---------- main ----------

def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    print(f"[1/4] Loading MIM SSSOM from {MIM_SSSOM}")
    mim_rows = load_mim()
    print(f"      {len(mim_rows)} rows (no dedup; multi-row subjects preserved)")

    print(f"[2/4] Building kg-microbe indexes from {KGM_SSSOM_GZ.name}")
    kgm_idx = load_kgm_indexes()
    print(
        f"      objects_with_mim={len(kgm_idx['objects_with_mim'])} "
        f"all_objects={len(kgm_idx['all_objects'])} "
        f"residual MIM:* subjects={len(kgm_idx['mim_subject_rows'])} "
        f"kgmicrobe.* subjects={len(kgm_idx['kgmicrobe_subjects'])} "
        f"legacy={len(kgm_idx['legacy_rows'])}"
    )
    kgm_source_tags = load_kgm_source_tags(kgm_idx["mim_subject_source"])

    print("[2b/4] Loading metatraits chemical mappings")
    chem_rows, special_rows = load_metatraits_chemical()
    print(f"      chemical_mappings.tsv: {len(chem_rows)} rows")
    print(f"      special_chemical_mappings.tsv: {len(special_rows)} rows")

    # Build label → CHEBI index for metatraits diverge detection.
    mim_label_index: dict[str, str] = {}
    for r in mim_rows:
        sl = (r.get("subject_label") or "").lower().strip()
        ol = (r.get("object_label") or "").lower().strip()
        ch = r.get("object_id", "")
        if sl and ch:
            mim_label_index.setdefault(sl, ch)
        if ol and ch:
            mim_label_index.setdefault(ol, ch)
    mim_by_chebi = defaultdict(list)
    for r in mim_rows:
        obj = r.get("object_id", "")
        if obj:
            mim_by_chebi[obj].append(r)
    chem_diff = diff_metatraits_against_mim(chem_rows, mim_by_chebi, mim_label_index)
    special_diff = diff_metatraits_against_mim(special_rows, mim_by_chebi, mim_label_index)
    print(
        f"      chemical_mappings: AGREE={len(chem_diff['IN_MIM_AGREE'])} "
        f"DIVERGE={len(chem_diff['IN_MIM_DIVERGE'])} "
        f"MISSING={len(chem_diff['MISSING_IN_MIM'])}"
    )
    print(
        f"      special_chemical_mappings: AGREE={len(special_diff['IN_MIM_AGREE'])} "
        f"DIVERGE={len(special_diff['IN_MIM_DIVERGE'])} "
        f"MISSING={len(special_diff['MISSING_IN_MIM'])}"
    )

    print("[3/4] Classifying each MIM row")
    classified: list[tuple[str, dict, str]] = []
    for row in mim_rows:
        cls, note = classify_row(row, kgm_idx)
        classified.append((cls, row, note))

    # STALE: residual MIM:* subjects in kg-microbe whose subject is not in MIM's current SSSOM.
    mim_subject_set = {r.get("subject_id", "") for r in mim_rows if r.get("subject_id")}
    stale = [
        r for sid, rows in kgm_idx["mim_subject_rows"].items()
        if sid not in mim_subject_set
        for r in rows
    ]

    print("[4/4] Writing report")
    report = render(
        classified,
        stale,
        kgm_idx["legacy_rows"],
        kgm_source_tags,
        mim_total=len(mim_rows),
        kgm_mim_subject_total=len(kgm_idx["mim_subject_rows"]),
        metatraits_chem=chem_diff,
        metatraits_special=special_diff,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(report)
    print(f"Wrote {OUT}")

    counter = Counter(x[0] for x in classified)
    print(f"\nDiff classes: {dict(counter)}")
    print(f"STALE_IN_KGM: {len(stale)}  MIM_LEGACY_IN_KGM: {len(kgm_idx['legacy_rows'])}")


if __name__ == "__main__":
    main()
