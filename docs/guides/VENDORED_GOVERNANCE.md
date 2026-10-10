# Claw-authoritative vendored governance

The canonical source for general byte-identical Mech artifacts is
`src/kg_microbe_governance/`. The package contains one strict manifest, the
canonical payload bytes, a provenance-verifying synchronizer, and the
standalone checker that each Mech vendors. Domain schemas, provider profiles,
prompts, adapters, and data remain owned by their Mech.

The claw repository is public. Public status was reverified on 2026-08-25, so
public Mech CI can read a pinned raw GitHub revision without credentials.

## Authority contract

`src/kg_microbe_governance/vendored_artifacts.json` is the only artifact list.
Every row declares:

- a stable artifact identifier;
- its canonical claw path and consumer-relative target path;
- fleet-wide or capability-scoped applicability;
- a SHA-256 digest; and
- the Git owner-executable-bit contract and safe write permissions.

The manifest's consumer identities and package paths are checked against
`src/kg_microbe_fleet/fleet.yaml`, which is the authority on how many there
are. Edison capture is checked against the `edison_key_discovery` capability,
and the provider-triage contract test against `deep_research`, rather than
independent repository lists.
Unsafe paths, duplicate JSON keys, duplicate expanded targets, unknown
consumers, missing package resources, and checksum drift are rejected.

Each Mech stores one full 40-character claw commit in
`scripts/.vendored_canon_ref`. The vendored checker downloads the manifest and
payloads from exactly that revision, validates manifest checksums, then compares
the local paths byte-for-byte, checks their owner-executable bits, and rejects
group/other-writable governed files and pins. It also
requires the exact Git worktree root and verifies every origin fetch and push
URL against the selected consumer. A branch name, tag, abbreviated SHA,
multiple-line pin, or Mech repository as authority is not accepted. Claw never
pins itself.

## Synchronizing a Mech

### Cross-corpus record links

The governed `mech_shared.yaml` provides `CrossCorpusLink` with four required
string fields (`corpus`, `identifier`, `relation`, `basis`) and the optional
string `source_version`. These field names retain NaturalProductMech's existing
serialized links. The shared module deliberately leaves domain vocabularies,
target validation, organism scope and evidentiary rules to each consumer.

A consumer can narrow the relation without duplicating the shared class:

```yaml
classes:
  NaturalProductCrossCorpusLink:
    is_a: CrossCorpusLink
    slot_usage:
      relation:
        range: CrossCorpusRelationEnum
```

Point the record's `related_records` range at that subclass and keep the local
enum. New consumer slots should be optional, multivalued and `inlined_as_list`.
For new links, record the full immutable commit checked in `source_version` and
verify the target identifier against that revision. A shared protein or reaction
is a review lead and cannot establish a stronger mechanistic or equivalence
relation by itself. Source-owned records must emit links through their maintained
extractor/seeder path; curated links must survive subsequent seeding.

Roll out a canonical class change by updating its manifest digest, committing
the canonical revision, and then synchronizing every consumer to that immutable
revision before adding consumer-specific links. A locally prepared commit is
not yet available to the remote provenance checker: publish the reviewed claw
revision before claiming the ordinary synchronization gate passed. Keep consumer
schema and data changes in their own repositories.

### Synchronization commands

Run the installed command from claw. It validates that `--target-root` is the
exact Git worktree root and that its `origin` matches the selected manifest
consumer. Before planning or writing, it fetches the manifest and every payload
from the supplied immutable claw revision and requires those bytes to match the
installed package. A typo, nonexistent commit, or package/ref mismatch is
therefore rejected before the target changes. These bounded public-GitHub
fetches use no model, research provider, credential, or paid API. Dry-run is the
default:

```bash
uv run kg-microbe-governance sync \
  --repository traitmech \
  --target-root /path/to/TraitMech-worktree \
  --ref <full-claw-commit>
```

A re-pin plans one file, `scripts/.vendored_canon_ref`, in a consumer that is
otherwise current, but a Mech can keep its own copy of the pin elsewhere. The
synchronizer does not know about it and the re-pin then breaks that Mech's CI
while every governance check passes (#526). Before fanning out, search every
consumer's committed `origin/main` for the outgoing pin:

```bash
uv run kg-microbe-governance pin-coupling \
  --old-ref <outgoing-full-claw-commit> \
  --target-root culturemech=/path/to/CultureMech ...   # one per consumer
```

It reports the pin in full or abbreviated to seven or more characters, in either case
(`pin-reference`), and any committed snapshot of claw's manifest
(`manifest-snapshot`), outside the pin file and dated `reports/`. A consumer
whose committed pin is not `--old-ref` is reported as `PIN`, since that means
a mistyped ref or a Mech already moved on. It exits 1 on either and never
writes. Put each reported file in that Mech's
re-pin commit. The rollout to `cb83def3` had two: MediaIngredientMech's
`.github/workflows/qc-evidence.yaml` checks claw out at a `ref:` a test
requires to equal the pin, and NaturalProductMech's
`scripts/.vendored_manifest.json` must equal claw's manifest at the pin.

Review the `WOULD_WRITE` rows, then explicitly apply the same plan:

```bash
uv run kg-microbe-governance sync \
  --repository traitmech \
  --target-root /path/to/TraitMech-worktree \
  --ref <full-claw-commit> \
  --apply
```

Apply mode also requires a clean target worktree. It serializes cooperating
writers with a stable lock in Git metadata, replans under that lock, snapshots
every changed target, stages the entire set beside its destinations, and creates
rollback anchors before the first promotion. Promotions use same-directory
atomic operations, fsync, and set-wide post-write verification; ordinary
exceptions and interrupts restore the prior bytes, modes, and inodes and remove
directories created by the transaction. If a non-cooperating process writes
third-party bytes observed during recovery, those bytes and the rollback anchor
are preserved and the command reports incomplete recovery rather than
overwriting them. Governed paths hidden by Git ignore rules, pre-existing untracked targets,
Git-environment routing overrides, and unsupported safe-dirfd/flock platforms
are rejected. The command never deletes unmanaged files.

Once every promoted target passes exact post-write verification, the operation
has reached its commit point. Rollback anchors are then cleanup debris, so a
cleanup error is reported as an already-committed synchronization and never
triggers an impossible partial rollback. A locked snapshot plus a second Git
preflight binds preparation to the state used for the apply plan; a target that
appears after that snapshot is preserved and rejected.

POSIX cannot make sixteen paths simultaneously visible or stop an editor that
ignores the advisory lock in a final compare/rename interval, including during
promotion or rollback. Such a writer can win the narrow interval after the last
observable comparison. Run apply only in the dedicated clean worktrees required
by this rollout. The implementation detects observed pre-promotion and recovery
changes, uses no-clobber creation for formerly absent targets, and provides
strong rollback for cooperating callers; crash- or power-loss recovery would
require a durable journal and is not claimed here.
`check` is read-only and returns nonzero on drift:

```bash
uv run kg-microbe-governance check \
  --repository traitmech \
  --target-root /path/to/TraitMech-worktree \
  --ref <full-claw-commit>
```

Inside a Mech, CI may continue invoking the thin launcher:

```bash
bash scripts/check_vendored_sync.sh
```

That launcher is the only supported executable entry point. The Python payload
is deliberately non-executable, and the launcher runs it in Python isolated mode
so sibling files cannot shadow standard-library imports. Fetch failures
remain retryable exit 1 results for compatibility with the existing Mech retry
workflows; local pin/identity/manifest precondition failures use exit 2. Tests
replace its fetch function with local fixtures, so the test suite is offline and
no provider, model, credential, or paid API is involved.

Each public fetch has a five-second total deadline and an 8 MiB response cap.
The largest consumer performs one manifest plus sixteen artifact fetches, so
three worst-case attempts plus the existing two five-second retry delays remain
within a five-minute workflow timeout (235 seconds before runner overhead).

## Phase 1 rollout record

Phase 1 completed through a two-commit claw migration because public downstream
CI needed an already-merged immutable claw revision before claw could retire the
old comparison layout. The reviewed bootstrap is pull request
[`#133`](https://github.com/CultureBotAI/culturebotai-claw/pull/133), merge commit
`a8f7c94d8d5ccfa0ed430e4d3c5d0dbf63af2416`.

All five downstream migrations passed their repository CI and were merged:

| Mech | Pull request | Audited `origin/main` |
|---|---:|---|
| CultureMech | [#340](https://github.com/CultureBotAI/CultureMech/pull/340) | `0422968004b99c91ed356d6ee4e38b7e93f371d5` |
| MediaIngredientMech | [#472](https://github.com/CultureBotAI/MediaIngredientMech/pull/472) | `82694054f5bbf74b5392bf8858c9962c2152a35a` |
| CommunityMech | [#683](https://github.com/CultureBotAI/CommunityMech/pull/683) | `ba596731b23b799f4baca96984ceb8f0d56874fe` |
| TraitMech | [#516](https://github.com/CultureBotAI/TraitMech/pull/516) | `3ee94eeec831d98d2a2cc1ebe2368fe3fa122f69` |
| ProteinTraitsMech | [#564](https://github.com/CultureBotAI/proteintraitsmech/pull/564) | `a70ff8f5564b77a50963daafaacc2dde013eb1a2` |

An audited SHA can be newer than the rollout PR when unrelated work reached
`main` afterward; the audit binds the current committed tip, not merely the
rollout merge.

Immediately before the authoritative flip, each detached audit worktree was
clean, had `HEAD == refs/remotes/origin/main`, and contained the full bootstrap
pin. One five-root audit then reported 14 matching artifacts for CultureMech,
MediaIngredientMech, CommunityMech, and TraitMech; ProteinTraitsMech correctly
reported its 13 applicable artifacts because Edison capture is not applicable.

`.github/workflows/governance-fleet-audit.yaml` preserves that central check
after the flip. It runs daily and on every claw pull request and main push,
sparse-checks out the public Mech mains derived from the trusted claw manifest,
and reads every pin from its committed tree. All pins must be identical and the
commit must be reachable from the exact trusted claw base/main revision before
the fleet audit runs. The job installs its governance package from that trusted
revision first so it can derive the consumers and paths; the downstream pin
supplies canonical data, never executable acceptance logic. On pull requests, a
separate candidate-validation step checks the proposed authority layout and
workflow contract while the deployed-fleet audit remains bound to the protected
base revision.

The final claw state is `authoritative`: every Mech is a consumer, no Mech
hub exists, and `legacy_hub` is forbidden. The compatibility mirrors, duplicate
root contracts, and CultureMech-hub audit were removed only after the fleet
audit passed. Claw's maintained history CLI and ID-label behavioral workflow now
consume the packaged canonical assets directly, and tests reject operational
references that would reintroduce the retired layout.

The audit command remains the release gate for future canonical revisions:

```bash
uv run kg-microbe-governance fleet-audit \
  --ref <full-claw-commit> \
  --target-root culturemech=/path/to/CultureMech-worktree \
  --target-root mediaingredientmech=/path/to/MediaIngredientMech-worktree \
  --target-root communitymech=/path/to/CommunityMech-worktree \
  --target-root traitmech=/path/to/TraitMech-worktree \
  --target-root proteintraitsmech=/path/to/ProteinTraitsMech-worktree \
  --target-root cellstructuremech=/path/to/CellStructureMech-worktree \
  --target-root antibioticmech=/path/to/AntibioticMech-worktree \
  --target-root habitatmech=/path/to/HabitatMech-worktree \
  --target-root naturalproductmech=/path/to/NaturalProductMech-worktree \
  --target-root taxonmech=/path/to/TaxonMech-worktree \
  --target-root pathwaymech=/path/to/PathwayMech-worktree \
  --target-root dufmech=/path/to/DUFMech-worktree \
  --target-root cmmmech=/path/to/CMMMech-worktree \
  --target-root aimech=/path/to/AIMech-worktree
```

It requires exactly the manifest keys, distinct exact Git roots, clean
trees, `HEAD == refs/remotes/origin/main`, one expected pin, and successful
checks for every applicable artifact. It reads bytes and executable modes from
each repository's committed `HEAD`, so ignored files and `skip-worktree` flags
cannot substitute working-tree state.

DUFMech completed its native and governed integration in
[`DUFMech#109`](https://github.com/CultureBotAI/DUFMech/pull/109), main
`658dc8c9e4ed2587f7bf1c62ee59563f327706de`, with all 18 applicable artifacts
and the published canonical pin
`59aead1ba791d1b1840a263a41260a0717115870` from
[`claw#573`](https://github.com/CultureBotAI/culturebotai-claw/pull/573).
Its completed admission exception is removed. The family schema is
`src/dufmech/schema/dufmech.yaml`; the inventory remains
`data/families/*.yaml`, generated by native seeding. Curation overrides under
`curation/families/` are not another inventory. Shared serialization remains
unverified to preserve native generation and reproduction.

The exact-main profile audit validated 6,532 records, two canonical history
sidecars, five reviews, and zero generated schema/record drift. The shared census
selects six populated seed metadata fields, not empty optional scientific
assertions or Discussions; their zero counts remain in native reports. Native
Pfam snapshot identity/label checks do not establish an OAK adapter, so shared
`id_label_validation` stays disabled. Shared source checks found 18 catalogue
blocks, zero errors and 12 unresolved-licence warnings, with no source-queue
findings. These warnings do not authorize ingestion or redistribution.

Shared writer scanning recognizes the real review `_validate_content` guard,
but cannot recognize module-based just recipes by filename and does not prove
all writes safe. Native multi-format auditing remains primary. Generated record
projections validate existing sidecar history without manufacturing new events.
The committed site (6,799 HTML pages) passed shared HTML, contrast and budget
checks. These are committed-artifact checks, not a deployment assertion.

This capability/policy update changes no governed payload or artifact manifest:
the published `59aead1` pin remains valid, with no third re-pin required. Full
fleet release still requires the exact-main audit above against all declared
consumers. `DUFMECH_ROOT` selects the verified local checkout; published readiness
does not imply local hooks are installed or that a dirty CLAW checkout was
fast-forwarded. The queue mapping permits scoped adoption after CI readiness;
remote rules and an actual queue merge require separate execution evidence.

### CMMMech Admission

CMMMech's admission inspection used main `c32d78e26a15bb67a737700668badaed7da10597`.
It contained three material records, a packaged LinkML schema and native strict
validation. `CMMMECH_ROOT` selects its identity-verified checkout. Shared
serialization remains unverified; the existence of records does not establish
round-trip options or a corpus-statistics field selection.

Native validation uses `scripts/check.py` and the `check`/`validate` recipes,
not the fleet validation agent's recipe contract. At admission, the native schema
and commands did not integrate canonical curation history. Timestamped record-review
Markdown and copied shared schemas are not substitutes for that integration.
Those capabilities were disabled at admission with explicit reasons; general
orchestration eligibility does not claim installed local coordination hooks.

The queue policy maps `.github/workflows/validate-strict.yaml` to the actual
`validate-strict` check, verified in successful Actions run `37709261918` at the
inspected SHA. Its PR trigger is unconditional and it supports `merge_group`.
This mapping does not enable remote rules or prove an actual queue merge.

All 18 applicable governed artifacts and the canonical pin were missing at that
inspected revision. The exact artifact paths were recorded in the temporary
`INCOMPLETE_CONSUMERS` ledger in `tests/test_vendored_consumer_completeness.py`;
its bidirectional checks must reject new gaps and require removal when adoption
finishes. This admission exception does not make a deployed fleet audit pass.

Adding CMMMech changes the canonical consumer manifest even though the governed
payload bytes are unchanged. Release completion therefore requires a published
immutable CLAW revision containing this admission, supported synchronization
into CMMMech, coordinated re-pinning of every manifest consumer, removal of the
completed admission exception, and the exact committed-main fleet audit above.
Do not report this registration alone as a completed governing release or merge
it without an authorized plan to complete that rollout.

Registration was published in
[`claw#581`](https://github.com/CultureBotAI/culturebotai-claw/pull/581), canonical
`849f336e025510316a5f235eb0af8547b8bd50cc`. Native bootstrap then merged through
[`CMMMech#9`](https://github.com/CultureBotAI/CMMMech/pull/9), main
`842edc17fc603831c6ab56fd0ef1d813416d3ea5`, with all 18 exact governed artifacts
and that pin. Its native gate passed 165 tests, three empty-command
parametrizations were skipped, and all three existing material records validated.
The native CI also passed the canonical-byte check; post-merge validation and
merge-integrity runs both succeeded at that exact main.

The bootstrap adds real optional inline `curation_history` events to the native
schema, with closed shape and strict timestamp, curator, action and summary
validation. Existing scientific records and reviews are unchanged. Both canonical
timestamp guards run unmodified; an absence-driven skip proposal was rejected
by adversarial review and removed because it could mask deletion of an adopted
model. That bootstrap did not yet implement shared history authoring or sidecars.

A separate, concurrent
[`CMMMech#11`](https://github.com/CultureBotAI/CMMMech/pull/11) then merged at
`905388523b6e9184783989484896e4cc20297832`. Its native adapter now authors and
validates canonical sidecars through `new-history` and `validate-history`, links
them from records with `history_refs`, and enforces append-only history against
the trusted CI event base. The refreshed main passed 215 tests with three
empty-command skips, validated three records and three history sessions, and
retained all 18 governed artifacts at `849f336`. Its merge-group validation,
post-merge native validation and merge-integrity checks passed. The independent
PR's adopted record provenance is preserved; it is not attributed to the earlier
bootstrap or rewritten here.

The shared `curation_history` capability also gates rendered record/category
review and curation skills. Enabling it against that exact CMMMech main failed
two real rendered-reference checks because the shared `curate-yaml-record`
skill/checklist and `review-yaml-record` adapter are absent. The declaration
therefore remains disabled for shared skill eligibility, with explicit checked
paths, while acknowledging the complete native history implementation. No test
is skipped or weakened to conceal those missing adapters; their adoption is a
separate downstream change. Other unverified capabilities remain disabled.

The completed CMMMech artifact-admission exception is removed in the convergence
follow-up. The coordinated release and its final committed-main audit are tracked
in [claw#580](https://github.com/CultureBotAI/culturebotai-claw/issues/580). This
follow-up changes no canonical artifact manifest or payload bytes: `849f336`
remains the governing pin, without another re-pin.

### AIMech Admission

AIMech registers `CultureBotAI/AIMech`, package `src/aimech`, and
`src/aimech/schema/aimech.yaml` (`AIConcept`). `AIMECH_ROOT` selects an exact,
identity-validated worktree. The read-only inventory includes generated
`data/aio/*.yaml`; the pinned AIO OBO JSON
and native seed/reproduction gate own generated bytes. Shared serialization
remains unverified with no round-trip options.

Native `aimech validate`, seeding and `just check` do not by themselves adopt
the shared validation or schema-generation agents. Native `new-history` does
not establish the shared curation skill's write contract. Structured record
review is independently enabled through native `review-yaml-record` and
`review-category` skills, `conf/record_review.yaml`, and the governed review
schema and saver. Optional adapters remain disabled or not applicable until
their own contracts are verified; ontology hierarchy edges are not evidence
of a mechanistic causal graph.

The native source manifest is `sources/aio/source.yaml`, consumed with
`sources/aio/aio.json` by `src/aimech/importer.py`. This bespoke provenance
contract does not adopt the shared `download.yaml` source catalogue. No curated
record inventory is declared before such a corpus exists.

The shared census selects identity, definition, branches, review status and
the pinned provenance fields. Census coverage is not a scientific-review score;
an imported `NOT_REVIEWED` concept is counted without being promoted to reviewed.

Admission inspected published main
`38594d6436195e7fdb0882613e9004a0132dd4fc`, merged through
[`AIMech#1`](https://github.com/CultureBotAI/AIMech/pull/1). Its committed tree
contains all 22 applicable artifacts with canonical digests and executable
modes, all declared capability path claims hold, and the census reads 442
generated concepts with every selected field populated. The embeddings rollout
binds its planned text adapter to this same inspected revision. No artifact
admission exception is needed; the exception ledger remains empty. These checks
establish artifact adoption, not a completed canonical pin rollout.

Adding AIMech changes the canonical consumer manifest without changing any
governed payload bytes. Publish the reviewed CLAW revision only after release
coordination, synchronize every consumer to that immutable revision, account
for coupled pins, then run the exact committed-main fleet audit above. A
passing local contract suite establishes registration consistency, not released
governance or queue execution.

Do not change canonical payload bytes as part of an authority-only migration.
A later pinned release can evolve a shared contract through the same bootstrap,
downstream rollout, exact-main audit, and final-state sequence. Some current
payload comments retain historical fleet wording; changing those bytes requires
that separate coordinated release.

## Rollback

Rollback means pinning every Mech to the previous reviewed claw commit; do
not reinstate a Mech authority or use a mutable branch. The canonical bytes
remain recoverable from every reviewed claw commit.

## Governed workflow action pins

`src/kg_microbe_governance/workflow_pins.json` owns the action SHAs, release
labels, and exact uv runtime for workflows registered in
`vendored_artifacts.json`. Their source files may live anywhere within the
governed artifact root; the manifest owns those locations. Every parsed `uses:` reference must match the contract's 40-hex revision and
release comment; every setup-uv step must also set the contracted `version:`.
Claw CI checks those values, the workflow registry, and the artifact checksums.
Per-Mech pin contracts may exempt these governed paths because claw checks them
centrally. Their remaining, Mech-owned workflows can keep their own versions.

The canonical upgrade command resolves full release tags through the action's
GitHub repository and previews the contract, workflow, and checksum changes:

```bash
just governed-workflow-pins --action astral-sh/setup-uv@v10.1.0
just governed-workflow-pins --action anthropics/claude-code-action@v1.0.221 --apply
just governed-workflow-pins --verify-upstream
just governed-workflow-pins --check
```

`--apply` validates an isolated candidate before writing canonical claw files,
then verifies the installed result within the same rollback scope. Errors and
interrupts before successful verification restore attempted files by atomic
replacement. Successful verification is the commit point: a later cleanup
failure returns nonzero but explicitly reports the update as committed and
identifies retained temporary files; it does not roll back the verified update.
Cleanup failures during recovery preserve the rollback outcome and backup
diagnostics in the error. If the
filesystem also prevents restoration, the command fails explicitly and retains
original-byte backups with their paths in the error. This local transaction does
not claim protection against process termination, power loss, or concurrent
noncooperating writers. `--verify-upstream` checks that
recorded labels still resolve to their recorded SHAs; CI's `--check` stays
offline and does not claim that a reviewed version remains the latest release.
Use `--uv-version X.Y.Z` for a deliberate runtime upgrade. Without that flag,
action upgrades retain the approved uv version. Neither the updater nor its
tests execute an action or a model, enable a schedule, publish a commit, or
change a Mech checkout. Review and merge the canonical patch, then use the
ordinary governance synchronizer to roll out that immutable revision together
with all its other governed artifacts.

A Mech's Dependabot configuration must exclude its governed workflow targets
from each applicable `github-actions` update block. For `directory: /`, the
current target is:

```yaml
exclude-paths:
  - ".github/workflows/pr-shepherd.yml"
```

Keep the exclusion list aligned with that consumer's workflow targets in
`vendored_artifacts.json`; preserve exclusions and update settings owned by the
Mech. A repository with no Dependabot configuration needs no new scanner solely
to exclude a path. If it later enables one, add the exclusions at the same time.
GitHub documents `exclude-paths` relative to each update directory and limits
GitHub Actions discovery to the root configuration and `.github/workflows`:
[Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#exclude-paths).
Canonical payloads under `src/` therefore use the explicit updater above;
Dependabot in a Mech must not rewrite them.

When an already-open Dependabot PR touches both a governed workflow and a
Mech-owned workflow, preserve the latter update in a fresh checked patch before
closing the obsolete PR. A successful vendored-sync run from before the
workflow became governed does not validate merging that old PR against today's
main branch. Require checks on the current candidate containing the canonical
copy and the Mech-owned update.
