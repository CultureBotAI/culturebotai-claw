#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Generate workspace/reports/kg_microbe_review.md — a row-level diff
of MIM's published SSSOM against kg-microbe's SSSOM-first consolidated
artifact on the chemical-mappings-mim-priority branch.

Output classifies every MIM subject_id into one of:
  IN_SYNC              both sides agree on (CHEBI, object_label)
  CHEBI_DIVERGED       kg-microbe has MIM's subject but different CHEBI
  LABEL_DRIFTED        same CHEBI, different object_label
  MISSING_IN_KGM       MIM publishes it; kg-microbe doesn't have it
  MIM_ONLY_NON_CHEBI   MIM row maps to FOODON/ENVO (covered by complex_ingredients)

Also scans kg-microbe's SSSOM for:
  STALE_IN_KGM         MIM:* subjects in kg-microbe that MIM no longer publishes
  MIM_LEGACY_IN_KGM    any MediaIngredientMech:* subjects remaining

The report is designed for sharing with a kg-microbe reviewer and
for deriving the PR scope for chemical-mappings-mim-priority.
"""

from __future__ import annotations

import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---------- paths ----------

MIM_SSSOM = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv"
)
KGM_SSSOM_GZ = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "kg-microbe/mappings/unified_ingredient_mappings.sssom.tsv.gz"
)
KGM_LEGACY_TSV_GZ = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "kg-microbe/mappings/unified_chemical_mappings.tsv.gz"
)
OUT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "culturebotai-claw/workspace/reports/kg_microbe_review.md"
)


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


def load_mim() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with MIM_SSSOM.open() as f:
        for _, row in _parse_sssom_header_and_rows(f):
            out[row["subject_id"]] = row
    return out


def load_kgm_mim_rows() -> tuple[dict[str, dict], list[dict]]:
    """Return ({mim_subject_id -> row}, [legacy_media_rows])."""
    mim_rows: dict[str, dict] = {}
    legacy: list[dict] = []
    with gzip.open(KGM_SSSOM_GZ, "rt", encoding="utf-8") as f:
        for _, row in _parse_sssom_header_and_rows(f):
            sid = row.get("subject_id", "")
            if sid.startswith("MIM:"):
                # Multiple rows may share a MIM: subject (xrefs, lexical,
                # etc.). Keep the one whose predicate is exactMatch.
                prior = mim_rows.get(sid)
                if prior is None:
                    mim_rows[sid] = row
                elif (prior.get("predicate_id") != "skos:exactMatch"
                      and row.get("predicate_id") == "skos:exactMatch"):
                    mim_rows[sid] = row
            elif sid.startswith("MediaIngredientMech:"):
                legacy.append(row)
    return mim_rows, legacy


def load_kgm_source_tags(kgm_mim_rows: dict[str, dict]) -> dict[str, int]:
    """Count frequency of each `source` tag across kg-microbe's MIM: rows."""
    counts: dict[str, int] = defaultdict(int)
    for row in kgm_mim_rows.values():
        for tag in (row.get("source", "") or "").split("|"):
            tag = tag.strip()
            if tag:
                counts[tag] += 1
    return counts


# ---------- diff ----------

def _expected_labels_for_chebi(mim_rows: list[dict]) -> set[str]:
    """All labels kg-microbe's canonical_name legitimately could be for a CHEBI.

    Multiple MIM subjects can share a CHEBI (e.g. MIM:Alcl3 narrowMatch +
    MIM:Alcl3_X_6_H2o exactMatch both → CHEBI:30115). kg-microbe emits
    one canonical per CHEBI; ANY of the contributing MIM rows' expected
    canonical is a valid match — the consolidator picks one deterministically.
    """
    out: set[str] = set()
    for row in mim_rows:
        predicate = row.get("predicate_id", "")
        subj = (row.get("subject_label") or "").strip()
        obj = (row.get("object_label") or "").strip()
        if predicate in ("skos:exactMatch", "skos:closeMatch"):
            if subj:
                out.add(subj.lower())
        elif predicate in ("skos:narrowMatch", "skos:broadMatch"):
            if obj:
                out.add(obj.lower())
        # Fall back: accept either side so unclassified-predicate rows
        # don't produce spurious drift.
        if subj:
            out.add(subj.lower())
        if obj:
            out.add(obj.lower())
    return out


def classify(
    mim_row: dict,
    kgm_row: dict | None,
    mim_rows_by_chebi: dict[str, list[dict]],
) -> tuple[str, str]:
    """Return (class, note)."""
    if kgm_row is None:
        if not mim_row.get("object_id", "").startswith("CHEBI:"):
            return "MIM_ONLY_NON_CHEBI", (
                f"maps to {mim_row.get('object_source', '?')} "
                "(covered by complex_ingredients.tsv.gz)"
            )
        return "MISSING_IN_KGM", (
            f"kg-microbe SSSOM has no MIM:{mim_row['subject_id'].split(':', 1)[1]} row"
        )

    mim_obj = mim_row.get("object_id", "")
    kgm_obj = kgm_row.get("object_id", "")
    if mim_obj and kgm_obj and mim_obj != kgm_obj:
        return "CHEBI_DIVERGED", (
            f"MIM object_id={mim_obj}, kg-microbe object_id={kgm_obj}"
        )

    kgm_lbl = (kgm_row.get("object_label") or "").strip()
    if not mim_obj:
        return "IN_SYNC", ""

    # Expected label set = every label MIM asserts for this CHEBI across
    # ALL MIM rows sharing the CHEBI. This avoids spurious drift when
    # MIM has multiple subjects (hydrate variant + anhydrous, etc.)
    # mapping to the same CHEBI.
    expected_set = _expected_labels_for_chebi(mim_rows_by_chebi.get(mim_obj, []))
    if kgm_lbl and kgm_lbl.lower() in expected_set:
        return "IN_SYNC", ""
    if kgm_lbl and expected_set:
        sample = ", ".join(f"'{e}'" for e in sorted(expected_set)[:3])
        return "LABEL_DRIFTED", (
            f"kg-microbe has '{kgm_lbl}'; MIM's candidates for {mim_obj} "
            f"are {{{sample}{'...' if len(expected_set) > 3 else ''}}}"
        )
    if not kgm_lbl and expected_set:
        return "LABEL_DRIFTED", (
            f"kg-microbe has no object_label; MIM has candidates for {mim_obj}"
        )
    return "IN_SYNC", ""


# ---------- report ----------

def render(
    classified: list[tuple[str, dict, dict | None, str]],
    stale: list[dict],
    legacy: list[dict],
    kgm_source_tags: dict[str, int],
    mim_total: int,
    kgm_mim_total: int,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts: dict[str, int] = defaultdict(int)
    for cls, _, _, _ in classified:
        counts[cls] += 1

    out = [
        "# kg-microbe Review (SSSOM-first, chemical-mappings-mim-priority)\n",
        f"_Generated {now} by `scripts/generate_kg_microbe_review.py`._\n\n",
        "Row-level diff of MIM's published SSSOM vs kg-microbe's "
        "consolidated SSSOM (`unified_ingredient_mappings.sssom.tsv.gz`) "
        "on the `chemical-mappings-mim-priority` branch.\n\n",
        "## Scope\n",
        f"- MIM published SSSOM: **{mim_total}** rows "
        f"(`{MIM_SSSOM.relative_to(MIM_SSSOM.parents[3])}`)\n",
        f"- kg-microbe consolidated SSSOM, `MIM:*` subjects only: "
        f"**{kgm_mim_total}** rows\n",
        f"- Legacy `MediaIngredientMech:*` subjects in kg-microbe "
        f"SSSOM: **{len(legacy)}**\n\n",
        "## Diff summary\n",
        "| Class | Rows | Suggested kg-microbe action |\n",
        "|---|---:|---|\n",
    ]
    for cls, action in [
        ("IN_SYNC", "None — consolidator will idempotently reproduce"),
        ("CHEBI_DIVERGED",
         "Rerun consolidator after refreshing MIM SSSOM input"),
        ("LABEL_DRIFTED",
         "Verify priority-11 `mediaingredientmech_reviewed` wins the name tiebreaker"),
        ("MISSING_IN_KGM", "Rerun consolidator — MIM SSSOM not picked up"),
        ("MIM_ONLY_NON_CHEBI",
         "Accept `complex_ingredients.tsv.gz` companion artifact"),
    ]:
        out.append(f"| `{cls}` | {counts.get(cls, 0)} | {action} |\n")
    out.append(f"| `STALE_IN_KGM` | {len(stale)} | "
               "Rerun consolidator — MIM dropped these |\n")
    out.append(f"| `MIM_LEGACY_IN_KGM` | {len(legacy)} | "
               "Should be zero after this branch merges |\n")
    out.append("\n")

    out.append("## kg-microbe source tag distribution (on `MIM:*` rows)\n")
    out.append("Sanity check that `mediaingredientmech_reviewed` "
               "dominates, as priority-11 intends.\n\n")
    out.append("| Source tag | Rows |\n|---|---:|\n")
    for tag, n in sorted(kgm_source_tags.items(), key=lambda x: -x[1])[:15]:
        out.append(f"| `{tag}` | {n} |\n")
    out.append("\n")

    # Per-class sample tables
    def sample(cls: str, limit: int = 25) -> None:
        rows = [(m, k, note) for c, m, k, note in classified
                if c == cls][:limit]
        if not rows:
            return
        out.append(f"## {cls} (showing {len(rows)} of {counts[cls]})\n\n")
        out.append("| MIM subject | MIM object | kg-microbe object | Note |\n")
        out.append("|---|---|---|---|\n")
        for m, k, note in rows:
            mim_obj = m.get("object_id", "")
            mim_lbl = m.get("object_label", "")
            if k:
                kgm_obj = k.get("object_id", "")
                kgm_lbl = k.get("object_label", "")
                kgm_str = f"`{kgm_obj}` — {kgm_lbl}" if kgm_obj else "_(row present, no obj)_"
            else:
                kgm_str = "_(missing)_"
            out.append(
                f"| `{m['subject_id']}` | `{mim_obj}` — {mim_lbl} | {kgm_str} | {note} |\n"
            )
        out.append("\n")

    sample("CHEBI_DIVERGED")
    sample("LABEL_DRIFTED")
    sample("MISSING_IN_KGM")
    sample("MIM_ONLY_NON_CHEBI")

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

    out.append("## Recommended contribution scope\n")
    out.append(
        "Based on this diff, candidate commits for the "
        "`chemical-mappings-mim-priority` branch:\n\n"
    )
    out.append(
        f"1. **Rerun consolidator** to absorb the {counts.get('MISSING_IN_KGM', 0)} "
        f"`MISSING_IN_KGM` + {counts.get('CHEBI_DIVERGED', 0)} `CHEBI_DIVERGED` "
        f"+ {len(stale)} `STALE_IN_KGM` rows and drop {len(legacy)} "
        f"`MIM_LEGACY_IN_KGM` rows.\n"
    )
    label_drift = counts.get("LABEL_DRIFTED", 0)
    if label_drift:
        out.append(
            f"2. **Priority-11 tiebreaker audit** — {label_drift} rows where "
            "kg-microbe's `object_label` differs from MIM's. If MIM is "
            "priority-11, its label should win; if it doesn't, the "
            "consolidator has a tiebreaker bug.\n"
        )
    out.append(
        "3. **Accept `complex_ingredients.tsv.gz`** — the FOODON/ENVO "
        "companion artifact covering the MIM_ONLY_NON_CHEBI rows.\n"
    )
    out.append(
        "4. **Surface MIM curator provenance** — MIM SSSOM's `source` "
        "column embeds `MIM:curator=<name>` tags that currently flatten "
        "to `mediaingredientmech_reviewed` in kg-microbe. A small "
        "consolidator enhancement could preserve the curator attribution.\n"
    )
    if counts.get("MIM_ONLY_NON_CHEBI", 0) > 0:
        out.append(
            "5. **Regression test fixtures** — the `MISSING_IN_KGM` and "
            "`STALE_IN_KGM` rows are useful as test inputs for the "
            "consolidator.\n"
        )
    out.append("\n---\n\n_Review complete._\n")

    return "".join(out)


# ---------- main ----------

def main() -> None:
    print(f"[1/4] Loading MIM SSSOM from {MIM_SSSOM}")
    mim = load_mim()
    print(f"      {len(mim)} rows")

    print(f"[2/4] Loading kg-microbe SSSOM from {KGM_SSSOM_GZ}")
    kgm_mim, legacy = load_kgm_mim_rows()
    print(f"      {len(kgm_mim)} MIM:* rows, {len(legacy)} legacy MediaIngredientMech:* rows")

    kgm_source_tags = load_kgm_source_tags(kgm_mim)

    print("[3/4] Classifying each MIM row")
    # Group MIM rows by object_id so we can accept any MIM-asserted label.
    mim_rows_by_chebi: dict[str, list[dict]] = defaultdict(list)
    for r in mim.values():
        obj = r.get("object_id", "")
        if obj:
            mim_rows_by_chebi[obj].append(r)

    classified: list[tuple[str, dict, dict | None, str]] = []
    for sid, mim_row in mim.items():
        kgm_row = kgm_mim.get(sid)
        cls, note = classify(mim_row, kgm_row, mim_rows_by_chebi)
        classified.append((cls, mim_row, kgm_row, note))

    # STALE: kg-microbe rows whose MIM subject is not in MIM's current SSSOM.
    stale = [row for sid, row in kgm_mim.items() if sid not in mim]

    print("[4/4] Writing report")
    report = render(classified, stale, legacy, kgm_source_tags,
                    mim_total=len(mim), kgm_mim_total=len(kgm_mim))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(report)
    print(f"Wrote {OUT}")

    from collections import Counter
    c = Counter(x[0] for x in classified)
    print(f"\nDiff classes: {dict(c)}")
    print(f"STALE_IN_KGM: {len(stale)}  MIM_LEGACY_IN_KGM: {len(legacy)}")


if __name__ == "__main__":
    main()
