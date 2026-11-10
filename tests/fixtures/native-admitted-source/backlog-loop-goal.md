# Backlog loop: select and deliver the right issue end to end

**Use:** Paste this prompt into Claude Code's native `/goal`; it is not a slash command. Keep it
under 4,000 ASCII characters and without YAML frontmatter. `$ARGUMENTS` may name
a repository, issue, theme, or `report`; otherwise inspect the full backlog.

Work until the agreed issue or batch is merged, its review findings are
resolved or filed, its branches/worktrees are removed, and the relevant tests
are green. Follow the repository's `CLAUDE.md` and optional
`prompts/backlog-loop-local.md`; they own local gates and data rules. Never spend
provider credits or mutate curated data without explicit authorization.

## 1. Reconcile before choosing

- Read `CLAUDE.md`, inspect Git status, and preserve unrelated work.
- Query all remote issues and PRs with explicit limits; print totals before
  ranking and verify pagination completeness.
- Read full bodies, state reasons and all comments of cited or selected items.
  Titles are not findings. Reproduce the premise on
  current `origin/main`; a stale local clone is not the repository.
- Reconcile open work, overlaps, dependencies and blockers. Use three-dot PR
  diffs; two-dot diffs can make a behind branch resemble a revert.
- Rank silently-wrong behavior first, then blast radius, blockers, missing
  regression gates, and cost. State what was not inspected.
- If no item was named, recommend one and pause for the user's choice. Also
  pause for decisions whose alternatives materially change the result.

## 2. Implement in isolation

- Fetch `origin/main`; branch before edits in a dedicated worktree under
  gitignored `<repo>/.temp/`, or `~/agent-work/<repo>/` for a separate clone.
  Never use `/tmp`, `/private/tmp` or `$TMPDIR` for campaigns, clones, helpers or handoffs;
  only disposable caches and pytest temp may. Never use a dirty shared checkout.
- Fix the cause. Add the smallest regression test that would have caught it.
  Mutate or otherwise prove the test fails on the old behavior.
- Mutators default to dry-run and require explicit apply/write. Do not make
  network/provider calls merely to test integration.
- Run focused tests, native and relevant CI checks, and `git diff --check`.
  Inspect skips; a green command finding zero targets is not evidence.
- Review every changed file for scope. Stage files explicitly; do not sweep
  runtime artifacts with `git add -A`.

## 3. Commit, push, and review

- Commit cause and issue. Push each batch branch to origin the same day,
  even without a PR; verify its remote head. Commits that exist only locally
  block goal closure. Use explicit refspecs and measured PR claims.
- Perform a separate read-only adversarial review. Check description versus
  diff, false factual claims, edge cases, whether the regression test kills the
  old behavior, CI path filters/skips, security-sensitive workflow changes,
  generated artifacts, and every vendored copy named by a manifest.
- Reproduce each finding. File every confirmed finding as an issue in the repo
  where it lives, even when it will be fixed immediately. Triage which findings
  belong in this PR, fix those, rerun checks, and report deferred ones.

## 4. Merge and finish

- If the user did not already authorize merging this batch, pause with the PR,
  checks, review findings, and recommended merge order. Prior authorization for
  the named batch is sufficient; it does not cover newly discovered work.
- Immediately before each merge, refresh the base and recheck mergeability and
  CI. Merge only green, non-draft PRs in dependency order.
- Verify closing keywords closed the intended issues. Delete remote/local
  branches and remove worktrees only after merge; never touch another session's
  tree.
- Re-query open issues and PRs. Report merged URLs, exact tests, filed follow-ups,
  remaining blockers, cleanup, and whether the working tree is clean.

Completion means the selected scope is merged and verified, not merely coded.
