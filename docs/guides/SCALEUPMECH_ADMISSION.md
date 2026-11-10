# ScaleupMech admission and release dependencies

This domain rationale is retained from #1074. See the
[combined candidate](COMBINED_FLEET_ADMISSION.md) for its composition and current
release dependencies; statements about an independent proposal below describe
that original proposal. Public output now follows the reserved
`exclude-from-public` tag described in [public membership](PUBLIC_FLEET_OUTPUT.md).

ScaleupMech was verified as private on 2026-11-10 at
[CultureBotAI/ScaleupMech](https://github.com/CultureBotAI/ScaleupMech).
Its inspected initial main is the empty commit
`38f8157fc960299f2458f4916dd581ce1b5d0262`. The planned package is
`src/scaleupmech`, schema `src/scaleupmech/schema/scaleupmech.yaml`, root class
`ScaleTransferRecord`, and record inventory `data/scale_transfers/*.yaml`.
Scaffold and seed PRs remain separate from registration. Private visibility is
not required: ScaleupMech may have a public repository and its own GitHub Pages
site. The tag excludes it from X-Mech suite representation and aggregate public
outputs, not from independent publication. This integration changes neither
repository visibility nor native Pages configuration.

Configure `SCALEUPMECH_ROOT` to the identity-verified repository root. Durable
clones, worktrees, review evidence, scripts and retained state belong under
`~/agent-work/ScaleupMech/`, never system temporary directories. Push authorized
commits the same day. All implementation capabilities remain disabled or not
applicable until default-branch behavior is verified. Mandatory `vendored_sync`
is a governance obligation. Shared serialization is unverified. The exact 22
missing applicable artifacts are recorded in the bidirectional admission ledger;
all three native test contracts apply. No Edge exclusion extends to Scaleup.
The `validate-strict` workflow/check mapping is prospective and does not activate
remote queue rules. `MERGE_QUEUE_AUTOMATION_PAUSED` is set to `true`.

A published immutable registration commit provides an exact canonical source
for the supported governance synchronizer. Bootstrap source publication is not
protected release approval. Scaleup requires its own separately sealed identity,
source pin and manifest, conservative fleet-entry digest and exact empty-main
boundary. Cofactor and Assay declarations confer no Scaleup authority; existing
DUF/Edge declarations and allowed pins remain unchanged.

## Audit boundary while the repository is private

Current public claw CI clones consumers and then executes candidate PR code in
the same job. Adding a private-read credential there would expose private Git
objects and files to that candidate. Anonymous cloning cannot establish private
consumer completeness. While the repository remains private, admission requires separately reviewed
trusted private-audit plumbing, isolated from candidate code and public logs.
Missing authorization must fail closed; a skipped private consumer is not a
successful fleet audit. No private data may be uploaded into a public CI artifact.
A bounded public result may contain only the explicitly approved governance
status and identity metadata, never private records, blobs, or credentials.
The credential and protected-workflow prerequisites remain explicit release
holds, not exceptions to artifact completeness or permission checks.

If the repository becomes public, recheck anonymous access and the ordinary
fleet audit. The private-audit plumbing is then unnecessary solely for access
to this repository; protected admission and artifact-completeness requirements
still apply. Public visibility does not remove its suite-exclusion tag.

Before the onboarding PR opens, scaffold and separate seed PRs must exist.
Independent adversarial review, issue fixes, exact-head re-review and all checks
remain required. Merges are the user's decisions. Only a user-approved protected
merge may activate a separately declared admission. Shared capability promotion,
coordinated re-pins, completed-ledger removal, remote queue activation and Suite
projection remain separately reviewed release work. Existing consumer repositories
are outside this proposal's mutation scope.

## Scientific scope

ScaleupMech records organism- and strain-level scale-transfer evidence: titer,
rate and yield across scales, OTR/kLa, scale-down models and media at scale. It
complements [Project PISCES](https://projectpisces.org/) by linking to PISCES
flowsheets where verified. It must never copy flowsheet, unit-operation or TEA
content. Cite original evidence and preserve scale, strain, operating context,
units and uncertainty; a single-scale observation does not establish transfer.

## Separately sealed infrastructure proposal

The independent declaration binds bootstrap
`88e719d5480d0008d6ce082510dcd066775f232b`, exact source bytes and all 22 native
obligations. Its shared mechanism is the independently reviewed Cofactor/Assay
implementation with one explicit Scaleup descriptor. This branch includes only
Scaleup's declaration and registration; the other descriptors remain dormant.
Each declaration requires immutable protected first-parent introduction, exact
identity/ref pairing and source authentication. Candidate declarations cannot
activate against an older protected base. Earlier consumer permissions and all
four DUF/Edge declaration/source files remain unchanged. Tests compose three
independent native source snapshots and reject every crossed newcomer pin.

This additive authority does not solve private CI access. The separate dormant
private-audit prerequisite is reviewable plumbing, not automatic fleet-gate
integration. Until protected activation, safe App/environment configuration and
a reviewed gate cutover exist, public hosted completeness cannot honestly pass
for this private consumer. Missing access is never recorded as success.


When integrating the three separately proposed admissions, preserve canonical
native artifact scope order: existing consumers, CofactorMech, AssayMech, then
ScaleupMech, matching the explicit descriptor order. The strict layout comparison
also compares these ordered scopes. Each immutable source snapshot remains
unchanged and may omit the other newcomers; reorder only the combined current
manifest during the reviewed integration, never a sealed source snapshot.

## Optional protected private-audit handoff

`audit_release(..., private_obligations=...)` accepts a separately installed
protected helper for an explicitly deferred private admission. The default
all-roots call remains independent of that helper. Nonempty deferral requires
exact disjoint public/private coverage, the protected additional declaration,
and its authenticated immutable source objects. Missing helper code fails.

The handoff returns `public_component_ok` for the checked public roots and
`ok: false` while any private obligation remains. Its deferred row reports zero
checked artifacts and no verified installation. Only the separate trusted
automatic verifier can complete private coverage; this hook does not install
that verifier, activate a receipt, supply credentials or remove the present
private-clone failure from the hosted gate. Existing public failures still fail
the public component.
