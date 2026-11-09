---
name: metpo-aggregate
description: "Survey and merge METPO proposals across the Mech fleet into class/property ROBOT templates, provenance, and a review narrative. Use for a combined or unified fleet proposal, coverage audit, or collision check. Resolves proposing Mechs through the manifest; writes only to CLAW's workspace."
metadata:
  category: cross-repo
  requires_database: false
  requires_internet: false
  version: 2.0.0
  tags: [metpo, ontology, proposal, cross-repo, fleet, aggregate, robot, read-only]
---

# METPO aggregate

Use the shared merger in `scripts/fleet_metpo_aggregate.py`. It gathers all
cohorts declared by the `metpo_proposal` capability in
`src/kg_microbe_fleet/fleet.yaml`. Local cohort authoring remains in each
proposer's `metpo-proposal` skill; this skill owns the combined review bundle.

## Survey before calling the result fleet-wide

Resolve all Mechs through the fleet root resolver. Read each capability's
status and reason, then inspect the local proposal files, authoring skills,
ground-or-propose commands, and verification recipes. Search with
`rg --no-ignore --hidden` when establishing absence, including ignored files.
Check Git HEAD, working-tree changes, and current remote default branch before describing
remote state; label unavailable remote checks and local-only results explicitly.

Disabled means excluded by the manifest, not proven absent. If an excluded Mech
has begun producing cohorts, inspect their compatibility and update its manifest
capability within the authorized task. Do not quietly skip discovered proposals
or enable domains merely because they consume METPO. The merger reports all
manifest declarations but only reads enabled proposers.

## Run from CLAW

```bash
uv run python scripts/fleet_metpo_aggregate.py --check
uv run python scripts/fleet_metpo_aggregate.py --check --json
uv run python scripts/fleet_metpo_aggregate.py --out workspace/metpo/review
```

The default output directory is `workspace/metpo/`. Prefer a distinct directory
for a review that should remain reproducible. `--check` writes nothing.

| Output | Purpose |
|---|---|
| `metpo_fleet_aggregate_classes_robot.tsv` | Combined class declarations |
| `metpo_fleet_aggregate_properties_robot.tsv` | Combined property declarations |
| `metpo_fleet_aggregate_provenance.tsv` | Every accepted input row's Mech, cohort, and source file |
| `metpo_fleet_aggregate_report.json` | Coverage, conflicts, errors, input SHA-256 fingerprints, and merge status |
| `proposal.md` | Review entry point with totals, findings, and remaining submission checks |

Exit `0`: mechanical merge is clean. Exit `1`: conflicting or incomplete input;
review outputs are diagnostic drafts. Exit `2`: usage, manifest, or output error.
Neither exit zero nor a generated TSV certifies an upstream-ready proposal.

## Merge contract

- Cohorts are additive unless a curated lifecycle explicitly supersedes them.
  A version suffix alone is not a supersession rule. The merger does not filter
  accepted or rejected proposals; reconcile lifecycle before submission.
- Each TSV has a human header and a ROBOT directive row. The aggregate carries
  the directive row once. Reject malformed widths, duplicate columns, missing
  identities, and repeated header rows.
- The supported class formats share OWL directives: legacy `synonyms` and newer
  `exact_synonyms` both denote exact synonyms. Normalize that alias and retain
  an optional `related_synonyms` column with its distinct related-synonym
  directive. Never promote related synonyms to exact synonyms.
- Other incompatible shapes are reported. A strict majority shape may be
  retained for diagnostic output; excluded inputs make the run incomplete.
  A plurality or tie does not choose a winner.
- Deduplicate only complete identical rows. Keep differing definitions,
  citations, parents, mappings, or other columns visible and report the
  disagreement. Do not silently select the first or newest cohort.
- Report one ID with multiple labels, one label with multiple IDs, differing
  rows for one ID/label, and class/property reuse of the same ID. Do not
  automatically renumber or choose the winning meaning.

## Complete the review

Read every source cohort's narrative and any SSSOM mapping sidecar. These carry
curation rationale and external matches; they remain source artifacts, not
additional ontology assertions inserted by the merger. Use their evidence to
expand the generated narrative with scope and hierarchy decisions when the user
asks for a submission proposal.

Reconcile with the current upstream METPO release and pending kg-microbe
proposals. kg-microbe is outside the fleet manifest and is not silently included
in the merge; it still shares the identifier space. Read its local
`metpo-proposal` skill and authoritative proposal/alias/placeholder ledgers.
Check current release IDs, labels and exact synonyms, not just a local numeric
block. Record accepted, pending, superseded, and rejected terms explicitly.
Keep placeholder migrations coordinated with consumers; proposed IDs are not
proof of upstream acceptance.

For an upstream-ready deliverable, resolve conflicts and lifecycle decisions,
verify parents/domain/range against released or retained terms, review definition
citations, and run ROBOT template ingestion plus ELK reasoning. Bind `METPO:` to the release namespace
`https://w3id.org/metpo/`; older examples using the OBO-style METPO prefix
create different IRIs and cannot validate against the released ontology. Record the
release version, checks actually run, and anything still unverified.

The merger writes only local review artifacts. For authorized downstream fixes,
follow the cross-repository checklist in `CLAUDE.md`. Upstream submission or
posting requires user authorization for that action.

## Maintenance

Run `tests/test_fleet_metpo_aggregate.py` after merger changes. Preserve the
shared implementation rather than distributing divergent mergers to Mechs.
Keep dated infrastructure surveys under `workspace/reports/`; use GitHub issues
for remaining shared-contract or release work.
