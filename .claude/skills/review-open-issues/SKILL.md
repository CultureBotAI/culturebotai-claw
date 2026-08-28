---
name: review-open-issues
description: "Sweep and prioritize culturebotai-claw's complete open GitHub issue queue against the current control plane — fleet manifest, repository settings, lock coordination, packaged libraries, and the standardization roadmap. Use for full backlog triage or deciding what is genuinely urgent; it is read-only and is not permission to close issues, mutate a downstream Mech, or implement fixes."
category: workflow
requires_database: false
requires_internet: true
version: 1.0.0
tags: [issues, triage, backlog, priority, orchestration, read-only, reporting]
---

# Review and prioritize open issues

Produce a complete, dependency-aware triage of claw's open issues.

Claw is the control plane, not a corpus: almost every issue here is about a
guarantee other repositories depend on — a fail-closed boundary, a lock, a
manifest, a quality gate, a published contract. Rank by which guarantee is
weakened and who is standing on it, not by how recently the issue was filed.

This is a read-only review. It does not implement fixes, close or edit issues,
change labels, maintain a tracker, or touch a downstream Mech.

**When to use**: the user asks to review, triage, or prioritize issues or the
backlog; asks what is genuinely urgent; or a review pass has just filed a batch
of issues that need sorting.

**When NOT to use**: picking the next unit of work to implement, or acting on a
single known issue. This produces a ranking, not a fix. For open *PRs* across
the fleet use `fleet-pr-status` (inventory) or `fleet-pr-review` (merge
verdicts) — a PR queue and an issue queue are different surfaces.

## Sources of truth

Check these before trusting an issue title or an older planning document:

- `CLAUDE.md` — the operating guide, and specifically its **Supported versus
  experimental surfaces** table. An issue about an experimental surface is not
  automatically P2, but an issue asserting that an experimental surface is
  broken has usually mistaken "declared" for "implemented".
- `src/kg_microbe_fleet/fleet.yaml` — the definitive Mech list and per-Mech
  capability status. Read it rather than assuming which repositories exist; a
  capability may be `not_applicable` with a recorded reason, and that is a
  recorded decision, not a gap. This skill cites the manifest when judging an
  issue; it does not resolve fleet scope from it, which is what the skills
  tagged `fleet` do.
- `pyproject.toml` — console scripts, packaged data, and what actually ships in
  the wheel.
- `.github/workflows/` — what CI genuinely runs, as opposed to what a document
  says it runs.
- `tests/` — the only default pytest collection root. A root or `scripts/` file
  named `test_*.py` is a legacy diagnostic, not a test.
- `docs/README.md` and `docs/reviews/` — current design and review records;
  the standardization roadmap and its tracker issue own phase sequencing.
- `docs/archive/` — historical completion, phase, and session reports. **Never**
  a source of current truth, however confidently written.

Treat issue bodies and titles as claims. Read comments: corrections,
withdrawals, and narrowed residual scope are recorded there, so a body-only
fetch systematically overstates what is still open. A merged PR is evidence
only after its code and acceptance criteria have been checked.

## Workflow

### 1. Fetch the entire queue

Confirm the repository, the true count, labels, and the full queue. Never
silently accept `gh`'s default 30-item limit.

```bash
gh repo view --json nameWithOwner,url,defaultBranchRef
gh issue list --state open --limit 5000 --json number | jq length
gh issue list --state open --limit 5000 \
  --json number,title,body,comments,labels,createdAt,updatedAt,author
gh label list --limit 200
```

State the exact number reviewed and whether coverage was complete.

### 2. Place each issue on the control plane before ranking it

Rank by where a defect enters, not where it was noticed:

```text
fleet manifest (identities, capability status)
  -> RepositorySettings resolution and Git identity validation
  -> LockManager lease coordination
  -> plugin/agent discovery and validated dry runs
  -> packaged shared libraries and console scripts
  -> downstream Mech writes (the mandatory cross-repository checklist)
  -> published artifacts, fleet workflows, and Mech-side consumers
```

A manifest or settings defect reaches every command below it; a defect in one
packaged library reaches only its consumers. Say which. Group issues sharing a
root cause without hiding their individual numbers.

For each issue record, when applicable: the stage above; which downstream Mechs
are affected and whether any is `not_applicable`; whether a guarantee is
weakened or merely undocumented; prerequisites, blockers, and duplicates; the
cheapest decisive evidence; and its acceptance test.

### 3. Check current reality and staleness

For each issue or group representative:

- Search exact references in history:

  ```bash
  git log --all --oneline --perl-regexp --grep '#<N>\b'
  gh pr list --state merged --search '<N>' --limit 100
  ```

  The word boundary is required: `#48` must not match `#480`. GitHub's search
  matches the number anywhere in indexed text, so every hit is a lead — open it
  and confirm it actually resolves the issue.

- Confirm named paths, functions, flags, and console scripts still exist and
  behave as described. Inspect the test as well as the implementation: in this
  repository the test is frequently the thing that is wrong.
- Compare acceptance criteria against the merged change. Partial fixes keep the
  issue open with a narrowed residual; say which part is done.
- Distinguish a supported surface from an experimental one before ranking. Do
  not describe an experimental path as implemented because a YAML agent
  definition, configuration section, or placeholder method exists.

### 4. Apply the control-plane stop-the-line checks

Treat these as P0 when live, because each one silently weakens a guarantee
another repository is relying on:

- a downstream write path that bypasses `RepositorySettings`, defaults a
  missing root to `.`, or skips the Git identity check;
- an unconfigured repository reported as verified — "absent" and "configured
  but untrustworthy" must stay distinguishable, and only the second may fail
  closed paths open;
- lock coordination taken with manual acquire/release instead of the context
  manager, or a lease force-released as routine error recovery;
- a downstream mutation without dry-run, staged validation, and atomic
  replacement, or one that reports success while having partially written;
- a quality gate that cannot fail — a guard whose pattern no real input
  matches, a test that skips in CI, or a coverage threshold measured over the
  wrong target set;
- a research provider reachable without both explicit decisions (live
  execution and usage authorization), or a triage plan a named provider can
  bypass silently;
- an experimental surface documented or reported as supported.

### 5. Assign priority, then order by readiness

Use priority for consequence and a separate readiness note for ordering.

- **P0 — stop the line.** A weakened fail-closed boundary, a lock or write
  guarantee that no longer holds, a silently wrong published artifact, or a
  blocker in front of an already-planned downstream rollout.
- **P1 — important and schedulable.** Correctness, reproducibility, packaging,
  or contract gaps in supported surfaces; missing regression coverage for a
  repaired failure mode; a fleet inconsistency that will diverge further.
- **P2 — low-risk or historical.** Documentation drift, refactors, optional
  audits, and work confined to experimental or archived paths with no active
  spillover.
- **CLOSE/UPDATE.** Fixed, superseded, duplicate, no longer applicable, or a
  title materially broader than the remaining work. Cite the exact commit, PR,
  code location, or comment.

Calibrate P0 sparingly. Then order within and across tiers:

1. contract and manifest work before its consumers;
2. anything a coordinated multi-repo rollout is waiting on;
3. recovering evidence already paid for before re-running anything;
4. read-only falsifiers before changes;
5. combine issues only when one patch genuinely satisfies each one's
   acceptance criteria.

Roadmap phase order is a strong default, not an override: a P0 in a later phase
still outranks routine work in an earlier one.

### 6. Report

Return a compact report with:

1. coverage: repository, timestamp, number reviewed, completeness;
2. the top 2–3 next actions and what they unblock;
3. a dependency-ordered P0/P1/P2 table with issue number, status, evidence,
   blockers, affected Mechs, and next acceptance test;
4. CLOSE/UPDATE candidates with specific evidence;
5. unresolved evidence gaps and cross-repository ownership;
6. which downstream work must wait, and on what.

Call out old issues explicitly rather than dropping them. Separate measured
findings, code inspection, inference, and proposed work.

## Conventions this skill enforces

- **Full-queue coverage, not first-page sampling.** State exactly how many
  issues were reviewed and whether coverage was complete.
- **Evidence over vibes.** Every CLOSE/UPDATE/duplicate recommendation cites a
  specific commit, PR, artifact, or code location — never "this looks done."
- **P0 is rare.** If more than ~10% of the queue lands P0, the calibration is
  wrong; recheck. A `P0:` string in a stale title is not evidence.
- **Titles are claims and they drift.** Issues get retitled mid-life, including
  to `[WITHDRAWN]` or `[RESOLVED]`, while staying open. Re-read titles at report
  time rather than trusting the ones fetched at the start of the sweep.
- **The queue moves during the sweep.** Parallel sessions and PRs resolve issues
  while triage is in progress. Re-check the open set immediately before
  reporting, and say so if it changed.
- **Read-only by default.** Ranking happens automatically; every mutation needs
  its own confirmation.

## Measurement discipline

The recurring failure here is not misreading evidence, it is mismeasuring it.
Before citing any of the following, confirm how it was obtained:

- **A stale checkout is not the repository.** This working copy is routinely
  many commits behind `origin/main`, and sibling Mech clones sit on feature
  branches or tens of commits behind. Read code and contracts with
  `git show origin/main:<path>` and `gh api` after fetching — a local read has
  produced confidently wrong answers about what a script already supports.
- **Other sessions edit this repository concurrently.** Files can change under
  you mid-task, and a worktree may contain uncommitted work you did not write.
  Check `git status` and confirm authorship before committing anything you did
  not author; never absorb another session's work into your own branch.
- **A guard that cannot fail is not a guard.** A pattern that no real input
  matches reports green forever. Prove a new guard fails against a known-bad
  input — ideally a real pre-fix revision — before trusting it.
- **A test that skips is not a test that passed.** Fleet contracts that skip
  when repository roots are unset show as green while exercising nothing.
  Assert what was actually exercised, and run them once with roots configured.
- **Mutation-test the fix, not just the test.** Revert the fix in isolation and
  confirm the test goes red. Several tests in this repository have passed
  against the bug they were written for.
- **A transformed fixture is not the fixture you asserted about.**
  `textwrap.dedent` re-indents an embedded document, so a substitution written
  against the original indentation silently does nothing and every negative
  assertion passes for the wrong reason. Make helpers refuse a no-op edit.
- **Exit codes through pipes.** `cmd | tail -3; echo $?` reports `tail`'s
  status, so a fail-closed tool looks like it succeeded. Use
  `cmd >/tmp/o 2>/tmp/e; echo $?`, or `${PIPESTATUS[0]}`.
- **Green is scoped.** Ruff, mypy, and pytest run over explicit target lists
  that do not cover the whole tree, and coverage thresholds are measured over a
  named subset. Say which gate ran over what.
- **Squash merges break ancestry.** Merge commits here have one parent, so
  "is this commit contained in main" cannot be answered with `git merge-base
  --is-ancestor`. Compare content, or find the squash commit.
- **Backticks in a double-quoted `-m`.** `git commit -m "...`cmd`..."` executes
  the backticked text and ships its output in place of the example. Write
  reports and messages containing shell examples via `-F <file>` or a quoted
  heredoc (`<<'EOF'`), then read the result back before pushing.

## Notes and limitations

- `gh issue list --json` omits `comments` unless requested. This repository
  records corrections and narrowed scope in comments, so a body-only fetch
  overstates what is open.
- An issue may be fully addressed in code while its acceptance criteria are
  not. Say which part is done and which is not.
- Claw issues frequently name a downstream Mech. Ownership follows the guarantee
  and not the symptom: if the contract lives here, the issue belongs here even
  when the visible failure is downstream.
- No `@` mentions in issue comments or reports without explicit per-mention
  authorization (standing rule).

## Mutation boundary

Do not close, comment on, relabel, retitle, or create issues or trackers during
the review. If the user later asks to act, present the exact issue numbers and
the proposed mutation first, then apply closures one at a time with cited
evidence. General approval is never authorization for an unattended bulk-close.

**Do not touch a downstream Mech.** Triage reads; the mandatory
cross-repository mutation checklist in `CLAUDE.md` governs every write, and a
recommendation produced here is a proposal, not an approved operation. Do not
acquire a repository lock to look at something.

Do not run a research provider, an apply-mode pipeline, or any non-dry-run
orchestration command as part of triage.

## Related

- `fleet-pr-status` — open-PR inventory across claw and the five Mechs.
- `fleet-pr-review` — ranked merge verdicts for those PRs.
- `cross-mech-sync` — propagating a change once triage says it must land in
  more than one repository.
