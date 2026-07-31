# Phase 1: EvidenceItem schema + reference validator (foundation)

**Status:** Draft
**Audience:** MIM maintainers; secondary CultureMech / CommunityMech
**Date:** 2026-05-01
**Source pattern:** `monarch-initiative/dismech` — `src/dismech/schema/dismech.yaml` + `.claude/skills/dismech-references/SKILL.md` + `references_cache/`

## Goal

Make every MIM evidence claim **traceable to a literature citation** with a
verifiable abstract snippet. Unblocks Phases 3-5 (which all consume
publication-evidence).

Today MIM's `ontology_mapping.evidence[]` carries `evidence_type`,
`source`, and free-form `notes`. There is no PMID/DOI slot, no snippet
field, and no validator. Curators can — and do — paste plausible-looking
prose that no human or machine has verified against a real abstract.

## Scope

**In scope:**
- LinkML schema extension to MIM ingredient YAML
- Reference cache infrastructure (cached PubMed abstracts as MD files)
- `linkml-reference-validator` Python script + skill in claw
- `just qc` integration in MIM
- One backfill pass on existing high-priority records (~50)

**Out of scope (later phases):**
- Backfilling all ~1,730 MIM records (curation-hour-heavy; phased)
- CultureMech / CommunityMech port (Phase 5 follow-up — same schema fragment)
- KGX export use of new fields (Phase 3)

## Critical files

| Path | Kind | Reason |
|---|---|---|
| `MediaIngredientMech/schema/mim.yaml` (or wherever LinkML lives) | EXTEND | Add EvidenceItem class with `reference`, `snippet`, `supports`, `explanation` |
| `MediaIngredientMech/references_cache/PMID_NNNNNNNN.md` | NEW DIR | Cached PubMed abstracts, one MD per PMID |
| `culturebotai-claw/scripts/validate_evidence_references.py` | NEW | Validator: snippet substring match against cache |
| `culturebotai-claw/scripts/fetch_pubmed_abstracts.py` | NEW | E-utilities client; populates references_cache |
| `culturebotai-claw/.claude/skills/evidence-reference-validation/SKILL.md` | NEW | Skill wrapping the validator |
| `MediaIngredientMech/justfile` | EXTEND | `qc-evidence` recipe; gate in `just qc` |
| `culturebotai-claw/justfile` | EXTEND | `validate-evidence` recipe |

## EvidenceItem schema fragment

Adopt dismech's exact slot names so the validator port is direct:

```yaml
EvidenceItem:
  attributes:
    reference:
      description: PMID:NNNNNNNN or DOI:10.xxxx/yyy
      pattern: '^(PMID:\d+|DOI:10\..+)$'
    supports:
      enum: [SUPPORT, REFUTE, PARTIAL, NO_EVIDENCE, WRONG_STATEMENT]
    snippet:
      description: Exact substring quoted from abstract
    explanation:
      description: Why this evidence supports/refutes the claim
    evidence_type:    # existing slot, retain
    source:           # existing slot, retain
    notes:            # existing slot, retain
```

## Execution order

1. **Schema patch**: extend `MediaIngredientMech/schema/mim.yaml`
   EvidenceItem; regenerate Python classes; bump version.
2. **Cache fetcher**: `fetch_pubmed_abstracts.py` reads PMIDs from existing
   YAMLs (none today; will be more useful after backfill); fetches title +
   abstract; writes `references_cache/PMID_*.md`. Skips already-cached.
   Polite: 3 req/s, NCBI Entrez API key env var supported.
3. **Validator**: `validate_evidence_references.py` walks every MIM YAML;
   for each evidence item with a `reference` + `snippet`, opens the
   cached abstract; checks snippet appears as substring (after Unicode
   NFKC normalization). Emits per-row verdicts:
   - `OK` — snippet found
   - `MISSING_CACHE` — abstract not in cache (run fetcher)
   - `MISSING_REFERENCE` — evidence has snippet but no PMID
   - `SNIPPET_NOT_IN_ABSTRACT` — likely hallucination → blocking failure
   - `NO_EVIDENCE` — evidence item has no snippet (allowed; warning only)
4. **Skill in claw**: `evidence-reference-validation/skill.md` wraps the
   validator with caching, dry-run, and auto-repair flag (drops
   unverifiable snippets to `notes` field).
5. **MIM `just qc` integration**: add `qc-evidence` recipe; CI gates merges
   on zero `SNIPPET_NOT_IN_ABSTRACT` errors. `MISSING_CACHE` warns but
   doesn't block (curator runs fetcher).
6. **Pilot backfill**: pick 50 high-occurrence MIM records (from
   `occurrence_statistics.total_occurrences`), add real PMIDs +
   snippets via the deep-research skill (Phase 4 dependency — bootstrap
   manually first).

## Verification

After step 5:
- `python3 scripts/validate_evidence_references.py` exits 0 against
  current MIM (validator handles records with no `reference` slot
  gracefully — they're just untouched).
- After step 6 pilot: 50 records show `OK` verdicts.
- `just qc` in MIM blocks if any record has `SNIPPET_NOT_IN_ABSTRACT`.

## What's deferred to later phases

- Bulk backfill of remaining ~1,680 records (Phase 1.5; multi-month)
- Reference enrichment via deep-research provider (Phase 4 unlocks this)
- Schema port to CultureMech / CommunityMech (Phase 5)
- KGX edge `publications` propagation (Phase 3)

## Effort estimate

| Step | Hours |
|---|---:|
| Schema patch + LinkML regen | 4 |
| Cache fetcher | 4 |
| Validator | 8 |
| Skill + docs | 4 |
| `just qc` integration | 2 |
| Pilot backfill (50 records) | 20 |
| **Total** | **~42** |
