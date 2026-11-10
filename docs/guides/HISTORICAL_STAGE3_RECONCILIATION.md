# Historical protein-example boundary

The version `2.0.0` operator record supports only the pinned parent v1 transition
from stage 3 `protein_examples` to stage 4 `record_review`, with one completed
historical receipt PR and between two and sixteen separately directed PRs under
one later completed native goal. It extends the held-boundary machinery in
[historical goal reconciliation](HISTORICAL_GOAL_RECONCILIATION.md). Version
`1.0.0` records retain their separate review-remediation-to-infrastructure
contract and single external PR. Neither format is a general mismatch override.

The NaturalProductMech case motivates this protocol: historical C4S3 belongs to
PR #1054, while PRs #1057 and #1062 belong to the separate chelator goal. Their
merge is not acceptance of C4S3. The existing receipt's acceptance findings must
be audited truthfully; open findings, missing review or evidence, unpublished
commits, or missing cleanup still stop the ordinary verifier. A later audit
correction must retain its own provenance, never be attributed to an old PR.

## Closed record and native corroboration

All common version-1 record fields remain required except `external_pr`, which
version 2 forbids. Version 2 additionally requires:

| Field | Contract |
| --- | --- |
| `transition` | Exactly `v1_protein_examples_to_record_review` |
| `native_proof_mode` | Explicit `checkpoint_before_external` or `retained_public_attestation`; no automatic fallback |
| `parent_version` | Exactly `1.0.0`; actual pinned stage keys and parent are also checked |
| `stage` | 3 for historical closure; 4 for separate boundary release |
| `required_infra_tasks` | Empty; this transition cannot freeze infrastructure scope |
| `external_prs` | Ordered list of 2–16 distinct external PRs; no historical receipt member |

Each external item is closed to `number`, `head_sha`, `merge_commit_sha`, `branch`,
`goal_identity`, and `native_statement`. The identity must equal the separate
`current_goal_identity`. The statement contains only `step_index` and the
SHA-256 of the original full public text (`text_sha256`). The reader requires an
actual completed assistant-public terminal-completion message after that native
declaration. User text, tool output, ordinary replies, hidden reasoning, a hash
from another step, and joined lines cannot supply it.

One real source line must associate the exact PR number, full 40-character merge
SHA and exact branch. It may use the canonical same-repository pull URL or an
explicit `PR #N` label. The latter accommodates preserved native completion
summaries that contain no URLs. Multiple PR numbers or commit candidates on one
line, prefix matches and conflicting repository/issue URLs refuse. The hash
always covers the original full text, not a reformatted excerpt.

This is corroboration of an independently reviewed operator attribution, not
automatic interpretation of scientific acceptance. Fresh GitHub checks bind
each number to its actual repository, default base, branch, head and merge.
Creation must follow the external native goal start; creation and merge must be
ordered and precede the assessment. Every merge must be in the default checkout;
the list's merge times and ancestry must establish its order. Missing or changed
facts fail closed. Both modes require the exact currently completed idle goal,
retained old completion, public terminal evidence and distinct ordered identities.

`checkpoint_before_external` retains the original strict native proof: a completed
old checkpoint before exactly one later done declaration. It refuses the retained
NPM case, whose older declarations/completion rows are cleared and whose first
retained old-goal checkpoint follows the external declaration.

`retained_public_attestation` is a separate, explicitly selected reviewed human
attestation. It requires every row index from the original historical declaration
through the current last step exactly once; matching row/payload type and status;
the original SYSTEM declarations and their original creation timestamps matching
both identities; completed public terminal payloads with original created and
completed timestamps inside their proper native goal intervals; and a latest
done checkpoint retaining the historical completed state. It examines all retained
statuses for intervening declarations, cancellation, conflicting checkpoints or
post-completion resumption. Missing rows/timestamps, unsupported shapes, altered
hashes and ambiguous histories refuse. Current external completion statements
still must be actual done public events.

Cleared rows remain labelled cleared. Their original public completion metadata
corroborates chronology; a later checkpoint proves retained state, **not the
earlier completion time**. Contiguous row indices cannot restore discarded
checkpoint fields or prove unretained intermediate state. The exact record and
independent reviewer must explicitly accept that limitation. This mode never
falls back from a failed strict proof and never infers task acceptance from
completion prose, which can itself contain inaccurate claims. Ordinary receipt
and issue acceptance remain separate mandatory gates. No historical timestamp
is invented or promoted to an acceptance timestamp.

## Effects and gates

Use the same reviewed implementation pins, record digest, independent review,
maximum 24-hour validity, exact live fingerprints, STOP requirement, supervisor
lock and input lock as the version-1 command. A draft is non-executable even if
all available fingerprints are populated. Shape validation is not live
eligibility. Keep unresolved acceptance or deployment requirements in
`prerequisites`; a reviewed record cannot carry them.

Historical closure accepts only an ordinary completed **single-PR** receipt.
It reuses the normal exact-head review, issue/fix, CI, evidence, infrastructure
notebook, publication and branch-cleanup gates. It does not accept `no_changes`
or reinterpret the external PRs as ordered historical receipt members. Existing
actions, old closures, native identities, workflow pins, registries and repair
budgets are retained. Ordinary advance closes exactly the historical stage and
holds C4S4 (or the corresponding cycle's stage 4) without sending input, freezing
infrastructure intake, or crediting the external work as another stage.

The audit retains the entire ordered `external_pr_verifications` list, with
native identity and statement fingerprints for every PR. The separate release
record must preserve the protocol/version, explicit native proof mode and the entire ordered list. It also
sends nothing. A later, separately authorized supervisor dispatch must pass
readiness, current native identity, prompt/composer, input-lock and duplicate
delivery checks. Only actual acceptance of a new native goal consumes the held
boundary. A PR, record draft, transport success or old goal repeating a marker is
not acceptance. Chemistry backlog implementation and any deviation from the
pinned next stage require their own authorized workflow decision.

## Preparation and application

1. Audit historical issue acceptance, exact review provenance, native history and
   all ordinary receipt gates. Keep later corrective work separately attributed.
2. Review and merge the prerequisite reconciliation implementation and this
   extension only with separate authorization. Rebase/integration-test against
   the then-current main and independently review the final combined head.
3. Prepare deployment outside active checkouts, validate all readers of retained
   boundary records, and obtain the separate deployment approval. Refresh only
   reviewed pins through the documented lifecycle workflow.
4. With separately approved lifecycle control, stop the supervisor, retain STOP,
   prove its process has exited, and check exclusive supervisor/input ownership.
   Re-capture every byte/native fingerprint and current source/review digest.
   Verify idle process binding, an empty composer and no prompting or queued
   work without sending input. A warning or changed stream ownership holds.
5. Back up exact configuration, ledger, completion receipt, PR registry, pinned
   workflow artifacts, relevant review/validation evidence and retained operator
   audit directories with a manifest. Create a new immutable reviewed record;
   never edit the prior draft into authority or invent acceptance timestamps.
6. Obtain approval of that exact record's byte digest. Run the read-only command
   first; apply only the separately approved matching digest. Auxiliary outputs
   remain append-only, and atomic ledger replacement is the commit point.
7. Verify one historical closure with its original identity, held next stage,
   both external PR identities, unchanged action/budget/history/registry bytes,
   no sends and preserved STOP. Recheck progress readers before any restart.
8. Boundary release, supervisor restart and any future chemistry dispatch are
   separate decisions with fresh evidence and actual native acceptance.

Use the existing command's `--validate-record` to inspect drafts. Do not run an
application against live state during preparation. On any failed write, keep
STOP and all journals and assess the commit point. No automatic rollback of a
committed ledger, reset, budget repair, release or downgrade is permitted. A
reader predating version 2 cannot release its retained boundary; an older
deployment must remain stopped until compatibility is reviewed.
