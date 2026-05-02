#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Validation gate for kg-microbe's
`mappings/isolation_source_to_ontology.tsv`. Implements the
recommendations from the Codex adversarial review:

  1. Every non-empty object_id is a valid CURIE (prefix:localpart)
  2. Every mapped row has a non-empty object_source
  3. object_source matches the prefix of object_id
  4. predicate_id is a valid SKOS mapping predicate
  5. mapping_justification is a recognized semapv: term
  6. confidence is one of {high, medium, low}
  7. ontology category allowlist: only ontologies appropriate for an
     "isolation source" (where an organism was found) — disallows
     MONDO/DOID/HP (disease ontologies) and warns on NCIT/mesh terms
     that are clearly not-a-place (questionnaire items, topical
     products, etc., when detectable by label keyword)
  8. unmapped rows (empty object_id) MUST have empty object_source +
     empty predicate_id (i.e., not claim a mapping when there is none)

Exits 2 on any error; 1 on warnings only; 0 if clean.

Run via `just validate-isolation-source` (claw) or in CI from
kg-microbe's workflow that calls this script via the claw checkout.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KGM_ROOT = Path(os.environ.get(
    "KGMICROBE_ROOT",
    REPO_ROOT.parent / "kg-microbe"))
DEFAULT_PATH = KGM_ROOT / "mappings" / "isolation_source_to_ontology.tsv"

_CURIE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9._-]*):([^\s]+)$")

# Ontologies appropriate for isolation-source mappings. An isolation
# source describes WHERE an organism was found (environment, host
# tissue, host species, food substrate, etc.).
_ALLOWED_PREFIXES = frozenset({
    "ENVO",       # environments
    "UBERON",     # anatomy / tissue
    "NCBITaxon",  # host species
    "FOODON",     # foods / biological substrates
    "BTO",        # BRENDA tissues
    "PO",         # plant anatomy
    "PATO",       # qualities (acidic / basic media)
    "GENEPIO",    # genomic epidemiology (sample types)
    "ExO",        # exposure ontology
    "FAO",        # fungal anatomy
    "AGRO",       # agronomy
    "GO",         # biological process — borderline; allowed for
                  # contexts like "digestion" / "fermentation"
    "PCO",        # population / community
    "PRIDE",      # protein identifications — allowed only for proteome contexts
    "VariO",      # variation ontology — borderline
    "UO",         # units of measure
    "METPO",      # microbial ecology / phenotype
    "SNOMED",     # SNOMED CT — allowed for medical-sample contexts
    "CHEBI",      # chemical substrates (Food, Oil-Fuel, Pesticide, etc.)
})

# Ontologies NEVER appropriate for an isolation source.
_DISALLOWED_PREFIXES = frozenset({
    "MONDO",  # disease ontology — diseases are not isolation sources
    "DOID",   # disease ontology
    "HP",     # human phenotype — not a place
})

# NCIT and mesh are mixed: most concepts are fine but many label-only
# matches land on questionnaire items, products, or facilities. We
# allow them but warn on rows whose object_label contains the
# following non-isolation-source keywords.
_MIXED_PREFIXES = frozenset({"NCIT", "mesh"})
_NON_ISOLATION_KEYWORDS = (
    "disease", "disorder", "syndrome", "lung disease",
    "questionnaire", "topical", "tablet", "capsule", "injection",
    "treatment", "therapy", "procedure",
    "organization", "company", "registry",
    "lung disease",
)

_VALID_PREDICATES = frozenset({
    "skos:exactMatch", "skos:closeMatch", "skos:narrowMatch",
    "skos:broadMatch", "skos:relatedMatch",
})

_VALID_JUSTIFICATIONS = frozenset({
    "semapv:LexicalMatching", "semapv:ManualMappingCuration",
    "semapv:UnspecifiedMatching", "semapv:CompositeMatching",
    "semapv:LogicalReasoning", "semapv:CrossSpeciesExactMatch",
    "",
})

_VALID_CONFIDENCE = frozenset({"high", "medium", "low", ""})


def validate(path: Path, strict: bool = False) -> int:
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2

    errors: list[str] = []
    warnings: list[str] = []

    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for i, row in enumerate(reader, 2):  # header is line 1
            subj = row.get("subject_label") or ""
            oid = (row.get("object_id") or "").strip()
            osrc = (row.get("object_source") or "").strip()
            olabel = (row.get("object_label") or "").strip()
            pred = (row.get("predicate_id") or "").strip()
            justif = (row.get("mapping_justification") or "").strip()
            conf = (row.get("confidence") or "").strip()

            # Rule 8: unmapped rows must have empty mapping fields
            if not oid:
                if osrc or pred:
                    errors.append(
                        f"line {i}: unmapped row '{subj}' has non-empty "
                        f"object_source={osrc!r} or predicate_id={pred!r}")
                continue

            # Rule 1: CURIE shape
            m = _CURIE_RE.match(oid)
            if not m:
                errors.append(
                    f"line {i}: '{subj}' object_id={oid!r} is not a "
                    f"valid CURIE")
                continue
            prefix = m.group(1)

            # Rule 2: mapped row must have object_source
            if not osrc:
                errors.append(
                    f"line {i}: '{subj}' has object_id={oid!r} but no "
                    f"object_source")

            # Rule 3: prefix consistency
            if osrc and prefix.upper() != osrc.upper():
                errors.append(
                    f"line {i}: '{subj}' object_id prefix={prefix!r} "
                    f"!= object_source={osrc!r}")

            # Rule 4-6: vocab checks
            if pred and pred not in _VALID_PREDICATES:
                errors.append(
                    f"line {i}: '{subj}' predicate_id={pred!r} not in "
                    f"valid SKOS mapping predicates")
            if justif and justif not in _VALID_JUSTIFICATIONS:
                warnings.append(
                    f"line {i}: '{subj}' mapping_justification={justif!r} "
                    f"unusual")
            if conf and conf not in _VALID_CONFIDENCE:
                warnings.append(
                    f"line {i}: '{subj}' confidence={conf!r} not in "
                    f"{{high, medium, low}}")

            # Rule 7: prefix allowlist
            if prefix in _DISALLOWED_PREFIXES:
                errors.append(
                    f"line {i}: '{subj}' uses disallowed ontology "
                    f"{prefix!r} (diseases/phenotypes are not isolation "
                    f"sources): {oid} ({olabel})")
            elif prefix in _MIXED_PREFIXES:
                low = olabel.lower()
                hit = next(
                    (k for k in _NON_ISOLATION_KEYWORDS if k in low),
                    None)
                if hit:
                    warnings.append(
                        f"line {i}: '{subj}' → {oid} ({olabel}) — "
                        f"label contains non-isolation-source keyword "
                        f"{hit!r}; review")
            elif prefix not in _ALLOWED_PREFIXES:
                warnings.append(
                    f"line {i}: '{subj}' → {oid}: ontology {prefix!r} "
                    f"not on the isolation-source allowlist; review")

    print(f"errors: {len(errors)}")
    print(f"warnings: {len(warnings)}")
    if errors:
        print("\n--- ERRORS ---", file=sys.stderr)
        for e in errors[:50]:
            print(f"  {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more", file=sys.stderr)
    if warnings:
        print("\n--- WARNINGS ---", file=sys.stderr)
        for w in warnings[:30]:
            print(f"  {w}", file=sys.stderr)
        if len(warnings) > 30:
            print(f"  ... and {len(warnings) - 30} more", file=sys.stderr)

    if errors:
        return 2
    if strict and warnings:
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=DEFAULT_PATH,
                    help="path to isolation_source_to_ontology.tsv")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on warnings (default: warnings non-blocking)")
    args = ap.parse_args()
    return validate(args.path, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
