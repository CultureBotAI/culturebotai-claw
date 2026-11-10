---
name: metpo-proposal
description: "Author and update METPO ontology term proposals for {{ display_name }} (`{{ github }}`) as five-file ROBOT template cohorts under `proposals/<cohort>/`, coordinated across the fleet via `<claw-root>/scripts/fleet_metpo_aggregate.py`."
---

# METPO Proposal Contract ({{ display_name }})

<!-- canonical:begin contract -->
**Durable session state.**
Use the gitignored `<repo>/.temp/` as the durable work root for review campaigns,
worktrees, batch state, draft review bundles and handoffs. Use
`~/agent-work/<repo>/` when a separate clone is needed. Verify `.temp/` is ignored
before use; provision a missing ignore rule through an authorized repository
change. Keep maintained helpers and accepted evidence in their native tracked
directories; a durable scratch root does not replace their provenance contract.

Never store session state or helper scripts in `/tmp/`, `/private/tmp/` or `$TMPDIR`.
Only disposable caches and pytest temporary fixtures may use system temp roots.
Use a unique subdirectory for each task and preserve other sessions' state.

Report every auxiliary clone for identity verification and inventory in
session_repository_roots, and owned campaign/handoff directories in
session_state_paths. Missing inventory is unknown, not healthy. Report new paths
to the supervisor/operator; do not edit live configuration or expand authority.

For authorized Git work, push each committed batch branch to `origin` the same
day, whether or not a PR is opened. Verify the exact pushed head with the remote;
a local commit or remote-tracking ref alone is not publication proof. Inspect
the repository's current workflow triggers before claiming a branch push runs
no CI. A goal delivering commits cannot close while recorded commits exist only
locally. Publication failure is a retained blocker, never permission to discard
the branch. This rule grants no Git mutation, merge, cleanup or provider
authorization beyond the task and the skill's existing boundaries.

Every METPO proposal cohort in a proposing Mech is an auditable five-file bundle
under `proposals/<cohort>/`:

| File | Required | Purpose |
|---|---|---|
| `proposals/<cohort>/proposal.md` | Yes | Narrative rationale, scope, hierarchy decisions, and upstream reconciliation |
| `proposals/<cohort>/metpo_proposal_classes_robot.tsv` | When proposing classes | ROBOT class template (header row + row-2 OWL directives + proposed class rows) |
| `proposals/<cohort>/metpo_proposal_properties_robot.tsv` | When proposing properties | ROBOT object/data property template (header row + row-2 OWL directives + proposed property rows) |
| `proposals/<cohort>/evidence.tsv` | Yes | Literature and database evidence backing each proposed term |
| `proposals/<cohort>/usage.tsv` | Yes | Corpus records in this repository that use each proposed term |

Bind `METPO:` to the release IRI namespace `https://w3id.org/metpo/`. Do not use
an OBO-style `http://purl.obolibrary.org/obo/METPO_` prefix, which produces
different IRIs that cannot validate against the released ontology.

### Canonical ROBOT class template (12 columns; 11-column legacy `synonyms` normalized)

Row 1 (header) and row 2 (ROBOT directive) must match the governed contract in
`<claw-root>/scripts/fleet_metpo_aggregate.py`:

1. `proposed_id` -> `ID`
2. `label` -> `LABEL`
3. `definition` -> `A IAO:0000115`
4. `parent` -> `SC %`
5. `exact_synonyms` (or legacy `synonyms`) -> `A oboInOwl:hasExactSynonym SPLIT=|`
6. `examples` -> `A IAO:0000112`
7. `source` -> `A dcterms:source`
8. `comment` -> `A rdfs:comment`
9. `creator` -> `A dcterms:creator`
10. `date` -> `A dcterms:date`
11. `subsets` -> `A oboInOwl:inSubset`
12. `related_synonyms` (optional in legacy 11-col; normalized on read) -> `A oboInOwl:hasRelatedSynonym SPLIT=|`

Never promote `related_synonyms` into `exact_synonyms`.

### Canonical ROBOT property template (13 columns; 12-column legacy `synonyms` normalized)

1. `proposed_id` -> `ID`
2. `label` -> `LABEL`
3. `definition` -> `A IAO:0000115`
4. `parent` -> `SP %`
5. `domain` -> `DOMAIN`
6. `range` -> `RANGE`
7. `inverse` -> `I`
8. `characteristic` -> `CHARACTERISTIC`
9. `exact_synonyms` (or legacy `synonyms`) -> `A oboInOwl:hasExactSynonym SPLIT=|`
10. `source` -> `A dcterms:source`
11. `comment` -> `A rdfs:comment`
12. `creator` -> `A dcterms:creator`
13. `related_synonyms` (optional in legacy 12-col; normalized on read) -> `A oboInOwl:hasRelatedSynonym SPLIT=|`
<!-- canonical:end contract -->

## Fleet ID-space coordination

<!-- canonical:begin id-coordination -->
All proposing Mechs (`TraitMech`, `CommunityMech`) and upstream `kg-microbe`
share one identifier space:

- **Classes**: `METPO:1007xxx`
- **Properties**: `METPO:2007xxx`

Before assigning any `METPO:` identifier in a new or updated cohort, run the
fleet merger from `culturebotai-claw` to inspect every existing allocation and
verify zero collisions across all enabled proposers:

```bash
uv run --project <claw-root> python <claw-root>/scripts/fleet_metpo_aggregate.py --check
```

Never reserve a range solely in one Mech's prose (`CommunityMech#756`): an ID
allocated in any cohort across the fleet is reserved fleet-wide. One identifier
must mean one label and one set of OWL assertions across every cohort, and one
label must not be split across two proposed identifiers.
<!-- canonical:end id-coordination -->

## Updating existing proposals and cohort lifecycle

<!-- canonical:begin updating-proposals -->
- **Cohorts are additive batches, not overwrite revisions.** The fleet aggregator
  merges every `proposals/<cohort>/` directory; adding `v2` does not supersede
  `v1`. Never copy an earlier cohort into a new directory with modified text for
  the same ID, because the merger will report conflicting OWL assertions.
- **In-place refinement before upstream submission:** When correcting a typo,
  tightening a definition, or fixing a parent on an unsubmitted term, update the
  row in the cohort that introduced that `METPO:` ID and keep any identical
  re-declaration in later cohorts byte-identical, or remove the duplicate row.
- **Never repurpose an assigned ID for a different concept.** If a proposed term
  is retired before submission, remove it from its cohort and update its local
  corpus references; do not assign its `METPO:` number to an unrelated label.
- **Reconcile after upstream METPO releases:** When an upstream METPO release
  accepts a proposed term under its permanent ID, migrate corpus references in
  {{ record_globs }} and record the cohort's lifecycle status in
  `proposals/<cohort>/proposal.md`.
- **Gate every proposal change:** Run
  `uv run --project <claw-root> python <claw-root>/scripts/fleet_metpo_aggregate.py --check`
  before opening a PR (writing any PR or issue body to an owned file and passing
  `--body-file <path>`).
<!-- canonical:end updating-proposals -->

## Repository-specific grounding and corpus conventions

In `{{ display_name }}` (`{{ github }}`), validate proposed terms against
{{ schema_paths }} and check usage across {{ record_globs }}. Keep repository-specific
grounding cascades, cohort range notes, and domain parent-class choices here,
outside the canonical regions.
