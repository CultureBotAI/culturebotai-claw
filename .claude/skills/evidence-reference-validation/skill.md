---
name: evidence-reference-validation
description: Anti-hallucination gate for literature evidence in MIM ingredient YAMLs. Verifies that every snippet attached to an ontology-mapping or role-assignment evidence claim appears verbatim in the cached PubMed abstract for the cited PMID. Phase 1 of the dismech-pattern port; the foundation for KGX `publications` propagation, automated curation review, and per-ingredient HTML evidence sections.
category: curation
requires_database: false
requires_internet: true
version: 1.0.0
tags: [mim, evidence, literature, pubmed, validation, anti-hallucination, dismech]
---

# Evidence Reference Validation Skill

## Purpose

A literature snippet on an evidence claim is only useful if it
**actually appears in the cited paper**. Curators (human or AI) sometimes
paste plausible-sounding sentences that no abstract ever contained —
either through honest paraphrasing or LLM hallucination. This skill
catches that.

For every MIM evidence item with a `pmid` + `snippet`, it:

1. Looks up the cached abstract at
   `MediaIngredientMech/references_cache/PMID_NNNNNNNN.md`.
2. Normalizes both texts (NFKC + collapsed whitespace + lowercase).
3. Confirms the snippet appears as a substring.

If not, the row gets `SNIPPET_NOT_IN_ABSTRACT` — a blocking failure
in MIM CI.

## Pipeline

```
   ┌────────────────────────────────────────────────────────────┐
   │  Step 1 — Fetch                                              │
   │                                                              │
   │  scripts/fetch_pubmed_abstracts.py                          │
   │   - Walks every MIM YAML, harvests pmids                   │
   │   - Fetches missing ones via NCBI E-utilities (3 req/s)    │
   │   - Caches as references_cache/PMID_NNNN.md (committed)    │
   └─────────────────────┬──────────────────────────────────────┘
                         │
                         ▼
   ┌────────────────────────────────────────────────────────────┐
   │  Step 2 — Validate                                          │
   │                                                              │
   │  scripts/validate_evidence_references.py                    │
   │   - Walks every MIM YAML                                    │
   │   - For each evidence item: checks snippet ⊂ cached abstract│
   │   - Emits per-row verdicts in workspace/reports/             │
   │   - Exits 2 on SNIPPET_NOT_IN_ABSTRACT (CI blocks)          │
   └────────────────────────────────────────────────────────────┘
```

## Verdicts

| Verdict | Meaning | Action |
|---|---|---|
| `OK` | Snippet found in cached abstract | None |
| `NO_EVIDENCE` | PMID/DOI cited without supporting snippet | Curator should add a snippet (warning, not blocking) |
| `MISSING_REFERENCE` | Snippet provided but no PMID/DOI | Curator must add a citation |
| `MISSING_CACHE` | PMID referenced but abstract not yet fetched | Run `fetch_pubmed_abstracts.py` |
| `SNIPPET_NOT_IN_ABSTRACT` | Snippet text does not appear in abstract | **Blocking.** Fix the snippet (paraphrase → verbatim quote) or remove the citation |

`SNIPPET_NOT_IN_ABSTRACT` is the anti-hallucination signal: zero
tolerance in CI.

## Run it

```bash
# Step 1 — refresh the cache (polite to NCBI)
python3 scripts/fetch_pubmed_abstracts.py
# With NCBI API key (10 req/s instead of 3):
NCBI_API_KEY=xxx python3 scripts/fetch_pubmed_abstracts.py
# Limit per-run (e.g. for big initial backfill):
python3 scripts/fetch_pubmed_abstracts.py --limit 200
# Specific PMIDs:
python3 scripts/fetch_pubmed_abstracts.py --pmids 12345678 87654321

# Step 2 — validate
python3 scripts/validate_evidence_references.py
# CI mode: also fails on MISSING_CACHE (forces full pre-fetch):
python3 scripts/validate_evidence_references.py --strict
```

Or via just:

```bash
just fetch-pubmed
just validate-evidence
```

Outputs:

- `workspace/reports/evidence_reference_validation.tsv` — per-row verdicts
- `workspace/reports/evidence_reference_validation.md` — bucketed summary

## Schema slots used

`MappingEvidence` (in `mediaingredientmech.yaml`) and `RoleCitation`:

| Slot | Type | Notes |
|---|---|---|
| `pmid` | string, `^[0-9]+$` | PubMed ID; primary citation key |
| `doi` | string, `^10\.\d{4,}/...` | Optional DOI; not yet validated against cache |
| `snippet` | string | Verbatim quote from abstract |
| `supports` | `EvidenceSupportEnum` | SUPPORT / PARTIAL / REFUTE / NO_EVIDENCE / WRONG_STATEMENT |
| `explanation` | string | Curator's rationale (separate from snippet) |

The `excerpt` slot in legacy `RoleCitation` is treated equivalent to
`snippet` for backward compatibility.

## When to use

| Trigger | Run |
|---|---|
| Before opening a curation PR | both steps |
| In CI on every push | `validate_evidence_references.py --strict` |
| After adding a new evidence claim manually | both steps |
| After backfilling PMIDs via `evidence-curation` skill (Phase 4) | both steps |
| Periodic audit (weekly) | `weekly-compliance.yaml` (Phase 4) |

## Cache hygiene

- Cache lives at `MediaIngredientMech/references_cache/PMID_*.md`
  and IS committed (small, deterministic, supports offline validation).
- Each abstract is ~2-5 KB; even at 1,000 PMIDs the cache is < 5 MB.
- To re-fetch a stale entry: delete the MD file, rerun the fetcher.
- The fetcher is idempotent — only fetches missing entries.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| All `MISSING_CACHE` | Cache empty or git-ignored | Run fetcher; verify `references_cache/` exists in MIM repo |
| New `SNIPPET_NOT_IN_ABSTRACT` after a clean run | Curator paraphrased the snippet instead of quoting | Paste the exact abstract substring; or change snippet to match |
| HTTP 429 from NCBI | Rate limit | Set `NCBI_API_KEY` env var; or pass `--rate 1.0` |
| Snippet has typography (smart quotes) | Unicode mismatch | The validator NFKC-normalizes; check source XML for unusual characters |

## Files

| Path | Role |
|---|---|
| `.claude/skills/evidence-reference-validation/skill.md` | This file |
| `scripts/fetch_pubmed_abstracts.py` | Cache fetcher (Step 1) |
| `scripts/validate_evidence_references.py` | Validator (Step 2) |
| `MediaIngredientMech/references_cache/` | Cache directory (committed) |
| `MediaIngredientMech/src/mediaingredientmech/schema/mediaingredientmech.yaml` | Schema with extended MappingEvidence |
| `workspace/reports/evidence_reference_validation.{tsv,md}` | Output |

## Dependencies

- Python 3 + `pyyaml` (stdlib otherwise)
- Internet access for the fetcher (NCBI E-utilities)
- Local LinkML schema with the Phase 1 evidence slots
- No DB, no OAK, no OLS

## Related skills

- `unmapped-inventory` — produces the curation backlog this skill
  validates downstream
- `ingredient-mapping` — creates the YAMLs whose evidence this validates
- `publish-sssom` — eventually consumes the validated evidence
- `evidence-curation` (Phase 4) — auto-proposes PMID + snippet candidates
- `mapping-taxonomy` — canonical reference for verdict vocabularies

## Phase 1 status

- ✅ Schema extended (`MappingEvidence` adds `pmid`, `doi`, `snippet`,
  `supports`, `explanation`; new `EvidenceSupportEnum`)
- ✅ Cache fetcher
- ✅ Validator
- ✅ Skill documentation (this file)
- ⏳ MIM `just qc` integration
- ⏳ Pilot backfill (50 high-occurrence records)
- See `docs/proposals/phase1_evidence_schema_and_reference_validator.md`
  for the full plan.
