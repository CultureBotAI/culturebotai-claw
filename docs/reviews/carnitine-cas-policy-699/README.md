# Carnitine hydrochloride resolver evidence

This bundle supports [Claw #699](https://github.com/CultureBotAI/culturebotai-claw/issues/699)
and the approved decision on [MIM #1004](https://github.com/CultureBotAI/MediaIngredientMech/issues/1004#issuecomment-6555569867).
It preserves the source evidence for a narrowly scoped rejection; it does not
approve a bulk import or automatically assign a replacement ontology term.

## Scientific scope

The captured NCI C216679 entry identifies DL-carnitine hydrochloride with CAS
461-05-2. PubChem CID 5970 describes the chloride, C7H16ClNO3, molecular weight
197.66. ChEBI 48601 instead describes carnitinamide chloride, with a different
amide structure, while retaining a conflicting CAS 461-05-2 cross-reference.
That cross-reference cannot establish the reviewed hydrochloride identity.
The original source contains both reviewed hydrochloride names; its tracked
correction changes the duplicate's wrong free-carnitine CAS 461-06-3 to 461-05-2.

The policy rejects CHEBI:48601 when the supplied CAS is 461-05-2 or the original
source/owner name is exactly `Carnitine Hydrochloride` or
`Carnitine (Dl) Hydrochloride`, after the documented case/whitespace handling.
The two named contexts are independently needed for owners with absent CAS or
old, wrong CAS. This is not a blanket prohibition on the legitimate amide or
on distinct carnitine substances. Rejection alone supplies no replacement ID.

The approved MIM record merge and its mapping promotion are a subsequent,
separately reviewed change. This software repair runs no production ingestion.

## Source snapshots

`source-inventory.json` binds every retained source file and its original run
location. The `primary/` JSON responses are exact captured bytes. Adjacent
receipts preserve URL, time, response status, size and hash; transport headers
are omitted from these public projections, and the original receipt hash is
retained. No live lookup is needed to inspect the evidence.

`culturebotht/selected-source-rows.json` contains the two raw source rows and
the whole raw-file hash. The raw CSV was ignored, rather than tracked at the
stated checkout revision; the revision identifies checkout context only.
The tracked overlay snapshot is preserved in full to distinguish the one
approved tuple from unrelated corrections that this work does not apply.

The actual PubChem CID 5970 synonym response contains no ChEBI token. Bad
PubChem/OLS results used in regression tests are synthetic acceptance probes,
not claims about those services' current answers. ChEBI's conflicting xref is
present in its captured primary response. Direct CAS Common Chemistry API
access returned HTTP 401 during preflight, so this bundle makes no claim of
independent direct CAS verification. No ChEBI contact or paid research occurred.

`implementation-contract.md` is the retained independent preparatory assessment,
not a final-head approval. It specifies conditional correction preflight before
the first yield, exact raw-tuple matching before CAS splitting, durable source
provenance, ordinary owner skips, and failure/control regressions.

## Deliberate boundary

Only the maintained CultureBotHT loader receives the existing exact correction.
Legacy proposal and persisted-result consumers receive the bounded wrong-amide
rejection. In particular, the historical fallback-only
`add_remaining_culturebotht.py` raw-CAS path is not converted into an overlay
consumer. This change does not claim that all historical raw-CAS intake is
corrected. Existing indexed owners remain subject to ordinary skip behavior.

Validation and independent implementation reviews are recorded separately from
these immutable source captures. No supervisor, goal or cycle binding is
invented for this standalone approved-plan work.
