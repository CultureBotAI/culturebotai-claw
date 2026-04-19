---
name: synonym-review
description: Cross-check the synonyms asserted in an SSSOM mapping TSV against CHEBI via OAK (local sqlite) and EBI OLS4 — flag label mismatches, drift between the two authorities, and propose-to-CHEBI synonym-enrichment candidates
category: validation
requires_database: true
requires_internet: true
version: 1.0.0
tags: [sssom, chebi, oak, ols, synonyms, validation, provenance]
---

# Synonym Review Skill

## When to use

Run this after regenerating an SSSOM mapping file (such as
`workspace/reports/residual_p25_mappings.sssom.tsv`) to **verify the
synonym assertions** — the `object_label` plus the pipe-separated
`other` column plus `subject_label` — are all grounded in CHEBI and to
surface new candidate synonyms worth proposing upstream.

Typical triggers:

- After `generate_residual_p25_sssom.py` or any other SSSOM emitter runs
- Before filing a batch of CHEBI synonym proposals in the ChEBI issue tracker
- When a reviewer reports that a mapping's label "doesn't look right" and
  you need an authority check

## What it does

The reviewer pipeline:

1. **Preflight: `sssom validate`** — shells out to the official
   `sssom` CLI (`sssom-py`) with validators `JsonSchema`,
   `PrefixMapCompleteness`, and `StrictCurieFormat`. If any hard
   errors appear (malformed row, unregistered prefix, missing
   `predicate_id`, non-CURIE where a CURIE is required) the reviewer
   **exits 2** without running — bad input is rejected before we
   waste OAK/OLS quota. Pass `--skip-validate` to bypass.
2. Fetches CHEBI's **labels + exact + related synonyms** via OAK against
   a local `sqlite:obo:chebi` (OBO-semantics, predicate-aware)
3. Fetches CHEBI's published synonyms via **EBI OLS4 REST**
4. Compares both against the row's `object_label`, `subject_label`, and
   each `|`-separated term in the `other` column

Each row is assigned one of five verdicts:

| Verdict | Meaning | Action |
|---|---|---|
| `CONFIRMED` | every label appears in OAK or OLS — mapping is well-grounded | None |
| `SYNONYM_ENRICH` | at least one alternate label is unknown to both authorities | Candidate to propose as a new CHEBI synonym |
| `LABEL_MISMATCH` | our `object_label` is not the CHEBI rdfs:label and not an exact synonym | Likely a data bug — fix in the mapping generator |
| `OLS_MISMATCH` | OAK and OLS disagree by ≥3 terms each way | Local sqlite is stale or OLS is out of sync; check CHEBI release |
| `UNKNOWN_TERM` | neither OAK nor OLS resolve the term ID | Deprecated / obsolete ID; fix in the source MIM YAML |

## Run it

```bash
# default: reviews workspace/reports/residual_p25_mappings.sssom.tsv
python scripts/review_sssom_synonyms.py

# spot-check first 20 rows
python scripts/review_sssom_synonyms.py --limit 20

# point at a different SSSOM file
python scripts/review_sssom_synonyms.py \
    --input workspace/reports/other_mappings.sssom.tsv \
    --tsv-out workspace/reports/other_review.tsv \
    --md-out workspace/reports/other_review.md
```

Outputs:
- `workspace/reports/sssom_synonym_review.tsv` — per-row verdict with
  CHEBI ID, verdict, new-candidate labels, and disagreement details
- `workspace/reports/sssom_synonym_review.md` — bucketed summary
  with the top 30 rows per attention bucket

## Caching

To keep reruns polite and fast:
- OLS responses → `workspace/.cache/ols/{CHEBI_NNN}.json`
- OAK alias tables → `workspace/.cache/oak/aliases_<hash>.tsv`

Delete the cache directories to force a re-fetch (e.g. after a CHEBI release).

## Dependencies

- **OAK (`runoak`)** — `pip install oaklib` (already on PATH in this env)
  - On first run, OAK downloads CHEBI sqlite (~1.5 GB) to `~/.data/oaklib/`
- **`sssom` CLI (sssom-py)** — `pipx install sssom-py` or `brew install sssom`
  - Used for the preflight `sssom validate` step. The reviewer detects it
    via `$PATH` and falls back to a clear error message if missing.
  - Pinned / tested against sssom-py **0.4.17**; the Shacl validator is
    intentionally not invoked because that version has a known crash in it.
- **Python stdlib only** — no extra packages for OLS (uses `urllib.request`)

## Input SSSOM schema expectations

The reviewer reads these columns from the input (YAML frontmatter
comment lines beginning with `#` are skipped):

Required: `subject_id`, `object_id`, `object_label`
Optional: `subject_label`, `other` (pipe-separated alternate labels)

Extra columns (including the custom `source` provenance column emitted
by `generate_residual_p25_sssom.py`) are preserved in the input but
ignored by the reviewer.

## Why two authorities

CHEBI is served to downstream consumers through two independent
channels: the OWL release (which OAK mirrors into sqlite) and the
CHEBI database that OLS4 crawls. They **do** drift — OAK sees the most
recent OWL; OLS sees the most recent database snapshot. Agreement
between them is a stronger signal than either alone.

When they disagree by ≥3 labels per side, we don't pick a winner — we
flag `OLS_MISMATCH` so the reviewer can check the CHEBI release notes
and decide whether to refresh the local sqlite
(`rm ~/.data/oaklib/chebi.db` then rerun).

## Related files

| File | Role |
|---|---|
| `scripts/review_sssom_synonyms.py` | The reviewer (invoked by this skill) |
| `scripts/generate_residual_p25_sssom.py` | Produces the primary SSSOM input with the `source` column |
| `workspace/reports/residual_p25_mappings.sssom.tsv` | Default input |
| `workspace/reports/sssom_synonym_review.tsv` | Per-row verdicts |
| `workspace/reports/sssom_synonym_review.md` | Bucketed summary |

## Provenance / `source` column

The SSSOM file emitted by `generate_residual_p25_sssom.py` carries a
`source` extension column with pipe-separated origins:

- `MIM:<evidence-source>` — from the MIM YAML `ontology_mapping.evidence[].source`
  (e.g. `MIM:CultureMech`, `MIM:manual curation`, `MIM:PubChem`)
- `MIM:curator=<name>` — the last `curation_history[].curator` on the
  MIM YAML (e.g. `cbclaw_kg_microbe_sweep`, `fetch_cas_rn_from_pubchem`)
- `kgm:<sources>` — one entry per source that contributed the CHEBI in
  `kg-microbe/mappings/unified_chemical_mappings.tsv.gz` (e.g.
  `kgm:chebi_xrefs`, `kgm:mediadive_compounds`, `kgm:bacdive_metabolites`,
  `kgm:primary_mappings[kegg_compound]`, `kgm:culturebotai_reviewed`)

The column is declared in the header as a `cbclaw:provenance-source`
extension so SSSOM validators accept it as free text rather than a
CURIE. The reviewer ignores the column — it's there for downstream
humans and for issue filing.

## Related skills

- `team-review-sssom` — parallel agent-team variant of this skill.
  Four sub-agents review row-shards in parallel, each emitting a
  per-row verdict with a human-readable `notes` field; stamps the
  same `validation_method` column. Use for release gates and
  audit-worthy reviews. Adds a sixth `UNVERIFIED` verdict for rows
  the agents couldn't classify.
- `review-ingredients` (MediaIngredientMech) — upstream curator that
  produces the kg-microbe sweep reports feeding the SSSOM generator
- `cross-repo-sync` (this repo) — rebuilds the unified ingredient
  mapping that the SSSOM file depends on
