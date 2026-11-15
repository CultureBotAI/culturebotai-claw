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

Parent v2.0.0 added issue triage before discovery. Parent v2.1.0 extends that
same first goal with open-PR maintenance and keeps all seven stages. The stable
stage key determines the work; numbers are meaningful only with that cycle's
pinned parent version.

| v2 stage | Stage key | Goal | Required result |
| --- | --- | --- | --- |
| 1 | `open_issue_triage` | Maintain open issues and PRs | Frozen issue inventory, groups, plans, dispositions and budget; parent 2.1 also requires frozen PR inventory and dispositions |
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
merged branches. Parent 2.1 additionally requires owned-feature-worktree
deletion after preserving valuable state and audit evidence. The supervisor
verifies a closure receipt before dispatching the next goal. Existing per-PR
authority still applies: a green check does not grant merge permission, and
previously granted authority need not be requested again. A genuine missing
approval or approval-review refusal remains an evidenced blocker.

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

### Version compatibility and boundary migration

Parent 2.1.0 uses additive LinkML schema version 2.0.0. New policy/result classes
and artifact kinds are optional in the schema so archived parent-2.0 records
remain readable; the semantic validator requires them when parent_version is
2.1.0. Removing the PR policy cannot disable maintenance. Parent 2.0 remains
available as `mech-cycle-v2.0.yaml` with its original stage-one outputs and
closure steps. Preserve older hash-pinned schema bytes as well as parent bytes;
an additive change does not justify replacing a consumer's installed pin.

An in-flight six-goal cycle keeps its immutable effective workflow, native goal,
receipt contract and evidence paths. History retains its old stage numbers;
the ledger records the parent version for each cycle. A candidate v2 profile
does not shift the active stage or insert issue triage into a cycle in progress.
The reviewed `workflow_parent_migration` binds the old and candidate effective
workflow hashes and its review artifact. Only verified closure of the old
infrastructure goal permits activation at the next cycle boundary. Failed
candidate validation or a missing/mismatched migration record holds that
boundary; it does not reset the ledger or rewrite old evidence.

The same reviewed boundary mechanism applies to parent 2.0.0 → 2.1.0. That
migration changes stage-one maintenance and closure evidence, without changing
stage numbers. The active cycle retains its old parent, schema and frozen
inputs until verified infrastructure closure. Historical release manifests,
receipts and report bytes remain immutable.

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

## PR maintenance under parent 2.1

At stage-one entry the supervisor separately freezes the complete open-PR queue
as `pr_scope` in status. Its JSON content, SHA-256 and UTC cutoff bind both drafts
and non-drafts, head/base SHAs, branch names, update time, mergeability and check
facts. PR and issue cutoffs may differ. Paginated reads and a complete inventory
readback must agree; moving heads or partial responses hold capture. Zero checks
or unknown/incomplete check facts cannot establish green.

Copy those exact bytes to the `pr_inventory` artifact. The structured
`pr_maintenance` result binds `frozen_at`, `inventory`, `dispositions`,
`shared_check_fixes`, `open_non_draft_limit`, `limit_source` and
`remaining_open_non_draft`. The `pr_dispositions` JSON artifact is exactly
`{"pr_maintenance": <that result>}`. Even an empty queue needs both artifacts.
Each later evidence revision preserves the original inventory, cutoff and limit.
Each frozen PR needs exactly one disposition with its original `head_sha`, a
reason and supporting evidence references:

| Status | Required meaning |
| --- | --- |
| `merged` | Exact `final_head_sha` and `merge_sha`, with that PR included in the independently verified full closure receipt |
| `closed_superseded`, `closed_duplicate` | A reason and a distinct same-repository replacement PR that remains open or is merged |
| `closed_stale` | A draft idle at least fourteen days at the cutoff, measured from `updatedAt` |
| `closed_conflicting` | An observed conflict and preserved follow-up scope |
| `refreshed` | A changed `final_head_sha`, updated without force-push, still requiring live assessment before closure |
| `retained` | A reasoned open disposition; unavailable for frozen green, stale or conflicting PRs |
| `blocked` | An explicit prerequisite and evidence; holds the goal rather than claiming closure |

Take every green PR through independent exact-head review, real findings issues,
fixes, re-review, checks, normal merge and branch/worktree cleanup, unless a
justified stale/superseded/duplicate/conflict closure applies. Batch preparation
never substitutes for review of each exact head. Preserve all existing approvals
and holds. A retained or refreshed PR that becomes green or conflicting before
closure requires further action or an explicit blocked result.

Backlog PRs can predate the maintenance goal. Keep their original ownership and
goal associations intact. The parent-2.1 stage-one allowance applies only to
the exact frozen inventory/disposition members: frozen-to-final head ancestry
accounts for older commits, while actual merges occur during this goal and
remain on the default branch's ancestry. New integration PRs still use normal
current-goal registration. This allowance never replaces review or checks.

A check failing on strictly more than half of all frozen PRs, including drafts,
requires one source-level disposition with its exact affected PR numbers. Record
`source_repository`, a real `source_issue_url`, evidence and either a merged
`source_fix_pr_url` or a blocked prerequisite. Both URLs must bind that source.
The supported source is the consumer or canonical
`CultureBotAI/culturebotai-claw`; another owner's dependency remains blocked
rather than implying mutation authority. A source issue may remain open for
broader work. The live verifier checks that each claimed fixed source PR merged.

The per-Mech manifest may set `open_pr_limit` from 1 to 1000; otherwise the
non-draft limit is 25. Claw's control-plane queue uses 25. The supervisor freezes
the resolved value and `limit_source` (`default` or `manifest`) with `pr_scope`.
Read the complete live queue before opening or readying another PR and include
later arrivals in `remaining_open_non_draft`, without inserting them into frozen
membership. Do not turn a ready PR into a draft to evade the limit. The final
live number list must match evidence and fit the frozen limit; otherwise closure
holds. A later manifest edit affects a later cycle, not this frozen scope.

Before deleting an owned feature worktree, preserve review outputs, ignored
valuable work and other needed state outside that worktree. Retain a hashed
cleanup audit identifying repository, reviewed head, branch, owned absolute
worktree paths and preservation manifest. Retain that manifest's actual bytes
and hash, including an ignored-inclusive inventory and retained-item hashes
and locations. Bind `worktree_paths` and
`worktree_cleanup` in the supplied closure receipt. The supervisor verifies audit
bytes, filesystem absence and removal from Git's worktree registrations. Do not
force removal, delete another owner's work, remove configured checkout/runtime
roots, or discard evidence to satisfy cleanup.

The cleanup audit is a JSON object with `repository`, `head_sha`, `branch`,
`worktree_paths`, `preservation_manifest_sha256`, and `preservation_manifest`.
The latter is an `artifact`/`sha256` descriptor; its digest must equal
`preservation_manifest_sha256`. The referenced JSON manifest contains
`inventory_includes_ignored: true`, the same `worktree_paths`, and
`retained_files`, a list of `artifact`/`sha256` descriptors. Each retained file
or recovery archive is read back. An empty list is valid only when the reviewed
inventory found no valuable untracked/ignored files to retain. Audit, manifest
and retained artifacts must remain regular files within the configured retained
repository or supervisor evidence root; symlink escapes are rejected.

This extension prepares the contract; release, Mech adoption and runtime
activation remain separate operations. It does not by itself complete the wider
batch-review, approval-refusal or fleet-rollout work tracked in #1230, #1248 and
#849. Neither the issue group's four-hour window nor an aging PR waives closure
or authorization requirements.

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
