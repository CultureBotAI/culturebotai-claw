# Public sync must retain the exact admitted source after current payload evolution

The real dry-run consumer canary at local CLAW integration commit
`0a3e7a6fad03bf69d71acf20d488e500aa50c923` failed in the public `plan_sync`
path before any receipt or target write:

```text
plan_sync -> _verify_canonical_ref
GovernanceError: Pinned claw manifest does not match the installed governance package
```

The installed manifest now contains the checksum-valid current-main payloads,
while EdgeMech deliberately retains the exact admitted source
`7e672227fb246a8359ad57b6d3975ce5ed329007`. The release audit already distinguishes
those snapshots, but the public sync API still assumes every requested pin is
the current installed package. Merely relaxing that equality would be unsafe:
the desired-file builder would then write current bytes under the old pin.

Add a bounded sync source selection for only the exact admitted EdgeMech
identity and declared immutable ref. Validate the packaged admission and frozen
manifest, current layout/checksums, fetched manifest bytes and every source
payload digest. Carry the same verified old payloads through planning, the
existing safe transaction and post-write verification. All other consumers,
refs and the generic canonical-ref verifier must retain their exact installed
package requirements. Test real fixture installation and no-op reuse after
current payload evolution, as well as wrong-consumer/ref, corrupted source and
current-checksum negatives. The real canary must continue to call the public
APIs without a helper bypass.

The failed command used the retained launcher, non-login Bash and explicit
`PYTHONPATH=src:.`; it exited 1. EdgeMech remained clean at
`375a86e9d0ae56533d73b54654867d55c29026e4`. An ignore-independent workspace search
confirmed neither requested dry nor apply receipt exists; no apply was run.
Keep that failure and use new v2 receipt paths for the corrected dry/apply
canary. This finding belongs in PR 953 and follows issue 997.
