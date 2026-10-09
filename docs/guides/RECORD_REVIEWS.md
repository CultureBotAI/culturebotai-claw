# Structured Record Reviews

Each Mech retains its own scientific rubric and authoritative input paths.
CLAW standardizes the resulting review observations so findings can be compared,
triaged and planned across repositories without equating unrelated domain scores.

## Contract

- [Canonical LinkML schema](../../src/kg_microbe_governance/artifacts/schema/record_review.yaml)
- [Authoring, persistence and disposition protocol](../../src/kg_microbe_governance/artifacts/docs/record-reviews.md)
- [Pinned pre-rollout fleet inventory](../reviews/2026-10-08-record-review-infrastructure-audit.md)

Each consumer carries `conf/record_review.yaml` identifying review skills and
rubrics, plus `docs/record-review-profile.md` describing local ownership and
scientific gates. The common helper writes authoritative YAML and derived
Markdown under `reviews/structured/<timestamp>-<slug>/`. Old ad hoc reports
remain historical evidence; there is no automatic migration or implied coverage.

## Fleet Triage

From a configured CLAW checkout:

```bash
uv run kg-microbe-reviews fleet --all --format json
uv run kg-microbe-reviews fleet --all --format markdown --output /tmp/review-triage.md
uv run kg-microbe-reviews fleet --mech culturemech --status open --severity major --format tsv
```

The command uses configured, identity-validated repository roots. By default it
reads each local cached `origin/main`, never fetching or modifying any Mech.
Use the normal fleet refresh workflow separately when remote freshness matters.
`--working-tree` includes local saved bundles, even ignored ones. Output files
are created exclusively, so choose a new filename for each exported report.

Every requested manifest member remains in the result, including unavailable
repositories and those with no structured reviews. `--require-reviews` makes
missing coverage an error. Zero reported findings is not evidence of a complete
scientific review. Schema, provenance and lineage errors return nonzero even
when severity or status filters hide the affected issue rows.

JSON retains complete reviews, evidence and proposed actions. Its issue heads
are repository-scoped and use explicit predecessor links; omitted findings do
not silently close. Conflicting dispositions stay visible. Current input hash
state is reported for both open and terminal findings. Working-tree provenance
is an attestation, not proof of committed bytes; historical-commit provenance is
verified against the named Git tree.

`planning_inputs` selects proposed actions for unresolved issue heads plus their
prerequisite closure. It does not infer that actions were executed. Native
severity, rule IDs, dimensions, metrics, owners, external issue links and
acceptance checks are retained for domain-aware organization and planning.

## Enforcement

The shared consumer contract checks configured review routes, valid saved pairs,
append-only history against the CI event's trusted base, and the saver. A valid
bundle does not authorize scientific edits, GitHub publication, paid research,
or native status promotion. Those remain governed by the Mech's existing rules.
