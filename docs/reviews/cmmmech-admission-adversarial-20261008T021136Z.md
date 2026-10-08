# Independent adversarial review: CMMMech bootstrap admission

## Identity, time and reviewed state

- UTC snapshot: 2026-10-08T02:11:36Z; review completed after the independent
  checks below.
- Reviewer: independent `queue_admission_audit` agent; no implementation edits.
- CLAW base: `73958edb97994bc16c5404443956ee64c47bfe9b`.
- Working changes reviewed: 16 tracked modified files covering fleet/configuration,
  governance consumer registration, research enum, queue policy, contract tests and
  maintained documentation. SHA-256 of `git diff --binary HEAD`:
  `d1a1b5f0490d824e7623de79c836225193675cbb6f4ed6b1dbab23ccf77280c9`.
- Additional measurement artifact reviewed:
  `docs/reviews/cmmmech-admission-20261008.md`, SHA-256
  `75f6704732795e34187e8e449eac87cc3f9cae098cd62e7fda029afdb402af23`.
- CMMMech evidence baseline: committed main
  `c32d78e26a15bb67a737700668badaed7da10597`; its remote main and local
  `origin/main` were independently verified. Developing worktree changes were not
  treated as committed capabilities.

## Scope and authority

Reviewed the bootstrap registration against CLAW `CLAUDE.md`,
`.claude/skills/onboard-mech/SKILL.md`, `VENDORED_GOVERNANCE.md`, and
`MERGE_QUEUES.md`. Exact-path ancestor checks and a repository instruction
inventory included hidden and ignored files; `CLAUDE.md` was the repository guide.
This verdict covers the proposed admission, not completion of the downstream
release or closure of CMMMech issue #3.

## Evidence checked

- Fleet, packaged configuration, environment example, research enum, consumer
  manifest, and queue-policy keys agree on `cmmmech`, `CultureBotAI/CMMMech`,
  `CMMMECH_ROOT`, and `src/cmmmech`.
- Inspected committed CMMMech schema, gate, recipes, record paths and CI.
  `data/records/**/*.yaml` selects exactly cobalt, neodymium and palladium.
  Existing strict CI invokes the same lint/test/nonempty-validation gate and has
  unconditional PR and `merge_group: checks_requested` triggers.
- Independently checked live Actions metadata: the exact successful context is
  `validate-strict`, run
  [37709261918](https://github.com/CultureBotAI/CMMMech/actions/runs/37709261918),
  head `c32d78e26a15bb67a737700668badaed7da10597`.
  CLAW `workflow_errors` returned no readiness errors for those workflow bytes.
- Compared canonical artifact declarations with base: payload digests, scopes,
  modes, canonical repository, pin path and version are unchanged. No canonical
  payload file is modified. Consumer identity is the only manifest addition.
- Re-derived every applicable artifact path from the candidate manifest and
  compared against `git ls-tree` of committed CMMMech main: all 18 applicable
  artifacts are absent, and the exact missing set equals `INCOMPLETE_CONSUMERS`.
  Git-tree inspection is independent of local hidden/ignored files. The separate
  pin is absent too; it is not misrepresented as one of the 18 artifacts.
- Re-ran all 32 documented PyYAML option combinations against `git show` record
  bytes: every combination reproduces zero of three records. The unverified
  serialization declaration and absence of emit options are warranted.
- Disabled history/provider/ID-label/source capabilities describe committed
  behavior. `vendored_sync: enabled` explicitly means a required bootstrap
  obligation with exact gaps, not a claim that the gate is deployed. The new
  reason-claim count and expected consumer lists add CMMMech without weakening
  existing guards.
- Independently inventoried all 13 consumers through live GitHub reads: the
  existing 12 share outgoing pin
  `59aead1ba791d1b1840a263a41260a0717115870`; CMMMech is unpinned. No main changed
  during the snapshot. Across 123 open PRs, no governed-path change was found in
  returned file lists. TaxonMech #77 exceeds GitHub's 3,000-file limit; exact
  governed-path traversal of untruncated base/head subtrees found identical
  entries. This is time-bounded coordination evidence, not a rollout lock.

## Validation

Independent run with only `CMMMECH_ROOT` configured:

```text
pytest tests/test_fleet_manifest.py tests/test_fleet_manifest_profiles.py
       tests/test_research_fleet_contract.py
       tests/test_authoritative_governance_layout.py
       tests/test_manifest_reason_claims.py tests/test_merge_queue.py
       tests/test_vendored_consumer_completeness.py
       tests/test_governance_fleet_audit_cli.py
510 passed, 126 skipped in 63.82s
```

Unconfigured other consumer roots account for applicable skipped checks; this
is not a claim that the complete live fleet audit ran. CMMMech's supported
incomplete-consumer branch also intentionally skips its all-artifacts assertion
after checking the exact gap; the separate bidirectional gap check passes.

A fresh standalone pytest process injected a mutated declaration claiming
`curation_history: enabled` and called the new candidate guard. It failed at the
intended disabled-capability assertion (expected exit 1). The repository's actual
manifest was never changed. `git diff --check` passed.

## Findings by severity

- Critical: none.
- Major: none.
- Minor: none requiring a code or documentation correction.

## Corrections and unresolved dependencies

No implementation correction was required by this review. Do not invent an
issue solely to populate the review process. Existing issue #3 already requires:

1. Publish the reviewed immutable registration, then synchronize and re-pin every
   consumer through the supported tool; admission changes the canonical manifest
   even though payloads are unchanged.
2. Land CMMMech's history integration and all governed artifacts, then remove the
   exact-gap ledger and update its history capability and corresponding contract.
3. Retain a passing committed-main fleet audit. The initial admission's main-push
   audit can report the declared incomplete rollout until consumer convergence;
   the ledger does not waive the deployed-fleet pin/artifact audit.
4. Review/apply/check the native queue plan and retain an actual merge-group
   execution, merged commit and post-merge checks. Workflow presence alone is
   insufficient. Shepherd installation/secret-name checks do not prove live
   credential validity; no model/provider call was made by this review.

## Verdict

**Accept the bootstrap admission as reviewed.** No actionable review defect was
confirmed. The coordinated release, final capability update, operational queue
receipts and closure criteria remain the parent integration task's work.
