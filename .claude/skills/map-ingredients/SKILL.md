---
name: map-ingredients
description: Run the unified ingredient mapping pipeline (openclaw-cli map_ingredients_skill) across CultureMech and MediaIngredientMech — dedupe, LLM + ontology curation, quality gates, canonical store update, sync to both repos. Use when the user invokes /map-ingredients or asks to run the unified ingredient mapping.
---

# Map Ingredients Skill

Execute the unified ingredient mapping pipeline across CultureMech and MediaIngredientMech.

## Usage

When the user invokes `/map-ingredients`, execute the OpenClaw agent for ingredient mapping.

## Instructions

1. Parse any arguments provided by the user (batch-size, threshold, min-occurrences, dry-run)
2. Execute the agent using: `uv run openclaw-cli agent run map_ingredients_skill [args]`
3. Monitor the output and report results to the user
4. If locks fail, check workspace/locks/ for stale locks
5. If execution fails, check logs in workspace/logs/

## Common Commands

**Dry-run (default)**:
```bash
uv run openclaw-cli agent run map_ingredients_skill --batch-size 20 --dry-run
```

**Production run**:
```bash
uv run openclaw-cli agent run map_ingredients_skill --batch-size 50 --threshold 0.85 --min-occurrences 10
```

## Parameters

- `--batch-size N`: Number of ingredients to process (1-100, default: 20)
- `--threshold FLOAT`: Confidence threshold for auto-accepting mappings (0.7-1.0, default: 0.90)
- `--min-occurrences N`: Only process ingredients appearing N+ times (default: 2)
- `--dry-run`: Preview mode, don't save changes (default: true)

## Workflow

The agent will:
1. Extract unmapped ingredients from both repos
2. Deduplicate using exact match, CHEBI ID, and synonym overlap
3. Prioritize by occurrence count
4. Curate with LLM + ontology validation
5. Apply quality gates (auto-accept/manual review/reject)
6. Update canonical store with accepted mappings
7. Sync to both CultureMech and MediaIngredientMech
8. Generate execution report

## Output

Results are saved to:
- `workspace/canonical_ingredients/` - Canonical ingredient store
- `workspace/reports/unified_ingredient_mapping/` - Execution reports
- `workspace/logs/` - Detailed logs
