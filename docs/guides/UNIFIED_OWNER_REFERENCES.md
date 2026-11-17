# Permanent owner references in unified comparisons

The unified TSV appends `mim_record_id` after the original ten columns. This is
the permanent `MIM:<seven-digit-id>` of the record already selected by the
existing comparison resolver. It is comparison provenance, **not** an approved
source-to-MIM identity, ontology mapping, role or publication decision.

The historical column named `mim_id` retains its original meaning: the selected
record's external, registry or unresolved `identifier`, subject to the existing
nonidentity rules. Do not replace it with a numeric MIM ID. Existing consumers
rank that column as a mapping candidate. The new `mim_record_id` must remain out
of that ranking and must not be interpreted as an exact-match assertion.

All existing column values, row membership/order, label resolution, statuses,
synonyms and holds remain governed by the existing resolver. A selected
UNMAPPED or AMBIGUOUS record can have a permanent record reference while its
external identity fields remain empty/unresolved. A name with no selected owner
or an unresolved rejected-record proxy has no reference. Existing resolved
merge aliases carry the already selected survivor's ID, not the tombstone's.
Shared external identifiers or native legacy aliases are never looked up to
derive this field; ambiguous aliases cannot mint or select a new owner.

## Current and historical inputs

For a current corpus, the builder captures all direct mapped/unmapped owners,
both native ID ledgers and `src/mediaingredientmech/stable_ids.py`. It reuses
Claw's native `identity_snapshot` contract to validate the complete inventory,
positive IDs, uniqueness, registration and lifecycle. Mapping REJECTED is not
the same as lifecycle retirement. The caller must supply the independently
qualified native source digest; computing a digest of arbitrary supplied code
does not establish its qualification. No ambient MIM module is imported.

If every owner lacks the `mim_id` field and both ledgers are absent, historical
inputs retain legacy behavior with blank `mim_record_id`. A present null/empty
ID, partial migration, malformed/duplicate YAML key, missing ledger, omitted
active owner or unregistered/retired/duplicate current ID fails. Invalid YAML
cannot establish a wholly pre-ID corpus. Non-record empty/list documents retain
the old legacy skip behavior, but are refused in a current corpus. Owner paths,
captured bytes and ledger absence observations are rechecked before emitting.

## Supported current invocation

Use the reviewed Claw environment, explicit verified roots and a fresh output:

```bash
CULTUREMECH_ROOT="$CULTUREMECH" MEDIAINGREDIENTMECH_ROOT="$MIM" \
  "$CLAW_PYTHON" "$CLAW/scripts/build_unified_ingredient_mapping.py" \
  --culturemech "$CULTUREMECH" --mim "$MIM" \
  --mim-stable-id-contract-sha256 "$QUALIFIED_NATIVE_CONTRACT_SHA256" \
  --output "$FRESH_UNIFIED_TSV" --format tsv
```

`QUALIFIED_NATIVE_CONTRACT_SHA256` selects the actual reviewed native file; it
is not an automatic hash discovery option. Bind the actual Claw revision,
native source/ledgers/owners, CultureMech inputs, label index and rejection
ledger in the caller's retained final artifact provenance receipt. The existing
MIM freshness stamp alone does not capture this extended producer/input set.
The owner-byte rechecks here are not
a new scientific approval or a global atomic filesystem guarantee.

Older MIM `rebuild-unified` recipes do not forward this new argument and cannot
run this builder on current-ID inputs: it refuses before writing and before
the recipe's rejection-check/stamp steps. Use the direct supported invocation, or
separately review a caller change that forwards the explicit qualified digest.
Run the existing MIM rejection and freshness commands against the actual final
artifact; do not stamp a failed build or silently substitute another producer.
This change does not edit MIM callers, source records or active campaign pins.

The native URI remains
`https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_`. The explicit
stable KG profile spells that same identity `MIM.ingredient:<seven digits>`.
Do not reinterpret historical filename-based or biomedical MIM namespaces.
The separate stable SSSOM and reviewed source-binding products retain their own
native gates. This comparison column neither replaces those products nor
releases a held source identity. The optional YAML summary is still a limited
legacy summary, not the full row-to-owner comparison product.
