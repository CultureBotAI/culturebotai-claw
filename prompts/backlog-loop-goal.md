# Backlog loop — pick the right next thing, then finish it properly

**A prompt, not a slash command.** Feed it to the native `/goal`, or paste it to another
agent or an independent reviewer — it is self-contained and drags no wrapper with it.

This file used to live at `.claude/commands/goal.md`, where its frontmatter registered a
CUSTOM `/goal` under the same name as the built-in. **If such a wrapper reappears pointing
here, delete it rather than repointing it** — a project-local `/goal` that is not the built-in
loop is a trap whichever one ends up winning.

`/goal` is a documented built-in command (Claude Code v2.1.139+): it sets a completion
condition and keeps working across turns until a small fast model judges the condition met.
That is exactly the loop this prompt describes, which is why the two belong together as
`/goal <condition>` + this document, rather than a command that replaces it.
See https://code.claude.com/docs/en/goal.

What that collision actually does is **unspecified**, and worth not guessing about. The docs
say a project skill overrides a *bundled* skill of the same name (`/code-review`, `/debug`,
`/loop`), but `/goal` is a *built-in command*, a category the override rule does not mention.
So do not assume the custom one shadows it, or that it loses — neither is documented.

It also sits under `prompts/` to match the other five repos in the fleet, every one of which
keeps its backlog-loop prompt there with no frontmatter. `.claude/commands/curate.md` stays a
command because nothing built-in is called `/curate`.

Run the full cycle on **one** unit of work: understand what is open, rank it,
get agreement on what to do, do it, review it adversarially, and land it.

`$ARGUMENTS` may narrow the scope — a repo name, an issue number, a theme
("test coverage", "CI gaps"), or `report` to stop after Stage 2. With no
arguments, survey the whole fleet.

**The two things this command exists to prevent:** working on the wrong thing,
and declaring something done before it has been checked. Every stage below
serves one of those.

---

## Stage 0 — Orient

Read the repo's `CLAUDE.md` and the user's global rules. They override anything
here. In particular: branch before the first edit, always open a PR, review
before proposing a merge, file issues from the review, and **merging is the
human's call, per PR, in the current conversation.**

## Stage 1 — Inventory (never from memory)

Discover repos from the org, not the filesystem:

```bash
gh repo list CultureBotAI --limit 100 --json name \
  -q '.[] | select(.name | test("(?i)mech$|^culturebotai-claw$")) | .name'
```

Then, per repo, with explicit limits (both `gh` list commands truncate silently
— `gh repo list` at `--limit`, `gh pr list`/`gh issue list` at **30**):

```bash
gh issue list --repo CultureBotAI/$r --state open --limit 200 \
  --json number,title,labels,createdAt,updatedAt,comments
gh pr list --repo CultureBotAI/$r --state open --limit 200 \
  --json number,title,isDraft,headRefName,baseRefName,changedFiles,updatedAt
```

Print raw totals per repo **before** analysing anything. A ranked list of 12
when 15 are open is worse than no list, because it reads as complete.

Then read the issues — not just their titles. **An issue's title is its
hypothesis; its state and comments are the finding.** A `CLOSED / NOT_PLANNED`
issue whose title asserts a bug is evidence that the bug was *refuted*. This
has already produced one false claim in this repo (TraitMech#219). For anything
you intend to act on or cite, check `state`, `stateReason`, and the comments.

## Stage 2 — Prioritise

Rank across the whole fleet, not per repo. Order by:

1. **Silently wrong beats loudly broken.** A guard that passes while verifying
   nothing, a report that is confidently incorrect, a check matching zero files
   — these cost more than a crash, because nobody is looking. This fleet's
   characteristic defect.
2. **Blast radius.** Shared/vendored code and anything five repos import
   outranks a single-repo fix.
3. **Blocks other work.** If it gates a queued PR or another issue, it rises.
4. **Unguarded regressions.** A bug that can silently return outranks one a test
   would catch.
5. **Cost.** Among equals, prefer the cheap one — but never let cheapness
   outrank correctness.

Note explicitly:

- **Dependency order between open PRs.** Which must merge before which, and
  why. Check for two PRs touching the same file, and for a PR that appears to
  revert another — reading the **three-dot** diff (`git diff base...head`, or
  the Files tab), since a two-dot diff also lists files where a branch is
  merely *behind*, which looks identical to a revert and is not one.
- **Anything already in flight** so two sessions do not collide.
- **What you did not read** and why.

Present as a table: rank, repo, issue, one-line why, cost, blocked-by.

## Stage 3 — PAUSE (ask, do not assume)

Show the ranking and **ask the user what to work on** before touching anything.
Offer your recommendation first with a one-line reason. Reasonable options are
usually: the top-ranked item, a specific issue they name, a batch that shares a
branch, or "just the report".

Also ask here — not later — anything whose answer changes the work: an
ambiguous requirement, a choice between designs with different trade-offs, a
question only the maintainer can settle. Do not ask about things you can
determine yourself, and do not ask permission to begin work that has already
been agreed.

If `$ARGUMENTS` already names the item, skip the ranking question but still
surface anything genuinely ambiguous.

## Stage 4 — Do the work

**Branch before the first edit**, not after:

```bash
git worktree add -b <type>/<slug> <scratch>/<slug> origin/main
```

A worktree, not the shared checkout — other agents work in this fleet
concurrently and a dirty tree breaks them.

Then:

- Fix the **cause**, not the symptom. If restoring a value that some process
  overwrites, fix the process too; otherwise the next run undoes it and the
  "fix" is theatre.
- **Write the test that would have caught it**, then prove it works by
  **mutation**: reintroduce the defect and confirm the suite goes red. Record
  how many tests fail. A test that passes on the bug it was written for is
  worse than no test. Watch for tests that only fail probabilistically — if a
  mutant survives some runs, the test is not a guard.
- Run the repo's **own** validators (`just`, LinkML, etc.), not just pytest.
- Run the **exact CI command**, and read the output. `N passed, M skipped` is
  not a clean baseline until you know what the M skips were.

## Stage 5 — Commit and push

**Stage files explicitly. Never `git add -A`** — it sweeps runtime state,
caches, and files some test rewrote into the commit. This has already put a
destructive change into a merged PR here.

Before committing, review your own diff file by file and ask of each: is this
in scope? Anything that is not, drop.

The commit message explains **why**, with the evidence: what was wrong, how you
know, what you measured. Reference issues by number. Then push and open a PR
whose body a reviewer could check without re-deriving anything.

## Stage 6 — Review, adversarially and read-only

Review the diff as a **separate pass**, not a restatement of what you just
wrote. Do not edit, push, or regenerate while reviewing.

Delegating to independent reviewers is good — they find things you will not,
precisely because they did not write it. If you do:

- **Wait for them.** Do not merge because a review is slow. Being slow is not
  the same as being wrong, and a review that arrives after the merge is a
  correction, not a gate. If they overrun, say so and hold, or ask the user.
- Verify their findings yourself before acting. Reviewers are wrong sometimes
  too; reproduce the failure before you accept it.

Check specifically:

- Does the description match the diff? A mismatch is itself a finding.
- Are the PR's factual claims true? They are hypotheses until measured.
- Would the tests fail if the code were wrong?
- **What did CI not run?** No PR CI at all, `paths:` filters excluding the
  changed files, `continue-on-error`, `|| true`, `skipif`, a validator matching
  zero files.
- Does it touch a vendored file without updating every copy? Read the MANIFEST
  rather than reciting a remembered list.
- Security, where workflows are touched: fork-PR execution, token scope,
  self-approval via a broad `gh api` allowlist.

## Stage 7 — File issues, then triage them

**Every finding becomes an issue**, in the repo where the finding lives — not
where it was noticed. An issue is the record that the finding existed even if
the answer is "won't fix". Include the reproduction, the verification, and
options with a recommendation.

Then decide, item by item, what belongs in **this** PR and what does not. Say
which is which and why. Fix the in-scope ones and re-verify. "As needed" is a
real judgement, not a rubber stamp — but a finding you skip must be filed, not
dropped.

## Stage 8 — PAUSE (merge approval)

**Ask the user to merge. Do not merge without an explicit go-ahead in the
current conversation.** Approval of an earlier PR is not approval of this one,
and a green report is not permission.

Present: what the PR does, what the review found and what you did about it,
what remains filed, and — if several PRs are ready — the **dependency order**
you recommend and why.

If the user asked at the outset for a batch to be merged, that is your
go-ahead for those specific PRs; still hold anything new that emerged along
the way, such as a follow-up PR fixing review fallout.

## Stage 9 — Merge and clean up

For each approved PR, in dependency order:

1. Re-check `mergeable` and CI **after** the previous merge — a green check
   from before the base moved proves nothing. For anything non-trivial, merge
   the new base into the branch in a scratch worktree and run the suite.
2. Merge, then delete the branch **remote and local**.
3. Cross-repo closing keywords **do** work when written as
   `Closes <owner>/<repo>#<n>` — claw#42 merged at `00:12:12Z` and closed
   TraitMech#193 at `00:12:13Z`. Do not close such an issue by hand first;
   check whether it already closed. Still comment on it either way, saying what
   landed, what was deliberately left, and what a downstream repo now has to do
   — a closing keyword fires silently and tells the other repo's readers
   nothing.

## Stage 10 — Report

State plainly: what merged, what is still open, what you filed, and **what you
could not verify**. Unverified is a valid result; silently treating it as fine
is not.

If anything you said earlier turned out to be wrong, correct it here in a
sentence and move on.

---

## Standing rules

- **Never merge without explicit per-PR approval.** The most important line here.
- **No @-mentions** in any issue, comment, or commit unless a human authorised
  that specific mention. Name people in plain prose instead.
- **Never commit directly to `main`.** If something already landed there, prefer
  `revert` + `cherry-pick` onto a branch over `reset` + force-push.
- **Canary before any batch.** One real unit, end to end, through the same path
  the batch will take, verifying the side effects rather than the exit code.
- **Report honestly.** If tests fail, say so with the output. If a step was
  skipped, say that.

## Traps this fleet has actually hit

- `gh issue create` does not accept `--json`; it fails, and a `||` fallback can
  make it look like it worked. `gh pr edit --body` has been seen to print a
  Projects-classic GraphQL error and leave the body **unchanged** — it is not
  reliably reproducible, so verify the edit landed rather than trusting either
  the exit code or the absence of output. `gh api -X PATCH
  repos/<owner>/<repo>/pulls/<n> --input <json>` avoids the path entirely.
- macOS APFS is case-insensitive, so a glob for `*/SKILL.md` also matches
  `skill.md` locally and misses it on Linux CI. Match on real directory entries
  when a sweep must agree across both.
- A file on disk is not a file in the repo. Check `git ls-files` before
  reporting a defect in a sibling repo.
- `uv run pytest` may resolve a `pytest` from `PATH` under a different
  interpreter — use `uv run --extra dev python -m pytest`. Note that
  `pytest tests/` can collect fewer tests than CI's bare `pytest`.
- Git pathspec `**/` requires an intervening directory: `data/curated/**/*.yaml`
  matches nothing where `data/curated/*.yaml` matches files.
- `proteintraitsmech` is lowercase on GitHub; CommunityMech nests as
  `CommunityMech/CommunityMech`.
