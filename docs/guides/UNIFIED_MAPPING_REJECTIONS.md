# Unified ingredient mapping rejection ledger

`scripts/build_unified_ingredient_mapping.py` reads the consumer MIM checkout's
`mappings/unified_mapping_rejections.tsv`. The ledger records reviewed negative
identity decisions; it neither mints identities nor changes ingredient records,
SSSOM aliases, or the general source-ID fallback policy. The producer and MIM's
`scripts/check_unified_rejections.py` implement this contract.

The header is exactly these four tab-separated fields, in order:

```text
ingredient_name	rejected_id	mim_id	reason
```

Every row must contain all four cells. The label, rejected CURIE, and reason
must be nonempty after trimming. Missing cells, extra cells or columns, malformed
rejected CURIEs, and duplicate rules fail closed. The reason retains the reviewed
evidence and source context outside the published identity columns. An older
MIM checkout without a ledger retains the prior behavior.

## Two scopes

| `mim_id` cell | Meaning | Matching key |
|---|---|---|
| Nonempty corrected identity | Reject a source ID for an independently resolved MIM identity | Corrected MIM identity and rejected ID, including that identity's accepted aliases |
| Explicitly empty | Reject one source-label/ID pair without asserting a replacement | Exact normalized source label and rejected ID |

A corrected-identity row must agree with the independent MIM name/label owner
and the owner's permitted status. It cannot reject the corrected identity or an
ID that the owner still publishes as its CHEBI or KG-Microbe node ID. These
checks and the identity-wide alias coverage remain in force.

A source-label row has an intentional empty third cell, represented by two
adjacent tabs between `rejected_id` and `reason`. A missing third or fourth cell
is malformed, not a hold. Source holds use separate keys; an empty replacement
never forms a global `('', rejected_id)` rule. Different held labels may reject
the same ID without affecting another label that uses it legitimately.

For source holds, exact label normalization means Unicode NFC, outer whitespace
trim, and case folding only. Internal whitespace, concentration, hydration,
stereochemistry, and parenthetical qualifications remain significant. The
producer's looser ingredient-name normalizer does not expand this finite set.

## Resolution and publication

The producer checks a source-label hold against the original ingredient name and
source term ID, then clears a matching term before any source-ID lookup or
publication. An independently resolved MIM name/label owner may still provide
its own identity and metadata. A hold contradicting that owner's primary ID,
CHEBI ID, or KG-Microbe node ID is rejected during ledger loading.

When no independent owner exists, the held label remains `UNMAPPED`, with empty
MIM, CHEBI, CultureMech term, CAS, KG-Microbe node, and borrowed synonym fields.
Its raw label, occurrence count, and media examples remain intact. The ledger
preserves the rejected source ID and review reason. No placeholder record or
replacement substance is inferred.

The MIM checker matches source-label holds by the same exact normalized label
and rejects the held ID in any published identity column. It permits a different
independently supplied MIM identity; it must never apply a source hold to every
row with empty `mim_id`. A different source ID for the same label is outside the
reviewed pair and follows the existing resolution policy; this does not certify
that different source ID as scientifically correct.

Producer regressions cover both indexed-record borrowing and source-only ID
publication, exact-label boundaries, independent owners, malformed input, and
coexistence with identity-wide rejections. Consumer corpus regressions must
separately establish the no-owner premise for any finite reviewed label cohort.

The source-label variant was introduced for [Claw #697](https://github.com/CultureBotAI/culturebotai-claw/issues/697)
and [MIM #1025](https://github.com/CultureBotAI/MediaIngredientMech/issues/1025).
