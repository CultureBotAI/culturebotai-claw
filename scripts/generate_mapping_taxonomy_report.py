#!/usr/bin/env python3
"""
Emit workspace/reports/mapping_taxonomy.md — a canonical reference of
every categorical state produced by the MIM ↔ kg-microbe reconciliation
pipeline.

The taxonomy is encoded as static tables below (editable when a new
bucket or verdict is introduced). At run-time we annotate each expected
artifact with live file-existence + size + row count, and each section
gets a pointer to the producer + consumer scripts.
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------- paths ----------


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
REPO = REPO_ROOT
MIM_ROOT = MIM_ROOT
OUT = REPO / "workspace/reports/mapping_taxonomy.md"


# ---------- taxonomy tables ----------

Section = dict  # {title, intro, states, producer, consumers, artifacts}

SECTIONS: list[Section] = [
    {
        "title": "1. Reconciliation buckets",
        "intro": (
            "Every (surface-form, CHEBI) assertion in the joint MIM ↔ "
            "kg-microbe universe lands in exactly one of these buckets."
        ),
        "states": [
            ("AGREE", "kg-microbe's synonym index returns MIM's CHEBI as "
                      "the only candidate for the surface form (or kg-microbe "
                      "has the CHEBI without indexing the label)."),
            ("DISAGREE", "kg-microbe's synonym index returns at least one "
                         "CHEBI other than MIM's pick for this surface form "
                         "— competing mapping exists."),
            ("MIM_ONLY", "kg-microbe has no entry for this surface form OR "
                         "the MIM mapping is non-CHEBI (FOODON, ENVO) and "
                         "kg-microbe's dict is CHEBI-scoped."),
            ("KGM_ONLY", "kg-microbe xrefs a MIM ingredient ID "
                         "(`MediaIngredientMech:000xxx` legacy namespace) "
                         "that MIM's current SSSOM no longer publishes."),
            ("UNMAPPED_PENDING_CURATION",
             "kg-microbe's `kgmicrobe.compound:*` or MediaDive "
             "`mediadive.ingredient:N` rows with no CHEBI anywhere — "
             "handoff queue for curation."),
        ],
        "producer": "scripts/audit_kgm_mim_reconciliation.py",
        "artifacts": [
            "workspace/reports/kgm_mim_audit.tsv",
            "workspace/reports/kgm_mim_audit.md",
        ],
        "consumers": [
            "scripts/fix_deprecated_chebi.py",
            "scripts/fix_label_drift.py",
            "scripts/generate_mim_migration_map.py",
            "scripts/round_trip_true_bugs.py --source audit",
        ],
    },
    {
        "title": "2. Audit row flags",
        "intro": (
            "Per-row flags layered on top of the bucket. Multiple flags "
            "can apply to one row (comma-separated in the `flags` column)."
        ),
        "states": [
            ("DEPRECATED_CHEBI", "`mim_chebi` is in OAK's `obsoletes` set."),
            ("LABEL_DRIFT", "`mim_object_label` is neither OAK's label nor "
                            "any alias of the CHEBI."),
            ("DUPLICATE", "Multiple MIM rows share the same `object_id` CHEBI "
                          "(intended for hydrate variants, unintended for "
                          "exact dupes — see MERGEABLE_DUPES taxonomy)."),
            ("PREFIX_IRREGULAR", "`object_id` doesn't start with a known "
                                 "prefix (CHEBI / FOODON / UBERON / ENVO)."),
        ],
        "producer": "scripts/audit_kgm_mim_reconciliation.py",
        "artifacts": ["workspace/reports/kgm_mim_audit.tsv"],
        "consumers": [
            "scripts/fix_deprecated_chebi.py",
            "scripts/fix_label_drift.py",
        ],
    },
    {
        "title": "3. DISAGREE round-trip verdicts",
        "intro": (
            "For every DISAGREE row we OLS-round-trip MIM's stored CHEBI "
            "and compare its canonical label against `preferred_term` via "
            "stem overlap. Verdict says who is right."
        ),
        "states": [
            ("MIM_WRONG", "OLS label has no chemical-stem overlap with "
                          "preferred_term — MIM's CHEBI is pointed at an "
                          "unrelated compound."),
            ("MIM_OK", "OLS label matches preferred_term — MIM is fine, "
                       "kg-microbe is noise (synonym contamination)."),
            ("AMBIGUOUS", "Partial stem overlap — manual review needed."),
        ],
        "producer": "scripts/round_trip_true_bugs.py",
        "artifacts": [
            "workspace/reports/kg_microbe_true_bugs_round_tripped.json",
            "workspace/reports/kg_microbe_true_bugs_round_tripped.md",
            "workspace/reports/kgm_mim_disagree_roundtrip.json",
            "workspace/reports/kgm_mim_disagree_roundtrip.md",
        ],
        "consumers": [
            "scripts/audit_kgm_mim_reconciliation.py "
            "(feeds into kgm_pr_candidates.tsv)",
            "scripts/apply_mim_wrong_fixes.py",
        ],
    },
    {
        "title": "4. P4.4 synonym-enrichment buckets",
        "intro": (
            "Per-candidate classification for every synonym kg-microbe "
            "proposes to add to a MIM ingredient YAML."
        ),
        "states": [
            ("CLEAN_ADD", "Novel, unambiguous — safe to append."),
            ("DUPLICATE", "Already present on the record (dedup safeguard)."),
            ("AMBIGUOUS", "One of: `hydration-state-mismatch`, "
                          "`collides-with-<CHEBI>`, or `maps-to-N-chebis`. "
                          "See section 5 for hydration sub-resolution."),
            ("NOISE", "Empty / CURIE-like / charge-state annotation / "
                      "structured metadata — never a valid synonym."),
        ],
        "producer": "MediaIngredientMech/src/.../ingredient_reviewer.py "
                    "(_check_kg_microbe_synonym_enrichment) → "
                    "scripts/review_p44_synonym_enrichment.py",
        "artifacts": [
            "workspace/reports/kg_microbe_p44_enrichment_review.json",
            "workspace/reports/kg_microbe_p44_enrichment_review.md",
        ],
        "consumers": [
            "scripts/apply_p44_synonym_enrichment.py (CLEAN_ADD only)",
            "scripts/disambiguate_p44_hydration.py "
            "(AMBIGUOUS + hydration-state-mismatch)",
        ],
    },
    {
        "title": "5. P4.4 hydration resolution",
        "intro": (
            "Sub-resolution of AMBIGUOUS hydration-state-mismatch rows. "
            "Matches each candidate's hydration count against the MIM "
            "YAML whose (stem, hydration) signature fits."
        ),
        "states": [
            ("ROUTE_TO_HYDRATE", "Candidate is a hydrate; exactly one "
                                 "matching hydrate MIM record found."),
            ("ROUTE_TO_ANHYDROUS", "Candidate is anhydrous; exactly one "
                                   "matching anhydrous MIM record found."),
            ("ROUTE_TO_UNKNOWN_HYDRATE", "Matched to a MIM record with a "
                                         "generic 'hydrate' marker."),
            ("AMBIGUOUS_TARGETS", "Multiple MIM records match "
                                  "(stem, hydration) — curator picks."),
            ("UNRESOLVED", "No matching sibling in MIM — candidate has "
                           "no home until a new record is created."),
        ],
        "producer": "scripts/disambiguate_p44_hydration.py",
        "artifacts": [
            "workspace/reports/p44_hydration_resolution.json",
            "workspace/reports/p44_hydration_resolution.md",
        ],
        "consumers": [
            "scripts/apply_p44_hydration_routing.py (ROUTE_* only)",
            "scripts/propose_hydrate_siblings.py (UNRESOLVED)",
        ],
    },
    {
        "title": "6. Hydrate sibling proposal tiers",
        "intro": (
            "For each UNRESOLVED (stem, hydration) group from section 5, "
            "OLS-search for a CHEBI. Confidence tier gates auto-apply."
        ),
        "states": [
            ("HIGH", "Exact label match OR exact synonym match on a "
                     "non-obsolete CHEBI."),
            ("MEDIUM", "Single lexical candidate, not exact label match."),
            ("LOW", "Multiple non-obsolete candidates with no exact match."),
            ("NONE", "No hits OR all hits obsolete OR OLS error."),
        ],
        "producer": "scripts/propose_hydrate_siblings.py "
                    "/ scripts/propose_chebi_for_unmapped.py",
        "artifacts": [
            "workspace/reports/hydrate_sibling_proposals.json",
            "workspace/reports/hydrate_sibling_proposals.md",
            "workspace/reports/mim_curation_candidates.tsv",
            "workspace/reports/mim_curation_candidates.md",
        ],
        "consumers": [
            "scripts/apply_hydrate_siblings.py (HIGH, optional --include-medium)",
            "scripts/apply_mim_chebi_fixes.py (HIGH curation candidates)",
            "scripts/apply_medium_unmapped_candidates.py "
            "(MEDIUM + stem-overlap verification)",
            "scripts/route_chebi_collision_synonyms.py "
            "(HIGH/MEDIUM routed to existing YAMLs when CHEBI already exists)",
            "scripts/emit_low_curator_queue.py (LOW → curator TSV)",
        ],
    },
    {
        "title": "7. Curation queue actions",
        "intro": (
            "Per-row recommended disposition for the 430 unmapped "
            "candidates in `mim_curation_queue.tsv`."
        ),
        "states": [
            ("curate-new-MIM-ingredient-with-chebi",
             "Source surface form is not present in MIM by label; needs a "
             "new MAPPED YAML."),
            ("link-to-existing-MIM-record", "Source label already exists "
                                            "in MIM — just wire the xref."),
            ("already_in_mim (column, yes/no)",
             "True when the source's `preferred_term` is a case-insensitive "
             "match to an existing MIM `subject_label`."),
        ],
        "producer": "scripts/audit_kgm_mim_reconciliation.py "
                    "(write_curation_queue)",
        "artifacts": ["workspace/reports/mim_curation_queue.tsv"],
        "consumers": [
            "scripts/propose_chebi_for_unmapped.py",
            "scripts/emit_low_curator_queue.py",
        ],
    },
    {
        "title": "8. Numeric-namespace migration actions",
        "intro": (
            "kg-microbe still xrefs an older `MediaIngredientMech:000xxx` "
            "namespace. For each legacy ID, derive a migration to the "
            "current `MIM:<slug>` namespace (or declare orphan)."
        ),
        "states": [
            ("migrate", "Exactly one current MIM subject_id has the same "
                        "CHEBI → safe rename."),
            ("ambiguous", "Multiple MIM subject_ids share the CHEBI "
                          "— curator picks."),
            ("orphan", "No current MIM subject_id has this CHEBI — MIM "
                       "dropped the chemical."),
            ("keep", "(Reserved for future use when kg-microbe legitimately "
                     "needs the legacy ID.)"),
        ],
        "producer": "scripts/generate_mim_migration_map.py",
        "artifacts": [
            "workspace/reports/mim_numeric_namespace_migration.tsv",
            "workspace/reports/mim_numeric_namespace_migration.md",
        ],
        "consumers": ["scripts/generate_kgm_xref_patches.py"],
    },
    {
        "title": "9. Duplicate-CHEBI classification",
        "intro": (
            "MIM CHEBIs with >1 mapped YAML, grouped by "
            "(CHEBI, hydration_count) with hydration=None canonicalized "
            "to anhydrous (0)."
        ),
        "states": [
            ("MERGEABLE_DUPES", "≥2 YAMLs with matching hydration state "
                                "— candidate consolidation."),
            ("MIXED", "At least one YAML has unknown hydration AND the "
                      "state counts are unequal (pre-None=0 convention)."),
            ("LEGITIMATE_VARIANTS", "All YAMLs have distinct hydration "
                                    "states — intended pattern."),
        ],
        "producer": "scripts/analyze_mim_chebi_duplicates.py",
        "artifacts": [
            "workspace/reports/mim_duplicate_consolidation_queue.tsv",
            "workspace/reports/mim_duplicate_consolidation_queue.md",
            "workspace/reports/mim_chebi_duplication_review.md",
        ],
        "consumers": ["scripts/plan_mim_merges.py"],
    },
    {
        "title": "10. Merge safety tiers",
        "intro": (
            "Per-merge classification — whether the collapse is "
            "mechanically safe or needs a CAS-RN adjudication first."
        ),
        "states": [
            ("SAFE", "≤1 distinct CAS-RN across all YAMLs in the group "
                     "— merge preserves chemistry metadata."),
            ("RISKY", ">1 distinct CAS-RN — resolved via OAK/CHEBI "
                      "canonical xref in `resolve_risky_cas_rn.py`."),
        ],
        "producer": "scripts/plan_mim_merges.py",
        "artifacts": [
            "workspace/reports/mim_merge_plan.tsv",
            "workspace/reports/mim_merge_plan.md",
        ],
        "consumers": [
            "scripts/apply_mim_merges.py (SAFE)",
            "scripts/resolve_risky_cas_rn.py (RISKY)",
        ],
    },
    {
        "title": "11. Label drift fix kinds",
        "intro": (
            "Per-row outcome when LABEL_DRIFT rows are round-tripped "
            "through OAK then OLS."
        ),
        "states": [
            ("LABEL_UPDATE", "OAK has a canonical label — mechanical swap."),
            ("STALE_LOCAL", "OAK missed it but OLS has it — refresh local "
                            "sqlite."),
            ("CHEBI_REMOVED", "OLS returns 404 — CHEBI ID no longer exists; "
                              "needs re-curation."),
            ("UNKNOWN", "OLS error — transient; retry."),
        ],
        "producer": "scripts/fix_label_drift.py",
        "artifacts": [
            "workspace/patches/mim_label_drift_patches.yaml",
            "workspace/reports/mim_label_drift_summary.md",
        ],
        "consumers": ["scripts/recurate_deprecated_and_removed.py"],
    },
    {
        "title": "12. Re-curation outcomes + curator-confirmed synonyms",
        "intro": (
            "When OLS search for a removed/obsolete CHEBI is attempted. "
            "CURATOR_CONFIRMED_SYNONYM is a special override for cases "
            "where a label mismatch is actually a correct chemistry "
            "synonym (trade name ↔ IUPAC)."
        ),
        "states": [
            ("HIGH", "Exact label or synonym match on a non-obsolete CHEBI."),
            ("MEDIUM", "Single non-obsolete lexical candidate."),
            ("LOW", "Multiple non-obsolete candidates."),
            ("NONE", "No OLS hits or only obsolete hits."),
            ("CURATOR_CONFIRMED_SYNONYM",
             "Special evidence_type for mappings where the ingredient "
             "name and CHEBI's canonical label differ but are known "
             "synonyms (e.g. angustmycin → psicofuranin)."),
        ],
        "producer": "scripts/recurate_deprecated_and_removed.py",
        "artifacts": [
            "workspace/patches/mim_chebi_recuration_patches.yaml",
            "workspace/reports/mim_chebi_recuration_summary.md",
        ],
        "consumers": ["scripts/apply_mim_chebi_fixes.py"],
    },
    {
        "title": "13. Complex-media extraction",
        "intro": (
            "When duplicate-CHEBI consolidation wrongly absorbs a "
            "complete media recipe (e.g. 'Brucella agar') as a synonym "
            "of a pure ingredient (e.g. 'Agar'). Extraction produces a "
            "new UNMAPPED_XXXX MIM record pending re-mapping."
        ),
        "states": [
            ("pure (stays)",
             "All alphabetic tokens are in the target's `pure_tokens` "
             "set OR the text is parenthesized metadata / Role / "
             "Properties prefix."),
            ("complex_medium (extracted)",
             "Contains a token from `medium_markers` (agar, broth, soy, "
             "tryptic…) that is not part of the target's pure-ingredient "
             "lexicon."),
        ],
        "producer": "scripts/extract_complex_media_from_agar.py "
                    "(Agar-specific), scripts/extract_complex_media_synonyms.py "
                    "(generalized with per-target config)",
        "artifacts": [
            "MediaIngredientMech/data/ingredients/unmapped/UNMAPPED_XXXX.yaml "
            "(one per extracted synonym)",
        ],
        "consumers": ["Curator — no automated consumer; "
                      "eventual FOODON complex-medium mapping or "
                      "per-component decomposition"],
    },
    {
        "title": "14. Evidence types (ontology_mapping.evidence[].evidence_type)",
        "intro": (
            "Per-mapping evidence classifier recorded in every MIM "
            "ingredient YAML."
        ),
        "states": [
            ("DATABASE_MATCH", "Matched via an authoritative database "
                               "(CultureMech import, CAS-RN via PubChem, etc.)."),
            ("LEXICAL_MATCH", "OLS / OAK exact label or synonym match."),
            ("CURATOR_CONFIRMED_SYNONYM", "Human-approved synonym override "
                                          "(see section 12)."),
            ("MANUAL_CURATION", "Handled by a human curator (varied sources)."),
        ],
        "producer": "All scripts that create/update MIM YAMLs",
        "artifacts": ["MediaIngredientMech/data/ingredients/mapped/*.yaml"],
        "consumers": ["scripts/build_mim_ingredient_sssom.py "
                      "(carries into SSSOM `source` column)"],
    },
    {
        "title": "15. SSSOM predicate richness",
        "intro": (
            "SKOS predicate on each SSSOM row. Default is `skos:exactMatch`; "
            "upgraded to narrower/broader/close when the residual-P2.5 "
            "triage determined a specificity or symmetry difference."
        ),
        "states": [
            ("skos:exactMatch", "Bidirectional exact equivalence "
                                "(~900 rows when session closed)."),
            ("skos:closeMatch", "Symmetric — both sides defensible "
                                "(~160 rows)."),
            ("skos:narrowMatch", "MIM term is more generic than the "
                                 "chosen CHEBI (~74 rows, 'CONSIDER_SPECIFIC')."),
            ("skos:broadMatch", "MIM term is more specific than the "
                                "chosen CHEBI (rare)."),
        ],
        "producer": "scripts/build_mim_ingredient_sssom.py "
                    "(uses kg_microbe_residual_p25_categorized.json as input)",
        "artifacts": [
            "workspace/reports/mim_ingredient_mappings.sssom.tsv (working)",
            "MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv (published)",
        ],
        "consumers": [
            "scripts/review_sssom_synonyms.py",
            "downstream: kg-microbe, CommunityMech",
        ],
    },
    {
        "title": "16. Curation history action codes",
        "intro": (
            "Per-change tag appended to `curation_history[].action` in MIM "
            "YAMLs. Each tag identifies the pipeline step that made the "
            "change."
        ),
        "states": [
            ("IMPORTED", "Initial CultureMech import"),
            ("ADDED_CAS_RN", "PubChem / CultureBotHT CAS-RN fetch"),
            ("ADDED_SYNONYMS", "P4.4 synonym enrichment"),
            ("ADDED_SYNONYMS_VIA_HYDRATION_ROUTING",
             "Hydration-mismatch re-routing to correct sibling"),
            ("ADDED_SYNONYMS_VIA_CHEBI_COLLISION_ROUTING",
             "HIGH/MEDIUM candidate routed into existing CHEBI owner"),
            ("FIXED_DEPRECATED_CHEBI", "OAK `obsoletes_migration_relationships` swap"),
            ("FIXED_OBSOLETE_CHEBI / FIXED_REMOVED_CHEBI",
             "OLS-re-curated replacement"),
            ("FIXED_LABEL_DRIFT", "Object label re-sync to CHEBI canonical"),
            ("FLAGGED_STALE_LOCAL_CHEBI / FLAGGED_CHEBI_REMOVED / "
             "FLAGGED_LABEL_DRIFT_UNKNOWN", "Flagged for curator; not auto-fixed"),
            ("FIXED_MIM_WRONG_CHEBI", "DISAGREE MIM_WRONG swap adopted"),
            ("CURATOR_CONFIRMED_CHEBI", "User-approved override"),
            ("CREATED_FROM_UNMAPPED_QUEUE",
             "New YAML seeded from propose_chebi_for_unmapped.py HIGH hit"),
            ("CREATED_FROM_HYDRATE_SIBLING_PROPOSAL",
             "New YAML seeded from propose_hydrate_siblings.py HIGH hit"),
            ("MERGED_FROM_DUPLICATES",
             "Winner absorbed duplicate-CHEBI losers"),
            ("RESOLVED_CAS_RN_CONFLICT",
             "RISKY merge resolved via OAK canonical CAS-RN"),
            ("EXTRACTED_COMPLEX_MEDIUM",
             "Complex-media synonym split out into its own UNMAPPED YAML"),
            ("EXTRACTED_CONTAMINATING_SYNONYMS",
             "Parent-side log of the split (Agar.yaml, Malt_Extract.yaml…)"),
        ],
        "producer": "All apply scripts under scripts/",
        "artifacts": ["MediaIngredientMech/data/ingredients/mapped/*.yaml "
                      "(curation_history list)"],
        "consumers": [
            "scripts/build_mim_ingredient_sssom.py (extracts "
            "MIM:curator=<name> into SSSOM `source` column)",
        ],
    },
]


# Artifact inventory — path to (section reference, description).
ARTIFACTS: list[tuple[str, str, str]] = [
    ("MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv",
     "CANONICAL", "Published SSSOM artifact consumed by all downstream repos"),
    ("MediaIngredientMech/mappings/complex_ingredients.tsv.gz",
     "CANONICAL", "FOODON/ENVO artifact for kg-microbe's future non-CHEBI consumption"),
    ("MediaIngredientMech/mappings/complex_ingredients.tsv",
     "CANONICAL", "Uncompressed preview of the above"),

    ("workspace/reports/mim_ingredient_mappings.sssom.tsv",
     "WORKING", "SSSOM working copy (overwritten on every `just build-sssom`)"),
    ("workspace/reports/complex_ingredients.tsv.gz",
     "WORKING", "Complex-ingredients working copy"),

    ("workspace/reports/kgm_mim_audit.tsv",
     "PIPELINE", "Section 1+2 — full reconciliation audit (5 buckets, 4 flags)"),
    ("workspace/reports/kgm_mim_audit.md",
     "PIPELINE", "Human-readable audit summary"),
    ("workspace/reports/kgm_pr_candidates.tsv",
     "PIPELINE", "kg-microbe PR-ready filtered rows (DISAGREE + DEPRECATED)"),
    ("workspace/reports/mim_curation_queue.tsv",
     "PIPELINE", "Section 7 — UNMAPPED_PENDING_CURATION handoff queue"),
    ("workspace/reports/mim_curation_candidates.tsv",
     "PIPELINE", "Section 6 — OLS proposals for the above"),
    ("workspace/reports/mim_low_confidence_curation_queue.tsv",
     "PIPELINE", "Section 6 LOW subset — curator review queue"),
    ("workspace/reports/kgm_mim_disagree_roundtrip.json",
     "PIPELINE", "Section 3 — verdicts for all DISAGREE rows"),
    ("workspace/reports/kgm_mim_disagree_roundtrip.md",
     "PIPELINE", "Human-readable of the above"),
    ("workspace/reports/kg_microbe_true_bugs_round_tripped.json",
     "PIPELINE", "Section 3 — first-wave (72 TRUE_BUG rows from P2.5)"),
    ("workspace/reports/mim_numeric_namespace_migration.tsv",
     "PIPELINE", "Section 8 — legacy MediaIngredientMech:000xxx → MIM:<slug>"),
    ("workspace/reports/mim_duplicate_consolidation_queue.tsv",
     "PIPELINE", "Section 9 — CHEBIs with >1 MIM YAML"),
    ("workspace/reports/mim_merge_plan.tsv",
     "PIPELINE", "Section 10 — merge operations plan"),
    ("workspace/reports/hydrate_sibling_proposals.json",
     "PIPELINE", "Section 6 — OLS-proposed CHEBIs for unresolved hydrates"),
    ("workspace/reports/p44_hydration_resolution.json",
     "PIPELINE", "Section 5 — hydration-mismatch sub-resolution"),
    ("workspace/reports/kg_microbe_p44_enrichment_review.json",
     "PIPELINE", "Section 4 — synonym-enrichment candidate buckets"),

    ("workspace/patches/mim_deprecated_chebi_patches.yaml",
     "PATCHES", "Proposed MIM YAML patches for DEPRECATED_CHEBI"),
    ("workspace/patches/mim_label_drift_patches.yaml",
     "PATCHES", "Proposed MIM YAML patches for LABEL_DRIFT"),
    ("workspace/patches/mim_chebi_recuration_patches.yaml",
     "PATCHES", "Section 12 — OLS re-curation patches"),
    ("workspace/patches/kgm_xref_patches.tsv",
     "PATCHES", "kg-microbe xref PR patches"),

    ("workspace/reports/mim_chebi_duplication_review.md",
     "REPORT", "Narrative view of multi-YAML-per-CHEBI groups"),
    ("workspace/reports/mim_wrong_unverified.md",
     "REPORT", "MIM_WRONG rows rejected by 2nd-pass OLS round-trip"),
    ("workspace/reports/medium_candidates_reviewed.md",
     "REPORT", "MEDIUM-confidence unmapped candidates rejected by stem-overlap"),
    ("workspace/reports/chebi_collision_routing_flags.md",
     "REPORT", "HIGH proposals that collided with existing MIM CHEBIs"),
    ("workspace/reports/mim_deprecated_chebi_summary.md", "REPORT", "11-row summary"),
    ("workspace/reports/mim_label_drift_summary.md", "REPORT", "6-row summary"),
    ("workspace/reports/mim_chebi_recuration_summary.md", "REPORT", "6-row summary"),

    ("workspace/status/sssom_promotions.jsonl",
     "AUDIT", "Every promotion: timestamp, sha256, row counts"),

    ("docs/proposals/kg_microbe_dict_extend_beyond_chebi.md",
     "DOCS", "FOODON/ENVO proposal — motivates the complex_ingredients artifact"),
]


# ---------- helpers ----------

def _file_status(rel: str) -> str:
    """Return a short marker + size + row count for an artifact path."""
    if rel.startswith("MediaIngredientMech/"):
        path = MIM_ROOT / rel[len("MediaIngredientMech/"):]
    else:
        path = REPO / rel
    if not path.exists():
        return "✗ (missing)"
    size = path.stat().st_size
    size_str = (
        f"{size:,} B" if size < 1024
        else f"{size / 1024:.1f} KB" if size < 1024 * 1024
        else f"{size / 1024 / 1024:.1f} MB"
    )
    # Try a row count for text files
    row_info = ""
    suffix = path.suffix.lower()
    try:
        if suffix in (".tsv", ".md", ".jsonl"):
            with path.open() as f:
                n = sum(1 for _ in f)
            row_info = f", {n} lines"
        elif suffix == ".json":
            # Skip — could be arbitrarily structured
            pass
        elif rel.endswith(".tsv.gz"):
            with gzip.open(path, "rt") as f:
                n = sum(1 for _ in f)
            row_info = f", {n} lines"
    except Exception:
        pass
    return f"✓ {size_str}{row_info}"


def _render_section(sec: Section) -> str:
    out = [f"## {sec['title']}\n", sec["intro"], ""]
    out.append("| State | Meaning |")
    out.append("|---|---|")
    for name, meaning in sec["states"]:
        out.append(f"| `{name}` | {meaning} |")
    out.append("")
    out.append(f"**Producer:** `{sec['producer']}`  ")
    if sec.get("consumers"):
        out.append(
            "**Consumers:** "
            + ", ".join(f"`{c}`" for c in sec["consumers"])
        )
    out.append("")
    if sec.get("artifacts"):
        out.append("**Artifacts:**")
        for art in sec["artifacts"]:
            out.append(f"- `{art}` — {_file_status(art)}")
    return "\n".join(out) + "\n\n"


def _render_artifact_inventory() -> str:
    out = ["## 17. Artifact inventory\n"]
    out.append(
        "One-line status of every file the pipeline produces or consumes. "
        "`CANONICAL` = consumed downstream; `WORKING` = overwritten on "
        "build; `PIPELINE` = input to at least one other script; "
        "`PATCHES` = proposed-but-not-applied YAML edits; `REPORT` = "
        "human-readable narrative; `AUDIT` = timestamped log; "
        "`DOCS` = narrative design docs.\n"
    )
    out.append("| Path | Role | Status | Description |")
    out.append("|---|---|---|---|")
    for path, role, desc in ARTIFACTS:
        out.append(f"| `{path}` | {role} | {_file_status(path)} | {desc} |")
    return "\n".join(out) + "\n\n"


def _render_pipeline_graph() -> str:
    return """## 18. Pipeline data-flow graph

```
CultureMech YAMLs ──┐
kg-microbe dict ────┤
MediaDive unmapped ─┤
                    │
                    ▼
        audit_kgm_mim_reconciliation.py
         (buckets 1, 2, 7 + kgm_pr_candidates)
                    │
         ┌──────────┼──────────┬──────────────────┬──────────────────┐
         ▼          ▼          ▼                  ▼                  ▼
  fix_deprecated  fix_label  generate_migration  round_trip_true    propose_chebi
  _chebi.py       _drift.py  _map.py             _bugs.py           _for_unmapped.py
         │          │          │                  │                  │
         ▼          ▼          ▼                  ▼                  ▼
  mim_dep_       mim_ldrift  migration.tsv    disagree_round      curation_candidates
  patches.yaml   patches.yaml  │                trip.{tsv,md}      .tsv
         │          │          │                  │                  │
         │          ▼          ▼                  ▼                  ▼
  recurate_deprecated          generate_kgm_    apply_mim_wrong    apply_mim_chebi_fixes.py
  _and_removed.py             _xref_patches.py  _fixes.py           apply_medium_unmapped
         │                      │                │                   _candidates.py
         ▼                      ▼                │                   │
  mim_chebi_recuration        kgm_xref_          │                   │
  _patches.yaml               patches.tsv        │                   │
         │                                       │                   │
         └────────────────┬──────────────────────┴───────────────────┘
                          ▼
              MediaIngredientMech/data/ingredients/mapped/*.yaml
                          │
                          ├───► build_mim_ingredient_sssom.py
                          │            │
                          │            ▼
                          │     mim_ingredient_mappings.sssom.tsv (working)
                          │            │
                          │            ▼
                          │     review_sssom_synonyms.py
                          │            │
                          │            ▼
                          │     publish_sssom.py --apply
                          │            │
                          │            ▼
                          │     MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv
                          │            │
                          │            ▼
                          │     downstream consumers (kg-microbe, CommunityMech)
                          │
                          ├───► analyze_mim_chebi_duplicates.py
                          │            │
                          │            ▼
                          │     plan_mim_merges.py ─► apply_mim_merges.py (SAFE)
                          │                      ─► resolve_risky_cas_rn.py (RISKY)
                          │
                          └───► build_complex_ingredients_tsv.py --publish
                                       │
                                       ▼
                                MediaIngredientMech/mappings/complex_ingredients.tsv.gz
```

Sub-pipeline for P4.4 synonym enrichment:

```
kg_microbe_p44_enrichment_review.json  (CLEAN_ADD / DUPLICATE / AMBIGUOUS / NOISE)
            │
   ┌────────┼────────────┐
   ▼        ▼            ▼
apply_p44_  disambiguate   propose_hydrate_siblings.py  (HIGH / MEDIUM / LOW / NONE)
synonym_    _p44_hydration          │
enrichment  .py                     ▼
.py         │              apply_hydrate_siblings.py  (HIGH → new YAMLs)
(CLEAN_ADD) │              route_chebi_collision_synonyms.py  (HIGH/MEDIUM → existing)
            ▼              emit_low_curator_queue.py  (LOW → TSV)
    apply_p44_hydration
    _routing.py  (ROUTE_*)
```

Sub-pipeline for complex-media decontamination:

```
CHEBI:2509 Agar winner absorbs 22 synonyms (merge)
            │
            ▼
extract_complex_media_from_agar.py  (pure / complex_medium)
            │
            ├─► Agar.yaml  (kept synonyms: Bacteriological, Noble, metadata)
            └─► data/ingredients/unmapped/UNMAPPED_XXXX.yaml × 20  (extracted)

extract_complex_media_synonyms.py  (generalized, per-target config)
            │
            └─► UNMAPPED_XXXX.yaml × N  (Malt Extract, Trypticase Peptone, …)
```
"""


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# MIM ↔ kg-microbe Mapping Case Taxonomy\n",
        f"_Generated {now} by "
        "`scripts/generate_mapping_taxonomy_report.py`._\n\n",
        "This document is the canonical reference for every categorical "
        "state the reconciliation pipeline produces. Each section shows "
        "the possible states, what they mean, the producer script, the "
        "downstream consumers, and the artifact file(s) that hold rows "
        "with those states.\n\n",
        "Sections 1–16 document state taxonomies. Section 17 is the "
        "full artifact inventory with live file-existence status. "
        "Section 18 is the pipeline data-flow graph.\n\n",
        "---\n\n",
    ]
    for sec in SECTIONS:
        lines.append(_render_section(sec))
    lines.append(_render_artifact_inventory())
    lines.append(_render_pipeline_graph())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(lines))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
