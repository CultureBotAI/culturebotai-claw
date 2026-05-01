---
name: evidence-curation
description: Auto-propose PMID + snippet candidates for MIM ingredient evidence claims via PubMed search. Bridges Phase 1 (validation) by giving curators a starter set of real, validatable references — they pick the best, paste into YAML, and the validator confirms snippet integrity. Phase 4 of the dismech-pattern port.
category: curation
requires_database: false
requires_internet: true
version: 1.0.0
tags: [mim, evidence, literature, pubmed, curation, dismech]
---

# Evidence Curation Skill

## Purpose

Phase 1 (`evidence-reference-validation`) catches AI-hallucinated
snippets but does nothing to *generate* the literature claims in the
first place. Curators previously had two options:

1. Hand-search PubMed and paste citations — slow, error-prone.
2. Ask an LLM to propose evidence — high hallucination risk.

This skill provides a third path: **deterministic, NCBI-grounded
proposals**. For any MIM ingredient (or batch), it queries PubMed via
E-utilities, fetches abstracts into the existing `references_cache/`,
and emits draft `MappingEvidence` YAML blocks the curator can review,
edit, and paste in. The Phase 1 validator then confirms the snippet
appears in the cited abstract — closing the loop.

## Pipeline

```
   ┌──────────────────────────────────────────────────────────┐
   │  Step 1 — Search                                         │
   │   PubMed esearch(<term> AND (culture OR medium ...))     │
   │   biased toward microbiology context                     │
   └────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Step 2 — Fetch (if not cached)                          │
   │   E-utilities efetch → references_cache/PMID_*.md        │
   │   (shares cache with Phase 1 fetcher)                    │
   └────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Step 3 — Snippet extraction                             │
   │   Sentences containing the ingredient name (case-ins.)   │
   │   Top 2 per abstract                                     │
   └────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Step 4 — Render draft MappingEvidence YAML              │
   │   workspace/reports/evidence_proposals/<slug>.md         │
   │   ready for curator copy-paste                           │
   └──────────────────────────────────────────────────────────┘
                            │
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Step 5 — Curator action (manual)                        │
   │   Pick best snippet, paste into MIM YAML, edit           │
   │   `explanation` to match the actual claim                │
   └────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Step 6 — Validate (Phase 1)                             │
   │   `just validate-evidence` confirms snippet ⊂ abstract   │
   └──────────────────────────────────────────────────────────┘
```

The skill **never auto-commits**. Curators always review proposals
before merging — the script just removes the discovery step.

## Run it

```bash
# Single ingredient by slug
python3 scripts/propose_evidence.py --slug Glucose

# Single ingredient by YAML path
python3 scripts/propose_evidence.py \
  --yaml ../MediaIngredientMech/data/ingredients/mapped/Lactose.yaml

# Batch: top N high-occurrence CHEBI ingredients
python3 scripts/propose_evidence.py --top-occurrences 50

# With NCBI API key (10 req/s vs 3)
NCBI_API_KEY=xxx python3 scripts/propose_evidence.py --top-occurrences 50

# Or via just
just propose-evidence -- --slug Glucose
just propose-evidence -- --top-occurrences 50
```

Output:

- `workspace/reports/evidence_proposals/<slug>.md` — per-ingredient
  draft with 1-N candidate `MappingEvidence` YAML blocks
- `workspace/reports/evidence_proposals/_summary.md` — batch index
  with hit counts

## Heuristics + caveats

The PubMed query is intentionally simple:

```
("<preferred_term>"[Title/Abstract])
  AND (culture OR medium OR growth OR microbial)
```

This biases toward microbiology context. The snippet picker takes the
first 2 sentences containing the ingredient name (case-insensitive
substring). **Both are heuristics** — they trade recall for speed and
cache stability.

Where they fail:

- **Generic substances** (water, NaCl, glucose) — too many hits;
  the bias terms barely narrow it. Curator should pick a more
  specific paper.
- **Trade names** (Bacto Yeast Extract, Difco) — PubMed often uses
  generic names; trade-name search may miss relevant work.
- **Negation** — "without distilled water" is a substring match. The
  curator's `supports` review catches this.

Future upgrades (deferred — see Phase 4 plan):

- Plug in a deep-research provider (Falcon / Perplexity / OpenAI) for
  semantic relevance ranking
- Use ingredient `chemical_properties.cas_rn` as alternate search key
- Fine-tune snippet ranking by semantic similarity to the
  `preferred_term`

## What the skill never does

- Modifies any MIM YAML (writes only to `workspace/reports/`)
- Commits anything to git
- Calls an LLM (no hallucination surface)
- Bypasses the Phase 1 validator (every committed snippet still gets
  checked)

## Files

| Path | Role |
|---|---|
| `.claude/skills/evidence-curation/skill.md` | This file |
| `scripts/propose_evidence.py` | Entry point + driver |
| `scripts/fetch_pubmed_abstracts.py` | Shared cache fetcher (Phase 1) |
| `MediaIngredientMech/references_cache/PMID_*.md` | Shared abstract cache |
| `workspace/reports/evidence_proposals/` | Draft outputs |

## Dependencies

- Python 3 + `pyyaml`
- Internet (NCBI E-utilities)
- Phase 1 schema slots (pmid/snippet/supports) on MIM `MappingEvidence`

## Related skills

- `evidence-reference-validation` (Phase 1) — closes the loop
- `unmapped-inventory` — surfaces *what* needs evidence
- `ingredient-mapping` — produces the YAMLs that get evidence-curated
- `mapping-taxonomy` — verdict / status reference

## Phase 4 status

- ✅ PubMed-search-based proposer
- ✅ Skill documentation
- ✅ Slash command (`.claude/commands/curate.md`)
- ⏳ Deep-research provider integration (deferred — needs provider
  choice + credentials)
- ⏳ `claude-code-review.yml` workflows in each mech repo
- ⏳ `cross-repo-validation.yaml` daily QC scan
- See `docs/proposals/phase4_post_review_agent_and_cross_repo_workflows.md`
