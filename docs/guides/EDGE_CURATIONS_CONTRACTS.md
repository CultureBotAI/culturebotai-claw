# EdgeMech shared contract decisions

Reviewed on 2026-11-07 for [#766](https://github.com/CultureBotAI/culturebotai-claw/issues/766)
and [#767](https://github.com/CultureBotAI/culturebotai-claw/issues/767), against CLAW
`c26f3a0906916f9641a5f82b004b5541ae5fbe52`. The existing identity, curation bundle,
and RecordReview contracts remain authoritative. The new contracts describe
storage transport and inherited native assertions; neither grants scientific
approval or permission to publish.

## Pinned existing semantics

| Existing contract | Pin / digest |
| --- | --- |
| Identity | `kg-microbe-curation/v1`; `src/kg_microbe_curation/identity.py` SHA-256 `9c760f3e82051d24b3c1cc79d787e96b35e24529b4ead9254ff55adc1266b948` |
| Bundle schema | `src/kg_microbe_curation/schema/bundle.json` SHA-256 `04db51cdeebf19b36d68ea8dae88ebabb9910e8f4eb03e31aff8d46f2902fb5e` |
| Bundle validation | `src/kg_microbe_curation/contract.py` SHA-256 `d9eb93add3fbb438cbd6008767b28a0c4eadfbc03688462d490c965ff034268e` |
| RecordReview | `1.0.0`; canonical validator SHA-256 `95a4ec41e38ec47ba3578e76838c46a0adbf47e49ad3636524735d08cfcb1c4d`; canonical schema SHA-256 `229baf9b69118a1fe318e4c31085c0820e4e3d1365e7b04d6ace451b7c35f9bb` |

An occurrence identifies one exact source row, binding the release manifest,
member name and digest, one-based data-row position, and digest of the original
row including its terminator. Migration must preserve CRLF and unterminated
final rows when present. Two identical triples at distinct source positions
remain distinct occurrences.

Native observation identity, the curation observation fingerprint, biological
context, interpreted claim, and occurrence identity remain separate. Canonical
JSON preserves scalar types, Unicode, string whitespace, and array order; it
does not normalize biology. Required interpretation pins describe the lexical
interpretation separately from biological context.

`retain` and `amend` still require canonical scientific RecordReview coverage
of the exact occurrence decision and claim digests. A deterministic reviewer
cannot set `scientific_review: true`. A native approval of a record or mapping
does not establish a new scientific review of a KG occurrence.

## External generation manifest

`kg_microbe_curation.artifact.ARTIFACT_CONTRACT` is
`kg-microbe-curation-artifact/v1`.
`validate_artifact_manifest(document)` validates the packaged
`schema/artifact.json` plus accounting and portable path constraints. It is a
pure validator; it does not open partition files or authenticate source bytes.

The root contains `contract`, `identity_contract`, `generation`,
`parent_manifest_sha256`, `source`, `layout`, `tables`, `counters`, and
`assurance`. Unknown fields fail. Generation is a bounded token; the parent is
null for the first generation or the SHA-256 of the preceding manifest bytes.

`source` binds the input export manifest, original release manifest, edge
member name and digest, source SQLite file digest (null for a direct import),
ledger revision, selected and total source row counts, and whether the export
is complete. The edge member digest is essential: the SQLite occurrence rows
alone do not contain enough provenance to reconstruct their occurrence IDs.

`layout` pins `sha256-first-key-modulo/v1`, a bucket count in 1–4096 and row-group
size in 1–10,000,000. The required tables are:

- `occurrences`, `current_decisions`, `bundles`, `metadata`, `coverage_counts`:
  preserve the SQLite values and original canonical bundle documents.
- `observations`, `claims`, `reviews`, `evidence`, `memberships`, `history`:
  indexed projections with explicit bundle-digest bindings. These projections
  do not replace the authoritative bundle documents or create new identifiers.

Each table declares its `edgemech-table/<name>/v1` physical schema, row count,
logical digest, and partitions. Each partition declares its relative POSIX
`.parquet` path, byte count, file digest and row count. Paths are globally
unique within the manifest; absolute paths, traversal, alternate separators,
control characters and noncanonical aliases fail. Empty tables may have no
partitions. The manifest is bounded to 16 MiB of canonical JSON.

Partition rows must sum to the table total. `occurrences` and
`current_decisions` must each cover every selected occurrence. Each of the
four independent coverage dimensions must sum to that same population; these
dimensions must never be summed together as separate observations. Counts
must be exact nonnegative integers. Artifact assurance always carries
`scientific_review: false`.

The storage implementation must additionally verify physical Arrow schemas,
all file sizes and SHA-256 hashes, logical table hashes, exact occurrence and
source-row digests, bundle hashes, history order, parent/revision chain, and
the current projection reconstructed by replay. It must reject filesystem
symlinks escaping the generation. Only after all files have persisted and
verified may it atomically publish the manifest; interrupted staging must not
replace the current manifest. Count equality alone is insufficient:
[#951](https://github.com/CultureBotAI/culturebotai-claw/issues/951).

## Native assertion transport and inherited review

`kg_microbe_curation.native.NATIVE_CONTRACT` is
`kg-microbe-native-assertion/v1`. `native_assertion_id(document)` identifies
the full canonical envelope excluding its own `assertion_id` field.
`validate_native_assertion(document)` checks the packaged
`schema/native_assertion.json`, digest bindings and inherited status. The
transport is bounded to 16 MiB and does not contact repositories or providers.

| Field | Meaning |
| --- | --- |
| `native_locator` | Exact repository, commit, relative path and native selector; separate whole-file and canonical native-payload SHA-256 values |
| `payload` | Exact projected subject, predicate, nullable object, context and interpretation pins, plus the complete original native row in `native_payload` |
| `evidence` | Unique evidence IDs with pinned file locators, whole-file digests, explicit ancestry and optional original selected-entry payloads |
| `native_review` | Status, exact review locator and file hash, complete original decision object and its canonical hash, and explanation of inheritance |
| `assurance` | `inherited_native_review`, `native_withheld_decision`, or `unassessed`, matching the review status |
| `limitations` | Required explicit inherited scope and eligibility limits |
| `independent_scientific_review` | Always false |

Source and review files must appear in the evidence closure with matching
digests. Different selectors in one file cannot assert different whole-file
hashes. Native review payloads retain their original owner-record hash,
review reason, evidence references and other fields. The adapter must verify
the complete native dependency inventory before emitting assertions; a review
document hash binds that inventory without expanding every dependency into
every row envelope. Selected source, owner, review, evidence and interpretation
dependencies remain explicit in the emitted envelope.

Adapters own native semantic eligibility and authentication of pinned bytes.
The generic validator cannot establish whether a projected triple faithfully
expresses its domain-specific native payload. An inherited supported assertion
requires a non-null object and pinned review provenance. Withheld assertions
may retain a null object and their exact restricted scope; withholding one
native mapping never establishes a global prohibition against the same triple.

The eligible-overlap census may classify exact matches to inherited supported
assertions. Its corresponding canonical occurrence bundles remain
`deferred`/`withheld` until a real scientific RecordReview covers the required
occurrence and claim digests. No reviewer is invented, historical native
decisions are not rewritten, and adapters do not promote inherited status to
independent approval. See
[#952](https://github.com/CultureBotAI/culturebotai-claw/issues/952).

## Adjacent work reviewed, not silently adopted

These live PR states were checked on 2026-11-07 during the prerequisite review:

| Work | Reviewed head | Implication |
| --- | --- | --- |
| [CLAW #448](https://github.com/CultureBotAI/culturebotai-claw/pull/448), open | `3c1df7e02836d923d5039b933239f7f3727a7ccb` | Claim support, study type, and source quotation are separate; no inferred defaults |
| [CLAW #537](https://github.com/CultureBotAI/culturebotai-claw/pull/537), open | `76d60d72d3e21c05b268295ee8c939cba3f9ef19` | Unmerged KGX work remains a separate dependency |
| [CLAW #543](https://github.com/CultureBotAI/culturebotai-claw/pull/543), open, based on another branch | `f9cc2fdfc656b16947001b60c3970c22475c4fd0` | Positional graph transport IDs and flattened values do not replace exact occurrence identities |
| [KG-Microbe #1585](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1585), draft open | `c5da4b3d80f843789a8d4f37d8067694672153d0` | RDF transport identifies different units and enforces different line-ending rules; IDs are not interchangeable |

[CLAW #461](https://github.com/CultureBotAI/culturebotai-claw/issues/461) and
[#540](https://github.com/CultureBotAI/culturebotai-claw/issues/540) remain open
publication-contract work. This local external generation contract does not
claim to implement authenticated remote release publication, asset promotion,
or a shared fleet release-manifest format. Those boundaries must be resolved
before publishing a release or linking a claimed production artifact.
