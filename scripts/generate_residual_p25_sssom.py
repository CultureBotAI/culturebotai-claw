"""
Emit an SSSOM TSV covering the 303 residual P2.5 findings (those that
survived TRUE_BUG round-trip and live in the CONSIDER_SPECIFIC /
ENRICH_SYNONYM / SYMMETRIC categories).

Each row expresses the *recommended* mapping from a MIM ingredient record
to a CHEBI term, choosing the most-specific CHEBI available:

  CONSIDER_SPECIFIC -> kg-microbe's CHEBI (more specific hydrate/stereo form)
  ENRICH_SYNONYM    -> MIM's CHEBI (already correct; kg-microbe is an alt label)
  SYMMETRIC         -> MIM's CHEBI (both sides defensible; MIM's wins)

The *alternate* label (the one not chosen as object_label) is carried in a
pipe-separated `other` column together with the raw kg-microbe surface
form, so downstream consumers can pick up both forms as synonyms.

Output files:
  workspace/reports/residual_p25_mappings.sssom.tsv
  workspace/reports/residual_p25_mappings.sssom.yaml   (curie_map + metadata)

Validation:
  python -m sssom.cli validate workspace/reports/residual_p25_mappings.sssom.tsv
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import yaml

from kgm_unified_mappings import load_kgm_source_index

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
KGM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe"
)
REPORT_DIR = CLAW_ROOT / "workspace" / "reports"
CATEGORIZED_JSON = REPORT_DIR / "kg_microbe_residual_p25_categorized.json"
OUT_TSV = REPORT_DIR / "residual_p25_mappings.sssom.tsv"

MIM_INGREDIENTS_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"
KGM_UNIFIED_TSV = KGM_ROOT / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"

MAPPING_SET_ID = "https://w3id.org/sssom/mappings/culturebotai_residual_p25"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"

# SSSOM 1.0 mapping-justification CURIEs (semapv vocabulary).
JUST_MANUAL = "semapv:ManualMappingCuration"
JUST_LEXICAL = "semapv:LexicalMatching"


def _pipe(alts: list[str], drop: set[str]) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for a in alts:
        a = (a or "").strip()
        if not a:
            continue
        key = a.lower()
        if key in drop or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return "|".join(out)


def _load_kgm_source_index() -> dict[str, str]:
    """CHEBI ID -> pipe-separated kg-microbe `sources` string.

    Reads kg-microbe/mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz,
    whose `source` column lists every upstream pipeline that contributed the
    CHEBI (chebi_xrefs, mediadive_compounds, bacdive_metabolites,
    primary_mappings[kegg_compound], culturebotai_reviewed, …).
    """
    if not KGM_UNIFIED_TSV.exists():
        return {}
    return load_kgm_source_index(KGM_UNIFIED_TSV)


def _load_mim_evidence(source_file: str) -> tuple[str, str]:
    """Return (evidence_sources, last_curator) for a MIM ingredient YAML.

    evidence_sources is pipe-separated (e.g. "CultureMech|manual curation").
    last_curator is the most recent `curation_history[].curator` (proxy for
    which automated pipeline or human last touched the mapping).
    """
    path = MIM_INGREDIENTS_DIR / source_file
    if not path.exists():
        return "", ""
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return "", ""
    srcs: list[str] = []
    for ev in (data.get("ontology_mapping") or {}).get("evidence") or []:
        s = (ev.get("source") or "").strip()
        if s and s not in srcs:
            srcs.append(s)
    history = data.get("curation_history") or []
    last_curator = ""
    if history:
        # last entry by list order; histories are append-only
        last_curator = (history[-1].get("curator") or "").strip()
    return "|".join(srcs), last_curator


def _mim_curie(source_file: str) -> str:
    """Turn an MIM YAML filename into a stable local CURIE.

    `Ca_No32.yaml`  -> `MIM:Ca_No32`
    `L-cysteine-hcl_X_H2o_2.yaml` -> `MIM:L-cysteine-hcl_X_H2o_2`
    Non-URL-safe characters are conservatively percent-style encoded so
    the resulting CURIE round-trips through SSSOM's prefix expansion."""
    stem = Path(source_file).stem
    # Keep alphanumerics, underscore, dash, period; replace others with ~hex
    safe = re.sub(
        r"[^A-Za-z0-9_\-.]",
        lambda m: f"~{ord(m.group(0)):02X}",
        stem,
    )
    return f"MIM:{safe}"


def _choose_object(dec: dict) -> tuple[str, str, str, str]:
    """Return (object_id, object_label, other_labels, mapping_justification)."""
    cat = dec["category"]
    mim_chebi = dec["mim_chebi"]
    mim_label = dec["mim_label"] or ""
    kgm_chebi = dec["kg_microbe_chebi"] or ""
    kgm_label = dec["kg_microbe_label"] or ""

    if cat == "CONSIDER_SPECIFIC" and kgm_chebi.startswith("CHEBI:"):
        object_id = kgm_chebi
        object_label = kgm_label
        # Carry the MIM-side generic label as the alternate
        other = _pipe([mim_label], drop={object_label.lower()})
        just = JUST_MANUAL  # discretionary choice, manual curation
    else:
        # ENRICH_SYNONYM and SYMMETRIC keep MIM's CHEBI
        object_id = mim_chebi
        object_label = mim_label
        other = _pipe([kgm_label], drop={object_label.lower()})
        just = JUST_LEXICAL
    return object_id, object_label, other, just


HEADER_YAML = f"""\
# curie_map:
#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"
#   MIM: "https://github.com/CultureBotAI/MediaIngredientMech/blob/main/data/ingredients/mapped/"
#   obo: "http://purl.obolibrary.org/obo/"
#   semapv: "https://w3id.org/semapv/vocab/"
#   skos: "http://www.w3.org/2004/02/skos/core#"
#   orcid: "https://orcid.org/"
#   cbclaw: "https://github.com/culturebotai/culturebotai-claw/blob/main/"
# license: "{LICENSE}"
# mapping_set_id: "{MAPPING_SET_ID}"
# mapping_set_version: "2026-04-18"
# mapping_set_description: "Residual P2.5 MIM→CHEBI mappings after TRUE_BUG round-trip cleared 72/72 to MIM_OK. Each row is the recommended most-specific CHEBI for a MIM ingredient; alternate labels from the other side live in the `other` column so downstream consumers can adopt them as synonyms."
# mapping_date: "2026-04-18"
# creator_id:
#   - "orcid:0000-0001-8175-045X"
# subject_source: "MIM:ingredients"
# object_source: "obo:chebi.owl"
# extension_definitions:
#   - slot_name: source
#     property: "cbclaw:provenance-source"
#     type_hint: "xsd:string"
"""

COLUMNS = [
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "source",
    "mapping_date",
    "confidence",
    "comment",
    "other",
]


def _join_sources(mim_ev: str, kgm_src: str, last_curator: str) -> str:
    """Pipe-separated MIM- and kg-microbe-side origins for this mapping.

    MIM side is prefixed `MIM:` and kg-microbe side is prefixed `kgm:` so
    downstream consumers can tell which repo attested which origin without
    CURIE collision."""
    parts: list[str] = []
    for s in filter(None, (p.strip() for p in mim_ev.split("|"))):
        parts.append(f"MIM:{s}")
    if last_curator:
        parts.append(f"MIM:curator={last_curator}")
    for s in filter(None, (p.strip() for p in kgm_src.split("|"))):
        parts.append(f"kgm:{s}")
    return "|".join(parts)


def main():
    data = json.loads(CATEGORIZED_JSON.read_text())
    decisions = data["decisions"]
    kgm_sources = _load_kgm_source_index()

    rows: list[dict] = []
    for d in decisions:
        subject_id = _mim_curie(d["source_file"])
        subject_label = d["preferred_term"] or d["mim_label"]

        object_id, object_label, other, just = _choose_object(d)
        if not object_id.startswith("CHEBI:"):
            continue  # skip rows with no usable CHEBI

        mim_ev, last_curator = _load_mim_evidence(d["source_file"])
        kgm_src = kgm_sources.get(object_id, "")
        source = _join_sources(mim_ev, kgm_src, last_curator)

        # SSSOM `other` is the spec-blessed place for alternate labels
        # that aren't the chosen object_label — this is what downstream
        # consumers should read as the "synonym" list for this mapping.
        rows.append(
            {
                "subject_id": subject_id,
                "subject_label": subject_label,
                "predicate_id": "skos:exactMatch",
                "object_id": object_id,
                "object_label": object_label,
                "mapping_justification": just,
                "source": source,
                "mapping_date": "2026-04-18",
                "confidence": "0.9" if d["category"] != "SYMMETRIC" else "0.8",
                "comment": f"{d['category']}: {d['rationale']}",
                "other": other,
            }
        )

    # Dedup: (subject_id, object_id) — SSSOM frowns on exact dupes
    seen: set[tuple[str, str]] = set()
    uniq = []
    for r in rows:
        key = (r["subject_id"], r["object_id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w") as f:
        f.write(HEADER_YAML)
        f.write("\t".join(COLUMNS) + "\n")
        for r in uniq:
            f.write("\t".join(str(r[c]) for c in COLUMNS) + "\n")

    print(f"Wrote {len(uniq)} SSSOM rows to {OUT_TSV}")
    print(
        f"Dedup removed {len(rows) - len(uniq)} (subject_id, object_id) collisions."
    )


if __name__ == "__main__":
    main()
