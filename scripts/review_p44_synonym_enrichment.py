"""
Review the 1,016 P4.4 enrichment candidates before any YAML edits.

For each P4.4 finding we emit a per-candidate decision:

  CLEAN_ADD    Candidate is novel, unambiguous (kg-microbe maps it to <=5
               CHEBI IDs globally), and passes the noise filter. Safe to
               propose as a new synonym on the MIM YAML.
  DUPLICATE    Candidate is already present on the MIM record (after
               normalization against preferred_term, ontology_label, and
               existing synonym_text entries).
  AMBIGUOUS    kg-microbe maps this surface form to too many CHEBI IDs
               (>5) — adding it as a synonym would contaminate the MIM
               dictionary the same way kg-microbe's own dictionary is
               contaminated.
  NOISE        Structured junk — CURIE-like, "Cross-references:" metadata,
               raw role/property dumps, charge-state-only variants, etc.

The classifier is deliberately conservative: anything it cannot confidently
label CLEAN_ADD falls to AMBIGUOUS or NOISE, which means "do not enrich
automatically."  A reviewer can still opt in manually from the AMBIGUOUS
bucket — that's the point of the review step.

Writes workspace/reports/kg_microbe_p44_enrichment_review.{json,md}.

No YAMLs are modified.  The separate apply script reads this review file
and only touches CLEAN_ADD candidates.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
REPORT_DIR = CLAW_ROOT / "workspace" / "reports"
INGREDIENTS_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"

sys.path.insert(0, str(MIM_ROOT / "src"))
from mediaingredientmech.validation.kg_microbe_dict import (  # noqa: E402
    AMBIGUITY_THRESHOLD,
    KgMicrobeDict,
)


# Patterns that mark a "candidate synonym" as junk rather than a chemical name
_CURIE_RE = re.compile(r"^[A-Z][A-Za-z0-9_.]*:[A-Za-z0-9_\-]+$")
_NOISE_SUBSTRINGS = (
    "cross-references:",
    "properties:",
    "role:",
    "synonym source:",
    "iupac:",
    "smiles:",
    "inchi=",
)
# Charge-only annotations like "foo(1-)" or "foo(2+)" — kg-microbe dumps these
# as separate synonyms but the MIM side already has the neutral form
_CHARGE_ONLY_RE = re.compile(r"\([0-9]*[+\-]\)\s*$")

# Hydrate markers — if one side has a hydrate counter and the other doesn't,
# the pair must NOT be merged. Anhydrous CHEBI:29101 is not the same compound
# as trihydrate CHEBI:32959 even though both are called "sodium acetate."
_HYDRATE_RE = re.compile(
    r"(·|・|⋅|\s*x\s*|\s*\.\s*)\s*\d*\s*h2o|"
    r"\b(mono|di|tri|tetra|penta|hexa|hepta)?hydrate\b|"
    r"\banhydrous\b",
    re.IGNORECASE,
)


def _has_hydrate_marker(s: str) -> bool:
    return bool(_HYDRATE_RE.search(s or ""))


def _normalize(s: str) -> str:
    """Lowercase, collapse whitespace, drop surrounding punctuation.

    We deliberately do NOT strip hyphens, digits, greek letters, or
    stereochem prefixes — those are part of chemical identity. The only
    job of this normalizer is to decide 'is this the same literal string
    the YAML already carries'."""
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _existing_surface_forms(yaml_doc: dict) -> set[str]:
    """All strings on the YAML that a new synonym would duplicate."""
    forms: set[str] = set()
    if pt := yaml_doc.get("preferred_term"):
        forms.add(_normalize(pt))
    om = yaml_doc.get("ontology_mapping") or {}
    if lbl := om.get("ontology_label"):
        forms.add(_normalize(lbl))
    for syn in yaml_doc.get("synonyms") or []:
        txt = syn.get("synonym_text") if isinstance(syn, dict) else None
        if txt:
            forms.add(_normalize(txt))
    return forms


def _classify_candidate(
    candidate: str,
    existing: set[str],
    this_chebi: str,
    preferred_term: str,
    mim_synonym_index: dict[str, set[str]],
    kg_dict: KgMicrobeDict,
) -> tuple[str, str]:
    """(bucket, rationale) for one candidate synonym string.

    this_chebi / preferred_term describe the MIM record receiving the synonym.
    mim_synonym_index maps normalized-surface-form -> set of CHEBI IDs it's
    already attached to across all of MIM, used to detect cross-record
    collisions (a surface form already meaning a different compound)."""
    if not candidate or not candidate.strip():
        return "NOISE", "empty"

    norm = _normalize(candidate)
    if len(norm) < 2:
        return "NOISE", "too-short"

    if _CURIE_RE.match(candidate.strip()):
        return "NOISE", "curie-like"

    low = candidate.lower()
    if any(sub in low for sub in _NOISE_SUBSTRINGS):
        return "NOISE", "structured-metadata"

    if _CHARGE_ONLY_RE.search(candidate.strip()):
        return "NOISE", "charge-state-annotation"

    if norm in existing:
        return "DUPLICATE", "already-on-record"

    # Hydration-state collision — do not conflate anhydrous and hydrate forms.
    # The MIM YAML "1_M_Sodium_Acetate.yaml" (anhydrous) and a hydrate record
    # "Sodium_Acetate_X_3_H2O.yaml" are separate records pointing at separate
    # CHEBI IDs; merging their synonyms corrupts both.
    cand_hydr = _has_hydrate_marker(candidate)
    mim_hydr = _has_hydrate_marker(preferred_term)
    if cand_hydr != mim_hydr:
        return "AMBIGUOUS", "hydration-state-mismatch"

    # Cross-MIM collision: candidate is already a synonym on a DIFFERENT
    # MIM record (different CHEBI).
    owners = mim_synonym_index.get(norm, set())
    other = owners - {this_chebi}
    if other:
        return "AMBIGUOUS", f"collides-with-{sorted(other)[0]}"

    # Ambiguity check against kg-microbe's own index
    hits = kg_dict.lookup_synonym(candidate)
    if len(hits) > AMBIGUITY_THRESHOLD:
        return "AMBIGUOUS", f"maps-to-{len(hits)}-chebis"

    return "CLEAN_ADD", "novel-unambiguous"


def main():
    src = REPORT_DIR / "kg_microbe_sweep.json"
    data = json.loads(src.read_text())
    p44 = data.get("p44_findings", [])
    print(f"Loaded {len(p44)} P4.4 findings", flush=True)

    kg_dict = KgMicrobeDict()
    kg_dict.load()
    print(f"kg-microbe dict: {kg_dict.size} CHEBI entries loaded", flush=True)

    # Build a global index of "which CHEBI IDs already claim this surface form
    # somewhere in MIM?" so we can detect cross-YAML collisions.
    mim_synonym_index: dict[str, set[str]] = defaultdict(set)
    yaml_cache: dict[str, dict] = {}
    print("Indexing MIM surface forms across all YAMLs...", flush=True)
    for yml in sorted(INGREDIENTS_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(yml.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        yaml_cache[yml.name] = doc
        chebi = doc.get("identifier") or ""
        if not chebi.startswith("CHEBI:"):
            chebi = (doc.get("ontology_mapping") or {}).get("ontology_id") or ""
        if not chebi.startswith("CHEBI:"):
            continue
        for form in _existing_surface_forms(doc):
            if form:
                mim_synonym_index[form].add(chebi)
    print(
        f"MIM surface-form index: {len(mim_synonym_index)} unique forms",
        flush=True,
    )

    def load_yaml(source_file: str) -> dict | None:
        if source_file in yaml_cache:
            return yaml_cache[source_file]
        path = INGREDIENTS_DIR / source_file
        if not path.exists():
            yaml_cache[source_file] = None
            return None
        doc = yaml.safe_load(path.read_text())
        yaml_cache[source_file] = doc
        return doc

    per_finding: list[dict] = []
    bucket_counter: Counter = Counter()
    per_file_clean_adds: dict[str, list[str]] = defaultdict(list)

    for f in p44:
        doc = load_yaml(f["source_file"])
        if doc is None:
            bucket_counter["MISSING_YAML"] += 1
            per_finding.append(
                {
                    **f,
                    "decisions": [],
                    "note": "yaml-not-found",
                }
            )
            continue

        existing = _existing_surface_forms(doc)
        this_chebi = f.get("mim_chebi", "")
        preferred_term = f.get("preferred_term", "") or doc.get(
            "preferred_term", ""
        )
        decisions = []
        for cand in f["evidence"].get("candidates", []):
            bucket, rationale = _classify_candidate(
                cand,
                existing,
                this_chebi,
                preferred_term,
                mim_synonym_index,
                kg_dict,
            )
            decisions.append(
                {"candidate": cand, "bucket": bucket, "rationale": rationale}
            )
            bucket_counter[bucket] += 1
            if bucket == "CLEAN_ADD":
                per_file_clean_adds[f["source_file"]].append(cand)

        per_finding.append({**f, "decisions": decisions})

    out_json = REPORT_DIR / "kg_microbe_p44_enrichment_review.json"
    out_json.write_text(
        json.dumps(
            {
                "summary": {
                    "findings": len(p44),
                    "candidates_total": sum(bucket_counter.values()),
                    "buckets": dict(bucket_counter),
                    "files_with_clean_adds": len(per_file_clean_adds),
                },
                "ambiguity_threshold": AMBIGUITY_THRESHOLD,
                "per_finding": per_finding,
            },
            indent=2,
        )
    )
    print(f"JSON: {out_json}")

    # Markdown report — a reviewer wants two things: aggregate bucket counts,
    # and a flat list of per-file CLEAN_ADD candidates they can skim.
    lines: list[str] = []
    lines.append("# P4.4 Synonym Enrichment — Review\n\n")
    lines.append("**Date:** 2026-04-18\n")
    lines.append(f"**Findings analyzed:** {len(p44)}\n")
    lines.append(
        f"**Candidate synonyms total:** {sum(bucket_counter.values())}\n"
    )
    lines.append(f"**Ambiguity threshold:** >{AMBIGUITY_THRESHOLD} CHEBI hits\n\n")

    lines.append("## Candidate classification\n\n")
    lines.append("| Bucket | Count | Action |\n|---|---:|---|\n")
    action = {
        "CLEAN_ADD": "**Apply as new synonym (via companion apply script)**",
        "DUPLICATE": "No action — already on record",
        "AMBIGUOUS": "Manual review — kg-microbe maps surface form to >5 CHEBIs",
        "NOISE": "Skip — structured metadata, CURIE, or charge-state annotation",
        "MISSING_YAML": "Investigate — referenced YAML not found",
    }
    for b in ("CLEAN_ADD", "DUPLICATE", "AMBIGUOUS", "NOISE", "MISSING_YAML"):
        lines.append(
            f"| {b} | {bucket_counter.get(b, 0)} | {action.get(b, '')} |\n"
        )
    lines.append("\n")

    lines.append(
        f"## CLEAN_ADD candidates — {len(per_file_clean_adds)} files\n\n"
    )
    if not per_file_clean_adds:
        lines.append("_None_\n\n")
    else:
        lines.append(
            "_Candidates ready for automatic application. Grouped by MIM "
            "YAML file. Ordered by file name._\n\n"
        )
        lines.append("| File | preferred_term | New synonym candidates |\n")
        lines.append("|---|---|---|\n")
        # Build a lookup from file to preferred_term
        file_to_pref: dict[str, str] = {}
        for f in p44:
            file_to_pref.setdefault(f["source_file"], f["preferred_term"])
        for src_file in sorted(per_file_clean_adds):
            cands = per_file_clean_adds[src_file]
            pref = file_to_pref.get(src_file, "?")
            # Deduplicate while preserving order
            seen: set[str] = set()
            uniq = []
            for c in cands:
                if c.lower() not in seen:
                    seen.add(c.lower())
                    uniq.append(c)
            cand_str = "; ".join(f"`{c}`" for c in uniq)
            lines.append(f"| `{src_file}` | {pref} | {cand_str} |\n")
        lines.append("\n")

    # Show a sample of AMBIGUOUS so reviewer can spot-check
    amb_examples = [
        (f["source_file"], d["candidate"], d["rationale"])
        for f in per_finding
        for d in f["decisions"]
        if d["bucket"] == "AMBIGUOUS"
    ]
    if amb_examples:
        lines.append(
            f"## AMBIGUOUS sample (5 of {len(amb_examples)})\n\n"
        )
        lines.append("| File | Candidate | Why |\n|---|---|---|\n")
        for src, cand, why in amb_examples[:5]:
            lines.append(f"| `{src}` | `{cand}` | {why} |\n")
        lines.append("\n")

    out_md = REPORT_DIR / "kg_microbe_p44_enrichment_review.md"
    out_md.write_text("".join(lines))
    print(f"Markdown: {out_md}")
    print()
    print("Bucket counts:")
    for b, c in bucket_counter.most_common():
        print(f"  {b:15s} {c}")
    print(f"Files with >=1 CLEAN_ADD: {len(per_file_clean_adds)}")


if __name__ == "__main__":
    main()
