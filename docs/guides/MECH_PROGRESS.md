# Mech sequence progress

[The Mech progress dashboard](https://culturebotai.github.io/culturebotai-claw/)
shows the manifest-defined fleet's current goal, verified goal closures, complete
versioned goal cycles, and distinct pull requests. Its data contract is
[`progress.yaml`](../../src/kg_microbe_progress/schema/progress.yaml), a packaged
LinkML schema. The sequence itself remains governed by
[the workflow contract](MECH_WORKFLOW_CONTRACT.md).

## What the counts mean

A **goal** is one stage of one cycle in one supervised run. Parent v2 adds open
issue triage before add records, causal graphs, protein examples, record review,
resolve review findings, and infrastructure. A **completed cycle** requires
verified closures for all stages of that run and cycle: six for pinned v1 cycles,
seven for v2. Six v2 closures do not constitute a complete cycle. The current
stage number never stands in for missing completion evidence.

Each new v2 cursor and closure carries its cycle's `parent_version`. Historical
public records without that field retain v1 stage meanings and remain unchanged.
The collector reads the supervisor's per-cycle version history rather than
applying the current cycle's stage numbers to earlier evidence. A version change
inside an observed cycle is rejected. This PR changes accounting compatibility;
it does not migrate live runs, re-pin Mechs, or publish progress data.

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

The optional `--durability-runtime PATH` appends saved local per-Mech alerts
for unpublished commits and owned temporary files approaching cleanup. Supply
the actual verified supervisor runtime; the command reads it without scanning
or changing sessions. Missing or stale observations remain unknown and exit 3.
The public bundle schema and counters are unchanged. See
[session-state durability](SESSION_STATE_DURABILITY.md) for ownership inventory,
read-only boundaries and publication requirements.

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

Collection excludes a well-formed registry record when its goal context is no
longer among the ledger's current or retained completed goals. Each observed
run cursor records `excluded_pr_associations`; each repository's snapshot sums
these counts across its retained run cursors. These count registry records, not
distinct PRs, and describe the latest collection of each run rather than a
cumulative total. An omitted run retains its last observed count. A direct
`collect_progress` call that omits the count map also preserves prior counts;
absence of a measurement does not assert zero. Older bundles without this
diagnostic remain readable; absence means it was not recorded. The count exposes
no native identity or private registry content.

A retained valid association takes precedence over a conflicting well-formed
orphan, including when a goal re-adopts the same PR. Conflicts between retained
valid associations still fail. Malformed or unsafe input, cross-run/repository
records, and malformed retained goal contexts fail closed. Registration validates
all existing records, preserves the original bytes of orphan records, and can
append a valid PR association for the current goal while orphans are present.
Collection never rewrites a registry or ledger. Exclusion does not remove
previously validated public history: a PR may remain visible through its retained
historical association or another valid binding.

## Durable records and public projection

Fleet members tagged `exclude-from-public` remain in local collection, saved
history and internal status. The publication boundary filters all four history
collections before recomputing counters against `FleetManifest.public()`.
Neither the public data branch nor the Pages build emits an excluded member's
identity, PRs, cursors, closures or numerical contribution. `--published` status
uses this same public fleet; ordinary local status retains the complete fleet.

Public remote history is reconciled with the public projection of local history.
A newer remote cursor or event cannot erase excluded local evidence. Existing
full-fleet bundles remain valid inputs and are projected before serialization;
malformed excluded evidence still fails validation. This updates code only:
upgrade the publisher and Pages consumers to the reviewed release before
publishing a run containing an excluded member. No running service, existing
data-branch commit or deployed site changes merely by preparing this patch.

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
`site/progress`. When `fleet.yaml` admits a new Mech at the end of the manifest
before `mech-progress-data` has been rewritten by an upgraded publisher,
`project_bundle_to_manifest` validates the published bundle against the prefix
manifest, confirms the newly admitted suffix Mechs have no historical entries,
and projects `unobserved` zero-counter rows so Pages, `--published` status, and
the first post-expansion publication succeed without losing strict validation.
The deployment artifact includes `data/publication.json` with
the exact data commit. Deployment alone does not make old observations fresh:
the UI shows both collection time and per-Mech observation age, warns after
15 minutes, and offers the underlying JSON for inspection.

The deployed service must use an explicitly pinned source release and the
configured runtime directories. Check the local publisher status and GitHub
Actions deployment when diagnosing refresh problems. If the local host is
asleep, offline, or the publisher fails, the last valid site remains available
with stale timestamps. Neither the exporter nor the website approves prompts,
resumes goals, merges PRs, or changes terminal state.

### Compatibility and upgrade order

The optional `excluded_pr_associations` diagnostic is an incompatible extension
for old readers, despite retaining `schema_version: "1.0.0"`. Their closed schema
rejects that field with `Additional properties are not allowed`. The updated
reader accepts existing bundles that omit it. A matching version string alone
therefore does not establish compatibility; pin consumers to the reviewed code.
This release chooses a coordinated consumer upgrade rather than introducing a
history migration or downgrade mechanism.

The cycle-v2 `parent_version` fields and seventh stage have the same upgrade
boundary. New readers accept unchanged v1 history, but six-stage readers cannot
read v2 bundles or correctly count them. Upgrade consumers before the first v2
cycle is collected. Keep old closures and receipt hashes unchanged; do not
renumber them or strip their cycle version to make an old reader accept them.

Before the updated publisher first writes a bundle to the production state
directory or publishes one, upgrade **every consumer** to the merged main commit
or a pinned release containing the change. This includes the Pages workflow,
the publisher, and every checkout used for `scripts/mech_progress_status.py`
(local and `--published` modes) or the `mech-progress-status` skill. Merely
updating Pages is insufficient: an older status checkout also rejects the new
bundle. Verify these consumers before starting the updated publisher. A dry run
in an isolated temporary state directory can precede the upgrade; its generated
bundle must be read only by updated consumers.

After the first updated bundle is written locally or published, rollback to the
old publisher is impossible with the retained history: it cannot read the new
fields, even when the diagnostic is zero. Retain the previous release and
backups for investigation, but do not strip diagnostic fields, reset history,
or replace newer observations with an old bundle to bypass this boundary.
Recover with a release that understands the extended schema; an older binary
would require a separately reviewed compatibility change before it could run.

### Reading status without updating the monitor checkout

If the live monitor checkout cannot be safely updated in place, leave it
untouched and run status from the pinned updated release instead. This meets
the consumer upgrade requirement without switching the monitor checkout or
changing its dependencies. Use that release's `mech-progress-status` skill and
substitute these commands for its checkout-relative `uv` or `just` invocation.
The release must already contain the reviewed change and its own environment,
as prepared by the installation procedure below.

Set `STATE` to the existing production publisher state directory and `RELEASE`
to the exact reviewed release. Both status modes explicitly select the producer's
fleet pin; local status also explicitly selects the production bundle so it
cannot accidentally read a different checkout's default state directory:

```bash
STATE=/absolute/path/to/production/progress-publisher
RELEASE="$STATE/releases/FULL_REVIEWED_MAIN_COMMIT_SHA"
PYTHON="$RELEASE/.venv/bin/python"

env PYTHONPATH="$RELEASE/src:$RELEASE" "$PYTHON" \
  "$RELEASE/scripts/mech_progress_status.py" \
  --bundle "$STATE/bundle.json" --manifest "$STATE/fleet.yaml"

env PYTHONPATH="$RELEASE/src:$RELEASE" "$PYTHON" \
  "$RELEASE/scripts/mech_progress_status.py" \
  --published --manifest "$STATE/fleet.yaml"
```

These commands read saved evidence; they neither deploy nor restart a publisher
or monitor. For the skill, return stdout unchanged and retain any freshness
warnings on stderr. Do not continue using the old checkout's status command
after updated bundles appear, and do not edit or remove the fleet pin to make
an incompatible reader accept them.

### Installing a reviewed publisher release

This is an operator procedure, not an automatic deployment command. First merge
the reviewed change and complete the consumer upgrades above. Choose the exact
reviewed main commit, not a moving branch name. Use a separate review checkout
to obtain its archive; never switch the checkout used by running monitors.
Preserve the state directory and every configured `--runtime` argument.
Keep the release archive and assessed dry-run bundle under the review
checkout's gitignored `.temp/` durable root; verify its ignore rule first. The
example below has one runtime; repeat that argument when the existing deployment
has more.

```bash
set -euo pipefail
CLAW_ROOT=/absolute/path/to/live-claw
REVIEW_CHECKOUT=/absolute/path/to/review-checkout
REVIEWED_COMMIT=FULL_REVIEWED_MAIN_COMMIT_SHA
STATE="$CLAW_ROOT/workspace/progress-publisher"
RUNTIME="$CLAW_ROOT/workspace/session-orchestration/RUN"
RELEASE="$STATE/releases/$REVIEWED_COMMIT"

git -C "$REVIEW_CHECKOUT" fetch origin main
test "$REVIEWED_COMMIT" = "$(git -C "$REVIEW_CHECKOUT" rev-parse "${REVIEWED_COMMIT}^{commit}")"
git -C "$REVIEW_CHECKOUT" merge-base --is-ancestor "$REVIEWED_COMMIT" origin/main
test ! -e "$RELEASE"
mkdir -p "$STATE/releases"
mkdir "$RELEASE"
DURABLE_ROOT="$REVIEW_CHECKOUT/.temp"
mkdir -p "$DURABLE_ROOT"
ARCHIVE="$(mktemp "$DURABLE_ROOT/mech-progress-release.XXXXXX")"
git -C "$REVIEW_CHECKOUT" archive --format=tar --output="$ARCHIVE" "$REVIEWED_COMMIT"
tar -xf "$ARCHIVE" -C "$RELEASE"
printf '%s\n' "$REVIEWED_COMMIT" > "$RELEASE/REVISION"
shasum -a 256 "$ARCHIVE" > "$RELEASE/archive.sha256"
UV_PROJECT_ENVIRONMENT="$RELEASE/.venv" uv sync --project "$RELEASE" --locked
PYTHON="$RELEASE/.venv/bin/python"

DRY_STATE="$(mktemp -d "$DURABLE_ROOT/mech-progress-dry-run.XXXXXX")"
cp -p "$STATE/bundle.json" "$DRY_STATE/bundle.json"
cp "$RELEASE/src/kg_microbe_fleet/fleet.yaml" "$DRY_STATE/fleet.yaml"
env PYTHONPATH="$RELEASE/src:$RELEASE" "$PYTHON" \
  "$RELEASE/scripts/mech_progress_publish.py" \
  --runtime "$RUNTIME" --state-dir "$DRY_STATE"
```

Stop at any failed command. Inspect the dry-run bundle's timestamp, exclusions,
and totals before proceeding. It writes only the temporary state directory and
makes no GitHub mutations. The release's own virtual environment avoids
upgrading dependencies underneath the live monitors.

Immediately before stopping the old publisher, verify its PID, start time, and
full command against the recorded deployment. Do not signal an unverified PID or
start a second publisher while the first is alive. `SIGTERM` asks the publisher
to finish its current collection and exit; wait for that exit without forcing
termination. Then preserve the current bundle, status, and fleet pin, install
the new release's fleet pin atomically, and start the pinned command:

```bash
PUBLISHER_PID=VERIFIED_CURRENT_PUBLISHER_PID
ps -p "$PUBLISHER_PID" -o pid=,lstart=,command=
# Compare the identity above with the recorded deployment before this signal.
kill -TERM "$PUBLISHER_PID"
while kill -0 "$PUBLISHER_PID" 2>/dev/null; do sleep 1; done
BACKUP="$STATE/backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP"
cp -p "$STATE/bundle.json" "$STATE/status.json" "$BACKUP/"
if test -f "$STATE/fleet.yaml"; then cp -p "$STATE/fleet.yaml" "$BACKUP/"; fi
FLEET_TEMP="$(mktemp "$STATE/.fleet.yaml.XXXXXX")"
cp "$RELEASE/src/kg_microbe_fleet/fleet.yaml" "$FLEET_TEMP"
mv "$FLEET_TEMP" "$STATE/fleet.yaml"
nohup env PYTHONPATH="$RELEASE/src:$RELEASE" "$PYTHON" -u \
  "$RELEASE/scripts/mech_progress_publish.py" \
  --runtime "$RUNTIME" --state-dir "$STATE" --apply --loop --interval 300 \
  >> "$STATE/publisher-$REVIEWED_COMMIT.log" 2>&1 < /dev/null &
printf 'Publisher PID: %s\n' "$!"
```

Record the new PID and release pin. Verify `status.json` reports `published`,
the data branch advances, and the Pages artifact's `data/publication.json`
identifies that data commit. Do not use `--initialize` for an existing data
branch. Retain the previous release and backup; do not prune releases, reset
history, or restore an old bundle over newer observations as a rollback. The
compatibility boundary above rules out restarting a pre-diagnostics publisher
after the updated publisher has written its first production bundle.

## Verification

```bash
uv run --extra dev python -m pytest -q \
  tests/test_progress_model.py tests/test_progress_prs.py \
  tests/test_progress_publish.py tests/test_progress_site.py
uv run --extra dev mypy src/kg_microbe_progress
uv run python scripts/build_mech_progress_site.py --output .temp/mech-progress-site
```

The build requires an initialized data branch and read access through `gh`.
Test fixtures cover duplicate collection, multiple PRs per goal, restart history,
incomplete cycle coverage, invalid receipt evidence, private-field rejection,
GitHub state changes, and publication failures. Browser checks cover the actual
built desktop/mobile site, controls, disclosures, and failed data loads.

An accepted [ordered multi-PR closure](MECH_SESSION_WORKFLOWS.md#ordered-multi-pr-closure-receipts)
contributes every independently verified member PR to the existing PR event and
association history. The goal closure remains one event naming the final
integration PR, so public schemas and single-PR history are unchanged. Member
identity and order must match the hash-bound archived receipt; an incomplete or
mismatched stored proof fails collection. A working multi-PR receipt may report
its member associations but never grants completion authority.
