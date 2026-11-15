# Stable MIM candidate generation

The builder requires `--identity-mode legacy` or `--identity-mode stable`.
`just build-sssom` explicitly selects legacy behavior for historical callers.
Neither mode publishes a canonical mapping or grants scientific approval.

Stable mode consumes MIM's existing positive seven-digit `mim_id`, mint ledger,
lifecycle and complete mapped/unmapped inventory. It executes the exact native
`src/mediaingredientmech/stable_ids.py` source selected by
`--mim-stable-id-contract-sha256`, against captured ledger/record bytes. It does
not allocate IDs, infer them from labels or filenames, or fall back when an ID
is absent. The contract digest selects trusted executable input; it is not a
signature authenticating the author. Use an independently reviewed native MIM
revision and record its provenance.

```bash
python scripts/build_mim_ingredient_sssom.py \
  --identity-mode stable \
  --mim-stable-id-contract-sha256 ACTUAL_REVIEWED_NATIVE_CONTRACT_SHA256 \
  --output /absolute/new-or-owned-output/candidate.sssom.tsv
```

Stable subjects use MIM's permanent resolver prefix. Canonical external rows
retain their distinct exact/broad/close predicates. Literal curated local
primaries and existing canonical registry objects are retained with their
original namespace, case and escaping. Historical MIM aliases must resolve to
one current owner; shared external identifiers never choose one. The builder
does not synthesize a `kgmicrobe.*` object from the numeric MIM suffix or from a
renamed filename. Competing registry namespaces and canonical registry rows
without a current native alias owner fail closed.

This remains a freshly generated candidate: comments, source tokens, dates,
synonyms and other fields follow current captured producer inputs and can
differ from retained canonical annotations. Stable mode deliberately does not
replay `validation_method` by matching a triple, even if the subject is already
numeric. Its manifest binds the untouched canonical/prior inputs, explicit
replay policy, owner inventory and row counts. Changed science needs fresh
review; the existing identity-only administrative proof is not generalized or
silently treated as current scientific approval. Legacy mode retains its
existing stamp policy and tests. Compare every candidate delta before any
separately authorized publication.

## Source identities are a separate native product

An owner without an external grounding emits no fabricated external row, MIM
self-loop or `MAPPED` status. A source-to-MIM identity instead uses MIM's native
`mediaingredientmech.export.source_bindings` contract, including its genuine
primary/skeptical decisions, source rows, occurrences, complete current owner
inventory and ledger evidence. Claw only consumes an already exported native
candidate and invokes `validate_candidate`; it does not implement a second
admission schema or manufacture review authority.

Pass all four options together in stable mode:

```text
--source-bindings-bundle /absolute/native-candidate-directory
--source-bindings-review /absolute/MIM/root/path/to/review.json
--source-bindings-manifest-sha256 ACTUAL_NATIVE_MANIFEST_SHA256
--source-bindings-producer-sha256 ACTUAL_REVIEWED_SOURCE_BINDINGS_PY_SHA256
```

The selected root is the explicit, repository-validated `MEDIAINGREDIENTMECH_ROOT`.
Claw runs the native read-only validator in a fresh child interpreter against
that root, avoiding ambient MIM modules and stale bytecode. All declared source,
review, product and native-package/resource inputs are captured and rechecked;
the output inventory is checked too. Unsupported capabilities, changed bytes,
wrong pins or native refusal abort before candidate publication.

The separate bundle retains complete SUPPORTED/WITHHOLD source accounting and
its independently reviewed external partition unchanged. Its source rows are
never joined into Claw's canonical MIM-to-external TSV. A concept-only result
can therefore have a header-only external candidate alongside the bound native
source product; without that genuine native product an empty canonical build
fails. Empty-candidate header dates derive from actual owner history, not the
clock. A zero-row candidate must have exactly its complete physical header,
explicit metadata, zero native parsed mappings, and pass the ordinary native
JSON-schema, prefix-map and strict-CURIE validators. Blank or malformed rows
cannot be dismissed as an empty set. A source-binding verdict does not authorize an external mapping, and a
candidate bundle remains `REVIEWED_CANDIDATE_ONLY`, with production permission
false.

Both modes retain the owned-name sidecar and the existing three-artifact lock,
validated transaction, output-alias refusals, complete no-op comparison and
recovery journal. Stable mode includes both owner-directory memberships and
checks repository revisions, native producer membership and captured input
bytes repeatedly. The native source bundle is a protected input, not a fourth
uncoordinated output. These are bounded observations, not a global atomic
filesystem guarantee. Preserve any partial-failure journal and obtain the
separate canonical/publication review before release.
