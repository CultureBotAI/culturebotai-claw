---
name: evolve-mech-workflow
description: "Maintain the shared Mech goal-cycle contract and prepare repository-specific workflow adaptations. Use when changing the recurring goal/commit sequence, review-output lifecycle, infrastructure intake, or a Mech's workflow profile and LinkML extension."
metadata:
  category: cross-repo
  requires_database: false
  requires_internet: true
  version: 1.0.0
  tags: [fleet, workflow, governance]
---

# Evolve the Mech workflow contract

The packaged parent YAML at
`src/kg_microbe_workflows/templates/mech-cycle.yaml` and its LinkML schema at
`src/kg_microbe_workflows/schema/workflow.yaml` govern the shared sequence.
Read both with the workflow loader before changing orchestration or rendering
instructions. Per-Mech profiles specialize domain work; repository-local
`.claude/skills` remain the operational skill source of truth.

Resolve current targets with `load_fleet_manifest` from `kg_microbe_fleet` and
`RepositorySettings`, using the explicit CLAW environment file. Revalidate the
exact worktree and every origin fetch/push URL before access. Record local
changes separately from current published behavior. Search ignored and hidden
files before declaring a skill, profile, schema, or infrastructure ledger absent.

## Shared contract and local adaptations

Preserve the parent sequence: add records, causal graphs, protein examples,
record review, grouped review remediation, and infrastructure implementation.
Every stage is followed by the full commit/PR, independent adversarial review,
real-issue creation, fixes and renewed review, verified merge, and owned-branch
cleanup sequence. Only the supervisor dispatches the next /goal after verified
closure; agents write their structured receipt and stop. The next cycle starts
only after infrastructure closure and validated boundary activation.
Keep cancellation, blockers, native goal identity, exact-head verification,
no-diff receipts, and stop requests effective throughout the sequence.

Render the canonical `evolve-mech-workflow` skill using
`kg-microbe-skills render --skill evolve-mech-workflow --mech <key>`.
For a namespaced installation, set its frontmatter name and folder to
`<key>-evolve-workflow`. The profile's `adaptation_skill` points to that exact
file. Keep Mech-specific knowledge outside canonical managed regions so later
updates preserve it. Add the adaptation skill to every stage's preflight. Require agents to read
their supervisor-supplied status.json, effective_workflow_path, receipt_template,
goal_evidence_schema_path and completion_receipt_path before creating evidence
or receipts. Receipt placeholders require observed proof.

Profiles live at each Mech's workflow/mech-workflow.yaml. Vendored parent
snapshots live at workflow/parent/mech-cycle.yaml and
workflow/parent/workflow.yaml; pin both byte hashes in the profile. A local
LinkML extension defines a separate namespaced document and may add native
validation or metadata without overriding parent fields or weakening gates.
Use the package's profile validator; do not treat successful YAML parsing as
schema or semantic validation.

Read the runnable evidence examples and validation commands in
`src/kg_microbe_workflows/examples/README.md`. The examples are illustrative
empty outcomes; agents must create real artifacts and replace all identities and
hashes. The save_goal_evidence API validates and creates a new manifest without
overwriting an existing revision; it does not manufacture supporting evidence.

Stage 4 must retain actual review reports, structured findings, corpus coverage,
reviewer provenance, limitations, input hashes, and disposition accounting.
Revision and cycle directories come from the parent policy under
reviews/workflow. Stage 5 groups related findings into deduplicated GitHub
issues, resolves them through native writers, and saves the finding-to-issue
mapping plus fresh review and validation. Preserve original reports; a new
assessment creates a linked revision. Neither a terminal summary nor a mutable
latest file is a versioned review artifact. Update the tracked latest-review
index only in a subsequent goal from the supervisor's verified-evidence-index.json
with verified_closure authority, preserving its hashes and closure references.
Do not advance the index on a current unverified report or edit the runtime index.

Each repository maintains INFRA_TASKS.md continuously. Entries retain stable
IDs, observed requirements or upgrade needs, evidence, originating cycle and
goal, priority, dependencies, status, and real GitHub issue links. Preserve any
existing ledger and append or reconcile narrowly. Keep the schema-versioned
tasks mapping in its mech-infra-tasks:start/end marked YAML section; an unlinked
initial note stays status note, while open/deferred/resolved tasks need real
issue URLs. Do not invent issues for an empty ledger. Stage 6 freezes a byte copy
of the supervisor-frozen infra_scope content/hash/time from status.json, accounts
for every non-resolved task, saves an implementation plan,
creates or reuses related issues, implements the plan, validates it, and records
deferred work explicitly before closure and restart. New arrivals after the
cutoff remain in the next cycle's intake.

## Prepare and activate a change

For each target, capture hashes of the installed profile, parent snapshots,
adaptation skill, optional extension, and existing infrastructure ledger. Build
candidates outside active checkouts; preserve unrelated changes. Check declared
skill paths, native model and writer constraints, actual validation commands,
and corpus ownership. Carry prerequisites as explicit blockers; applicability
requires a domain-based reason, not a workaround for a failed check.

An active cycle retains its pinned profile and evidence paths. Prepare evolution
in the repository profile as the next-cycle candidate, with version, rationale, source evidence,
validation results, and a migration plan when old artifacts would become invalid.
Do not silently rewrite a running goal or its receipt contract. Activate only
at the coordinator's verified cycle boundary after the change's closure; a
coordinator without next-profile support remains blocked on activation.

Use existing authorization and the cross-repository mutation checklist in
CLAUDE.md. Acquire the owned repository lock, compare captured hashes again,
stage and validate the complete file set, then replace atomically. Report local
installation separately from committed or published adoption. Do not claim
successful activation merely because a profile validates or files were copied.
