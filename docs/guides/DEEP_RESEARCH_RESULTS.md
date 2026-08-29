# Deep-research result records

The version 1 research-result contract is an audit and persistence
format. It records what was planned, what a provider actually returned, how the
saved artifacts were checked, and which evidence-backed changes may later be
considered by a curator. It is not an execution API, an authorization token, or
a substitute for a Mech's domain schema.

No provider call is needed to scaffold or validate a result. The commands are:

```bash
uv run kg-microbe-research scaffold-result [arguments]
uv run kg-microbe-research validate-result RESULT.yaml --repository-root /path/to/Mech
```

`scaffold-result` creates a dry-run skeleton. `validate-result` reads local
metadata and artifacts. Neither command contacts a provider, probes provider
health, imports a provider client, or consumes provider quota or credits.
Scaffolding needs at least one provider with previously supplied functional
availability evidence for every selected stage; it fails closed when a stage
has none. The cached evidence is used only to construct the audit plan and
dry-run queries, never to make a call. Each profile stage must also declare a
nonblank objective because it is copied into the plan and rendered query.

## Evidence boundary

Deep-research output starts as an untrusted lead. A provider report, extracted
citation, suggested identifier, or proposed YAML edit is not curated knowledge
merely because it was saved in a schema-valid result.

The v1 flow keeps raw capture, evidence assessment, and promotion separate:

1. **Raw capture.** Preserve the question, plan, terminal run, provider report,
   provider-native citation text, and checksums. A `COMPLETED` result with
   `assessment_status: NOT_ASSESSED` is valid and makes no evidence claim.
2. **Evidence assessment.** A named assessor creates per-claim,
   per-source `ResearchEvidence` records against independent
   `SOURCE_SNAPSHOT` artifacts. Bibliographic resolution, topical relevance,
   and support polarity remain separate facts.
3. **Promotion.** A later Mech-specific adapter and curator decide whether a
   proposed change is valid against the target Mech schema and appropriate for
   the corpus. Promotion is a separate validated write operation.

An assessed result may therefore contain well-formed findings while every
proposed change remains `NOT_RUN`. A recorded validator pass is audit data, not
independent certification. Research-result validation never applies a change
and never certifies the resulting domain record.

## Record structure

`ResearchResult` is the LinkML tree root. Its supporting classes include:

- `ResearchQuestion` for the exact research question, caller-declared target
  metadata, and target-byte snapshot;
- `ResearchPlan`, the complete provider-evaluation matrix, and ordered eligible
  stage assignments for the focus and triage result;
- `ResearchProviderEvaluation` for every catalogue provider at every stage,
  including its observed status and reason, fit, cost, billing, and
  policy-admission facts;
- `ResearchRun` for the requested provider, actual provider, status, rendered
  query, timestamps, task identifier, and cost or budget facts;
- `ResearchArtifact` for checksum-addressed content: embedded immutable profile
  and target inputs, plus path-backed reports, sources, and validation output;
- `ResearchCitation` for lossless provider-native text plus optional normalized
  identifier-resolution provenance;
- `ResearchEvidence` for a named, timestamped claim-to-source assertion,
  snippet or non-text locator, relevance, and support polarity;
- `ResearchFinding` for the aggregate disposition of linked evidence;
- `ProposedChange` for an unapplied, evidence-linked curation suggestion; and
- `ResearchResult` for the complete terminal snapshot.

Each result declares its schema version and assessment state. Identifiers within
the result are unique, and references between runs, artifacts, citations,
evidence, findings, and proposed changes must resolve exactly once.

The rendered query is saved exactly as submitted and is bound to its SHA-256
digest. The result also records the selected focus, caller-declared target
identifier, label and type, research-profile digest, and other reproducibility
facts required to understand how the query and plan were produced. Generic v1
validation checksum-binds the exact target bytes and rerenders the declarations
into every query; it does not infer or certify those declarations from the
domain file. That requires a future Mech-specific target adapter.

## Plans are not execution authority

A saved plan is historical evidence. For every stage it records a complete,
deterministically ranked `provider_evaluations` row for every canonical
catalogue provider, including providers excluded because they were blocked,
unavailable, configured-only, stubs, or outside current policy. The separate
`stage_assignments` list retains only policy-eligible providers in execution
order, including fallbacks. Both structures are bound to the versioned
catalogue and triage-contract digests. Status reasons and configuration-context
labels must remain non-secret; credential values and secret configuration are
never retained. Loading a saved plan must never authorize a provider call.

Provider availability can expire, configuration can change, a provider can
become blocked, and billing policy can change after a record is written. An
executor must therefore build a fresh in-memory triage plan and pass the current
execution-policy gate immediately before any future call. It must not deserialize
a `ResearchPlan` into the private policy object or reuse a prior authorization
decision.

The record distinguishes:

- the canonical provider requested by the plan;
- the provider that actually handled the run, when there was a call;
- an explicit provider override and its reason; and
- the provider-status snapshot observed for the run.

Requested and actual providers must not be silently collapsed. In the policy
CLI, explicitly naming any eligible provider other than the recommendation also
requires `--override-reason`; normal runtime fallback is represented only after
the preceding higher-ranked attempt failed or was unusable. A triage or
allowlist override can be recorded, but no record can make an override waive
`--no-paid`, provider status, usage acknowledgement, or a cost ceiling.
Historical provider status is an audit snapshot, not a claim that the provider
is available now.

Archive validation accepts only explicitly retained `(version, digest)` pairs
for the provider catalogue and triage contract. Recorded cost, billing, and
status facts are validated internally rather than silently replaced with the
current catalogue. When either contract evolves, maintainers must retain the
older pair and immutable v1 vocabulary or introduce a result-schema migration.

## Terminal, append-only persistence

Version 1 records are terminal snapshots and are written once under a
collision-resistant result identifier. The public writer has no overwrite
mode. Corrections use a new record with the prior result's ID,
repository-relative `supersedes_path`, and `supersedes_sha256` alongside
`supersedes_result_id`. Later assessment of a raw capture uses
`assessment_of_result_id`, `assessment_of_path`, and `assessment_of_sha256`.
When external artifacts are verified, each relationship must resolve to an
older strict, schema-valid, checksum-matching result and may not create a direct
cycle. Version 1 verifies the current record's immediate relationships and
direct reverse links; it does not recursively attest every ancestor in a
transitive lineage chain.

An `assessment_of` result is an immutable projection of a raw `COMPLETED` or
`PARTIAL` capture: it preserves lifecycle status, plan, and every run exactly,
preserves the exact set of provider-native citation IDs and every prior citation
field, and preserves every prior artifact exactly. It may enrich an existing
citation through checksum-bound resolver provenance and add only source,
reference-validation, evidence-assessment, or proposed-change artifacts. It
cannot append provider output or silently rewrite the provider record it is
assessing. `supersedes` expresses correction lineage and does not imply that the
two payloads are otherwise equal.

The supported terminal outcomes distinguish at least:

- `DRY_RUN`: a complete plan and rendered query were captured, and no provider
  was called;
- `COMPLETED`: the final run for every planned stage completed and every
  completed run has a non-empty primary report; recovered earlier failures do
  not make the overall result partial;
- `PARTIAL`: every planned stage has a live terminal outcome, with at least one
  final completed stage and at least one final failed or unusable stage;
- `FAILED`: at least one live attempt actually failed and no usable result is
  claimed; and
- `UNUSABLE`: at least one stage's final run is unusable; that provider output
  is checksum-preserved but barred from evidence, findings, and proposed
  changes.

A completed raw capture may have no findings. A completed assessment that found
no support uses `NO_EVIDENCE` evidence assertions and a `NO_EVIDENCE` finding,
so the checked sources and search outcome remain auditable.

A dry-run skeleton contains no fabricated task identifier, charge, citation,
finding, provider output, or proposed change. Empty evidence collections mean
that research has not occurred, not that evidence was checked and found absent.

Authorization is deliberately not a durable lifecycle state. A recorded policy
decision is audit information only and cannot be replayed. Future support for
running-task journals or recovery events must use a separate append-only design
rather than weakening terminal v1 records.

## Validation contract

Saving a result requires both LinkML validation and semantic validation. LinkML
checks the governed shape, required slots, ranges, enums, and cardinalities.
Semantic validation enforces relationships that cannot safely be reduced to
independent field types.

The semantic gate fails closed on, among other things:

- duplicate or unknown keys, unsupported schema versions, unknown providers,
  provider aliases where canonical names are required, and non-finite numbers;
- duplicate identifiers, dangling references, duplicate stage positions, or a
  run whose stage and provider do not agree with its plan;
- status contradictions, such as a dry run with a provider task identifier or a
  completed run without a primary output artifact, a completed result missing a
  planned stage, or a failed result without a failed live attempt;
- missing or reversed timezone-aware timestamps;
- malformed digests, query/config checksum mismatches, artifact size or digest
  mismatches, and a claimed evidence snippet that is absent from the referenced
  cached source;
- absolute, escaping, ambiguous, or non-normalized artifact paths; and
- evidence that uses a provider `REPORT` instead of an independent
  `SOURCE_SNAPSHOT`, a normalized citation without resolver provenance, or a
  claim assertion without assessor and assessment time; and
- a text assertion whose exact snippet is absent from its source, or a non-text
  assertion without both a locator and assessment artifact; and
- raw captures containing assessment/change-only artifacts, resolved citation
  metadata without verified resolver provenance, or proposed changes whose
  retained patch or domain schema is empty.

Validation of committed artifacts is rooted explicitly at the Mech repository.
External artifact paths use normalized repository-relative POSIX syntax.
Absolute paths, `..`, backslashes, URL-shaped paths, and paths that traverse
repository-internal symlinks are rejected. With artifact verification enabled,
the validator compares each external file's byte size and lowercase SHA-256
digest with the actual bytes.

Every v1 record embeds canonical base64 for the exact plan-bound `PROFILE` and
`TARGET_SNAPSHOT` input artifacts; those two artifact IDs cannot use an
external path. Their canonical encoding, size, and digest are checked on every
validation, even when external artifact verification is disabled. The embedded
profile is always parsed and replayed to bind the Mech, focus label, evidence
policy, source priorities, stage order/objectives, complete provider rankings,
and all rendered queries to the historical input. `--verify-snapshots` has the
narrower capture-time purpose of comparing the current profile and target
files—and the current domain-schema and update/delete target files for proposed
changes—with their retained bytes, or checking CREATE target nonexistence.
Without that flag, a self-consistent old record remains valid after an
intentionally versioned source file changes.

On supported POSIX systems, external reads open each repository-internal path
component relative to directory descriptors with no-follow semantics. The
append-only writer requires POSIX `dir_fd` and `O_NOFOLLOW` support, publishes a
new inode without replacement, and refuses an existing destination. The
resolved repository root and its parent remain a trusted boundary: callers
must not concurrently rename or replace the real repository directory across
the complete validate-then-publish operation.

A checksum detects byte drift relative to the record; it is not a signature or
proof of who produced the bytes. Git review and repository provenance remain the
trust boundary.

## Artifact and reference integrity

The schema stores typed, allowlisted provenance rather than copying an entire
provider response into an arbitrary metadata object. A result must not contain
credential values, request headers, process environments, provider tokens,
hidden model reasoning, chain-of-thought, or unrestricted agent-state traces.
Provider-specific material that is safe and useful may be retained as a typed
artifact with an explicit path and checksum.

Citations preserve provider-native reference text losslessly. A normalized
identifier such as a PMID, DOI CURIE, accession, or HTTPS URL may be added only
with a checksum-addressed `REFERENCE_VALIDATION` artifact, named resolver, and
validation time, all bound to the citation's run. Identifier resolution still
does not show that a source bears on a claim.

That relationship lives in `ResearchEvidence`. Every evidence assertion names
one finding, one completed run, and an independently obtained
`SOURCE_SNAPSHOT`; when it also names a citation, the normalized citation and
source identity must agree. Text evidence uses `EXACT_TEXT_MATCH`, and the CLI
checks whitespace-normalized snippet membership against UTF-8 source bytes.
Figures, tables, datasets, accessions, sequences, and structures use a non-text
verification method, a precise locator, and a retained assessment artifact.
The assessor and assessment time are mandatory in both cases.

Every assessed result declares an `assessment_scope`. `ASSESSED` means complete
only within that explicit boundary. `PARTIALLY_ASSESSED` additionally records
one or more `assessment_limitations`; raw `NOT_ASSESSED` captures may claim
neither field. Claim-assessment details use `EVIDENCE_ASSESSMENT` artifacts,
kept distinct from bibliographic `REFERENCE_VALIDATION` output and bound to the
same run as the evidence assertion. A `NO_EVIDENCE` assertion still requires an
on-topic source: an off-topic source cannot establish that an on-topic search
found nothing.

These are auditable assertions, not signatures. A malicious author could lie
about an artifact role or assessor. Byte verification, Git provenance, and
human review remain the trust boundary. Calling `validate_result()` with
both `verify_artifacts=False` and `verify_snapshots=False` skips path-backed
artifact reads and checksum-bound lineage resolution, but validation
still verifies embedded input bytes and all profile, query, reference,
lifecycle, and semantic invariants. The CLI and public writer verify path-backed
artifact bytes and lineage by default.

Actual cost may be absent when a provider does not report it. Missing cost means
unknown, never zero. The provider's billing class, relative cost tier, caller's
budget decision, and provider-reported charge remain distinct fields.

Proposed changes reference exact `PATCH`, `DOMAIN_SCHEMA`, and, for an update or
delete, `TARGET_SNAPSHOT` artifacts. An attempted check records its command,
time, message, and `DOMAIN_VALIDATION` output. The status names
`RECORDED_PASS`, `RECORDED_FAILURE`, and `ERROR` deliberately describe captured
provenance; Phase 3's separate validated-write adapter is responsible for
rerunning domain validation before any mutation.
At capture time, snapshot verification also requires the current domain-schema
path and update/delete target bytes to match the retained schema and pre-change
artifacts.

## Fleet-specific focus

The result schema and validation method are shared by every Mech. Research
focus remains domain-owned:

- CultureMech investigates culturing media, growth evidence, and formulation;
- TraitMech investigates microbial trait definitions, scope, and evidence;
- MediaIngredientMech investigates ingredient identity, formulation, roles, and
  ontology grounding;
- CommunityMech investigates community composition, interactions, environment,
  and evidence; and
- ProteinTraitsMech investigates sequence, structure, mechanism, and
  protein-trait evidence.

Each Mech continues to own its research profile, prompt content, target
resolution, and eventual domain validation. Shared result records preserve the
selected local focus and profile digest rather than replacing those differences
with a fleet-wide generic prompt.

## Future scope

Version 1 does not provide a provider command builder or executor, an executable
mock provider, live provider availability checks, domain target adapters,
schema-validated promotion, or migrations of the five existing Mech runners and
historical Edison sidecars. Those are later integration steps. Until they land,
the result contract must not be described as enforcing the behavior of existing
runners or making legacy Markdown and metadata schema-compliant retroactively.
