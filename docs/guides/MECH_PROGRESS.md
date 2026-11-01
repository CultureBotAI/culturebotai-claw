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

Example output (`N` is the tracked fleet size; other counts are illustrative):

```text
N Mechs, 8 PRs (5 merged, 3 open), 1 completed goal, 0 completed cycles
```

Closed PRs without a merge are included in the parentheses when nonzero. The
command validates the history and snapshot before reporting counts. Exit 0
means observations are fresh; exit 3 prints the last verified counts and warns
on stderr about a snapshot or Mech observation older than 15 minutes, missing
observations, or timestamps more than one minute in the future. Retain those
warnings when quoting a stale summary. Exit 1 means data could not be verified
and prints no counts; exit 2 means invalid arguments.

## Save stats responses and historical snapshots

Keep stats requested in conversation in the local structured report
`workspace/reports/mech-stats/report.json`. Its `snapshots` array is ordered by
the snapshot's actual `as_of` timestamp. Its separate `responses` array contains
only attributable answers: an available snapshot does not establish that an
answer was sent. Unknown message times remain `null`, and reconstructed answer
summaries are marked `text_kind: summary` rather than presented as verbatim.
Recovered transcript replies without a matching full bundle are kept in
`response_only_observations`, with `snapshot_id: null` and explicitly
transcript-reported `reported_counts`. These are not validated historical
snapshots. Exact recovered replies may supersede an earlier summary through
`superseded_by`; exclude superseded summaries when counting actual replies.
Transcript-backed records retain original prompt/message times and source-line
references. The `record_response_history` helper supports this narrow backfill
and parses only the leading stats line, preserving stale qualifications as text.
For a numeric report embedded in a longer final response, an optional
`reported_summary` must be an exact unique excerpt of that response; only this
explicit excerpt is parsed, and the complete original reply remains retained.

Archive a previously collected bundle without collecting or publishing:

```bash
uv run python scripts/mech_stats_record.py --bundle /path/to/bundle.json \
  --manifest workspace/progress-publisher/fleet.yaml \
  --source "read-only runtime and GitHub collection"
```

To associate an actual response, pass `--response-file /path/to/response.json`
with this JSON shape (the values below describe the fields, not measurements):

```json
{
  "source_id": "stable identifier for this particular response",
  "source": "conversation transcript or supplied conversation summary",
  "text_kind": "verbatim",
  "text": "Exact answer text, or an explicitly attributed summary",
  "responded_at": null,
  "prompt": null
}
```

Use a timezone-aware `responded_at` only when the message timestamp is known;
the snapshot time and archive time are separate facts. Set `text_kind` to
`summary` when the original wording is unavailable. Never import examples or
requested display formats as observations. Reusing a `source_id` deduplicates
the same response and rejects conflicting content.

Use the same saved bundle for the numerical answer and its archive. A publisher
update between reporting and archiving can otherwise select a different
measurement. The recorder automatically parses a leading stats line or an
explicit unique `reported_summary` excerpt and rejects counts that differ from
the linked snapshot, even when `reported_counts` was omitted. Nonnumerical
summaries remain unparsed; numbers appearing only in later notes are not inferred.
Supersession must be acyclic. Multiple summaries may share one replacement, and
valid replacement chains retain their final unsuperseded response.

The recorder validates the full history/snapshot bundle against its pinned
fleet before saving. Each snapshot retains totals, per-Mech counters and current
state, freshness warnings evaluated at archive time, source attribution, and
hash references to complete archived bundle/fleet files. Optional
`--observations /path/to/observations.json` retains additional raw PR observations
as supplementary provenance; it does not derive counts from them. The original
snapshot includes the detailed PR and verified goal-closure history.

Existing reports and evidence are revalidated before an atomic report update.
Identical imports are idempotent; historical snapshot backfills do not create
response records. `--report-dir PATH` selects another local archive. These files
remain under the existing ignored workspace: saving them does not publish,
change the active collector, or advance supervised goals.

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
