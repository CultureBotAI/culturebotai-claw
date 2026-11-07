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

## Seven goals, one publication sequence

Parent v2.0.0 adds issue triage before discovery. The stable stage key determines
the work; numbers are meaningful only with that cycle's pinned parent version.

| v2 stage | Stage key | Goal | Required result |
| --- | --- | --- | --- |
| 1 | `open_issue_triage` | Triage and resolve open issues | Frozen inventory, stable groups, plans, dispositions, validation and shared-budget evidence |
| 2 | `add_records` | Discover and add records | Evidence-backed additions and a bounded, documented search frontier |
| 3 | `causal_graphs` | Review and update causal graphs | Coverage of applicable records, with unsupported representations recorded |
| 4 | `protein_examples` | Add UniProt protein examples | Supported protein examples, especially for gene/protein graph elements |
| 5 | `record_review` | Review all records | Versioned coverage, review report, and structured findings |
| 6 | `resolve_review_findings` | Resolve related review problems | Finding groups linked to real issues, fixes, and validation |
| 7 | `infrastructure` | Implement infrastructure improvements | A plan from `INFRA_TASKS.md`, issue links, implementation, and verification |

Pinned v1 cycles retain their original six goals (v2 stages 2–7 at v1 stages
1–6). Stage 0 still means not started; it is never the issue-triage goal.

Every goal ends with the same publication sequence: validate and commit the
goal-owned changes, push a branch and open a PR, independently review the exact
head, file issues for confirmed problems, fix them, repeat affected validation
and review, merge under the repository's current rules, and delete the exact
merged branches. The supervisor verifies a closure receipt before dispatching
the next goal.

After the final infrastructure goal closes (v2 stage 7; v1 stage 6), the cycle
number increases and the next pinned profile's stage 1 begins.
Cancellation, unresolved prerequisites, uncertain delivery, or failed closure
verification hold progress. They do not silently restart a goal or a cycle.
An inapplicable domain task needs a documented applicability audit; a missing
capability remains blocked until its prerequisite exists.

The record_review goal and the adversarial review of each PR are separate:
record_review can report unresolved record problems for resolve_review_findings. Each PR's
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
must pass validation and publication review. At the infrastructure closure boundary, the
supervisor checks the candidate against the verified closure commit before
activating it. Editing a working file does not change the running goal.

Use the repository's adaptation skill throughout the cycle. Record why a
profile or schema change is needed, its issue, validation evidence, and any
migration impact. Preserve the current native goal and its evidence rather
than relabeling it to fit a new profile.

### Boundary migration from v1 to v2

An in-flight six-goal cycle keeps its immutable effective workflow, native goal,
receipt contract and evidence paths. History retains its old stage numbers;
the ledger records the parent version for each cycle. A candidate v2 profile
does not shift the active stage or insert issue triage into a cycle in progress.
The reviewed `workflow_parent_migration` binds the old and candidate effective
workflow hashes and its review artifact. Only verified closure of the old
infrastructure goal permits activation at the next cycle boundary. Failed
candidate validation or a missing/mismatched migration record holds that
boundary; it does not reset the ledger or rewrite old evidence.

Phase 1 prepares the Claw contract and tests. Merging and publishing a reviewed
release need the maintainer's go-ahead. DUFMech is the phase-3 test repository:
after release, its own session can prepare the new pins, skill and stage-1
profile text, adopt at its next boundary, and demonstrate a complete stage-1
closure. The remaining Mechs follow only after that test. This core change does
not re-pin or change any Mech repository. Infrastructure policy redesign is
separate research in #850; its intake and implementation policy is unchanged.

## Open-issue triage and resolution

Stage 1 of v2 uses the canonical `triage-and-resolve-issues` skill. The existing
`review-open-issues` skill remains read-only advice. The supervisor freezes the
complete open-issue queue at stage entry in `status.json` as `issue_scope`, with
content, SHA-256 and UTC cutoff. The retained inventory records each issue's
number, title, labels and `updatedAt`; structured triage evidence adds severity
and its reason without changing the frozen bytes. Failed pagination or an
incomplete queue blocks the freeze. Later arrivals go to the next cycle's queue.

Every reviewed issue has exactly one of `severity:critical`, `severity:high`,
`severity:medium` or `severity:low`, with a reason based on observed consequence.
Map CellStructureMech's `P0`–`P3` and HabitatMech's `priority: P0`–`priority: P2`
to critical, high, medium and low respectively; preserve the existing priority
labels and reconcile conflicts explicitly. Use the existing standard labels;
create them only if absent in an authorized repository. `rollout:cycle-v2`
marks adoption issues and `claw-delegated` marks delegated Claw work. Neither
label expands the authorized scope.

Group by shared cause or implementation work, retaining stable group IDs,
members, shared cause and issue count. Write one implementation plan per group.
An active group has a real tracking issue with its members linked as sub-issues;
groups are evidence records, not new labels. Deferred groups keep their IDs and
remain visible in the next cycle. Record fixes with PR/commit evidence,
deferrals with reasons, duplicates with surviving issues, won't-fix reasons,
and blockers with prerequisites. A confirmed critical/high issue that cannot
be resolved holds the goal; it is never silently deferred.

Resolve critical and high issues first. Then work the largest one or two
remaining groups, ranked by remaining medium/low issue count, then medium
count, then stable group ID, in one
four-hour wall-clock window per cycle. Codex primary and agy secondary share
that elapsed interval even when working in parallel; it is not four hours per
agent or group, and unused time does not carry over. Record the selection,
start/end and actual work intervals; the deadline is start plus 14,400 seconds.
A deadline stops further deferred
implementation while preserving incomplete work and its disposition; it does
not waive validation or closure gates. An empty eligible frontier is recorded
honestly rather than filled with invented work.

Evidence revisions retain cumulative selected-group and work-interval histories.
A worked group remains counted if it later becomes blocked. New selections
append in ranked order among eligible unselected groups; the cycle-wide union
never exceeds two. Prior intervals and the original clock origins cannot be
erased or retimed by a later report.

The Codex primary owns the freeze, groups, plans, review and acceptance. The
assigned agy secondary implements fixes in separate worktrees. Shared indexes
require coordination, and permission or sandbox-bypass prompts remain the
user's. Required output artifacts are `issue_inventory`, `issue_groups`,
`group_plans`, `dispositions` and `validation`, bound in the versioned goal
evidence. Stage 1 consumes only its frozen queue; the current cycle's review
findings and `INFRA_TASKS.md` retain their existing later-stage owners.

## Review artifacts and cycle history

Review outputs are repository files committed with the goal's changes.
Transient terminal text and an assertion that a review happened are
insufficient. The parent defines an immutable directory for each run, cycle,
stage, and revision, such as:

```text
reviews/workflow/<run_id>/cycle-000001/stage-05/revision-0001/
```

Each revision records scope and coverage, the reviewed source revision, the
report, structured findings with stable identifiers, and the manifest that
binds the artifacts by path and SHA-256. A correction creates a new revision;
it does not overwrite an earlier report. Retain historical revisions and
cross-reference superseded reports. A current-cycle index is a pointer, not a
replacement for the history.

Revision 1 omits `supersedes_evidence`. Every later revision pins the exact
immediately preceding revision by path and hash in that field.
`previous_evidence` separately retains the frozen prior-stage or prior-cycle
source; revising a report does not change that source. Unresolved finding IDs
and artifact bytes must survive both lines of history.

After closure verification, the supervisor writes
`verified-evidence-index.json` in the repository's runtime directory. The
next goal uses that verified pointer to update tracked
`reviews/workflow/latest.yaml` and includes the update in its own publication
sequence. This avoids an uncommitted index change immediately after a merge.

The reviewed source commit can precede the commit that adds the report.
Do not put a report's own eventual commit SHA inside that report: that would
make its identity self-referential. The external closure receipt binds the
committed report bytes to the final reviewed PR head.

The resolve_review_findings goal consumes the exact record_review findings for its cycle. Group problems by
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
The infrastructure snapshot preserves the actual Markdown bytes and structured task
list so a plan cannot silently omit an outstanding entry.

On entry to infrastructure (v2 stage 7; v1 stage 6), the supervisor freezes the actual intake bytes and task
list in `status.json` as `infra_scope`. Copy that frozen input into the evidence
revision and define the implementation scope. Turn related entries into a plan with dependencies, acceptance checks,
and issue links; create missing issues and implement the plan. Newly discovered
work is added to the intake and explicitly carried forward rather than
continually expanding the frozen plan. An empty intake requires a documented
reviewed empty result, not invented work.

The infrastructure evidence binds the intake snapshot, selected tasks, plan, issue
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
