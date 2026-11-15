# ScaleupMech admission after scaffold adoption

The current proposal is a **review-only candidate**, recorded in
[`candidate.yaml`](../reviews/2026-11-15-scaleup-admission/candidate.yaml) and
[`evidence.json`](../reviews/2026-11-15-scaleup-admission/evidence.json).
It changes neither fleet membership nor protected audit authority. This refresh
preserves the unfinished work from retired proposals #1074 and #1146 under
[#1254](https://github.com/CultureBotAI/culturebotai-claw/issues/1254).

## Verified starting point

At the recorded acquisition time, `CultureBotAI/ScaleupMech` is public,
repository ID `1450887724`, with default `main` at
`3a512d53e9b9d797cace768fea896a196ec24588`. The native scaffold and template
adoption are present. The committed tree contains the package
`src/scaleupmech`, its LinkML schema, native validation, tests, review helpers,
and the required instruction/skill symlinks. The record inventory is
`data/scale_transfers/*.yaml`; the inspected tree has no matching records.
This is a committed-tree inventory, independent of ignore rules; local ignored
or uncommitted native files were not inspected.

All 22 proposed native governance artifact paths exist. Four content hashes
differ from this review's canonical CLAW source: the standalone checker,
backlog prompt, shared schema, and merge-queue admission controller. These are
version differences, not evidence of corrupt native artifacts. The native pin
still names `88e719d5480d0008d6ce082510dcd066775f232b`. Existing files and a pin
do not establish installation of a new canonical admission.

The candidate retains scale-transfer-specific capability decisions from #1076
while replacing obsolete statements about an empty main or missing scaffold.
Native implementation and compatibility with shared general-agent adapters
remain separate. Only the future governance obligation is enabled in the
candidate; scientific and execution capabilities require their own evidence.
The workflow mapping comes from the committed `validate-strict` job, including
its unconditional pull-request and merge-group triggers. No remote queue rule
is enabled here.

Suite exclusion is independent of repository visibility. The candidate records
`exclude-from-public` as its public-projection intent. The public-projection
prerequisite must support that tag before a membership change adds it to the
fleet entry. It does not require private GitHub visibility or disable a native
Pages site. Scientific seed work remains outside this admission.

## Required protected-framework change

The current mechanism cannot honestly treat this repository as the old empty
bootstrap. Do not republish the historical Scaleup declaration unchanged.

1. `private_audit_coverage.obligation` and
   `automatic_fleet_component` reserve the Scaleup identity for the fixed
   private-audit policy, regardless of its current GitHub visibility. A
   separately reviewed protected transition must explicitly select public
   acquisition for a new Scaleup admission while retaining the old policy and
   its evidence. A public-site exclusion tag must never choose the governance
   transport. Candidate code, a live visibility response, or an unreviewed pin
   must not grant this authority.
2. `consumer_admission.bootstrap_pending` requires the exact recorded bootstrap
   commit to contain none of its governed artifacts or pin. The present native
   tree already contains both. A reviewed transition must either authenticate
   its existing governed source and exact retained artifact state, or require
   adoption of a newly published source before activating the admission. Missing
   artifacts, a partial installation, or arbitrary existing pins must still
   refuse. Merely replacing `bootstrap_main_ref` with today's SHA is invalid.
3. Publish an immutable canonical source for the new admission, bind its exact
   manifest, fleet-entry digest, and complete universal native obligations, then
   introduce the declaration through protected history. Preserve the sealed
   DUF/Edge/Cofactor/Assay declarations and snapshots. Do not modify the dormant
   private policy to manufacture an accepted new pin.

The prerequisite regression repair for #1174 keeps deferred private rows
explicitly unverified, with zero checked artifacts. Protected source binding
still runs before a deferred row can be reported; unknown admissions, incomplete
coverage, and public failures still refuse a successful full-fleet verdict.
The workflow derives its reserved key from its existing repository identity,
so adding the key to the manifest does not break the manifest-derived checkout
guard. This does not change private/public routing.

## Membership and installation after the prerequisite

Prepare the membership change from the refreshed candidate, rechecking native
main before publication. Reconcile `fleet.yaml`, `vendored_artifacts.json`, the
explicit admission descriptor and declaration, root configuration/example,
merge-queue policy, research and pull schemas, embedding rollout inventory, and
manifest-driven tests. Preserve sealed historical cohorts. Do not restore an
`INCOMPLETE_CONSUMERS` entry claiming the native artifact paths are missing.

Use the supported synchronizer on an identity-verified, locked native worktree
to prepare an ordinary governed pin, first in dry-run mode. Retain native
science and existing template decisions. Review its exact diff, run the native
and hosted checks, prove a repeat-run no-op, and audit all applicable consumers
against committed default branches. Admission source publication, protected
activation, downstream installation, scientific seeding, and live cycle
activation remain distinct steps.

The retained helper
`scripts/adhoc/prepare_scaleup_admission_candidate_20261115.py` reproduces the
bounded evidence and candidate from immutable inputs. It verifies repository
identity, actual root-tree identity and unchanged main before saving output;
it never writes downstream repositories or GitHub. Later captures use a new
review directory rather than rewriting committed evidence.
