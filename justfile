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
