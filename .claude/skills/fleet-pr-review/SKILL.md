---
name: fleet-pr-review
description: "Review every open PR across the explicit claw control plane and canonical manifest-defined Mech fleet in one pass. Uses exact packaged-manifest identities, runs each repo's own validators, checks what CI did NOT run, and adversarially verifies findings before reporting. Strictly read-only — it never merges, pushes, or edits the branches under review."
category: cross-repo
requires_database: false
requires_internet: true
version: 1.0.0
tags: [review, pr, cross-repo, fleet, quality, read-only, gate]
---

# Fleet PR review

## Purpose

Answer one question for the whole fleet at once: **which open PRs are ready to
merge, and what is wrong with the ones that are not?**

Reviewing PRs one repo at a time hides the things that only show up fleet-wide —
two PRs editing the same vendored file, a PR that reverts what another just
landed, or a scoped fix missing one declared consumer. This skill takes the
whole set in one pass and ranks it.

This is a **reporting** skill. It produces a report and, optionally, GitHub
issues. It does not merge, push, or edit the code under review.

## When to use

- "review the open PRs across the repos"
- Before a merge round, to decide ordering and spot conflicts between PRs
- After a fleet-wide change, to confirm every repo actually got it

For a single PR in depth, use `/dynamic-review` instead — it goes deeper on one
diff. This skill is the breadth pass, and it delegates to that depth pass when a
PR warrants it.

## Scope: exact declared identities, never org-name discovery

The review scope is one explicit control-plane repository plus every identity
in the packaged fleet manifest. It is not every repository in an organization,
and it is not every name ending in `Mech`. An undeclared experimental or future
repository is excluded until the manifest deliberately adopts it.

Build the exact scope once and reuse that immutable file for inventory,
coverage accounting, and subagent dispatch:

```bash
set -euo pipefail
CLAW_REPOSITORY="CultureBotAI/culturebotai-claw"
REVIEW_TMP="$(mktemp -d "${TMPDIR:-/tmp}/fleet-pr-review.XXXXXX")"
MECH_TSV="$REVIEW_TMP/mechs.tsv"
REPOSITORIES="$REVIEW_TMP/repositories.txt"

uv run python -m kg_microbe_fleet list --format tsv > "$MECH_TSV"
test -s "$MECH_TSV" || { echo "Fleet manifest returned no Mechs" >&2; exit 2; }
if awk -F '\t' -v claw="$CLAW_REPOSITORY" \
  '$3 == claw {found=1} END {exit !found}' "$MECH_TSV"; then
  echo "Control-plane identity must not also be a Mech identity" >&2
  exit 2
fi

printf '%s\n' "$CLAW_REPOSITORY" > "$REPOSITORIES"
cut -f 3 "$MECH_TSV" >> "$REPOSITORIES"
test "$(sort -u "$REPOSITORIES" | wc -l | tr -d ' ')" \
  -eq "$(wc -l < "$REPOSITORIES" | tr -d ' ')"
chmod 400 "$MECH_TSV" "$REPOSITORIES"
```

Do not replace this with an organization listing, suffix regex, remembered
table, or repository-name inference. In particular, an unknown `*Mech` repo is
not silently absorbed. The manifest CLI validates identity fields and fails
closed on malformed or duplicate declarations.

Include **draft** PRs, marked as such. A draft that reverts a merged fix still
matters. Exclude nothing silently: if you skip a PR, the report must say which
and why.

## Procedure

### 1. Inventory

```bash
INVENTORY_FAILURES="$REVIEW_TMP/inventory-failures.txt"
: > "$INVENTORY_FAILURES"
while IFS= read -r repository; do
  printf '\n=== %s ===\n' "$repository"
  if ! gh pr list --repo "$repository" --state open --limit 200 \
    --json number,title,isDraft,author,createdAt,updatedAt,headRefName,baseRefName,additions,deletions,changedFiles,labels; then
    printf '%s\n' "$repository" >> "$INVENTORY_FAILURES"
  fi
done < "$REPOSITORIES"
if test -s "$INVENTORY_FAILURES"; then
  echo "Inventory is incomplete; failed identities:" >&2
  sed 's/^/  /' "$INVENTORY_FAILURES" >&2
fi
```

`--limit` is not optional here. `gh pr list` defaults to **30** and truncates
silently.

Print the raw inventory **before** reviewing anything, so the reader can see the
denominator. A report on 5 PRs when 6 are open is worse than no report.

API-only review steps do not need local checkouts. When a validator or
counterfactual test does, query identity-validated Mech targets rather than
guessing paths:

```bash
LOCAL_TARGETS="$REVIEW_TMP/testing-targets.tsv"
uv run python -m kg_microbe_fleet targets \
  --capability testing > "$LOCAL_TARGETS"
```

Each row is `key`, display name, exact GitHub identity, root variable, and a
validated absolute root or an empty unconfigured field. Match the PR's exact
GitHub identity to field three. Never fall back from an empty field to a
remembered directory. For an unconfigured Mech, or for the explicit claw
control plane, make a private temporary clone from the exact identity in
`$REPOSITORIES`, then create the counterfactual worktree inside that clone.
This avoids both unvalidated local state and edits to a shared checkout.

### 2. Cross-PR analysis (do this before the per-PR passes)

This is the step that justifies doing all repos at once. Look for:

- **Same file, two PRs.** Especially vendored files that must stay byte-identical
  across repos. The vendored set is declared only in
  `src/kg_microbe_governance/vendored_artifacts.json`; read it together with the
  capability scopes in `src/kg_microbe_fleet/fleet.yaml`, rather than reciting a
  remembered list. The installed `kg-microbe-governance fleet-audit` command is
  the enforcer used by `.github/workflows/governance-fleet-audit.yaml`. For a
  rollout, audit the five exact `origin/main` commits against their common,
  immutable claw pin. Two independently-correct PRs can both be wrong together.
- **Revert pairs.** A PR that undoes something recently merged. **Read the
  three-dot diff** (`git diff origin/main...HEAD`, or the Files tab, which shows
  three-dot). A two-dot `git diff origin/main HEAD` also lists files where the
  branch is merely *behind* `main`, which looks identical to a revert and is not
  one. Only a file the branch actually **modified** can revert anything; confirm
  with `gh api repos/<owner>/<repo>/pulls/<n>/files`, and simulate the result
  with `git merge-tree --write-tree` before claiming it.

  This trap has already produced a false blocking verdict in the fleet after a
  branch turned out to be merely behind on a workflow file, not reverting it.
  Treat a suspected revert as a hypothesis until the three-dot diff shows the
  file.
- **Fleet-wide fixes with a missing declared repo.** If a change lands in only a
  subset of its manifest-scoped consumers, that is a finding, not an omission
  to be polite about.
- **Dependency order.** Which PRs must merge before which. State the order
  explicitly; do not leave it implied.
- **Duplicate IDs / overlapping data edits** between repos.

### 3. Per-PR review

Run these in parallel — one subagent per PR — and give each subagent the repo's
own context (`CLAUDE.md`, `justfile`, LinkML schema). For a large or risky diff,
have the subagent invoke `/dynamic-review` with `{repo, target: "PR:<n>",
depth: "thorough"}` rather than reimplementing a deep review.

For each PR the reviewer must establish:

**a. What the diff actually does**, in its own words, from the diff — not from
the PR description. A description that does not match the diff is itself a
finding.

**b. Whether the claims are true.** If the PR says "7,858 xrefs improve with zero
regressions", check it. Claims in PR bodies are hypotheses.

**c. Whether the tests would fail if the code were wrong.** Do not accept a green
run as evidence. Revert the substantive change and confirm the suite goes red —
**in a throwaway `git worktree`, never in a live checkout.** Other agents are
working in this fleet concurrently; mutating a shared tree to test a hypothesis
breaks them, and it contradicts the read-only rule below. Create the worktree,
mutate, run, and remove it.
A test that passes on the bug it was written for is the single most common defect
in this fleet's history. One real example: a determinism test compared two
generated files that both embedded a whole-second timestamp — against the very
bug it existed to catch it passed **19 runs out of 20**, because both runs landed
in the same second.

**d. What CI did *not* run.** Mandatory, not optional:

- Read the actual test output. `76 passed, 2 skipped` is **not** a clean
  baseline until you know what the 2 skips were. In one prior review they were
  the only two data-driven invariants in the file — skipped because `data/raw` was
  gitignored and the repo had no PR CI at all. The review that quoted "76 passed"
  as clean was wrong, and had to be publicly corrected.
- Does the repo even have PR CI, or only `schedule:`/`push: main` workflows?
- `paths:` filters that exclude the changed files.
- `continue-on-error: true`, `|| true`, `if: always()` on a gating step.
- `@pytest.mark.skipif` on the tests that matter.
- A validator run against zero files. A prior `data/curated/**/*.yaml` pathspec
  matched nothing because git `**/` requires an intervening directory.

Report the gate's *effective* coverage, not its name.

**e. Fleet conventions.** Does it hardcode an interpreter path instead of
`uv run python`? Undeclared imports? Does it touch a vendored file without
updating every copy?

**f. Security**, where the diff touches workflows: fork-PR execution paths,
token scope, `gh api` in an allowlist (which permits self-approval), comments
inside `claude_args:` block scalars.

### 4. Adversarially verify before reporting

Every candidate finding gets an independent skeptic whose job is to **refute** it,
defaulting to "refuted" when uncertain. Drop what does not survive. A review that
reports six findings of which two are wrong is worse than one that reports four
solid ones — it costs the maintainer trust and time.

Where a finding can fail in more than one way, give the verifiers different
lenses (correctness / does-it-reproduce / is-it-in-this-diff) rather than three
identical passes.

### 5. Report

Lead with the table, then the detail. Rank by severity across the whole fleet,
not per repo.

```markdown
## Fleet PR review — <N> open PRs across <M> repos

| Repo | PR | Title | Verdict | Blocking findings |
|---|---|---|---|---|
| <manifest display name> | #226 | … | ready | — |
| <manifest display name> | #316 | … | changes needed | 2 |
| claw | #42 | … | ready, merge after #41 | — |

### Merge order
1. …  (because …)

### Per-PR detail
…

### Not reviewed
… and why
```

Verdicts: **ready** / **changes needed** / **blocked** (on another PR or an
external answer) / **needs author** (a question only they can settle).

For each finding give: severity, `file:line`, the concrete failure scenario
(inputs → wrong behaviour), and how it was verified. "This looks fragile" is not
a finding.

State plainly what the review could **not** check — a validator that needs
credentials, a claim resting on ungitignored data, a runtime behaviour not
exercised. Unverified is a valid and useful result; silently treating it as fine
is not.

## Rules

- **Read-only.** Do not edit files in the PR's branch, do not push, do not
  regenerate outputs, do not `gh pr merge`. Reviewing and fixing in the same pass
  is how a reviewer stops seeing the code as it is.
- **Never merge.** Merging is the maintainer's call, per-PR, in the current
  conversation. A green report is not permission.
- **No @-mentions** in any issue or comment this skill creates. Name people in
  plain prose instead. See the global standing rule.
- **Posting is opt-in.** Default is a report to the session. Post inline PR
  comments or file issues only when explicitly asked.
- **Report the count honestly.** If a repo's PR list failed to fetch, say so
  rather than reporting on what did come back.

## Filing issues from the review

When asked to file, one issue per finding, in the repo where the finding lives —
not where it was noticed. Shared-library bugs go to claw even when a Mech is
where the cost shows up. Include the reproduction, the verification, and the
options with a recommendation. An issue is the record that the finding existed
even if the answer turns out to be "won't fix".

## Known traps

- `gh pr edit --body` can fail with a Projects-classic GraphQL error and still
  exit 0. Verify the edit landed, or use
  `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> --input <json>`.
- **Repository identity and local checkout spelling can differ.** Preserve the
  exact GitHub identity from the manifest and use only the validated path from
  `targets`; never derive one from the other.
- **macOS hides case bugs.** APFS is case-insensitive by default, so a glob for
  `*/SKILL.md` also matches `skill.md` locally and finds nothing on Linux CI.
  A fleet repo previously carried a mixed `skill.md`/`SKILL.md` split until it
  normalized the casing, so a fleet sweep that globs one spelling can
  under-report on CI and over-report on a Mac. Match both casings, and state
  which files were actually examined.
- **A file on disk is not a file in the repo, and a local clone is not the
  repo.** Check `git ls-files` before reporting a defect in a sibling repo — an
  untracked local artifact is not something that repo is shipping. Then check
  `git rev-list --count HEAD..origin/main`: reporting from a stale checkout is
  the same error one level up, and has already produced a wrong answer here
  about a task that a sibling repo had finished 25 commits ago. Prefer
  `git ls-tree -r origin/main` or the API over the working tree.
- A configured checkout may be nested or named differently from its GitHub
  repository. The validated target path is authoritative.
- `uv run pytest` can resolve a `pytest` from `PATH` under a different
  interpreter. Use `uv run --extra dev python -m pytest` and compare the
  collected count against CI's.
- Running `pytest tests/` locally may collect fewer tests than CI's bare
  `pytest`, which also picks up root-level and `scripts/` test files. Compare
  totals before concluding anything from a local run.
