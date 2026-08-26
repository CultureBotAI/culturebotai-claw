# Autonomous agent loops for the Mechs — research + design

Research question: how do we let Claude self-prompt and continue Mech development
autonomously, using `monarch-initiative/dismech` as the reference implementation?

Everything below about DisMech was read from a clone of `main` (2026-07-31), and
everything about the Mechs was verified against the working copies and the GitHub
API on the same day. Where I could not verify something I say so.

---

## 1. The headline answer

**Do not build a self-prompting loop.** DisMech — which is materially more
advanced at this than we are — has no long-running agent, no self-continuation
prompt, and nothing that asks Claude "what should I do next?" in-session.

What it has instead is a **stateless tick**:

> cron fires → an agent reads state **from GitHub** → it does **exactly one** unit
> of work → it writes the result **back to GitHub** → the process exits.

Continuity is not in the model's context. It is in the issue tracker. The next
tick reconstructs everything it needs from labels, assignees, PR review state, and
comments. That is what makes the loop survivable: any run can die, be cancelled,
or hallucinate, and the next tick still sees the true state of the world.

The corollary is that **the queue is GitHub issues**, not a file. This is the
single most important design decision to copy, and it is the opposite of the
architecture currently documented in this repo's `CLAUDE.md` (see §4).

---

## 2. How DisMech's loop actually works

### 2.1 The three roles

The system is three cooperating workflow families, not one agent.

| Role | Workflows | What it does |
|---|---|---|
| **Producers** | `knowledge-gap-scan`, `literature-scan`, `preprint-scan`, `discussion-scanner` | Find new work and file it as issues |
| **Worker** | `curation-scanner` | Pick **one** open issue/PR and advance it |
| **Shepherd** | `pr-shepherd`, `post-review-agent`, `auto-merge-compliance` | Drive open PRs to merged |

A unit of work flows: *ranking artifact → issue → PR → review → merge*, and a
human can intervene at any of those points because every one is a GitHub object.

### 2.2 Producers: deterministic script first, agent second

This separation is deliberate and worth copying exactly. `knowledge-gap-scan`
runs `scripts/knowledge_gap_scan.py` to produce a candidate packet at
`output/knowledge_gap_scan/knowledge_gap_scan.md`, and only then hands it to an
agent whose permissions are extraordinarily narrow:

> Your only allowed write action is creating GitHub issues. Do not edit files.
> Do not create pull requests. Do not fetch or edit `references_cache/*.md`.

The agent's whole job is judgment — deciding which candidates are *true*
mechanistic gaps versus boilerplate "more research is needed" — plus dedup:

```bash
gh issue list --repo "$REPO" --search "PMID:<ID> in:body is:open" --json number,title
```

It is capped by `MAX_ISSUES`. The expensive, error-prone part (searching the
literature) is deterministic Python; the part needing judgment is the agent; the
blast radius is one issue at a time.

### 2.3 The worker: one item per run, and it must justify itself

`curation-scanner.yml` is the core loop. Cron:

```yaml
schedule:
  - cron: "0 */4 * * 1-5"  # weekday: every 4h
  - cron: "0 */8 * * 0,6"  # weekend: every 8h
```

The prompt's governing constraints, quoted because the exact wording is doing
real work:

> You may scan multiple candidates, but you must choose exactly one issue or pull
> request to actively work on in this run. Leave all other items untouched.

> Selection is deliberately restricted to items with no human / non-agent
> assignee, so the scanner never steps on work a person has already claimed.
> Always begin the comment or PR you post for the selected item with one sentence
> stating WHY you selected it over the other candidates — name the deciding
> ranking signal and confirm it had no non-agent assignee.

> Avoid repeatedly touching the freshest bottom-of-queue items while older
> unassigned candidates remain.

Three mechanisms in there are load-bearing:

1. **The lock is the GitHub assignee.** No lock files, no lease expiry, no
   distributed-consensus problem. Assignment is atomic at GitHub and visible to
   humans. Combined with `concurrency: group: curation-scanner-${{ matrix.effort }}`
   and `cancel-in-progress: true`, two runs cannot collide.
2. **Forced auditability.** The agent must state its selection reason in the
   artifact it produces. You can reconstruct why the fleet did what it did months
   later, from the issue thread alone.
3. **Explicit anti-starvation.** Without that clause, ranking heuristics converge
   on whatever was touched most recently.

There is also a hard verification rule before any destructive act:

> VERIFY completion against the actual repository state before closing — confirm
> the relevant `kb/` entry really contains the requested content … and cite the
> real integrating commit, which you find with `git log -S '<distinctive string>'
> -- <path>` — do NOT trust a remembered or inferred PR number.

### 2.4 Effort tiers route to different models

`.github/agent-config.yaml` is the single source of truth for model selection,
resolved at runtime by a composite action into a strategy matrix:

```yaml
curation-scanner:
  matrix:
    - effort: low_effort
      model: claude-haiku-4-5-20251001
      selector: "label:curation label:low_effort"
    - effort: medium_effort
      model: claude-sonnet-5
      selector: "label:curation label:medium_effort -label:low_effort"
    - effort: high_effort
      model: claude-opus-5
      selector: "label:curation -label:low_effort -label:medium_effort"
```

So each tick is really three parallel agents, each cheap-to-expensive matched to
label-declared difficulty. `default_model: claude-opus-5` covers everything else.
Changing a model repo-wide is a one-line edit, no workflow changes.

The tier rules include an escalation path rather than a guess:

> `low_effort`: … Do not create new disease entries from this tier. If a task
> requires new disease curation, leave a brief comment and ensure the work is
> routed to `high_effort`. … If an item has more than one effort label, skip it
> rather than guessing.

### 2.5 The shepherd: a state machine, not a free-form agent

`pr-shepherd.yml` runs at `"37 */4 * * *"` — deliberately offset from the
scanner's `"0 */4"` so they do not contend. It classifies each candidate PR into
`APPROVED + CLEAN`, `APPROVED + DIRTY`, `CHANGES_REQUESTED`, or
`REVIEW_REQUIRED + cancelled review`, and each state has an explicit allowed-action
list. It processes at most `MAX_PRS` (default 3).

Its constraints are the interesting part:

- **Never rebase, never force-push.** Branch refresh goes through GitHub's
  update-branch API; a local merge is the only fallback.
- **Scope-restricted edits**: "Only edit curation-scope files: `kb/`, `cache/`,
  `references_cache/` via regeneration only, and `research/`."
- Candidate detection is by bot author **or** `claude/` branch prefix.

### 2.6 Identity: two GitHub Apps, and why it matters

Runs mint a short-lived App token:

```yaml
- name: Generate ai4c-agent token
  uses: actions/create-github-app-token@…
  with:
    app-id: ${{ secrets.AI4C_AGENT_APP_ID }}
    private-key: ${{ secrets.AI4C_AGENT_PRIVATE_KEY }}
```

Two things follow, both called out in DisMech's own comments:

- The **writer** identity (`ai4c-agent`) is distinct from the **reviewer**
  identity (`ai4c-reviewer`), "so follow-up review can still act independently on
  the resulting work." One bot cannot approve its own PR.
- Because it is an App token and not the built-in `GITHUB_TOKEN`, "a `git push`
  to a PR branch DOES fire the PR `synchronize` event and automatically starts the
  claude-code-review workflow." **`GITHUB_TOKEN` deliberately does not trigger
  downstream workflows** — this is the classic trap that makes an agent loop
  silently fail to chain.

The token is never persisted (`persist-credentials: false`); git authenticates via
the `gh` credential helper.

### 2.7 Cadence control and the kill switch

`.github/cron-profiles.yaml` centralises cadence across every managed workflow,
with named profiles applied by `scripts/apply_cron_profile.py` (`just cron-profile
<name>`), which rewrites only the `on.schedule` block.

Profiles: `slow` (minimise spend), `medium` (baseline), `fast` (hourly ceiling),
`fast-weekend`, and `off` — "Kill switch — no scheduled agent runs at any time
(manual dispatch still works)."

**DisMech currently runs `active: "slow"`.** Note that even the reference
implementation dials itself down. Also note the deliberate design choice:

> We intentionally do NOT use impossible dates such as Feb 30: GitHub can ignore
> invalid cron updates and leave the previous valid schedule registered.

### 2.8 Prompt-injection defence

`untrusted-comment-guard.yml` fires on `issue_comment` and
`pull_request_review_comment` and minimizes risky comments from untrusted authors
via `.github/scripts/github-trust-gate.js`. This exists because the interactive
`@claude` responder reads comments — meaning **anyone who can comment can attempt
to steer the agent**. `close-fork-prs.yml` is the companion control.

If we adopt an interactive responder, we must adopt this at the same time, not
later.

---

### 2.9 The `history/` provenance layer — the most copyable piece here

This is the part I would port first, ahead of any workflow. It is the only durable,
machine-readable record of *which model, using which tool, made which change, why,
and under what issue*. There are **2,651 such records** in the repo today.

One append-only YAML per session per target, never edited after write:

```
history/disorders/<SLUG>/<TIMESTAMP>-<actor>-<shortid>.yaml
```

A real record:

```yaml
history_version: 1
target: {kind: disorder, slug: 22q11.2_Deletion_Syndrome, path: kb/disorders/22q11.2_Deletion_Syndrome.yaml}
session:
  id: 2026-07-03T061234Z-claude-code-5d0694
  timestamp: '2026-07-03T06:12:34Z'
  actors:
  - {type: ai_agent, name: claude-code, model: claude-sonnet-4-6, agent_tool: claude-code}
links: {issues: ['https://github.com/monarch-initiative/dismech/issues/5170'], prs: []}
events:
- type: EDIT
  outcome: changed
  sections: [genetic]
  summary: Backfill gene_term on genetic node
  details: |
    Added HGNC-verified gene_term descriptor(s) to genetic[] node(s) …
```

It is backed by a real LinkML schema (`src/dismech/schema/history.yaml`) with four
enums. The vocabularies are worth taking verbatim:

- kind: `disorder | module | comorbidity | schema | other`
- actor: `human | ai_agent | automation | other`
- event: `GENERAL | CREATE | EDIT | REVIEW | AUDIT`
- outcome: `changed | no_change | needs_followup | blocked`

**Outcome being orthogonal to event type is the good design call** — it lets you
record a REVIEW that found nothing (`no_change`) or an EDIT that got stuck
(`blocked`) without inventing event types. `events` has `minimum_cardinality: 1`
and `details` is **required**, so a contentless record cannot be emitted.

Two properties make this scale to arbitrary parallelism, which is exactly our
problem:

1. **Directory-per-slug with an unguessable filename** (`secrets.token_hex(3)` plus
   a second-resolution timestamp). No shared mutable file, therefore **zero merge
   conflict surface**. Compare a single `CHANGELOG.md`, which conflicts on every
   parallel PR.
2. **Scaffolded, never hand-written.** `just new-history --kind … --event … --summary
   … --details …` generates a schema-valid skeleton; the agent edits only `details`.
   The script prints the bare path as its final stdout line specifically so
   automation can capture it.

The enforcement split is the subtle part and I'd copy it exactly: **presence is
advisory, schema is hard.** CI posts a non-blocking warning when a KB entry changes
without a history record — the docs consistently say "should", never "must", in a
file that uses MUST elsewhere — but if you *do* write one, `just validate-history`
is ordinary LinkML validation and fails CI like any other error. That gets you
provenance coverage without a gate that blocks legitimate work at 3am.

Do **not** port `.ai-blame.yaml`. It configures an external tool that appears
nowhere in the build, and the sidecar pattern it describes
(`kb/**/*.history.yaml`) has been explicitly abandoned — `project.justfile`
actively excludes that glob from validation, and the legacy sidecars were
compacted into `history/`. It is vestigial config for a superseded design.

### 2.10 Where DisMech is weak — do not copy these

**The claim protocol is race-*tolerant*, not race-safe.** Between `gh issue list`
and `gh issue create` there is no compare-and-swap, no conditional create, no
advisory lock. If two runs pick the same disease, **both file an issue**. Nothing
detects the collision afterward.

What DisMech does instead is make a duplicate cheap to detect and cheap to abandon,
by re-running the same three-surface preflight at *every stage transition* — at
claim, at selection, at dispatch, and again in the sub-agent before it writes
files. Four checks of the same surfaces. That repetition *is* the concurrency
control, and the design bet is that a wasted issue costs less than a locking
protocol. Three details in that preflight are load-bearing:

- Check `origin/main`, **not the working tree** — another agent's merge may have
  landed since you pulled.
- Use `--state all`, **not `--state open`** — a closed PR may already be merged, and
  a closed issue may explain why the target should *not* be curated.
- Repeat the search for **synonyms**, not just the primary label.

**There is no stale-claim detection anywhere.** No TTL, no lease, no heartbeat, no
sweep. An issue assigned to an agent that died is invisible to the scanner (which
only considers `no:assignee`) and sits assigned forever. The only release verbs are
human. The scanner's anti-starvation clause doesn't help, because it only ranks
*unassigned* items.

**If we adopt this model we must add the sweep DisMech lacks** — a scheduled job
over `is:issue is:open assignee:* label:agent-ok updated:<DATE` that unassigns
agent-held issues after a timeout. This is cheap for us and would be the single
biggest robustness win over the reference implementation.

**The pre-write hook is fragile enough that I would port a different one.**
`validate_disorder_hook.py` simulates an edit in memory and runs the full validator
stack before allowing the write. Good idea, but: it hardcodes `count=1` and ignores
`replace_all`, so what it validates differs from what gets written; it **fails open
on infrastructure errors** (a crash is not exit 2, so the edit proceeds); it runs
three validators including live ontology lookups on *every* edit, with repo side
effects; and it resolves the project root from its own file location, which
misbehaves under the worktree-per-agent model it otherwise recommends. Its coverage
is also narrow — it guards the one thing CI would catch anyway, while every
incident the docs actually cite (`git add -A`, local rebases, hand-edited caches,
cross-worktree writes) has no hook backing.

### 2.11 Two definitions worth stealing outright

**"A PR being opened is NOT completion."** DisMech's orchestrator skill is explicit
that a task is done only when the PR is *approved and all checks pass*: "'I opened
a PR' is a milestone, not a finish line. If you mark it done-ish and walk away,
you've left an un-reviewed draft sitting in the queue." Any completion metric we
define should follow this.

**Keep dispatch prompts terse.** This is the opposite of the instinct: "The worker
launches inside the worktree and inherits everything: `CLAUDE.md`, all project
skills, the `just` targets, and the validation stack. Do **not** restate SOPs,
validation steps, or skill names in the prompt — the worker finds and invokes them
on its own. Over-instructing wastes tokens, crowds out the worker's own planning,
and risks contradicting project guidance."

## 3. What the Mechs have today

Verified 2026-07-31.

**Agentic workflows: zero.** CultureMech 0 of 7, MIM 0 of 6, CommunityMech 0 of 6,
TraitMech 0 of 4 invoke `anthropics/claude-code-action`. All 23 are validation,
build, or deploy.

**But the hard prerequisites are already met**, which is the pleasant surprise:

- `CLAUDE_CODE_OAUTH_TOKEN` exists as a **CultureBotAI org secret with ALL-repo
  visibility** (alongside `CLAUDE_ACCESS_TOKEN`, `CLAUDE_REFRESH_TOKEN`,
  `CLAUDE_EXPIRES_AT`, `SECRETS_ADMIN_PAT`).
- The `claude` GitHub App (app id `1236702`) is installed on the org.
- Every repo already runs `uv`, `just`, and a real validation gate in CI — which
  is what makes an agent's output checkable.

**The producer layer is far further along than the workflow count suggests.** All
four Mechs already ship, as justfile recipes, the DisMech-derived scan pipeline:

- `knowledge-gap-scan` — seeds `Discussion(kind=KNOWLEDGE_GAP)`
- `gen-discussions-data` — builds the Discussions browser
- `enrich-edison-response` — backfills Edison provenance without re-billing

claw hosts the shared library at `src/kg_microbe_kgscan/`, whose own docstring
describes it as a "Generalized port of DisMech's `scripts/knowledge_gap_scan.py` +
`literature_scan.py`" — and it already supports `--apply` to write the Discussion
back into the record YAML. **The scan-to-write-back path exists.** What is missing
is only the scheduler and the issue-filing step.

**We already have ranking artifacts that can seed a queue**, though coverage is
uneven:

| Repo | Artifact | Ranking key |
|---|---|---|
| CultureMech | `data/import_tracking/reports/deep_research_priority.json` (9,895 entries; top-100 slice alongside) | composite priority |
| CultureMech | `data/import_tracking/reports/edison_batch.json` (100 entries) | `completeness_score` + `priority`, with a pre-built `queries` array |
| CultureMech | `concentration_plausibility.tsv` (11,540 rows), `filename_collisions.tsv` (290) | detector + classification |
| MIM | `data/curated/unmapped_ingredients_index.json` (398 entries) | `occurrences` |
| TraitMech | `reports/knowledge_gap_scan.json`, `reports/graph_enrichment_backlog.md` | scan score |
| CommunityMech | **none** | — |

Two things stand out. `edison_batch.json` is the closest thing in the fleet to a
machine-consumable task payload — it already carries per-field queries — and
CultureMech's `researched_media.json` (53 entries) is the fleet's **only
re-billing guard**. TraitMech's `reports/knowledge_gap_scan.json` is the only
committed knowledge-gap scan output anywhere, and its *shape* is the right
template for what an autonomous scan should commit — but its *content* is the
ten misfiled gaps that motivated the #69 precision gates (all ten are rejected
by the current scanner), and it predates the `duplicates_dropped` field, so
regenerate rather than imitate it.

**CommunityMech has no ranked work queue at all** — its `reports/` is 37 files of
per-community author-request email drafts, and despite the `ground-taxa-gtdb`
skill existing, no GTDB gap list is committed. Its pending work lives only in
`NEXT_TASKS.md` (1,056 lines) and `docs/LLM_REPAIR_ROADMAP.md`. That queue has to
be generated before CommunityMech can join the fleet.

**A cross-repo producer→consumer seam is already wired**: CultureMech's
`prioritize-role-research-candidates` emits a payload directly consumed by MIM's
`research-ingredient-roles-edison-batch`. That is the natural first automated
handoff, because both halves already exist and are already used by hand.

**There is also precedent for an agent filing issues.** claw's
`cross-repo-validation.yaml` (cron `27 7 * * *`) checks out all four repos, runs
evidence-reference validation plus the unmapped inventory, and has an "Open issue
on validation failure" step. It is the fleet's only automated write-back today.

**Scheduled-workflow coverage is thin**: claw has 2 crons, CultureMech 2
(`vendored-fleet-audit`, `weekly-compliance`). **MIM, CommunityMech and TraitMech
have zero** — all 16 of their workflows are PR/push/dispatch only.

**Gaps, concretely:** no agent workflows; no agent-config/model routing; no cron
profile or kill switch; no writer/reviewer App split; no `EDISON_PLATFORM_API_KEY`
in org secrets (it lives in local `.env` only), so scheduled deep research cannot
run in CI yet; no untrusted-comment guard; no per-repo effort labels; and no work
queue in CommunityMech.

---

## 4. Local coordination is live, but it is not the autonomous-loop substrate

This repo's `CLAUDE.md` documents a file-based multi-Claude protocol built from
`LockManager`, `workspace/locks/`, project hooks, and advisory status records.
That protocol is now a supported **same-machine** coordination boundary.
`install_hooks.sh` resolves applicable targets from the fleet manifest and
safely merges handlers into each target's project-level
`.claude/settings.json`. Edit and Bash pre-hooks fail closed on active or
unreadable leases; post-hooks record advisory completion status. Existing
settings and user hooks are preserved, repeat installation is idempotent, and
malformed or unsafe project/local settings stop installation. Restrictive
`disableAllHooks` and `allowManagedHooksOnly` values also fail installation.
Higher-scope user or managed policy is not visible to the project installer, so
operators must restart active sessions and confirm activation with `/hooks`.

The boundary is deliberately narrower than an autonomous fleet loop.
`workspace/` is gitignored local runtime state. A process on another machine or
in CI cannot observe its leases or status, and an advisory task/status file is
not a durable queue. Local workers also need isolated branches and worktrees;
a repository lease is held only for a short shared metadata transition and is
released before the worker edits or commits. The supported details live in
`docs/guides/MULTI_CLAUDE_COORDINATION.md`.

**One correction worth recording**, because it changes the migration plan: the
library is not entirely dead. `scripts/publish_sssom.py` is a **live consumer** —
it loads `lock_manager` via `importlib` to bypass `plugins/__init__.py`, acquires
the `mediaingredientmech` lock with a 300s timeout, and releases it in cleanup
(last touched 2026-04-19). Two other importers,
`scripts/import_curated_ingredients.py` and
`pipelines/unified_ingredient_mapping_pipeline.py`, are stale (2026-03-26). Any
retirement needs a migration path for `publish_sssom.py` specifically.

Unrelated but easy to confuse: `.claude/scheduled_tasks.lock` files exist in MIM
and claw. Those are Claude Code's own stale session locks, not part of this system.

The broader coordination problem remains real. During a single session on
2026-07-30 I watched about 38 concurrent Claude processes move branches and
HEADs across three Mech repos, push commits, and file issues with no mutual
visibility. Two research agents' edits were absorbed by other sessions'
commits; one repo changed branch three times in twenty minutes. Local hooks
cannot arbitrate processes that do not share their workspace.

**Recommendation:** retain the file-based protocol for same-machine, bounded
coordination and use GitHub objects as the authority for autonomous,
cross-machine, and CI work. GitHub issues, assignees, branches, PRs, checks, and
workflow concurrency provide the durable state that the autonomous loop needs.

---

## 5. Proposed design

### 5.1 Where the loop lives

Use **GitHub Actions**, not a long-running local session. Comparison of the three
options actually available to us:

| Option | Durable? | Shared across sessions? | Auditable | Verdict |
|---|---|---|---|---|
| GitHub Actions cron + `claude-code-action` | yes | yes | run logs + GitHub objects | **the loop** |
| Claude Code `/loop`, `ScheduleWakeup` | no — session-bound | no | local only | interactive burst work |
| Scheduled cloud agents (`/schedule`) | yes | partly | yes | good for reporting, not curation |

`/loop` is genuinely useful for a human-supervised burst ("keep going until the
backlog is dry") but it dies with the session and cannot be the backbone.

### 5.2 Queue and lock

- **Queue = GitHub issues**, one per unit of work, labelled by domain and effort.
- **Lock = assignee.** An issue with a non-agent assignee is untouchable.
- **Concurrency = `concurrency:` group per repo per tier**, `cancel-in-progress: true`.
- `NEXT_TASKS.md` stays as the **narrative** layer — why something matters, what
  was tried — and stops being the queue. Today's reconcile is the argument: four
  backlogs had drifted from reality, one carried an abandoned plan for over a
  week, and three CultureMech issues were closed while their PRs said they were
  unfinished. Prose backlogs drift; issues have state transitions.

### 5.3 Labels to create (per Mech)

`agent-ok` (opt **in** — nothing is agent-eligible without it), `low_effort` /
`medium_effort` / `high_effort`, `high-priority` / `low-priority`,
`needs-human` (hard stop), and a domain label per repo (`curation`, `grounding`,
`schema`, `infra`).

Opt-in rather than opt-out is the important choice: a new issue is invisible to
the fleet until a human labels it.

### 5.4 Workflows to add, in dependency order

1. **`agent-config.yaml` + resolver** — model routing before anything else, so
   cost is controllable from day one.
2. **`cron-profiles.yaml` + applier, shipped at `active: "off"`.** Build the kill
   switch before the thing it switches off.
3. **`pr-shepherd`** — safest first agent. It only moves *existing* PRs forward;
   it cannot invent work. Run it manually for a week.
4. **`issue-scanner`** (our `curation-scanner`) — one item per run, `agent-ok`
   only, draft PRs only.
5. **Producers**, one per repo, wrapping ranking artifacts we already have:
   - CultureMech → `deep_research_priority_top100.json`, and the #150 detector rows
   - TraitMech → causal-graph baseline (#183 backfill: 219 traits remaining)
   - CommunityMech → GTDB gaps (#276)
   - MIM → unmapped inventory
6. **`untrusted-comment-guard`** — mandatory before any `@claude` responder.

### 5.5 Vendor shared contracts through claw

The Phase 1 governance rail makes claw the external authority for
fleet-identical artifacts. Every Mech, including CultureMech, consumes a full
claw commit pin; applicability comes from the canonical fleet capabilities and
one artifact manifest. Agent workflow templates should use that same rail (or a
pinned reusable workflow in Phase 5) rather than being copied independently.
See `docs/guides/VENDORED_GOVERNANCE.md` for the transitional rollout—during
that bounded window the legacy CultureMech comparison remains active solely to
avoid an unpinned gap.

### 5.6 Safety rails to adopt verbatim

- One unit of work per run; state the selection reason in the output.
- Draft PRs by default.
- Scope-restricted file edits per workflow; anything outside → comment, don't guess.
- Never rebase, never force-push.
- Verify against repo state before closing anything; cite the integrating commit
  found with `git log -S`, never a remembered PR number.
- `timeout-minutes` on every job (DisMech uses 60).
- Escalate rather than guess when labels conflict.

### 5.7 The identity question

We have the stock `claude` App but no writer/reviewer split. Two consequences:

- With `GITHUB_TOKEN`, **agent pushes will not trigger our validation
  workflows** — the agent's own PR would appear green because nothing ran. This is
  the failure mode most likely to bite us silently.
- One identity means an agent could approve its own work.

Recommend creating a `culturebot-agent` App (writer) and, before enabling
auto-merge, a `culturebot-reviewer` App. Until then, require human review on every
agent PR and do not enable auto-merge at all.

---

### 5.8 Adopt graded compliance — and note DisMech already solved TraitMech #183

DisMech's `dismech-compliance` is not a boolean gate. It is a **weighted score**
over *recommended* (not required) fields — required fields are the LinkML schema's
job — with per-slot weights and thresholds in `conf/qc_config.yaml`, surfaced by
`just compliance`, `just compliance-weighted`, `just compliance-report`. Two
consequences we want:

- **Scores become work-selection input.** `just gen-dashboard` emits "Priority
  Curation Targets (10 lowest-scoring files)", and the `projman` skill writes the
  score into the project checkbox on completion, so the queue file doubles as the
  quality ledger. That is a cheap and very good idea.
- **Thresholds are negotiable, not sacred.** The skill's own troubleshooting says
  a blocking violation may mean "lower the threshold if it's too aggressive."

**The part that matters most to us is `causal_inlink`.** DisMech hit exactly the
problem TraitMech has, and its write-up of why field-presence checking cannot see
it is worth quoting:

> Recommended-slot compliance only measures whether fields are *populated* on an
> object. It cannot express cross-object graph properties — most importantly,
> whether a phenotype is actually wired into the causal **pathograph**. A phenotype
> can have a perfect HPO `term`, evidence, and description (full compliance credit)
> yet still float as a disconnected node, because the edge that connects it lives
> on a *different* object's `downstream` list.

Their solution: compute connectivity from the built causal graph in a
`QCMetricPlugin` (`src/dismech/qc_plugins.py`) and emit it as an ordinary score at
path `phenotypes[].causal_inlink`, so it composes with the existing weights and
thresholds like any other field. It is **graded coverage, not a binary gate** — a
file with 9 of 12 phenotypes wired scores 75% — with
`just compliance-connectivity [--list-unconnected] [--fail-under 30]`.

This is the same shape as TraitMech's #183 (220 of 353 graphs fragmented, 1,264 of
4,136 nodes unreachable) and the same shape as the ratchet TraitMech just shipped
(`--fail-on new` against a frozen baseline). **Recommend converging on DisMech's
formulation**: express connectivity as a graded score that feeds the priority
ranking, rather than only as an audit finding. That turns #183's backfill from a
219-item slog into a queue that automatically surfaces its own worst files — which
is precisely what an autonomous worker needs.

### 5.9 A launch blocker: skill filenames differ in case across the fleet

Agents in CI run on **Linux, which is case-sensitive**. Our Macs are not
(`core.ignorecase=true`), so this is invisible locally and will only surface as an
agent that silently cannot find its own instructions.

As recorded in git — not on disk, which lies:

| Repo | `SKILL.md` | `skill.md` |
|---|--:|--:|
| CultureMech | 4 | 10 |
| MIM | 0 | 11 |
| CommunityMech | 0 | 12 |
| TraitMech | 6 | 1 |
| claw | 1 | 18 |

Two repos are internally inconsistent (TraitMech's lone `schema-gap-analysis`
lowercase outlier; claw's lone `map-ingredients` uppercase outlier), and
CultureMech is thoroughly mixed. DisMech uses `SKILL.md` uniformly.

Normalise on `SKILL.md` fleet-wide before any agent workflow runs, using
`git mv` with an explicit two-step rename (`git mv skill.md tmp && git mv tmp
SKILL.md`) — a direct case-only `git mv` is a no-op on a case-insensitive
filesystem. CultureMech also has a stray loose `.claude/skills/stats-report.md`
outside any skill directory, which should be moved or removed at the same time.

This is cheap now and expensive later: debugging "the agent ignored its skill"
across four repos is far harder than a rename.

## 6. Phasing

**Status as of 2026-07-31 — phase 0 is largely done.** Shipped:

- **Skill filenames normalised** (§5.9). All 63 skills across the five repos are
  now `SKILL.md`; 52 renamed via two-step `git mv`, with the `../skill.md` links
  inside `reference/` subdirs and the stale prose references updated. Archived
  docs (`ATTIC/`, `docs/archive/`) deliberately left as historical record.
- **`history/` provenance layer** (§2.9) — canonical LinkML schema at
  `src/kg_microbe_governance/artifacts/schema/history.yaml` (with the old
  `shared/history/history.yaml` compatibility path retained during rollout),
  scaffolder at `src/kg_microbe_history/`,
  vendored schema + `just new-history` / `just validate-history` + advisory
  `curation-history.yaml` workflow in TraitMech as the pilot consumer.
- **Weekly knowledge-gap scan** — `.github/workflows/knowledge-gap-scan.yaml`
  here, running the deterministic scan across all four Mechs with no agent.

**Phase 0 landed 2026-07-31**, apart from the writer App. `.github/agent-config.yaml`
routes effort tiers to models; `.github/cron-profiles.yaml` carries `off` / `slow`
/ `medium` / `fast` with **`off` active**, applied by
`scripts/apply_cron_profile.py` (`just cron-profile <name>`); and the five agent
labels exist in all six repos.

One scoping correction worth recording: `knowledge-gap-scan` is deliberately NOT
managed by the cadence config. It spends no tokens, and an early draft that
managed it would have made the kill switch silently disable a wanted nightly job
that has no model in the loop. Only token-spending workflows belong under it.

Two portability defects surfaced while doing it, both now fixed in the
`knowledge-gap-scan` recipe: it hardcoded `/opt/homebrew/bin/python3.13`, and it
resolved the shared library through a bare relative path into private claw. **25
other recipes across the fleet still hardcode the Homebrew path** (CultureMech 11,
MIM 5, CommunityMech 5, TraitMech 4) and will not run in CI — deliberately left
alone to keep this change reviewable, but they block any further CI adoption.

| Phase | Scope | Exit criterion |
|---|---|---|
| 0 | ~~Normalise skill filenames~~, ~~labels~~, ~~`agent-config.yaml`~~, ~~`cron-profiles.yaml` at `off`~~ **done**; writer App remains | Manual dispatch produces a correct no-op |
| 0b | ~~**`history/` provenance layer** (§2.9)~~ **done in TraitMech** — roll to the other three | Humans and agents both emit records by hand |
| 1 | `pr-shepherd` in **one** repo (TraitMech) | 10 manual runs, no bad action |
| 2 | `issue-scanner`, `low_effort` tier only, draft PRs | 20 runs; human merges everything |
| 3 | Cadence `slow`; add medium/high tiers; **stale-claim sweep** (§2.10) | Two weeks, no human rescue needed |
| 4 | Producers: schedule the existing `knowledge-gap-scan` recipe and add an issue-filing step | Scan output becomes issues without hand-holding |
| 5 | Roll to the remaining three Mechs via the vendored rail; generate CommunityMech's missing queue | Fleet audit green |

The cheapest genuinely useful first automation is not in this table: **schedule
what already works.** MIM, CommunityMech and TraitMech have zero cron workflows,
yet all three ship a working `knowledge-gap-scan` recipe that is run by hand.
Putting that on a weekly cron with no agent involved at all — just the
deterministic scan, committing its report the way TraitMech's
`reports/knowledge_gap_scan.json` already is — delivers value on day one and
builds the operational habit before any agent gets write access.

TraitMech is the right pilot: smallest surface, a well-defined mechanical backlog
(#183's 219 remaining traits), and an existing non-blocking ratchet
(`--fail-on new`) that already distinguishes new breakage from known debt — which
is precisely the guard an autonomous backfill needs.

---

## 7. Open decisions

1. **Does the schema axis on `validate-media-recipes` land before we start?** An
   autonomous fleet operating against CultureMech while an 11,088-record backfill
   sits unmerged will generate conflicts faster than anyone can resolve them.
2. **Cost ceiling.** DisMech runs `slow` with three-tier fan-out. We have no
   budget instrumentation at all. Decide a monthly cap and how we observe it
   before phase 3.
3. **Does `EDISON_PLATFORM_API_KEY` go into org secrets?** Required for scheduled
   deep research; also the point at which an agent can spend real money unattended.
4. **What is `needs-human` in practice?** Anything touching ontology term minting,
   record deletion, or schema changes should probably be permanently ineligible.
5. **Do we retire `plugins/lock_manager.py` and the `workspace/` protocol
   outright**, or keep them for local orchestration? My recommendation is retire
   and rewrite the `CLAUDE.md` section — but note this is not a pure deletion:
   `scripts/publish_sssom.py` genuinely uses the lock and needs a replacement
   (a `concurrency:` group if it moves to CI, or a committed lock if it stays
   local).
6. **Who owns the `agent-ok` label?** The opt-in gate is only meaningful if
   applying it is a deliberate human act. If agents can label their own issues
   `agent-ok`, the gate is decorative.

---

## 8. Sources

- `monarch-initiative/dismech` @ `main`, cloned 2026-07-31: `.github/workflows/`
  (24 files), `.github/agent-config.yaml`, `.github/cron-profiles.yaml`,
  `.claude/skills/` (17 skills incl. `claim-disease`, `curate-next`, `boss`,
  `projman`, `dismech-compliance`), `.claude/commands/`, `.claude/settings.json`,
  `.claude/hooks/validate_disorder_hook.py`, `src/dismech/schema/history.yaml`,
  `src/dismech/qc_plugins.py`, `scripts/new_history.py`, `history/` (2,651
  records), `AGENTS.md`, `ai.just`, `.ai-blame.yaml`.
- CultureBotAI org: `gh secret list --org`, `gh api /orgs/CultureBotAI/installations`.
- The four Mech working copies and `culturebotai-claw`, 2026-07-31.
