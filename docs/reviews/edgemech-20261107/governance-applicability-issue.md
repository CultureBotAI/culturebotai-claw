The initial EdgeMech governance synchronization exposed three artifacts whose
`consumers: all` declaration asserts native-record capabilities:

- `curation_timestamp_contract` requires exactly one native `CurationEvent`.
- `record_review_contract` requires a native review profile, skill and rubric.
- `skill_frontmatter_contract` requires at least one native skill.

EdgeMech uses the canonical external ledger and explicitly has not adopted
those native record/skill interfaces. The synchronized tests therefore produce
four failures even though the shared storage, native assertion and candidate
packet contracts pass. An independent read-only applicability review confirmed
that inventing a duplicate history schema or scientific review route just to
pass these checks would misrepresent its capabilities.

Fix within CLAW #953: use the registry's existing explicit-consumer mechanism
for these three native-adoption artifacts, preserving all existing native
consumers. Canonical schemas, helpers, docs and applicable integrity tests
continue to be distributed to EdgeMech. Add a regression proving the exact
scope and document why admission does not imply native review adoption.

Future refinement: split generic RecordReview semantic tests from the
native-profile adoption test. This task need not introduce a new selector
language or change other repositories' payloads.
