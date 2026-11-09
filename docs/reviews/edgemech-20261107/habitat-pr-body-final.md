This adds a native EdgeMech adapter for HabitatMech's authoritative curation
decision table. Complete rows, source positions, source commit and native
review depth remain bound to immutable file hashes. Explicit ITEM decisions
retain their native action predicate; other native states remain unassessed.
No SKOS or biological edge projection is invented.

The shared-contract prerequisite is
[CLAW #962](https://github.com/CultureBotAI/culturebotai-claw/pull/962), at
unchanged source pin `1b5391d083ba85ac94e5279c3cba25ac4fde243c`.
The historical validation receipt refers to the original combined PR #953;
its shared contracts have since moved to #962. Admission-specific PR #953
is not this adapter's shared-contract prerequisite. This metadata correction
is recorded in [CLAW #964](https://github.com/CultureBotAI/culturebotai-claw/issues/964).

Validation: 16 focused mandatory integration tests passed, including valid-row
reversal/duplication during persisted readback, exclusive publication,
interrupted publication and directory sync. Ruff passed. A real position-11
canary preceded the complete 1,831-row export against native commit
`3b232e8a50ac434e4c1131edc43fb39ba0af10e3`. Exact persisted bytes, ordered
membership and counters were verified before manifest-last publication.

The full table has 424 inherited native ITEM decisions and 1,407 unassessed
curation states; zero independent scientific reviews or KG approvals.
Its JSONL has 7,911,812 bytes, SHA256
`fed100eeadd35bf114167c5ba07bad67c3493e6fc6c629cec917a70143867e56`;
manifest SHA256 is
`484e037facef2e3f4edff792c5acfd52ac932a46b4af321f8526aca40e17d4c4`.
The committed `docs/EDGE_CURATION_VALIDATION_20261107.md` records the commands,
canary hashes and review evidence. Large analytical payloads stay outside Git.

Independent read-only review filed #2312; repaired persisted byte/membership
verification and mutation tests passed reinspection, and the corrected
canary was independently checked on disk. Fixes #2312.

Issue #2311 remains open for exact taxon/organism observations, ancestry and
reviewed cross-schema projections. Counts, characteristic taxa, preferences
and causal mechanisms remain outside this decision-table surface. This
implements the HabitatMech slice of
[CLAW #767](https://github.com/CultureBotAI/culturebotai-claw/issues/767).
