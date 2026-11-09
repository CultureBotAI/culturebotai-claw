# Current-main admission integration evidence, 2026-11-08

The final readiness refresh found new protected main
`081e9c8f44c5ce28849e162b7fecac1b3ba17ad7`, containing PRs 978 and 956.
Issue 997 records the two release-audit conflicts. Normal merge commit
`0a3e7a6fad03bf69d71acf20d488e500aa50c923` preserves upstream future-payload
publication and separates it from the immutable admitted source. No force push
or PR merge occurred. Historical tests and receipts at `85a69ee2` remain
historical evidence, not validation of this new combined tree.

The DUF declaration remains SHA256
`89a362436eb3df0f3b4bfdb9feeaf9a258b2476291e565a744568b41f9445697`;
its packaged historical manifest remains
`368edbac106cb49c0a4159a87c07eeba4a5ed79c343ff042c0ddbc1b6b990ebb`.
The unchanged infrastructure declaration remains
`1d65bcbe0b6697c20cff09af817f2e864e564e8f62303ed76c30383072fc705f`.
The newly packaged admitted manifest is the exact Git blob at source
`7e672227fb246a8359ad57b6d3975ce5ed329007`, SHA256
`bfd4b703f46ce748487253d6fe093e79fe00ba7a9a88293f5cc6df176f11b519`.
Current canonical payloads checksum-validate independently; their authority and
layout must remain exact. Historical and admitted consumer bytes stay pinned.

The first real dry-run failed in public `plan_sync` before any target write or
receipt, because it still required the installed current manifest at every pin.
Issue 1004 records that failure. Commit
`a099f2559e334bdec9941b1d25fb3f714d36add0` adds only an exact Edge identity/ref
source selection, authenticates the frozen manifest and every fetched payload,
and carries one immutable desired tuple through the existing transaction and
post-write checks. Generic canonical-ref verification stays strict. The public
canary launcher was not bypassed or changed.

Independent read-only reviews passed the integration, sync transaction path,
installed-resource smoke and final mutation harness. Validation performed:

- 124 focused release/admission/workflow/canary/scope tests passed in 444.89s.
- Nine new public sync tests passed in 12.09s, including actual old-byte
  installation, no-op reuse, wrong context, corruption and rollback.
- 51 existing governance/transaction/sparse tests passed in 92.35s.
- The final wheel/source test passed in 8.06s. It checks the exact packaged
  snapshot and executes public admitted `plan_sync` from unpacked-wheel modules,
  with externally supplied SHA-bound fixture data, 20 planned files and no writes.
- Complete maintained Ruff and mypy for all three affected governance modules passed.
- Three integration mutation controls and two sync controls failed at the
  intended assertions in fresh Python processes; their small receipts are retained.
  Issue 1006 records the first sync harness attempt's import-origin refusal.
  The corrected harness isolates pytest configuration while retaining the exact
  imported-module assertion and fresh bytecode. It never claimed the failed
  first attempt as a successful proof.

The corrected real canary used local policy commit `a099f2559e334bdec9941b1d25fb3f714d36add0`
and clean EdgeMech `375a86e9d0ae56533d73b54654867d55c29026e4`, the unchanged retained
launcher, explicit `PYTHONPATH=src:.`, the same interpreter and non-login Bash.
Dry-run succeeded and its persisted receipt was verified before apply mode.
Both modes verified all 19 working and committed artifacts plus the exact pin,
planned/applied zero changes and left the consumer clean. Both explicitly report
inactive trusted admission and no scientific capabilities.

| Retained receipt | SHA256 |
| --- | --- |
| `current-main-canary-dry-v2.json` | `67e712957d5db6df26bcab37fdf628c454d8b8fa5eb530dd8261fde45009c851` |
| `current-main-canary-applied-v2.json` | `811436513d01591f8631f640aafcc2829b2e4b01421ae839366e7547e0b2a77c` |

The final evidence commit changes documentation only; it is not relabeled as
the code commit exercised by those canaries. The complete canonical suite and
five authoritative checks run once on the final pushed PR candidate. Their
exact-head result belongs to the PR handoff. The EdgeMech full census and its
185-test CI proof are unchanged; neither is rerun by this CLAW integration.
