---
name: publish-sssom
description: Build, validate, review, and promote the canonical MIM→ingredient-ontology SSSOM mapping file (CHEBI + FOODON) — the official cross-repo ingredient mapping artifact
category: release
requires_database: true
requires_internet: true
version: 1.0.0
tags: [sssom, chebi, mim, release, mapping, cross-repo, provenance]
---

# Publish SSSOM Skill

## Purpose

`mim_ingredient_mappings.sssom.tsv` is the **authoritative chemical/ingredient
mapping artifact** consumed by every downstream repo (CultureMech,
CommunityMech, kg-microbe, external integrators). This skill runs its
4-stage release lifecycle:

```
 build → validate → review → promote
```

Every stage is a gate. A failure at any stage halts the release and
leaves the previously-published copy untouched.

## The four stages

### 1. Build

```bash
just build-sssom
# or:
python scripts/build_mim_ingredient_sssom.py --output workspace/reports/mim_ingredient_mappings.sssom.tsv
```

Scans all MIM ingredient YAMLs with a CHEBI `ontology_id`, emits one
SSSOM row per record with:

- **Predicate richness** — `skos:exactMatch` by default, upgraded to
  `skos:narrowMatch` / `skos:broadMatch` / `skos:closeMatch` using the
  residual-P2.5 categorization (`workspace/reports/kg_microbe_residual_p25_categorized.json`).
- **Source column** — pipe-separated `MIM:<evidence>|MIM:curator=<name>|kgm:<sources>...` drawn
  from the MIM YAML `ontology_mapping.evidence` + `curation_history` and
  from `kg-microbe/mappings/unified_chemical_mappings.tsv.gz`.
- **Dates** — taken from the most recent `curation_history` entry so the
  SSSOM mapping_date reflects the curation provenance, not the build
  machine's clock.
- **Other column** — alternate labels from kg-microbe and MIM synonyms
  (excluding role/property RAW_TEXT entries that aren't chemical names).

Expected output (≈1,100 rows):

| Predicate | Count | Meaning |
|---|---:|---|
| `skos:exactMatch` | ~900 | MIM identifier is the CHEBI identifier |
| `skos:closeMatch` | ~90 | SYMMETRIC — both sides defensible |
| `skos:narrowMatch` | ~75 | CONSIDER_SPECIFIC — MIM is more generic than the chosen CHEBI |

The builder auto-runs `sssom validate` against its own output and
exits 2 on hard errors before the file is considered built.

### 2. Validate

```bash
just validate-sssom
```

Runs the full validation suite (JsonSchema, PrefixMapCompleteness,
StrictCurieFormat) against the working-copy file. The builder already
did this internally; this recipe exists so reviewers can independently
re-validate an artifact they didn't build. Exits non-zero on any hard
error.

### 3. Review

```bash
just review-sssom
```

Invokes the **synonym-review** skill to cross-check every row's label
and `other` synonyms against CHEBI via OAK (local sqlite) and EBI OLS4.
Produces:

- `workspace/reports/sssom_synonym_review.tsv` — per-row verdict
- `workspace/reports/sssom_synonym_review.md` — bucketed summary

Promote only if:

- Zero `LABEL_MISMATCH` (our object_label really is a CHEBI label/synonym)
- Zero `UNKNOWN_TERM` (every term ID resolves)
- `OLS_MISMATCH` count is small and understood (normally a stale local
  CHEBI sqlite — refresh with `rm ~/.data/oaklib/chebi.db` and rerun)
- `SYNONYM_ENRICH` rows are acceptable: each represents an alternate
  label we think CHEBI should adopt as a synonym. These are **candidate
  upstream proposals**, not blockers.

### 4. Promote

```bash
just publish-sssom
```

Copies the working-copy file to the canonical publish location:

```
MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv
```

Promotion acquires the `mediaingredientmech` lock through
`plugins.lock_manager.LockManager` (see `CLAUDE.md` → "Lock System").
If the lock is held by another agent, promotion waits — do NOT
force-release. Emits a `curation_history`-style log entry in
`workspace/status/sssom_promotions.jsonl` with the file hash, row
count, and validator results so the release is auditable.

## When to run each stage

| Trigger | Stages |
|---|---|
| MIM ingredient YAML added/changed | build → validate |
| Weekly "all green" release | build → validate → review → promote |
| kg-microbe sources refreshed | build → validate (source column changes) |
| Proposing CHEBI synonyms upstream | build → validate → review (then export `SYNONYM_ENRICH` rows) |
| Residual-P2.5 categorization reran | build → validate → review (predicates may shift) |

## Working-copy vs. published file

| Path | Who writes it | How often | Visibility |
|---|---|---|---|
| `workspace/reports/mim_ingredient_mappings.sssom.tsv` | `build-sssom` | Every build, overwritten freely | Local / PR reviewer |
| `MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv` | `publish-sssom` only | Only after all 4 stages pass | Committed to MIM, distributed |

## Artifact invariants (published file)

Every released copy MUST satisfy:

1. SSSOM validation clean under JsonSchema + PrefixMapCompleteness + StrictCurieFormat
2. Every `object_id` resolves in OAK **or** OLS (no `UNKNOWN_TERM`)
3. Every `object_label` is CHEBI's rdfs:label or one of its synonyms (no `LABEL_MISMATCH`)
4. Row count ≥ last published count minus 5 (guards against accidental truncation)
5. `mapping_set_version` equals the build date, UTC
6. `source` column populated for ≥95% of rows

## Dependencies

- `uv` / Python 3.x + `pyyaml`
- `sssom` CLI (sssom-py 0.4.17 or compatible) on PATH
- `runoak` (oaklib) on PATH, for the review stage
- Internet access for EBI OLS4, for the review stage
- MIM repo checkout at `MediaIngredientMech/` (read/write)
- kg-microbe repo checkout at `kg-microbe/` (read-only)

## Files

| Path | Role |
|---|---|
| `scripts/build_mim_ingredient_sssom.py` | The builder (stage 1) |
| `scripts/review_sssom_synonyms.py` | The reviewer (stage 3; invoked via `synonym-review` skill) |
| `scripts/publish_sssom.py` | The promoter (stage 4) |
| `workspace/reports/mim_ingredient_mappings.sssom.tsv` | Working-copy output |
| `workspace/reports/sssom_synonym_review.{tsv,md}` | Review stage output |
| `workspace/status/sssom_promotions.jsonl` | Audit log of every promotion |
| `MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv` | Canonical published file |

## Related skills

- `synonym-review` — executes stage 3
- `cross-repo-sync` — rebuild unified ingredient mapping; run after a
  publish so downstream CHEBI backfills use the new canonical data
- `review-ingredients` (MIM) — the upstream curation pipeline that
  populates the ingredient YAMLs this skill reads
