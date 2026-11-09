# EdgeMech admission validation, 2026-11-07

The implementation for CLAW #960 is committed at
`ce87c61d813fb26e78d0d2e4475967424074cc2c`. It adds infrastructure admission
alongside the active DUF lane. The historical release declaration, governance
payloads, fourteen-consumer rules and shared curation identities are unchanged.
The candidate is not an active protected admission; merging remains a separate
explicit user decision.

Independent adversarial review found and repaired #982 (candidate completeness
at the exact empty bootstrap), #984 (receipt parent symlinks), #986 (binding the
declared source ref to actual Git object bytes), and #988 (explicit rejection
before fetching a malformed data ref). Each finding has a retained body in this
directory. Subsequent read-only review accepted the repaired policy, source
binding, trusted workflow preparation and canary helper.

## Real consumer canary

The same retained launcher and environment ran dry-run first, then `--apply`,
under the EdgeMech edit lease against its clean feature head
`ea2503df9ffdbf9cb6b6ae82b3c0ba32d272f3d2`:

```sh
uv run --no-sync python scripts/adhoc/verify_edgemech_admission_canary_20261107.py \
  --edge-root /Users/marcin/Documents/VIMSS/ontology/Mechs/EdgeMech-milestones-20261107 \
  --receipt workspace/edgemech-admission-canary-dry-20261107.json
uv run --no-sync python scripts/adhoc/verify_edgemech_admission_canary_20261107.py \
  --edge-root /Users/marcin/Documents/VIMSS/ontology/Mechs/EdgeMech-milestones-20261107 \
  --receipt workspace/edgemech-admission-canary-applied-20261107.json --apply
```

Both persisted receipts were independently read and rehashed, then copied here
without overwriting any destination and checked byte-for-byte:

| Receipt | SHA256 |
| --- | --- |
| [Dry-run](admission-canary-dry.json) | `c946ac224216c78d6c4ddd7c19f27929e705c7ed4d93d2395e0c0c260634d4a5` |
| [No-op apply](admission-canary-applied.json) | `8707cf3e10034604af02908477fbc9bd11f8adcf279bb60ea6aa48a1d96e6e74` |

Both verified all 19 applicable artifacts in the working and committed trees,
plus the committed source pin. Both reported zero planned and applied changes;
EdgeMech remained clean at the same head. The source pin was
`7e672227fb246a8359ad57b6d3975ce5ed329007`, with source manifest SHA256
`bfd4b703f46ce748487253d6fe093e79fe00ba7a9a88293f5cc6df176f11b519`.
The launcher SHA256 was
`a6b64f7c0ba77d512335405f5e76251b74594869c9655eb2f85df9f20f993072`.

This proves candidate synchronization planning, the no-op apply path, and
complete persisted consumer-byte/pin verification. It does not install new
bytes, verify a broader rollout, activate trusted admission, grant scientific
capabilities, or certify deployment from protected main. Both receipts explicitly
report `trusted_admission_active: false` and
`scientific_capabilities_enabled: false`.

## Local regression evidence

Development validation included 75 focused release/admission/workflow tests,
then targeted reruns after review repairs: four additional bootstrap/source-pin
controls, six receipt-path tests, three source-binding/preparation tests, and
the final seven-test workflow suite. Required Ruff checks passed; required mypy
checks passed across 104 source files. These are staged local checks, not a
claim that the complete final-head suite ran locally. Authoritative CI follows
the final evidence commit and push.

The retained mutation launcher ran six negative controls in fresh isolated
processes. Removing each guard made its regression fail: capability, historical
payload, changed bootstrap tip, actual source snapshot, receipt symlink, and
workflow ref rejection. [Five-guard proof](admission-mutation-proof.json) and
[workflow proof](admission-workflow-mutation-proof.json) bind the tested source
digests and confirm production sources were unchanged. The original failed
development traces remain in ignored `workspace/`; they are not counted as
successful validation.

The companion site membership remains in
CultureBotAI/CultureBotAI.github.io#541. This policy addition does not change its
projected fleet entry. Shared contracts remain separately reviewable in #962;
the downstream immutable contract pin is still
`1b5391d083ba85ac94e5279c3cba25ac4fde243c`.

## Final CI follow-up

The first evidence-head authoritative run at `90bf24612108653d0b608c3e1ab39042a90878f1`
passed its protected historical audit, then failed one candidate-workflow
assertion with 183 other tests passing. The policy filename embedded a fleet
key in the otherwise manifest-derived workflow. Finding #989 records the exact
run and repair; the existing assertion remains unchanged. Preparation now
checks only the generic protected selector, whose empty/no-admission result
skips fetching. Nonempty output retains the explicit 40-hex guard.

The repaired workflow and ID-label regression suites passed all 21 tests;
focused Ruff and diff checks passed. A fresh [workflow mutation proof](admission-generic-workflow-mutation-proof.json)
confirms malformed-ref rejection still fails when its guard is removed. The
policy and real canary helper digests remain identical to the verified receipts,
so this workflow-only repair does not change the consumer synchronization
canary. Final authoritative/full CI must run on the repaired head.
