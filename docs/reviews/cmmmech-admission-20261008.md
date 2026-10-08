# CMMMech admission measurements

Measured 2026-10-08 UTC against CMMMech committed main
`c32d78e26a15bb67a737700668badaed7da10597`, in the dedicated worktree
`/private/tmp/CMMMech-claw-integration-20261007`. CLAW candidate is based on
published `73958edb97994bc16c5404443956ee64c47bfe9b`. These are bootstrap
measurements, not proof that the coordinated release has completed.

## Identity and inventory

The inspected Git root has `origin` fetch and push identity
`https://github.com/CultureBotAI/CMMMech.git`. Its installed package is
`src/cmmmech`, its closed LinkML record schema is
`src/cmmmech/schema/cmmmech.yaml`, and the inventory glob
`data/records/**/*.yaml` selects cobalt, neodymium and palladium. Scientific
reviews live separately under `reviews/records/` and are not corpus records.
The local inventory used hidden- and ignored-inclusive traversal, excluding only
Git implementation metadata (91 paths at the follow-up inventory). Published
artifact availability was checked with `git ls-tree` against the committed
revision, independently of local files. The follow-up local inventory includes
an uncommitted `src/cmmmech/history.py` adapter under development; it is not
part of the admitted default-branch capability baseline.

## Capability decisions

The native gate runs lint, tests and strict nonempty corpus validation.
`.github/workflows/validate-strict.yaml` has unconditional `pull_request` and
`merge_group: {types: [checks_requested]}` triggers. The exact job/check context
is `validate-strict`; queue policy membership does not enable remote rules.

The shared census reports three records, no unreadable or empty records, and
all six declared fields populated in every record: `id`, `name`,
`material_kind`, `criticality.jurisdiction`, `criticality.edition`, and
`mechanisms.process`. These are inventory facts, not scientific completeness.

Current native validation checks identifier syntax; it does not establish
ontology ID-label correspondence. The source-discovery skill is a research
handoff, not a shared provider executor, download catalogue or source queue.
Shared history, source profiles, graph projection, writer auditing, ontology
correspondence and automated gap scanning remain disabled at this baseline.
General orchestration capabilities express eligibility, not installed hooks.
The manifest records the applicable path assertions for these decisions.

Serialization was measured from `git show <revision>:<record>` bytes with
PyYAML 6.0.3. The 32 combinations of `default_flow_style` false/true,
`sort_keys` false/true, `allow_unicode` false/true and `width` 80/100/120/1000
all reproduced **zero of three** records byte-for-byte. The records use six,
seven and nine folded block scalars respectively; generic `safe_dump` does not
preserve their presentation. Serialization is unverified with no emit options.

## Supported bootstrap and release dependencies

All 18 `consumers: all` governed artifacts are absent from committed CMMMech
main at the measured revision. Their exact expanded paths are recorded in
`INCOMPLETE_CONSUMERS` in `tests/test_vendored_consumer_completeness.py`.
The pin is also absent. The ledger compares both directions: any new gap or
completed admission must change the declaration. It is not deployment evidence.
`vendored_sync: enabled` is the authoritative consumer obligation required by
CLAW's supported bootstrap, with the pending deployment stated explicitly.

No canonical payload bytes or artifact scopes are changed. Adding the consumer
identity still changes the authority manifest, so publish the reviewed CLAW
revision before using `kg-microbe-governance sync`. Then synchronize all declared
consumers to that immutable revision and audit their exact committed main tips.
CMMMech's native history adapter must land before its history capability becomes
enabled. Remove the exact-gap ledger only after CMMMech has committed all
applicable artifacts. Do not bypass immutable-ref matching or hand-edit governed
copies. Remote queue and PR-shepherd readiness require operational receipts;
this registration does not claim either is running.

## Local runtime checks

With only `CMMMECH_ROOT` exported to the exact dedicated CMMMech worktree,
`openclaw-cli config validate` passed, reporting the other 12 roots as
unconfigured. The `vendored_sync` target inventory includes CMMMech at that
verified root. The corpus report selected exactly the three expected records.
The original dirty CLAW checkout and its environment were not changed by this
registration work.
