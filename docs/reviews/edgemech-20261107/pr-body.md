EdgeMech needs immutable external storage and native-review transport without
changing exact release occurrence identity or inventing scientific approval.

This PR adds canonical artifact and inherited native-assertion contracts for
#766/#767, records the reviewed dependency pins, and registers EdgeMech as a
fleet consumer. Implementation and end-to-end validation are in progress.

The prerequisite adversarial findings are #951 and #952. Existing curation v1
and RecordReview authority remain unchanged. Native reviewed assertions do not
authorize retain/amend for newly joined KG occurrences.

Validation so far: focused contract compatibility tests and separate read-only
shared-contract review. Full repository gates, storage migration canary,
native adapter conformance and full pinned-snapshot census are pending.

Merging requires explicit user approval. Downstream feature PRs must pin the
reviewed CLAW commit; none of the open historical prerequisite PRs is treated
as a deployed contract.
