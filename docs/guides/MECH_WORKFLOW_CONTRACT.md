# Shared Mech goal-cycle contract

The machine-readable source of truth is
[`mech-cycle.yaml`](../../src/kg_microbe_workflows/templates/mech-cycle.yaml),
validated by the
[LinkML workflow schema](../../src/kg_microbe_workflows/schema/workflow.yaml).
The parent owns the goal order, publication sequence, evidence requirements,
and restart policy. Repository-specific skills and profiles supply the domain
objectives, applicable skills, validation requirements, and schema extensions.
The session supervisor consumes the validated contract; this guide explains
its operation.

## Six goals, one publication sequence

| Stage | Goal | Required result |
| --- | --- | --- |
| 1 | Discover and add records | Evidence-backed additions and a bounded, documented search frontier |
| 2 | Review and update causal graphs | Coverage of applicable records, with unsupported representations recorded |
| 3 | Add UniProt protein examples | Supported protein examples, especially for gene/protein graph elements |
| 4 | Review all records | Versioned coverage, review report, and structured findings |
| 5 | Resolve related review problems | Finding groups linked to real issues, fixes, and validation |
| 6 | Implement infrastructure improvements | A plan from `INFRA_TASKS.md`, issue links, implementation, and verification |

Every goal ends with the same publication sequence: validate and commit the
goal-owned changes, push a branch and open a PR, independently review the exact
head, file issues for confirmed problems, fix them, repeat affected validation
and review, merge under the repository's current rules, and delete the exact
merged branches. The supervisor verifies a closure receipt before dispatching
the next goal.

After stage 6 closes, the cycle number increases and stage 1 begins again.
Cancellation, unresolved prerequisites, uncertain delivery, or failed closure
verification hold progress. They do not silently restart a goal or a cycle.
An inapplicable domain task needs a documented applicability audit; a missing
capability remains blocked until its prerequisite exists.

The review in stage 4 and the adversarial review of each PR are separate:
stage 4 can report unresolved record problems for stage 5. Each PR's
adversarial review must be complete before that PR closes.

## Repository ownership and evolution

Each Mech has:

- `workflow/parent/`: pinned copies of the shared parent record and schema.
- `workflow/mech-workflow.yaml`: the Mech's versioned profile.
- Optional `workflow/schema/`: local LinkML extensions for its adaptation data.
- `.claude/skills/<mech>-evolve-workflow/SKILL.md`: its adaptation instructions.
- `INFRA_TASKS.md`: continuous infrastructure intake linked to GitHub issues.

The shared copies retain the parent identity, version, content hashes, and
release provenance. Change the shared definition in CLAW and publish a reviewed
release before updating those copies. Local extensions may refine Mech-specific
adaptation data; they cannot remove goals, bypass closure, or relax the shared
evidence requirements.

During a cycle, the supervisor uses an immutable runtime snapshot of the
validated effective profile. Agents can evolve the tracked profile and local
extension while working. Those edits are candidates for the next cycle, and
must pass validation and publication review. At the stage 6 boundary, the
supervisor checks the candidate against the verified closure commit before
activating it. Editing a working file does not change the running goal.

Use the repository's adaptation skill throughout the cycle. Record why a
profile or schema change is needed, its issue, validation evidence, and any
migration impact. Preserve the current native goal and its evidence rather
than relabeling it to fit a new profile.

## Review artifacts and cycle history

Review outputs are repository files committed with the goal's changes.
Transient terminal text and an assertion that a review happened are
insufficient. The parent defines an immutable directory for each run, cycle,
stage, and revision, such as:

```text
reviews/workflow/<run_id>/cycle-000001/stage-04/revision-0001/
```

Each revision records scope and coverage, the reviewed source revision, the
report, structured findings with stable identifiers, and the manifest that
binds the artifacts by path and SHA-256. A correction creates a new revision;
it does not overwrite an earlier report. Retain historical revisions and
cross-reference superseded reports. A current-cycle index is a pointer, not a
replacement for the history.

After closure verification, the supervisor writes
`verified-evidence-index.json` in the repository's runtime directory. The
next goal uses that verified pointer to update tracked
`reviews/workflow/latest.yaml` and includes the update in its own publication
sequence. This avoids an uncommitted index change immediately after a merge.

The reviewed source commit can precede the commit that adds the report.
Do not put a report's own eventual commit SHA inside that report: that would
make its identity self-referential. The external closure receipt binds the
committed report bytes to the final reviewed PR head.

Stage 5 consumes the exact stage 4 findings for its cycle. Group problems by
shared cause or implementation work, retain every finding's identifier, and
link each actionable group to an actual GitHub issue. Reuse matching issues
after checking their current state. Record fixes and validation against the
group, and retain explicit dispositions for non-actionable or deferred items.
Unresolved work must remain visible in subsequent cycles; it must not disappear
because a new review was started. A review with no findings still produces
coverage and an explicit empty findings result.

## Continuous infrastructure intake

Maintain `INFRA_TASKS.md` during every goal. Capture concrete repository needs,
missing capabilities, requirements, dependency upgrades, recurring failures,
or improvements needed to perform the work. Use stable task identifiers,
evidence, impact, dependencies, and real issue links. Search existing issues
before opening a duplicate. Preserve completed and deferred entries and their
resolution links.

Keep the machine-readable task list between the following markers; surrounding
Markdown can contain context and longer notes:

````markdown
<!-- mech-infra-tasks:start -->
```yaml
schema_version: "1.0.0"
tasks: []
```
<!-- mech-infra-tasks:end -->
````

A newly captured `note` may await issue triage. Actionable `open`, `deferred`,
and `resolved` entries require a real issue URL; deferrals need a reason.
The stage 6 snapshot preserves the actual Markdown bytes and structured task
list so a plan cannot silently omit an outstanding entry.

On entry to stage 6, the supervisor freezes the actual intake bytes and task
list in `status.json` as `infra_scope`. Copy that frozen input into the evidence
revision and define the implementation scope. Turn related entries into a plan with dependencies, acceptance checks,
and issue links; create missing issues and implement the plan. Newly discovered
work is added to the intake and explicitly carried forward rather than
continually expanding the frozen plan. An empty intake requires a documented
reviewed empty result, not invented work.

The stage 6 evidence binds the intake snapshot, selected tasks, plan, issue
dispositions, implementation, and validation. The standard publication sequence
then closes the goal, seals the cycle, and permits the next cycle.

## Validation and operational limits

Validation has two layers: LinkML checks record shapes and types; workflow
semantic checks enforce ordering, pins, cross-references, cycle identity, and
evidence requirements. The supervisor also checks artifact bytes in Git and
the actual PR, merge, checks, issue, and branch state. These checks verify
provenance and workflow completion; scientific correctness still requires
the domain and adversarial reviews.

The implementation follows LinkML's documented
[data-validation](https://linkml.io/linkml/data/validating-data.html) and
[schema-import](https://linkml.io/linkml/schemas/imports.html) mechanisms.
See [session operation](MECH_SESSION_WORKFLOWS.md) for terminal bindings,
receipts, stopping, and recovery.
