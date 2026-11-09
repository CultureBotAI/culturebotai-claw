# Post-cutoff infrastructure admission

CLAW #960 adds a versioned EdgeMech admission alongside the active single-DUF
cycle release. It does not retire that release, assert that the DUF work is
finished, or change any historical consumer's rollout permission. The user
authorized designing and implementing this separate admission on 2026-11-07.
Activation still requires an explicitly approved merge onto protected main.
Candidate validation alone cannot authorize its own deployment.

The immutable `releases/mech-cycle-v2-canary.json` and its pinned historical
workflow and governance payload bytes remain unchanged. Current main may publish
future checksum-valid payload revisions under the authority/layout rule added
by PR 956; these do not replace any consumer's allowed historical or admission
data pin. Its original governance manifest is
also packaged byte-for-byte as `releases/mech-cycle-v2-governance-manifest.json`,
with the historical SHA256 `368edbac106cb49c0a4159a87c07eeba4a5ed79c343ff042c0ddbc1b6b990ebb`.
The existing fourteen consumers retain their exact identities, artifact targets,
Git modes, bytes and applicability. Their allowed baseline/DUF refs retain the
same protected-history and committed/working-tree checks.

The new `releases/edgemech-infrastructure-admission-v1.json` binds:

- The exact historical declaration and manifest digests.
- One infrastructure identity, `CultureBotAI/EdgeMech`, and its complete fleet
  entry digest. Only `vendored_sync` is enabled; native scientific, execution and
  publication capabilities remain disabled or not applicable, and native
  serialization remains explicitly unverified.
- The exact reviewed governance data pin
  `7e672227fb246a8359ad57b6d3975ce5ed329007` and manifest digest
  `bfd4b703f46ce748487253d6fe093e79fe00ba7a9a88293f5cc6df176f11b519`.
- Exactly three native-record test exclusions for EdgeMech:
  `curation_timestamp_contract`, `record_review_contract` and
  `skill_frontmatter_contract`. Those tests continue to apply to every original
  consumer. All other artifact definitions and payload hashes remain exact.
- The exact empty EdgeMech main bootstrap commit
  `e853bf22b9f708bfd381910107aec9283a3bcee3`.

Every other member, identity, capability, mode, target or applicability delta
is refused. The admitted source payload hashes remain exact even when current
canonical payload hashes evolve. When the fleet capability catalogue grows after
admission, EdgeMech must declare each new catalogued capability as `disabled` or
`not_applicable` while preserving the exact admitted digest across its original
28 capabilities and identity fields. Changing the admitted fleet entry's original
fields or enabling a scientific worker requires another reviewed policy transition;
enabling a scientific worker is not an admission side effect.

`cycle_release_audit` requires a clean trusted CLAW checkout on protected
`origin/main` first-parent history. It proves that the new declaration has one
immutable introduction after the original lane. Editing, deleting or
resurrecting that declaration fails. The original release declaration keeps its
independent immutable-introduction checks. A historical trusted checkout before
admission continues to audit only its historical cohort.

The data pin is deliberately separate from executable authority. Its source
commit can be on the reviewed feature branch; a squash merge need not retain it
in main's ancestry. The protected admission declaration approves only that
exact pin and exact manifest/payload bytes. A preparation step selects this one
40-hex data ref using only protected trusted code and the protected declaration;
historical trusted checkouts without admission skip that step. It fetches the
ref from canonical origin without changing HEAD, refs or FETCH_HEAD. The audit
itself remains read-only: it resolves that exact commit, validates its actual
manifest/fleet identities and payloads, and compares them to the admitted bytes.
It supplies only those verified source bytes through a closed URL-to-bytes
mapping, refusing an absent source or mismatched snapshot. It never
executes or installs code selected by the downstream pin. A different pin or
changed source-manifest hash fails. The preparation helper verified the actual
source commit's manifest and every payload before creating the declaration.

The admitted manifest is also packaged byte-for-byte as
`releases/edgemech-infrastructure-source-manifest.json`, bound to the unchanged
declaration's `source_manifest_sha256`. Candidate/package checks compare that
snapshot to the frozen historical manifest, then require the current manifest
to preserve its complete authority/layout apart from payload digests. Every
current payload must still match its own digest. The protected audit separately
authenticates the actual source commit and its exact historical payloads before
serving data under its URLs. Tests reject newer current bytes substituted under
any historical or admitted pin. This separation resolves the current-main
integration finding in PR 953 under issue 997 without repinning a consumer.

The public sync APIs also distinguish this exact admitted source. Only the
declared EdgeMech identity requesting the declaration's exact source ref may
select its packaged frozen manifest. Current package checksums and admission
layout still validate; the fetched manifest must match that snapshot exactly,
and every fetched payload must match its frozen digest. The same authenticated
bytes then flow through planning, the existing transactional writer and
post-write verification. No current package bytes are written under the old
pin. Other repository/ref pairs and `verify_canonical_ref` retain strict
installed-package equality. Issue 1004 records the real dry-run failure that
exposed this missing sync path before any target write or receipt.

The infrastructure result has two distinct states:

| State | Required evidence | What is established |
| --- | --- | --- |
| `pending_infrastructure_bootstrap` | Exact canonical repository, clean trusted checkout at the bound bootstrap `origin/main` tip, and no governed files or pin in its committed tree or working paths | Admission is pending. `expected_artifacts` and `checked_artifacts` are zero; `installation_verified` is false. No rollout or installed-payload success is claimed. |
| `installed_infrastructure` | A clean canonical main tip, the single approved data pin, and complete committed/working-file bytes, modes and applicability verified by the existing checker | Infrastructure payload installation only. No scientific capability or publication authority is added. |

Any main-tip change ends the bootstrap exception. A changed uninstalled tip,
partial installation, unknown pin or wrong repository fails; there is no
generic exception for newly registered repositories. Candidate completeness
uses the same exact-tip rule on `origin/main` trees in its no-checkout clones.
That cheap guard checks presence, not payload integrity, and cannot activate
trusted admission. Its separate policy tests prove the transition and negative
cases before the production gate can use the new declaration.

`scripts/adhoc/prepare_edgemech_admission_20261107.py` retains declaration
generation and source-byte verification. The source-edit lease is held by
`scripts/adhoc/hold_edgemech_admission_lease_20261107.py`. No existing Mech is
repinned, no native record is changed, and the companion site membership
projection is unaffected by these additive policy files. PR and site merges
remain explicit user decisions.
