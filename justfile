# Justfile for CultureBotAI-CLAW workflows

# Default recipe - show available commands
default:
    @just --list

# =============================================================================
# FEBA Media Workflows
# =============================================================================

# Extract FEBA ingredients without CAS-RN coverage
feba-extract-uncovered:
    @echo "Extracting FEBA ingredients without CAS-RN..."
    python scripts/extract_feba_uncovered_ingredients.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --output-list workspace/feba_uncovered_ingredients.txt \
        --output-report workspace/feba_uncovered_report.yaml

# Map FEBA notation variants to CAS-RN
feba-map-variants:
    @echo "Mapping FEBA notation variants..."
    python scripts/map_feba_notation_variants.py \
        --ingredients workspace/feba_uncovered_ingredients.txt \
        --output workspace/feba_notation_mapping_results.yaml

# Classify FEBA ingredients by mappability
feba-classify:
    @echo "Classifying FEBA ingredients by mappability..."
    python scripts/classify_feba_mappability.py \
        --uncovered-report workspace/feba_uncovered_report.yaml \
        --mapping-results workspace/feba_notation_mapping_results.yaml \
        --output workspace/feba_mappability_classification.yaml

# Resolve FEBA resolvable ingredients (HIGH priority)
feba-resolve-high:
    @echo "Resolving HIGH priority resolvable ingredients..."
    python scripts/resolve_feba_resolvable.py \
        --classification workspace/feba_mappability_classification.yaml \
        --output workspace/feba_resolvable_resolution_results.yaml \
        --priority HIGH

# Resolve FEBA resolvable ingredients (MEDIUM priority)
feba-resolve-medium:
    @echo "Resolving MEDIUM priority resolvable ingredients..."
    python scripts/resolve_feba_resolvable.py \
        --classification workspace/feba_mappability_classification.yaml \
        --output workspace/feba_resolvable_resolution_medium.yaml \
        --priority MEDIUM

# Resolve FEBA resolvable ingredients (ALL priorities)
feba-resolve-all:
    @echo "Resolving ALL resolvable ingredients..."
    python scripts/resolve_feba_resolvable.py \
        --classification workspace/feba_mappability_classification.yaml \
        --output workspace/feba_resolvable_resolution_all.yaml \
        --priority ALL

# Generate TSV export of FEBA uncovered ingredients
feba-generate-tsv:
    @echo "Generating FEBA uncovered ingredients TSV..."
    python scripts/generate_feba_uncovered_tsv.py \
        --uncovered-report workspace/feba_uncovered_report.yaml \
        --classification-report workspace/feba_mappability_classification.yaml \
        --output FEBA_UNCOVERED_INGREDIENTS.tsv
    @echo "✅ TSV generated: FEBA_UNCOVERED_INGREDIENTS.tsv"

# Run complete FEBA analysis workflow
feba-analyze: feba-extract-uncovered feba-map-variants feba-classify feba-resolve-high feba-generate-tsv
    @echo ""
    @echo "====================================================================="
    @echo "FEBA Analysis Complete!"
    @echo "====================================================================="
    @echo "Generated files:"
    @echo "  - workspace/feba_uncovered_ingredients.txt"
    @echo "  - workspace/feba_uncovered_report.yaml"
    @echo "  - workspace/feba_notation_mapping_results.yaml"
    @echo "  - workspace/feba_mappability_classification.yaml"
    @echo "  - FEBA_UNCOVERED_INGREDIENTS.tsv"
    @echo ""
    @cat FEBA_UNCOVERED_INGREDIENTS.tsv | wc -l | awk '{print "Total rows: " $1-1 " ingredients"}'

# =============================================================================
# CAS-RN Integration Workflows
# =============================================================================

# Export unmapped CAS-RN ingredients to TSV
cas-export-unmapped:
    @echo "Exporting unmapped CAS-RN ingredients..."
    python scripts/export_unmapped_cas_rn_tsv.py \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --output workspace/unmapped_cas_rn_ingredients.tsv
    @cp workspace/unmapped_cas_rn_ingredients.tsv UNMAPPED_CAS_RN_INGREDIENTS.tsv
    @echo "✅ TSV generated: UNMAPPED_CAS_RN_INGREDIENTS.tsv"

# =============================================================================
# FEBA Ontology Enrichment Workflows
# =============================================================================

# Analyze FEBA ontology coverage
feba-analyze-ontology:
    @echo "Analyzing FEBA ontology coverage..."
    python scripts/analyze_feba_ontology_coverage.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --output-report workspace/feba_ontology_coverage_report.yaml \
        --output-unmapped workspace/feba_ontology_unmapped_ingredients.txt

# Enrich FEBA ontology mappings using CAS-RN (test mode with 10 ingredients)
feba-enrich-ontology-test:
    @echo "Testing ChEBI enrichment (10 ingredients)..."
    python scripts/enrich_feba_ontology_from_cas.py \
        --ontology-report workspace/feba_ontology_coverage_report.yaml \
        --cas-mapping-results workspace/feba_notation_mapping_results.yaml \
        --cas-resolvable-results workspace/feba_resolvable_resolution_results.yaml \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --output workspace/feba_chebi_enrichment_results.yaml \
        --max-queries 10

# Enrich FEBA ontology mappings using CAS-RN (full run)
feba-enrich-ontology:
    @echo "Enriching FEBA ontology mappings via ChEBI API..."
    python scripts/enrich_feba_ontology_from_cas.py \
        --ontology-report workspace/feba_ontology_coverage_report.yaml \
        --cas-mapping-results workspace/feba_notation_mapping_results.yaml \
        --cas-resolvable-results workspace/feba_resolvable_resolution_results.yaml \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --output workspace/feba_chebi_enrichment_results.yaml
    @echo "✅ Enrichment complete. Check workspace/feba_chebi_enrichment_results.yaml"

# Apply ChEBI enrichments to CultureMech media files (dry-run)
feba-apply-enrichments-dry:
    @echo "Testing enrichment application (dry-run)..."
    python scripts/apply_ontology_enrichments.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --enrichment-file workspace/feba_chebi_enrichment_results.yaml \
        --dry-run

# Apply ChEBI enrichments to CultureMech media files
feba-apply-enrichments:
    @echo "Applying ChEBI enrichments to CultureMech media files..."
    python scripts/apply_ontology_enrichments.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --enrichment-file workspace/feba_chebi_enrichment_results.yaml
    @echo "✅ Enrichments applied to CultureMech media files"

# Update MediaIngredientMech with ChEBI enrichments (dry-run)
feba-update-mim-dry:
    @echo "Testing MediaIngredientMech update (dry-run)..."
    python scripts/update_mim_with_enrichments.py \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --enrichment-file workspace/feba_chebi_enrichment_results.yaml \
        --dry-run

# Update MediaIngredientMech with ChEBI enrichments
feba-update-mim:
    @echo "Updating MediaIngredientMech with ChEBI enrichments..."
    python scripts/update_mim_with_enrichments.py \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --enrichment-file workspace/feba_chebi_enrichment_results.yaml
    @echo "✅ MediaIngredientMech updated"

# Create MIM ingredient files for enriched ingredients (dry-run)
feba-create-mim-ingredients-dry:
    @echo "Testing MIM ingredient file creation (dry-run)..."
    python scripts/create_mim_ingredients_from_enrichments.py \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --enrichment-file workspace/feba_chebi_enrichment_results.yaml \
        --dry-run

# Create MIM ingredient files for enriched ingredients
feba-create-mim-ingredients:
    @echo "Creating MIM ingredient files for enriched ingredients..."
    python scripts/create_mim_ingredients_from_enrichments.py \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --enrichment-file workspace/feba_chebi_enrichment_results.yaml
    @echo "✅ MIM ingredient files created"

# =============================================================================
# Utility Commands
# =============================================================================

# =============================================================================
# Unified Ingredient Mapping
# =============================================================================

# Build unified ingredient mapping across CultureMech, MIM, and CommunityMech
build-unified-mapping:
    @echo "Building unified ingredient mapping..."
    python scripts/build_unified_ingredient_mapping.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --output workspace/unified_ingredient_mapping.tsv
    @echo "✅ Unified mapping: workspace/unified_ingredient_mapping.tsv"

# =============================================================================
# MIM → CultureMech Sync
# =============================================================================

# Sync MIM CHEBI mappings into CultureMech ingredient term.id fields (dry-run)
sync-mim-to-culturemech-dry:
    @echo "Syncing MIM CHEBI → CultureMech (dry-run)..."
    python scripts/sync_mim_to_culturemech.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --mapping workspace/unified_ingredient_mapping.tsv \
        --dry-run

# Sync MIM CHEBI mappings into CultureMech ingredient term.id fields (apply)
sync-mim-to-culturemech:
    @echo "Syncing MIM CHEBI → CultureMech..."
    python scripts/sync_mim_to_culturemech.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --mapping workspace/unified_ingredient_mapping.tsv
    @echo "✅ MIM CHEBI IDs synced to CultureMech ingredient term.id fields"

# =============================================================================
# KG-Microbe Matching Workflows
# =============================================================================

# Match CultureMech media to KG-Microbe nodes (dry-run)
match-culturemech-dry:
    @echo "Testing CultureMech → KG-Microbe matching (dry-run)..."
    python scripts/match_culturemech_to_kg.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --kg-microbe ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe \
        --dry-run

# Match CultureMech media to KG-Microbe nodes (populate kg_microbe_match field)
match-culturemech:
    @echo "Matching CultureMech media to KG-Microbe nodes..."
    python scripts/match_culturemech_to_kg.py \
        --culturemech ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech \
        --kg-microbe ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe
    @echo "✅ CultureMech kg_microbe_match fields populated"

# Match MIM ingredients to KG-Microbe nodes (dry-run)
match-mim-dry:
    @echo "Testing MIM → KG-Microbe matching (dry-run)..."
    python scripts/match_mim_to_kg.py \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --kg-microbe ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe \
        --dry-run

# Match MIM ingredients to KG-Microbe nodes (populate kg_microbe_node_id field)
match-mim:
    @echo "Matching MIM ingredients to KG-Microbe nodes..."
    python scripts/match_mim_to_kg.py \
        --mim ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech \
        --kg-microbe ~/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe
    @echo "✅ MIM kg_microbe_node_id fields populated"

# Run both KG-Microbe matching workflows (dry-run)
match-all-dry: match-culturemech-dry match-mim-dry
    @echo "✅ Dry-run complete"

# Run both KG-Microbe matching workflows
match-all: match-culturemech match-mim
    @echo "✅ All KG-Microbe matches populated"

# =============================================================================
# SSSOM Mapping Product (official MIM→ingredient-ontology artifact; CHEBI + FOODON)
# =============================================================================

# Stage 1: Build the working-copy SSSOM from all MIM ingredient YAMLs
build-sssom:
    @echo "Building MIM→ingredient-ontology SSSOM..."
    python scripts/build_mim_ingredient_sssom.py \
        --output workspace/reports/mim_ingredient_mappings.sssom.tsv
    @echo "Working copy: workspace/reports/mim_ingredient_mappings.sssom.tsv"

# Stage 2: Validate the working-copy SSSOM (JsonSchema + PrefixMap + StrictCurie)
validate-sssom:
    @echo "Validating SSSOM working copy..."
    sssom validate \
        -V JsonSchema \
        -V PrefixMapCompleteness \
        -V StrictCurieFormat \
        workspace/reports/mim_ingredient_mappings.sssom.tsv

# Stage 3: Review synonyms in the working-copy SSSOM via OAK + EBI OLS
review-sssom:
    @echo "Reviewing SSSOM synonyms against ingredient ontologies (OAK + OLS)..."
    python scripts/review_sssom_synonyms.py \
        --input workspace/reports/mim_ingredient_mappings.sssom.tsv \
        --tsv-out workspace/reports/sssom_synonym_review.tsv \
        --md-out workspace/reports/sssom_synonym_review.md

# Stage 3 (alternate): Shard the SSSOM for agent-team review. The orchestrating
# Claude session then dispatches 4 sub-agents via the Agent tool — see the
# team-review-sssom skill. This recipe only handles stage 1 (shard) and the
# final merge; agent dispatch is Claude-side.
review-sssom-team-shard:
    @echo "Sharding SSSOM for agent-team review..."
    python scripts/shard_sssom_for_review.py \
        --input workspace/reports/mim_ingredient_mappings.sssom.tsv \
        --n 4
    @echo ""
    @echo "Shards written to workspace/shards/sssom_review/shard_{0..3}.tsv"
    @echo "Now invoke /team-review-sssom in the main Claude session so it can"
    @echo "dispatch the 4 Agent sub-agents. When their JSONL results are all"
    @echo "under workspace/results/sssom_review_shard_*.jsonl, run:"
    @echo "  just review-sssom-team-merge"

# Stage 3 (alternate, final step): Merge per-shard agent JSONL into the SSSOM.
# Stamps validation_method per row; rows missing from every shard get
# none|UNVERIFIED|{date}.
review-sssom-team-merge:
    @echo "Merging per-shard agent reviews into the SSSOM..."
    python scripts/merge_sssom_shard_reviews.py

# Stage 4: Promote the working copy to MediaIngredientMech/mappings/ (dry-run)
publish-sssom-dry:
    @echo "Previewing SSSOM promotion (dry-run)..."
    python scripts/publish_sssom.py --dry-run

# Stage 4: Promote the working copy to MediaIngredientMech/mappings/
publish-sssom:
    @echo "Promoting SSSOM to MediaIngredientMech/mappings/ ..."
    python scripts/publish_sssom.py --apply

# Full lifecycle: build → validate → review (stops before promote)
sssom-release: build-sssom validate-sssom review-sssom
    @echo ""
    @echo "====================================================================="
    @echo "SSSOM release candidate ready for review"
    @echo "====================================================================="
    @echo "  Working copy: workspace/reports/mim_ingredient_mappings.sssom.tsv"
    @echo "  Review:       workspace/reports/sssom_synonym_review.md"
    @echo ""
    @echo "Next: inspect the review report, then run 'just publish-sssom' to promote."

# =============================================================================
# MIM ↔ kg-microbe Reconciliation Audit
# =============================================================================

# Produce the canonical reconciliation report (AGREE/DISAGREE/MIM_ONLY/
# KGM_ONLY/UNMAPPED_PENDING_CURATION). Feeds every other recipe below.
audit-kgm-mim:
    @echo "Running MIM ↔ kg-microbe reconciliation audit..."
    /opt/homebrew/bin/python3.13 scripts/audit_kgm_mim_reconciliation.py

# Emit MIM YAML patch proposals for ingredients using deprecated CHEBIs.
fix-deprecated-chebi:
    /opt/homebrew/bin/python3.13 scripts/fix_deprecated_chebi.py

# Emit MIM YAML patch proposals for ingredients whose SSSOM object_label
# drifted from CHEBI's canonical label (or whose CHEBI was removed).
fix-label-drift:
    /opt/homebrew/bin/python3.13 scripts/fix_label_drift.py

# OLS round-trip every DISAGREE row in the audit; dedup against the
# 72-row TRUE_BUG run. Classifies each as MIM_WRONG / MIM_OK / AMBIGUOUS.
roundtrip-disagree:
    /opt/homebrew/bin/python3.13 scripts/round_trip_true_bugs.py --source audit

# Build old MediaIngredientMech:000xxx → current MIM:<slug> migration map
# from KGM_ONLY rows in the audit.
generate-migration-map:
    /opt/homebrew/bin/python3.13 scripts/generate_mim_migration_map.py

# Generate kg-microbe xref patches (consumes the migration map). Output
# is the input for a future kg-microbe PR.
generate-kgm-xref-patches:
    /opt/homebrew/bin/python3.13 scripts/generate_kgm_xref_patches.py

# Propose candidate CHEBI IDs for the 430 UNMAPPED_PENDING_CURATION
# entries via OLS search. Slow (API-bound); results are cached.
propose-chebi-unmapped:
    /opt/homebrew/bin/python3.13 scripts/propose_chebi_for_unmapped.py

# Full reconciliation pipeline, in dependency order.
reconcile-all: audit-kgm-mim fix-deprecated-chebi fix-label-drift roundtrip-disagree generate-migration-map generate-kgm-xref-patches

# Build the canonical complex-ingredients artifact (FOODON/ENVO MIM rows
# that kg-microbe's CHEBI-only unified_chemical_mappings.tsv.gz can't
# absorb). Writes a working copy to workspace/reports/.
build-complex-ingredients:
    /opt/homebrew/bin/python3.13 scripts/build_complex_ingredients_tsv.py

# Build AND promote complex_ingredients.tsv{,.gz} to
# MediaIngredientMech/mappings/ — the canonical location consumed by
# kg-microbe on its next unified-mappings rebuild.
publish-complex-ingredients:
    /opt/homebrew/bin/python3.13 scripts/build_complex_ingredients_tsv.py --publish

# Generate the canonical mapping-case taxonomy reference. See
# .claude/skills/mapping-taxonomy/skill.md for what this documents.
mapping-taxonomy:
    /opt/homebrew/bin/python3.13 scripts/generate_mapping_taxonomy_report.py

# Diff MIM's published SSSOM against kg-microbe's consolidated SSSOM on
# the chemical-mappings-mim-priority branch. See
# .claude/skills/kg-microbe-review/skill.md for the full methodology.
kg-microbe-review:
    /opt/homebrew/bin/python3.13 scripts/generate_kg_microbe_review.py

# Inventory all "unmapped / pending-curation" ingredient surfaces across
# the four repos (MIM, kg-microbe, CultureMech, CommunityMech). See
# .claude/skills/unmapped-inventory/skill.md for the sync model.
inventory-unmapped:
    /opt/homebrew/bin/python3.13 scripts/inventory_unmapped_ingredients.py

# Fetch missing PubMed abstracts for every PMID referenced by MIM
# evidence claims. Polite (3 req/s; 10 req/s with NCBI_API_KEY env var).
# See .claude/skills/evidence-reference-validation/skill.md.
fetch-pubmed *args:
    /opt/homebrew/bin/python3.13 scripts/fetch_pubmed_abstracts.py {{args}}

# Verify every literature snippet in MIM evidence claims appears
# verbatim in its cited PubMed abstract. Anti-hallucination gate.
# Exits 2 on SNIPPET_NOT_IN_ABSTRACT (CI blocking).
validate-evidence *args:
    /opt/homebrew/bin/python3.13 scripts/validate_evidence_references.py {{args}}

# Propose PMID + snippet candidates via PubMed search for MIM ingredient
# evidence claims (Phase 4). Outputs to workspace/reports/evidence_proposals/.
# Curators review, paste into MIM YAMLs, then validate-evidence confirms.
# See .claude/skills/evidence-curation/skill.md.
propose-evidence *args:
    /opt/homebrew/bin/python3.13 scripts/propose_evidence.py {{args}}

# Backfill chemical_properties.molecular_formula/smiles/inchi for every
# CHEBI-mapped MIM ingredient using the local CHEBI sqlite. Default
# dry-run; pass --apply to write YAMLs.
backfill-chemistry *args:
    /opt/homebrew/bin/python3.13 scripts/backfill_chebi_chemistry.py {{args}}

# Same for cas:* primaries via PubChem REST (CAS → CID → properties).
# Cached to workspace/cache/pubchem_cas_chemistry.json.
backfill-cas-chemistry *args:
    /opt/homebrew/bin/python3.13 scripts/backfill_cas_chemistry.py {{args}}

# Apply propose-evidence drafts: parse workspace/reports/evidence_proposals/
# and append validated literature evidence (Phase 1 substring check) to
# the target MIM YAMLs. Default dry-run; pass --apply to write YAMLs.
apply-evidence *args:
    /opt/homebrew/bin/python3.13 scripts/apply_evidence_proposals.py {{args}}

# Generate the curator-review report covering UNDEFINED_MIXTURE
# classifications + unset records, with heuristic suggestions and an
# `action` column for batch overrides. Read-only.
review-classifications:
    /opt/homebrew/bin/python3.13 scripts/review_ingredient_classifications.py

# Cascading multi-ontology resolver for heuristic-complex MIM
# ingredients (yeast extract, peptone, soil, manure, milk, etc.).
# FOODON → ENVO → CHEBI → NCIT via OLS, with token-subset re-scoring.
# See .claude/skills/complex-ingredient-resolver/skill.md.
foodon-pass *args:
    /opt/homebrew/bin/python3.13 -u scripts/foodon_pass.py {{args}}

# Detect MIM mappings where the ontology term is more general than the
# named ingredient (e.g. "Vermont Soil" → ENVO:soil). Read-only review.
# See .claude/skills/specificity-loss-review/skill.md.
detect-specificity-loss:
    /opt/homebrew/bin/python3.13 scripts/detect_specificity_loss.py

# Mint a kgmicrobe.ingredient:* custom term to preserve specificity.
# See .claude/skills/specificity-loss-review/skill.md.
#   just mint-kgm-ingredient --slug Vermont_Soil
#   just mint-kgm-ingredient --from-tsv workspace/reports/specificity_loss_review.tsv
mint-kgm-ingredient *args:
    /opt/homebrew/bin/python3.13 scripts/mint_kgm_ingredient.py {{args}}

# Import a new ingredient/compound source into MIM. See
# .claude/skills/ingredient-mapping/skill.md for the full source→resolver→emit
# cascade. Defaults to dry-run; pass --apply to write YAMLs.
#
# Examples:
#   just import-ingredients --source culturebotht --apply
#   just import-ingredients --source kgm-unmapped --apply
#   just import-ingredients --source mim-queue --apply --accept-medium
import-ingredients *ARGS:
    /opt/homebrew/bin/python3.13 scripts/import_ingredients.py {{ARGS}}

# =============================================================================
# Utility Commands
# =============================================================================

# Clean workspace directory
clean:
    @echo "Cleaning workspace..."
    rm -rf workspace/feba_*
    rm -rf workspace/unmapped_*
    @echo "✅ Workspace cleaned"

# View FEBA uncovered TSV
view-feba-tsv:
    @if [ -f FEBA_UNCOVERED_INGREDIENTS.tsv ]; then \
        head -20 FEBA_UNCOVERED_INGREDIENTS.tsv | column -t -s$$'\t'; \
        echo ""; \
        echo "Showing first 20 rows. Total:"; \
        wc -l FEBA_UNCOVERED_INGREDIENTS.tsv; \
    else \
        echo "FEBA_UNCOVERED_INGREDIENTS.tsv not found. Run 'just feba-analyze' first."; \
    fi

# View unmapped CAS-RN TSV
view-cas-tsv:
    @if [ -f UNMAPPED_CAS_RN_INGREDIENTS.tsv ]; then \
        head -20 UNMAPPED_CAS_RN_INGREDIENTS.tsv | column -t -s$$'\t'; \
        echo ""; \
        echo "Showing first 20 rows. Total:"; \
        wc -l UNMAPPED_CAS_RN_INGREDIENTS.tsv; \
    else \
        echo "UNMAPPED_CAS_RN_INGREDIENTS.tsv not found. Run 'just cas-export-unmapped' first."; \
    fi
