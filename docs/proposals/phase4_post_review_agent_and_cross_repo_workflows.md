# Phase 4: post-review-agent + cross-repo workflows in claw

**Status:** Draft
**Audience:** culturebotai-claw maintainer; secondary all-repo CI owners
**Date:** 2026-05-01
**Source pattern:** dismech `.github/workflows/post-review-agent.yml` + `claude-code-review.yml` + `weekly-compliance.yaml` + `dragon-ai.yml`; `.claude/commands/curate.md`

## Goal

Lift the **automation infrastructure** from dismech that turns AI-assisted
curation from a manual ritual into a default behavior. Instead of curators
remembering to run validators and skills, GitHub Actions run them
automatically; instead of one-off `/curate` invocations, a slash command
orchestrates the full pipeline.

This phase is the connective tissue between Phase 1 (evidence schema)
and the day-to-day curator workflow. Without it, Phase 1's validators
are voluntary; with it, every PR runs them and every weekly snapshot
shows compliance trends.

## Scope

**In scope:**
- `claude-code-review.yml` workflow in each mech repo — AI review of PRs
- `post-review-agent.yml` cross-repo daily scan — turns reviewer
  comments into suggested-changes commits or follow-up issues
- `weekly-compliance.yaml` — runs Phase 2's QC dashboard generator on a
  schedule; commits the snapshot to a `compliance/` branch
- `/curate` slash command in claw — orchestrates source selection →
  ingredient-mapping → publish-sssom → kg-microbe-review
- `evidence-curation` skill — wraps Phase 1 reference-validator + a
  deep-research provider; suggests PMID + snippet for a given claim
- `ai.just` integration — repo-local hooks layered on the justfile

**Out of scope:**
- New deep-research provider integration (use whichever is already
  available — Falcon, Perplexity, OpenAI; provider-agnostic interface)
- Production ChatOps (Slack/Discord bots) — file/PR-based only
- Editorial review of generated content (curators retain final approval)

## Critical files

| Path | Kind | Reason |
|---|---|---|
| `culturebotai-claw/.github/workflows/cross-repo-validation.yaml` | NEW | Daily; runs validators on all 3 mechs in parallel |
| `culturebotai-claw/.github/workflows/post-review-agent.yaml` | NEW | Hourly; scans review comments, opens follow-up issues |
| `culturebotai-claw/.claude/skills/evidence-curation/SKILL.md` | NEW | Deep-research-backed evidence proposer |
| `culturebotai-claw/.claude/commands/curate.md` | NEW | Slash command orchestrator |
| `culturebotai-claw/scripts/propose_evidence.py` | NEW | Calls deep-research provider; returns PMID+snippet candidates |
| `culturebotai-claw/ai.just` | NEW | Repo-local hooks layered on justfile |
| `MediaIngredientMech/.github/workflows/claude-code-review.yml` | NEW | PR review automation |
| `CultureMech/.github/workflows/claude-code-review.yml` | NEW | Same |
| `CommunityMech/CommunityMech/.github/workflows/claude-code-review.yml` | NEW | Same |
| `MediaIngredientMech/.github/workflows/weekly-compliance.yaml` | NEW | Weekly QC dashboard regen |

## Workflow architecture

```
   ┌──────────────────────────────────────────────────────────────┐
   │  PR opened in MIM / CultureMech / CommunityMech              │
   │             │                                                 │
   │             ▼                                                 │
   │  claude-code-review.yml (per-repo)                           │
   │  - Run repo's `just qc`                                      │
   │  - Run claw's evidence-reference-validator (Phase 1)          │
   │  - Comment AI summary on the PR                              │
   └────────────────┬─────────────────────────────────────────────┘
                    │
                    ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  post-review-agent.yaml (claw, hourly cron)                  │
   │  - Scan unresolved review comments across 3 repos           │
   │  - Classify: actionable (auto-suggest commit) vs.            │
   │    follow-up (open issue with tagged labels)                │
   │  - For actionable: open a suggested-changes commit on a     │
   │    side branch tagged `review-suggestion/<PR>-<comment-id>` │
   └──────────────────────────────────────────────────────────────┘
   ┌──────────────────────────────────────────────────────────────┐
   │  cross-repo-validation.yaml (claw, daily cron)              │
   │  - Run all 3 mech `just qc` in parallel matrix              │
   │  - If any fail, open issue tagging the relevant maintainer  │
   │  - Updates a status badge in claw README                    │
   └──────────────────────────────────────────────────────────────┘
   ┌──────────────────────────────────────────────────────────────┐
   │  weekly-compliance.yaml (per-repo, Sunday cron)             │
   │  - `just gen-dashboard`                                       │
   │  - Commit dashboard HTML to `compliance/` orphan branch     │
   │  - GitHub Pages serves trend over time                      │
   └──────────────────────────────────────────────────────────────┘
```

## `/curate` slash-command flow

When a curator types `/curate <source>` in claw's Claude Code session:

1. Read inventory (Phase: unmapped-inventory) for `<source>`
2. Run `python3 scripts/import_ingredients.py --source <source>` (dry-run)
3. Show resolver-tier breakdown; ask curator to confirm
4. On confirm, apply with `--apply`
5. Run `evidence-curation` skill to propose PMIDs for the new mapped
   records (Phase 1 + this phase)
6. Run `just publish-sssom` (build → validate → review)
7. Run `just kg-microbe-review` to confirm propagation
8. Open a PR in each affected repo with the diffs

This is the **end-to-end curation pipeline as a single command**.

## `evidence-curation` skill design

Inputs: a MIM ingredient YAML path (or set).
Outputs: for each YAML, a list of candidate `EvidenceItem` blocks with
real PMIDs and verified snippets.

```python
# pseudocode
for record in records:
    claim = f"{record.preferred_term} maps to {record.ontology_id}"
    candidates = deep_research_provider.search(claim, n=3)
    for c in candidates:
        snippet = extract_supporting_snippet(c.abstract, claim)
        if snippet:
            yield EvidenceItem(
                reference=c.pmid,
                supports="SUPPORT" if relevant else "PARTIAL",
                snippet=snippet,
                explanation=llm_summarize(c.abstract, claim),
            )
```

The skill never auto-commits; it produces a draft YAML the curator
reviews before merging.

## Execution order

1. **Skill scaffolding**: `evidence-curation/skill.md` + stub script
   that returns hand-coded fixtures (no provider call yet). Prove the
   plumbing.
2. **`/curate` command**: implement orchestration in claw
   `.claude/commands/curate.md` calling existing skills sequentially.
3. **`claude-code-review.yml`** in MIM: simplest case, single repo, no
   cross-repo concerns. Roll out + validate.
4. **Replicate** the workflow to CultureMech + CommunityMech.
5. **`cross-repo-validation.yaml`** in claw: matrix over 3 repos, runs
   each repo's `just qc`. Reports via GitHub issue if anything red.
6. **`post-review-agent.yaml`** in claw: scan comments, classify, open
   suggested-changes commits on side branches.
7. **`weekly-compliance.yaml`**: rolls up Phase 2 dashboards weekly.
8. **Plug in deep-research provider** to `evidence-curation`: replace
   fixtures with real provider call. Provider selection by env var so
   we can swap.

## Verification

After step 4:
- Open a test PR in each mech; AI comment lands within 3 minutes
- `just qc` failures block merge

After step 7:
- A simulated stale comment in a PR → `post-review-agent` opens a
  follow-up issue within 1 hour

After step 8:
- `python3 scripts/propose_evidence.py --record MIM:<slug>` returns
  ≥1 candidate with a real PMID; snippet validates against
  references_cache (Phase 1 dependency)

## Effort estimate

| Step | Hours |
|---|---:|
| Skill scaffolding + fixtures | 8 |
| `/curate` command | 8 |
| `claude-code-review.yml` × 3 | 12 |
| `cross-repo-validation.yaml` | 6 |
| `post-review-agent.yaml` | 12 |
| `weekly-compliance.yaml` × 3 | 6 |
| Deep-research provider integration | 12 |
| **Total** | **~64** |

## What's deferred to later phases

- ChatOps integration (Slack/Discord)
- Production-grade rate-limiting + provider fallback
- Curator trust scores / per-curator audit dashboards
- Editorial review automation (Phase 5+)
