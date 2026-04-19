---
name: team-review-sssom
description: Parallel agent-team review of the canonical MIM→ingredient-ontology SSSOM mapping — four sub-agents review row-shards, each emitting per-row verdicts with human-readable notes; merge stamps validation_method or marks rows UNVERIFIED
category: validation
requires_database: true
requires_internet: true
version: 1.0.0
tags: [sssom, chebi, foodon, envo, review, parallel, agents, validation, provenance]
---

# Team Review SSSOM Skill

## Purpose

Replaces the single-process `synonym-review` skill with a **parallel
agent-team review**. Splits the working-copy SSSOM into 4 shards of
~273 rows each, dispatches 4 in-process sub-agents (Mode A of the
`boss` skill), and merges their per-row verdicts back into the SSSOM's
`validation_method` column.

Every row ends up with either a populated stamp
(`{authorities}|{verdict}|{date}`) or explicit `UNVERIFIED` — the
latter is a real verdict, distinct from an empty string (which still
means "never reviewed since the last build").

## When to run

| Trigger | Use this skill |
|---|---|
| Release gate — want audit-worthy stamps with rationale | yes |
| Fast lexical-only re-check (e.g., after a CHEBI release refresh) | no — use `synonym-review` |
| New ingredient batch added, reviewing only a handful of rows | no — use `synonym-review --limit N` |
| Investigating specific LABEL_MISMATCH / OLS_MISMATCH rows | can help; agents write prose rationale per row |

Runs off the same working-copy file that the other stages of the
`publish-sssom` lifecycle produce: `workspace/reports/mim_ingredient_mappings.sssom.tsv`.

## Pipeline

```
 build-sssom ─▶ shard ─▶ 4 agents in parallel ─▶ merge ─▶ stamp ─▶ (validate → publish)
```

### Stage 1 — Shard

```bash
python scripts/shard_sssom_for_review.py --input workspace/reports/mim_ingredient_mappings.sssom.tsv --n 4
```

Writes `workspace/shards/sssom_review/shard_{0..3}.tsv`. Each is a
valid mini-SSSOM (frontmatter + column header + slice). Directory is
wiped first so stale shards don't leak in.

### Stage 2 — Dispatch 4 agents in parallel

**The orchestrating Claude session** (you, if you invoked this skill)
issues 4 `Agent` tool calls **in a single message** with:
- `subagent_type="general-purpose"`
- `isolation="worktree"`
- `run_in_background=True`

Each agent receives the same prompt structure, varying only by shard
index (`0, 1, 2, 3`):

> Review the SSSOM shard at `workspace/shards/sssom_review/shard_N.tsv`
> against CHEBI/FOODON/ENVO authorities.
>
> For each row, verify that the `object_id` exists, that `object_label`
> matches the authority's rdfs:label or a listed synonym, and that the
> pipe-separated alternate labels in `other` are either known synonyms
> or defensible enrichment candidates. Use the existing per-ontology
> dispatch in `scripts/review_sssom_synonyms.py:70-81` (OAK for CHEBI,
> OLS4 REST for CHEBI/FOODON/UBERON/ENVO).
>
> Emit `workspace/results/sssom_review_shard_N.jsonl` with one
> JSON object per row:
> ```json
> {"subject_id": "...", "object_id": "...", "verdict": "CONFIRMED",
>  "authorities": ["OAK", "OLS:chebi"], "notes": "1-2 sentences"}
> ```
>
> Verdicts:
> - `CONFIRMED` — authorities resolve and all proposed labels are known
> - `SYNONYM_ENRICH` — ≥1 alternate label is unknown to both authorities
>   (candidate to propose upstream)
> - `LABEL_MISMATCH` — our `object_label` isn't the rdfs:label and isn't
>   an exact synonym
> - `OLS_MISMATCH` — OAK and OLS disagree substantively (CHEBI only)
> - `UNKNOWN_TERM` — neither authority resolves the ID
> - `UNVERIFIED` — authorities unreachable (OLS 5xx, OAK timeout) OR the
>   match is genuinely ambiguous
>
> **Always include a `notes` field** (1-2 sentences): why CONFIRMED,
> which alternates were unknown, what disagreement OLS showed, etc.
> This is audit context — terse is fine, omitting it is not.
>
> Do NOT modify any file outside `workspace/results/`. Do NOT acquire
> any lock. This is read-only review work.

### Stage 3 — Merge

After all 4 agents report completion (Claude Code auto-notifies when
`run_in_background` agents finish — do not poll):

```bash
python scripts/merge_sssom_shard_reviews.py
```

Reads every `workspace/results/sssom_review_shard_*.jsonl`, joins by
`(subject_id, object_id)` onto the working-copy SSSOM, stamps
`validation_method = "{authorities}|{verdict}|{date}"` per row, and
writes:
- `workspace/reports/sssom_team_review.tsv` — per-row verdict + notes
- `workspace/reports/sssom_team_review.md` — bucketed summary

Rows missing from every shard output get
`none|UNVERIFIED|{date}` with a placeholder note. If a whole shard
file is missing the merge fails loud (exit 1) — re-dispatch that
shard rather than silently losing ~273 rows.

### Stage 4 — Validate + (optional) publish

```bash
just validate-sssom      # preflight
just publish-sssom       # only after human review of sssom_team_review.md
```

## Recommended invocation

```bash
just review-sssom-team
```

The recipe runs shard → dispatch-instructions → merge end-to-end. The
dispatch step itself is the orchestrating Claude's responsibility —
the shell recipe only prints the dispatch prompts and waits for the
JSONL shard files to appear before invoking merge.

## UNVERIFIED accounting

`UNVERIFIED` counts tell you how much the team review missed. Healthy
ranges:

| Count | Meaning | Action |
|---|---|---|
| 0 | Every row got a verdict | None |
| 1–20 | A few rows genuinely ambiguous or authorities flaked | Spot-check the notes; may be fine |
| 20–100 | One agent partially failed or OLS had intermittent issues | Re-run a targeted shard |
| 100+ | Systemic failure (whole shard lost, OLS down) | Abort; investigate before merging |

`validation_method` starting with `none|UNVERIFIED|` specifically
means the row was never seen by any shard (agent crashed before
writing or the shard split dropped it). Start there when
investigating.

## Files

| Path | Role |
|---|---|
| `scripts/shard_sssom_for_review.py` | Stage 1 — shard |
| `scripts/review_sssom_synonyms.py` | Serial fallback (`synonym-review` skill) |
| `scripts/merge_sssom_shard_reviews.py` | Stage 3 — merge + stamp |
| `workspace/reports/mim_ingredient_mappings.sssom.tsv` | Working copy (stamped in place) |
| `workspace/shards/sssom_review/shard_{i}.tsv` | Per-shard mini-SSSOM |
| `workspace/results/sssom_review_shard_{i}.jsonl` | Per-shard agent output |
| `workspace/reports/sssom_team_review.{tsv,md}` | Merged summary |

## Dependencies

- Python 3.x, stdlib only for merge; `oaklib` (`runoak`) + `sssom` CLI
  for the agent shards
- Internet for EBI OLS4 (agents hit OLS per-term, cached to
  `workspace/.cache/ols/`)
- Agent tool with `isolation="worktree"` and `run_in_background=True`
  (see `boss/skill.md:40-58`)

## Comparison

| | `synonym-review` (serial) | `team-review-sssom` (this skill) |
|---|---|---|
| Parallelism | 1 process | 4 agents |
| Verdict vocabulary | 5 | 6 (adds UNVERIFIED) |
| Per-row notes | no | yes (always) |
| Duration | ~4–8 min | ~8–10 min + orchestration |
| Judgment | lexical matching only | lexical + AI judgment |
| Use when | fast re-check, small batches | release gate, audit needed |

## Related skills

- `synonym-review` — the serial fallback; same file format, same
  stamp schema, runs on a single process
- `publish-sssom` — 4-stage release lifecycle; invokes either this
  skill or `synonym-review` in stage 3
- `boss` — parallel-agent orchestration patterns; this skill uses
  Mode A (in-process Agent tool)
