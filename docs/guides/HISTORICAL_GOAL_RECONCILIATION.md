# Historical goal reconciliation

`mech_goal_reconcile.py` supports a narrow, explicit operator assessment when a
completed review-remediation goal was followed by one separately directed,
completed native goal. It preserves the old goal identity for closure and records
the external goal separately. It neither observes a terminal nor sends input.
This is not a replacement for an ordinary receipt or permission to skip a goal.

**DUFMech is not yet eligible.** Its historical ordered #365/#367 receipt and its
later #455 infrastructure intake cannot currently satisfy the same final-head
notebook gate. [Claw #1005](https://github.com/CultureBotAI/culturebotai-claw/issues/1005)
tracks that distinct prerequisite. The negative regression reproduces this
chronology; the positive fixture is explicitly synthetic and has its required
intake already present in the verified closure head. Do not register #455 under
the old goal, or claim this identity reconciliation resolves that artifact gap.

## Authority and scope

The private JSON operator record is a human attestation, not a cryptographic
signature. The caller must obtain approval for its exact byte SHA-256 and an
independent review of the same substantive record. Implementation and review
artifact digests prevent substitution; they do not establish that a person
actually approved the record. Never publish native identities, repository paths,
or raw native evidence in GitHub issues, PRs, or public progress data.

The closed version `1.0.0` record has these fields:

| Fields | Meaning |
|---|---|
| `operation`, `record_status` | `close_historical_goal` or `release_boundary`; `draft` or `reviewed` |
| `assessed_at`, `expires_at` | Timezone-aware timestamps, at most 24 hours apart |
| `requested_by`, `reason` | Responsible operator and factual rationale |
| `repository_key`, `run_id`, `cycle`, `stage`, `parent_version`, `workflow_sha256` | Exact retained workflow context |
| `historical_goal_identity`, `current_goal_identity` | Separate exact conversation/start time/start step identities |
| `fingerprints` | SHA-256 of configuration, ledger, completion, PR registry, actual infrastructure notebook, and canonical native evidence |
| `required_infra_tasks` | Nonempty task IDs required in the current committed notebook before its scope freezes |
| `external_pr` | Number, head SHA, merge SHA of the separately directed merged PR; receives no historical stage credit |
| `review` | Different reviewer, relative artifact path, artifact SHA-256 |
| `prerequisites` | Explicit unmet requirements, allowed only on a draft |
| `reconciliation_sha256` | Null for closure; exact prior canonical assessment digest for release |
| `implementation_commit`, `implementation_sha256` | Clean deployed source commit and the five paths in `IMPLEMENTATION_PATHS` |

`fingerprints` uses the exact keys defined in `FINGERPRINTS` in
`kg_microbe_workflows.reconciliation`; the registry filename is
`pr-associations.jsonl`. Native proof and assessment IDs use the existing
supervisor canonical JSON digest (`json.dumps(..., sort_keys=True)`); all file
fingerprints and `--approved-sha256` hash raw bytes. Drafts may have missing
implementation/review/fingerprint values and can only be shape-validated. Never
turn a draft into an approved record by filling guesses or copying stale hashes.

## Supported sequence

Prepare a durable private record and review artifact under the workspace or
`~/agent-work/claw/`, never a temporary directory that can be purged. Use the
reviewed deployment's interpreter and script. The following commands illustrate
the interface; substituting real paths or approving the operation is separate
operator work:

```bash
uv run python scripts/mech_goal_reconcile.py --record "$RECORD" --validate-record
uv run python scripts/mech_goal_reconcile.py --config "$CONFIG" --record "$RECORD"
```

The second command is read-only. It validates fresh native evidence, all recorded
fingerprints, the independent review, the deployed clean implementation, and the
normal ordered receipt. It also reuses the supervisor’s pinned profile, retained
legacy inputs and immutable workflow snapshot checks without eager writes;
matching snapshots remain untouched. Native proof requires an old completed checkpoint before
exactly one later declaration, terminal public completion evidence on both sides,
a latest checkpoint retaining the old completion, and the exact completed idle
current goal. Ambiguous, active, cancelled, resumed, or additional goals refuse.

For a separately authorized application, stop the supervisor through its normal
monitor control, leave its `STOP` file present, and renew the evidence and record
if any bound bytes changed. The script acquires the existing supervisor lock and
that session's input lock before validation and refuses a running supervisor or
concurrent input owner. It does not stop any service itself.

```bash
uv run python scripts/mech_goal_reconcile.py --config "$CONFIG" --record "$RECORD" \
  --apply --approved-sha256 "$APPROVED_RECORD_SHA256"
```

The closure operation reuses ordinary issue/fix/review/validation/branch cleanup,
ordered member attribution and versioned artifact verification. It freezes the
actual committed notebook through ordinary `advance`, retains prior actions and
closures, closes exactly the historical stage, and records an explicit held
next-goal boundary. It adds no completion for the external goal or next stage,
and does not alter any PR registry or other session. The global STOP remains.

Release is a **second separately approved record** with operation
`release_boundary`, stage equal to the new infrastructure stage, refreshed exact
fingerprints, and the prior reconciliation digest. It must preserve the same
historical/current identities, workflow, external PR and required intake IDs.
Apply it through the same interface and locks. Release sends nothing. After an
independently authorized supervisor start, normal dispatch still rechecks the
live process, terminal readiness, exact current identity, native completed state,
skills, workflow, input lock and duplicate-delivery guards. Only a new native
goal with the sent marker and a later identity consumes the boundary; the old
closure and reconciliation audits remain retained. A held boundary cannot be
consumed by an existing external goal repeating a marker.

## Commit point and recovery

The writer prepares and validates everything before any mutation. Append-only
receipt, frozen-scope and audit artifacts are written with a recovery journal;
the single atomic ledger replacement occurs **last** and is the authoritative
commit point. The immutable audit records `prepared` and the expected canonical
ledger digest; only a matching committed ledger proves application, and the CLI
returns `applied` only after that replacement succeeds. This is not a multi-file filesystem transaction. Fresh fingerprint
and native-proof checks run before auxiliary writes and immediately before the
ledger replacement. A changed fact or write failure retains the old ledger and
STOP; partial auxiliary files are evidence for reviewed recovery, not authority
for closure. The CLI never removes them, resets a ledger or retries by force.

An exact completed operation is idempotent while its reviewed record and source
remain valid: it returns `already_applied` without modifying files. An interrupted
operation with auxiliary files but no ledger commit refuses append-only path
collisions. Preserve the journal and files, assess the actual ledger commit point,
and obtain a specific recovery plan; do not hand-edit ledger fields or restore a
stale bundle. After a successful closure, reverting the runtime ledger would
retract published progress and is not an automatic rollback. Revert code only
while the supervisor remains stopped and after assessing whether the deployed
reader understands the retained reconciliation boundary.
