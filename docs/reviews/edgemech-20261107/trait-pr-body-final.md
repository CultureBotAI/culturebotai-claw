Export TraitMech canonical examples from an immutable source commit into CLAW's pinned native assertion contract. Every envelope retains the complete owning record, exact example position, source/evidence hashes and native qualifiers. Reference examples remain unassessed; whole-record review and taxon-agnostic mechanisms do not approve organism or strain observations.

The shared-contract prerequisite is [CLAW #962](https://github.com/CultureBotAI/culturebotai-claw/pull/962). This adapter retains the reviewed immutable source pin `1b5391d083ba85ac94e5279c3cba25ac4fde243c`. CultureBotAI/culturebotai-claw#953 and its release-policy dependency CultureBotAI/culturebotai-claw#960 are separate from this contracts-only change.

The publisher verifies persisted assertions and source/accounting invariants, reserves a new destination exclusively, and publishes a durable manifest last. Dedicated CI requires the exact shared-contract checkout and validates the actual YAML-loader source closure.

Validation: 27 focused adapter tests, lint, PR sanity and the live shared-runtime pin check passed. The complete native `just --no-dotenv qc` suite passed, including all 1,130 records and derived-artifact freshness; publication-only follow-ups passed focused regression tests and lint. A real one-example canary verified nonempty persisted files, exact hashes, unassessed=1 and zero approvals before the full native export. Generated exports remain outside Git under `workspace/`.

Independent review findings are recorded in `docs/EDGE_CURATION_REVIEW_20261107.md` and addressed in this PR. Related to CultureBotAI/culturebotai-claw#767.

Closes #2079.
Closes #2080.
Closes #2081.

This PR remains draft; merging requires explicit approval.
