# Mech sequence progress

[The Mech progress dashboard](https://culturebotai.github.io/culturebotai-claw/)
shows the manifest-defined fleet's current goal, verified goal closures, complete
six-goal cycles, and distinct pull requests. Its data contract is
[`progress.yaml`](../../src/kg_microbe_progress/schema/progress.yaml), a packaged
LinkML schema. The sequence itself remains governed by
[the workflow contract](MECH_WORKFLOW_CONTRACT.md).

## What the counts mean

A **goal** is one stage of one cycle in one supervised run. The six stages are
add records, causal graphs, protein examples, record review, resolve review
findings, and infrastructure. A **completed cycle** requires verified closures
for all six stages of that same run and cycle. The current stage number never
stands in for missing completion evidence.

A **PR round** is a distinct `(repository, PR number)`, not a commit. Several PRs
can belong to one goal, and one PR associated with multiple goals still counts
once. Open, closed without merge, and merged states are separate. A GitHub merge
does not complete a goal: the supervisor must still verify the review, issues,
validation, evidence, and branch cleanup. A verified no-change goal counts as a
goal and creates no PR.

Counts are lower bounds for explicitly tracked activity. Earlier history is
**unknown**, not zero. A session adopted at stage four does not imply that this
tracker verified stages one through three. Scientific corpus round numbers and
commit messages are not imported as workflow-cycle counts.

## One-line progress report

Run `just mech-progress` from the CLAW checkout, or invoke the
`mech-progress-status` skill:

```bash
uv run python scripts/mech_progress_status.py
uv run python scripts/mech_progress_status.py --published
```

The first reads the local atomic publisher bundle; `--published` reads both
documents at one pinned commit on the GitHub data branch through `gh`. An
alternate local bundle can be selected with `--bundle PATH`.

If the publisher uses a pinned release newer than the local checkout, keep an
exact copy of that release's fleet manifest as `fleet.yaml` beside the local
bundle, or pass `--manifest PATH`. The report validates against that manifest;
when no pin exists it uses the packaged fleet. Invalid pins and fleet
mismatches fail rather than changing the active fleet configuration.

Example output (illustrative counts):

```text
14 Mechs, 8 PRs (5 merged, 3 open), 1 completed goal, 0 completed cycles
```

Closed PRs without a merge are included in the parentheses when nonzero. The
command validates the history and snapshot before reporting counts. Exit 0
means observations are fresh; exit 3 prints the last verified counts and warns
on stderr about a snapshot or Mech observation older than 15 minutes, missing
observations, or timestamps more than one minute in the future. Retain those
warnings when quoting a stale summary. Exit 1 means data could not be verified
and prints no counts; exit 2 means invalid arguments.

## Register every PR in the coding session

As soon as a goal opens a PR, including every follow-up PR, register it using the
CLAW environment and the exact session directory provided by the supervisor:

```bash
/path/to/claw/.venv/bin/python -m kg_microbe_progress.prs register \
  --session-dir /path/to/claw/workspace/session-orchestration/RUN/MECH \
  --number 123
```

Registration copies the current run, repository, cycle, stage, native goal
identity, and workflow digest from matching supervisor ledger and status files.
It atomically adds an idempotent entry to `pr-associations.jsonl` and never edits
the goal ledger. A mismatched or transitioning goal fails and should be retried
after the next supervisor sweep. Do not register an unrelated PR merely because
it was open at the same time. Completed-goal associations remain valid against
the supervisor's retained closure identities. This private registry is never
published.

The collector also accepts exact version-2 completion-receipt PR associations;
these are informational until supervisor closure verification. Noncanonical
progress prose and commit messages are excluded. Previously omitted PRs need an
explicit evidence-backed association; the tracker does not guess from titles,
creation dates, or commit counts.

## Durable records and public projection

`kg_microbe_progress.collect_progress` reads explicit supervisor runtime roots.
The supervisor's archived receipt must match its recorded hash and goal identity
before a closure is exported. The exporter trusts the supervisor's stored
verification; it does not claim to rerun an independent adversarial review.

The history retains append-only goal closures, PR state transitions, and PR-to-
goal associations. Stable identities make repeated collection idempotent. Run
observation cursors may advance, but cannot regress or disappear. Restarts and
new runs retain earlier history. Deleting, rewriting, or conflicting with prior
history fails rather than resetting counters. GitHub state is fetched for each
explicitly associated PR; merged identities and evidence cannot regress.

Public fields are allowlisted and validated structurally with LinkML-generated
JSON Schema and semantically against the fleet and history. The public snapshot
must equal the projection of its history. Native conversation identifiers, local
paths, terminal content, free-form agent summaries, credentials, and arbitrary
links are excluded. PR and repository URLs are reconstructed from fleet identity.

## Collection and publication

The local publisher reads live runtime files; GitHub Actions cannot access the
machine running the agents. First inspect a local collection:

```bash
uv run python scripts/mech_progress_publish.py \
  --runtime workspace/session-orchestration/RUN \
  --state-dir workspace/progress-publisher
```

That command reads GitHub PR facts but does not write to GitHub. Add `--apply` to
publish. Only the first creation of the dedicated `mech-progress-data` branch
also needs `--initialize`. Use repeated `--runtime` arguments to include multiple
supervised runs. `--loop --interval 300` refreshes every five minutes.

The state directory contains a private process lock, an atomically written
`bundle.json`, and an operational `status.json`. Keep it across restarts. A
failed upload retains local observations. Divergent local and remote histories
require explicit reconciliation; they are never overwritten automatically.

Each publication creates one Git commit containing exactly `history.json` and
`progress.json`. Fast-forward-only updates protect against competing publishers.
The branch is a versioned data store; it contains no executable site code and
is not a feature branch to delete after a PR. Publication dispatches the Pages
workflow. A fifteen-minute GitHub schedule recovers missed dispatches.

The Pages workflow executes reviewed main-branch code, pins the data-branch
commit before reading its fixed files, validates the complete bundle, and builds
`site/progress`. The deployment artifact includes `data/publication.json` with
the exact data commit. Deployment alone does not make old observations fresh:
the UI shows both collection time and per-Mech observation age, warns after
15 minutes, and offers the underlying JSON for inspection.

The deployed service must use an explicitly pinned source release and the
configured runtime directories. Check the local publisher status and GitHub
Actions deployment when diagnosing refresh problems. If the local host is
asleep, offline, or the publisher fails, the last valid site remains available
with stale timestamps. Neither the exporter nor the website approves prompts,
resumes goals, merges PRs, or changes terminal state.

## Verification

```bash
uv run --extra dev python -m pytest -q \
  tests/test_progress_model.py tests/test_progress_prs.py \
  tests/test_progress_publish.py tests/test_progress_site.py
uv run --extra dev mypy src/kg_microbe_progress
uv run python scripts/build_mech_progress_site.py --output /tmp/mech-progress-site
```

The build requires an initialized data branch and read access through `gh`.
Test fixtures cover duplicate collection, multiple PRs per goal, restart history,
incomplete cycle coverage, invalid receipt evidence, private-field rejection,
GitHub state changes, and publication failures. Browser checks cover the actual
built desktop/mobile site, controls, disclosures, and failed data loads.
