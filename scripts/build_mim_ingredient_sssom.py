"""
Build the canonical MIM → ingredient-ontology SSSOM mapping file.

This is the authoritative cross-repo ingredient mapping artifact. Every
MediaIngredientMech record whose `ontology_mapping.ontology_id` starts
with a supported ingredient ontology prefix (CHEBI / FOODON; UBERON /
ENVO when populated) becomes one SSSOM row with:

  subject_id        MIM:<safe_stem>         -- stable per-YAML CURIE
  subject_label     preferred_term
  predicate_id      skos:exactMatch         -- default
                    skos:narrowMatch        -- MIM is more specific than CHEBI
                    skos:broadMatch         -- MIM is less specific than CHEBI
                    skos:closeMatch         -- SYMMETRIC (both defensible)
  object_id         <CHEBI|FOODON|...>:X
  object_label      canonical rdfs:label from OAK/OLS (fallback: MIM label)
  object_source     per-row ontology OWL URI (CHEBI/FOODON/... differ per row)
  mapping_justification  semapv:ManualMappingCuration | semapv:LexicalMatching
  source            MIM:<evidence>|MIM:curator=...|kgm:<sources>  (extension)
  mapping_date      YAML modification date (ISO, UTC)
  confidence        0.99 EXACT_MATCH / 0.9 CONSIDER_SPECIFIC / 0.8 SYMMETRIC
  comment           short human-readable rationale
  other             pipe-separated alternate labels (kg-microbe side, etc.)

Inputs (all read-only):
  MIM/data/ingredients/mapped/*.yaml
  kg-microbe/mappings/unified_chemical_mappings.tsv.gz   (CHEBI-only)
  workspace/reports/kg_microbe_residual_p25_categorized.json   (optional)
      — enriches predicate / confidence for the 303 triaged CHEBI cases

Outputs:
  workspace/reports/mim_ingredient_mappings.sssom.tsv
      — working copy, regenerated on every run
      — validated with `sssom validate` before being written

Use `just publish-sssom` to promote the working copy to
  MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv
after it passes `sssom validate` + `synonym-review`.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
KGM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe"
)

MIM_INGREDIENTS_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"
KGM_UNIFIED_TSV = KGM_ROOT / "mappings" / "unified_chemical_mappings.tsv.gz"
REPORT_DIR = CLAW_ROOT / "workspace" / "reports"
RESIDUAL_JSON = REPORT_DIR / "kg_microbe_residual_p25_categorized.json"
OUT_TSV = REPORT_DIR / "mim_ingredient_mappings.sssom.tsv"

MAPPING_SET_ID = "https://w3id.org/sssom/mappings/culturebotai_mim_ingredient"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"
SSSOM_BIN = "sssom"

# Ontologies we emit mappings for. Add a new prefix here and to
# `_OBJECT_SOURCE_BY_PREFIX` (and plug a label loader into main()) to extend
# coverage.
SUPPORTED_OBJECT_PREFIXES: tuple[str, ...] = ("CHEBI:", "FOODON:", "UBERON:", "ENVO:")
_OBJECT_SOURCE_BY_PREFIX: dict[str, str] = {
    "CHEBI:": "obo:chebi.owl",
    "FOODON:": "obo:foodon.owl",
    "UBERON:": "obo:uberon.owl",
    "ENVO:": "obo:envo.owl",
}

# Matches MIM's kg_microbe_dict.POLLUTION_SYNONYM_THRESHOLD. Any kg-microbe
# entry above this is contaminated by the upstream row-merge bug (CHEBI:86254
# was observed at 50,686 in the 2026-04 dump; legitimate entries cap around
# 250). We drop kg-microbe-side synonyms for polluted CHEBIs — the mapping
# itself is still valid.
POLLUTION_SYNONYM_THRESHOLD = 500
# Additional defensive cap on the `other` column to keep SSSOM rows parseable
# by downstream tools (pandas default csv field limit is 128 KiB).
MAX_OTHER_ENTRIES = 50

JUST_MANUAL = "semapv:ManualMappingCuration"
JUST_LEXICAL = "semapv:LexicalMatching"

_PREDICATE_BY_CATEGORY = {
    # Residual-P2.5 buckets → SKOS predicates.
    "CONSIDER_SPECIFIC": "skos:narrowMatch",  # we pick kg-microbe CHEBI which
                                              # is *narrower* than the MIM
                                              # generic → narrowMatch from the
                                              # MIM subject's perspective.
    "ENRICH_SYNONYM": "skos:exactMatch",
    "SYMMETRIC": "skos:closeMatch",
}
_CONFIDENCE_BY_CATEGORY = {
    "CONSIDER_SPECIFIC": "0.9",
    "ENRICH_SYNONYM": "0.95",
    "SYMMETRIC": "0.8",
}


def _mim_curie(source_file: str) -> str:
    """Stable local CURIE for a MIM ingredient YAML.

    `Ca_No32.yaml` → `MIM:Ca_No32`. Non-URL-safe characters are
    percent-style `~HEX`-encoded so the CURIE round-trips through SSSOM's
    prefix expansion."""
    stem = Path(source_file).stem
    safe = re.sub(
        r"[^A-Za-z0-9_\-.]",
        lambda m: f"~{ord(m.group(0)):02X}",
        stem,
    )
    return f"MIM:{safe}"


def _load_kgm_source_index() -> dict[str, str]:
    """CHEBI:X → pipe-separated kg-microbe `sources` string."""
    out: dict[str, str] = {}
    if not KGM_UNIFIED_TSV.exists():
        return out
    with gzip.open(KGM_UNIFIED_TSV, "rt") as f:
        header = f.readline().rstrip("\n").split("\t")
        try:
            id_col = header.index("id")
            src_col = header.index("sources")
        except ValueError:
            return out
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(id_col, src_col):
                continue
            cid = parts[id_col].strip()
            if cid.startswith("CHEBI:") and parts[src_col].strip():
                out[cid] = parts[src_col].strip()
    return out


def _load_kgm_labels() -> dict[str, tuple[str, list[str]]]:
    """CHEBI:X → (canonical_name, [synonyms...]) from kg-microbe."""
    out: dict[str, tuple[str, list[str]]] = {}
    if not KGM_UNIFIED_TSV.exists():
        return out
    with gzip.open(KGM_UNIFIED_TSV, "rt") as f:
        header = f.readline().rstrip("\n").split("\t")
        try:
            id_col = header.index("id")
            name_col = header.index("canonical_name")
            syn_col = header.index("synonyms")
        except ValueError:
            return out
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(id_col, name_col, syn_col):
                continue
            cid = parts[id_col].strip()
            if not cid.startswith("CHEBI:"):
                continue
            name = parts[name_col].strip()
            syns = [s for s in parts[syn_col].split("|") if s.strip()]
            if len(syns) > POLLUTION_SYNONYM_THRESHOLD:
                # Polluted entry — keep canonical_name, drop synonyms.
                syns = []
            out[cid] = (name, syns)
    return out


def _load_chebi_labels(chebi_ids: list[str], batch: int = 80) -> dict[str, str]:
    """CHEBI:X → rdfs:label from the local OAK sqlite. Batched so we
    don't pay cold-start overhead per term. Writes nothing if OAK isn't
    on PATH — the builder falls back to the MIM-stored ontology_label."""
    out: dict[str, str] = {}
    if not chebi_ids:
        return out
    try:
        for i in range(0, len(chebi_ids), batch):
            chunk = chebi_ids[i : i + batch]
            proc = subprocess.run(
                ["runoak", "-i", "sqlite:obo:chebi", "aliases"] + chunk,
                capture_output=True, text=True, timeout=300,
            )
            for line in proc.stdout.splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) >= 3 and parts[1] == "rdfs:label":
                    out[parts[0]] = parts[2]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return out


def _load_ols_labels(
    term_ids: list[str],
    ontology: str,
    iri_prefix: str,
) -> dict[str, str]:
    """Fetch rdfs:label via EBI OLS4 REST for ontologies without a local
    OAK sqlite (e.g. FOODON). `ontology` is the OLS ontology slug
    (\"foodon\"); `iri_prefix` is the OBO IRI stem (
    \"http://purl.obolibrary.org/obo/FOODON_\").

    Non-fatal — on any network error we return whatever we've resolved so
    far; the builder falls back to the MIM-stored ontology_label."""
    out: dict[str, str] = {}
    if not term_ids:
        return out
    try:
        import urllib.parse
        import urllib.request
    except ImportError:
        return out
    base = f"https://www.ebi.ac.uk/ols4/api/ontologies/{ontology}/terms"
    for curie in term_ids:
        try:
            local = curie.split(":", 1)[1]
        except IndexError:
            continue
        iri = iri_prefix + local
        double_encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
        url = f"{base}/{double_encoded}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        label = (payload.get("label") or "").strip()
        if label:
            out[curie] = label
    return out


def _load_residual_categorization() -> dict[str, dict]:
    """source_file → residual-P2.5 decision, for predicate upgrading."""
    if not RESIDUAL_JSON.exists():
        return {}
    data = json.loads(RESIDUAL_JSON.read_text())
    return {d["source_file"]: d for d in data.get("decisions", [])}


def _last_curator(history: list[dict]) -> str:
    if not history:
        return ""
    return (history[-1].get("curator") or "").strip()


def _mapping_date(path: Path, history: list[dict]) -> str:
    """Prefer the most recent curation_history timestamp; fall back to the
    filesystem mtime. Always emit `YYYY-MM-DD`."""
    if history:
        ts = history[-1].get("timestamp") or ""
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", ts)
        if m:
            return m.group(1)
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _pipe(labels: list[str], drop: set[str], max_entries: int | None = None) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for a in labels:
        a = (a or "").strip()
        if not a:
            continue
        key = a.lower()
        if key in drop or key in seen:
            continue
        seen.add(key)
        out.append(a)
        if max_entries is not None and len(out) >= max_entries:
            break
    return "|".join(out)


def _join_sources(mim_ev: list[str], last_curator: str, kgm_src: str) -> str:
    parts: list[str] = [f"MIM:{s}" for s in mim_ev if s]
    if last_curator:
        parts.append(f"MIM:curator={last_curator}")
    for s in filter(None, (p.strip() for p in kgm_src.split("|"))):
        parts.append(f"kgm:{s}")
    return "|".join(parts)


def _row_from_yaml(
    path: Path,
    residual: dict[str, dict],
    kgm_sources: dict[str, str],
    kgm_labels: dict[str, tuple[str, list[str]]],
    canonical_labels: dict[str, str],
) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return None

    ont = data.get("ontology_mapping") or {}
    obj_id = (ont.get("ontology_id") or "").strip()
    if not any(obj_id.startswith(p) for p in SUPPORTED_OBJECT_PREFIXES):
        return None
    is_chebi = obj_id.startswith("CHEBI:")

    preferred = (data.get("preferred_term") or "").strip()
    ont_label = (ont.get("ontology_label") or "").strip()
    quality = (ont.get("mapping_quality") or "").strip().upper()
    evidence = [
        (e.get("source") or "").strip()
        for e in (ont.get("evidence") or [])
        if (e.get("source") or "").strip()
    ]
    history = data.get("curation_history") or []

    # Default: exact match at high confidence
    predicate = "skos:exactMatch"
    justification = (
        JUST_LEXICAL
        if quality in {"EXACT_MATCH", "LEXICAL_MATCH", ""}
        else JUST_MANUAL
    )
    confidence = "0.99" if quality == "EXACT_MATCH" else "0.9"
    # Non-EXACT_MATCH quality (e.g. CLOSE_MATCH used by FOODON peptones)
    # earns a closeMatch predicate by default so downstream consumers
    # don't treat them as identity mappings.
    if quality and quality != "EXACT_MATCH":
        predicate = "skos:closeMatch"
    comment = ""

    # Residual-P2.5 override: the generator ran a specificity / symmetry
    # analysis for 303 records; use its decision when available. This is
    # where broad/narrow/closeMatch predicates come from. CHEBI-only — the
    # residual pipeline wasn't run for FOODON/UBERON/ENVO.
    src_file = path.name
    if is_chebi and src_file in residual:
        dec = residual[src_file]
        cat = dec.get("category")
        if cat == "CONSIDER_SPECIFIC":
            # Residual chose kg-microbe's more-specific CHEBI → object
            # becomes that CHEBI, not the MIM one.
            kgm_chebi = (dec.get("kg_microbe_chebi") or "").strip()
            kgm_label = (dec.get("kg_microbe_label") or "").strip()
            if kgm_chebi.startswith("CHEBI:"):
                obj_id = kgm_chebi
                ont_label = kgm_label or ont_label
        predicate = _PREDICATE_BY_CATEGORY.get(cat, predicate)
        confidence = _CONFIDENCE_BY_CATEGORY.get(cat, confidence)
        justification = JUST_MANUAL if cat == "CONSIDER_SPECIFIC" else JUST_LEXICAL
        comment = f"{cat}: {dec.get('rationale', '')}"

    # Prefer the ontology's canonical rdfs:label for object_label (SSSOM
    # best practice). Fall back to MIM's stored ontology_label if the
    # label loader didn't resolve. When we replace, keep MIM's stored
    # label in `other` so the surface form is preserved for downstream
    # tools.
    canonical_label = canonical_labels.get(obj_id, "")
    mim_stored_label = ont_label
    if canonical_label:
        ont_label = canonical_label

    # kg-microbe cross-source data is CHEBI-only.
    kgm_name, kgm_syns = kgm_labels.get(obj_id, ("", [])) if is_chebi else ("", [])
    kgm_src = kgm_sources.get(obj_id, "") if is_chebi else ""
    mim_yaml_syns = [
        (s.get("synonym_text") or "").strip()
        for s in (data.get("synonyms") or [])
        if isinstance(s, dict) and s.get("synonym_text")
    ]
    # `other` carries alternate surface forms that downstream consumers can
    # adopt as synonyms. Order: MIM's original ontology_label (preserved
    # when we replaced it with the canonical) → kg-microbe canonical →
    # kg-microbe synonyms → MIM's own EXACT_SYNONYMs. Drop the chosen
    # object_label and the preferred_term so we don't duplicate what's in
    # the dedicated columns.
    drop = {(preferred or "").lower(), (ont_label or "").lower(), ""}
    candidate_alts = [mim_stored_label] + [kgm_name] + kgm_syns + mim_yaml_syns
    # Filter MIM RAW_TEXT entries that encode roles/properties — those are
    # not chemical synonyms.
    candidate_alts = [
        a for a in candidate_alts
        if not re.match(r"^\s*(Role:|Cross-references:|Properties:)", a or "")
    ]
    other = _pipe(candidate_alts, drop=drop, max_entries=MAX_OTHER_ENTRIES)

    # Per-row object_source — SSSOM supports per-row override when the
    # mapping_set mixes ontologies.
    prefix = next(p for p in SUPPORTED_OBJECT_PREFIXES if obj_id.startswith(p))
    object_source = _OBJECT_SOURCE_BY_PREFIX.get(prefix, "")

    return {
        "subject_id": _mim_curie(src_file),
        "subject_label": preferred,
        "predicate_id": predicate,
        "object_id": obj_id,
        "object_label": ont_label,
        "object_source": object_source,
        "mapping_justification": justification,
        "source": _join_sources(evidence, _last_curator(history), kgm_src),
        "mapping_date": _mapping_date(path, history),
        "confidence": confidence,
        "comment": comment,
        "other": other,
    }


HEADER_YAML = f"""\
# curie_map:
#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"
#   FOODON: "http://purl.obolibrary.org/obo/FOODON_"
#   UBERON: "http://purl.obolibrary.org/obo/UBERON_"
#   ENVO: "http://purl.obolibrary.org/obo/ENVO_"
#   MIM: "https://github.com/KG-Hub/MediaIngredientMech/blob/main/data/ingredients/mapped/"
#   obo: "http://purl.obolibrary.org/obo/"
#   semapv: "https://w3id.org/semapv/vocab/"
#   skos: "http://www.w3.org/2004/02/skos/core#"
#   orcid: "https://orcid.org/"
#   cbclaw: "https://github.com/culturebotai/culturebotai-claw/blob/main/"
# license: "{LICENSE}"
# mapping_set_id: "{MAPPING_SET_ID}"
# mapping_set_version: "{{version}}"
# mapping_set_description: "Canonical MediaIngredientMech → ingredient-ontology mappings (CHEBI + FOODON; UBERON/ENVO when populated). One row per mapped MIM ingredient record. Per-row object_source distinguishes ontologies. Predicate is skos:exactMatch by default; narrowMatch/broadMatch/closeMatch where residual-P2.5 triage found a specificity or symmetry difference, or where mapping_quality != EXACT_MATCH. The `source` extension column records the upstream origin (MIM evidence + kg-microbe source pipeline, CHEBI only)."
# mapping_date: "{{version}}"
# creator_id:
#   - "orcid:0000-0001-8175-045X"
# subject_source: "MIM:ingredients"
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
    "object_source",
    "mapping_justification",
    "source",
    "mapping_date",
    "confidence",
    "comment",
    "other",
]


def _write_sssom(rows: list[dict], out_path: Path, version: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = HEADER_YAML.format(version=version)
    with out_path.open("w") as f:
        f.write(header)
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in COLUMNS) + "\n")


def _sssom_validate(path: Path) -> list[str]:
    """Run `sssom validate` and collect hard errors (ignores informational
    `No attr for ...` warnings that sssom-py emits for declared extensions)."""
    try:
        proc = subprocess.run(
            [
                SSSOM_BIN, "validate",
                "-V", "JsonSchema",
                "-V", "PrefixMapCompleteness",
                "-V", "StrictCurieFormat",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except FileNotFoundError:
        return [f"sssom CLI not on PATH; skipping validation"]
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    markers = ("is not well-formed", "is not a valid URI or CURIE", "must be supplied")
    return [ln.strip() for ln in combined.splitlines() if any(m in ln for m in markers)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=OUT_TSV)
    ap.add_argument("--no-validate", action="store_true", help="skip post-write sssom validate")
    args = ap.parse_args()

    residual = _load_residual_categorization()
    kgm_sources = _load_kgm_source_index()
    kgm_labels = _load_kgm_labels()

    yamls = sorted(MIM_INGREDIENTS_DIR.glob("*.yaml"))
    print(f"Scanning {len(yamls)} MIM ingredient YAMLs...", file=sys.stderr)

    # Group target term IDs by prefix so we can dispatch the right label
    # loader (OAK sqlite for CHEBI, OLS4 REST for FOODON, etc.). The
    # residual-P2.5 override can swap CHEBI to kg-microbe's more-specific
    # one, so include both sides when collecting CHEBIs.
    needed_by_prefix: dict[str, set[str]] = {p: set() for p in SUPPORTED_OBJECT_PREFIXES}
    for p in yamls:
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        cid = ((data.get("ontology_mapping") or {}).get("ontology_id") or "").strip()
        for pref in SUPPORTED_OBJECT_PREFIXES:
            if cid.startswith(pref):
                needed_by_prefix[pref].add(cid)
                break
        dec = residual.get(p.name)
        if dec and (dec.get("kg_microbe_chebi") or "").startswith("CHEBI:"):
            needed_by_prefix["CHEBI:"].add(dec["kg_microbe_chebi"])

    canonical_labels: dict[str, str] = {}
    for pref, ids in needed_by_prefix.items():
        if not ids:
            continue
        ids_sorted = sorted(ids)
        if pref == "CHEBI:":
            print(f"Fetching rdfs:labels for {len(ids_sorted)} CHEBI ids from OAK...", file=sys.stderr)
            resolved = _load_chebi_labels(ids_sorted)
            if not resolved:
                print("  (OAK unavailable — falling back to MIM-stored ontology_label)", file=sys.stderr)
            else:
                print(f"  resolved {len(resolved)} / {len(ids_sorted)}", file=sys.stderr)
            canonical_labels.update(resolved)
        elif pref in ("FOODON:", "UBERON:", "ENVO:"):
            ontology = pref.rstrip(":").lower()
            iri_prefix = f"http://purl.obolibrary.org/obo/{pref.rstrip(':')}_"
            print(f"Fetching rdfs:labels for {len(ids_sorted)} {pref.rstrip(':')} ids from OLS4...", file=sys.stderr)
            resolved = _load_ols_labels(
                ids_sorted,
                ontology=ontology,
                iri_prefix=iri_prefix,
            )
            print(f"  resolved {len(resolved)} / {len(ids_sorted)}", file=sys.stderr)
            canonical_labels.update(resolved)
        else:
            print(f"  (no label loader for {pref}; falling back to MIM-stored labels)", file=sys.stderr)

    rows: list[dict] = []
    skipped_unsupported = 0
    for p in yamls:
        row = _row_from_yaml(p, residual, kgm_sources, kgm_labels, canonical_labels)
        if row is None:
            skipped_unsupported += 1
            continue
        rows.append(row)

    # Dedup: MIM CURIEs are unique per YAML; but residual CONSIDER_SPECIFIC
    # can redirect object_id, and we still want one row per MIM subject, so
    # dedup on subject_id alone (keep the last).
    uniq: dict[str, dict] = {}
    for r in rows:
        uniq[r["subject_id"]] = r
    final = list(uniq.values())

    version = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    _write_sssom(final, args.output, version=version)

    print(f"Wrote {len(final)} rows to {args.output}", file=sys.stderr)
    print(
        f"  (skipped {skipped_unsupported} MIM records without a supported ontology_id "
        f"prefix: {', '.join(SUPPORTED_OBJECT_PREFIXES)})",
        file=sys.stderr,
    )

    # Predicate breakdown so we can see at a glance how many rows got
    # upgraded beyond skos:exactMatch by the residual pass.
    pred_counts: dict[str, int] = {}
    for r in final:
        pred_counts[r["predicate_id"]] = pred_counts.get(r["predicate_id"], 0) + 1
    print("Predicate breakdown:", file=sys.stderr)
    for p, n in sorted(pred_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {p:24s} {n}", file=sys.stderr)

    # Per-prefix row counts (CHEBI vs FOODON vs ...).
    pref_counts: dict[str, int] = {}
    for r in final:
        for pref in SUPPORTED_OBJECT_PREFIXES:
            if r["object_id"].startswith(pref):
                pref_counts[pref] = pref_counts.get(pref, 0) + 1
                break
    print("Object-prefix breakdown:", file=sys.stderr)
    for pref, n in sorted(pref_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {pref:10s} {n}", file=sys.stderr)

    if not args.no_validate:
        print(f"\nValidating {args.output.name}...", file=sys.stderr)
        errors = _sssom_validate(args.output)
        if errors:
            print("SSSOM validation FAILED:", file=sys.stderr)
            for e in errors[:20]:
                print(f"  - {e[:200]}", file=sys.stderr)
            sys.exit(2)
        print("  OK", file=sys.stderr)


if __name__ == "__main__":
    main()
