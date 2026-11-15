# Public discussion export, version 1

`kg_microbe_discussions.public_export.normalize_record` projects a pinned native
record's Discussions into public browser items. It does not read repositories,
query literature, write records, render pages or establish a fleet denominator.
The existing `kg-microbe-discussions` browser is unchanged. The JSON Schema is
packaged beside the module as `public_export.schema.json`; `SCHEMA_VERSION` is 1.

Call the normalizer with `doc` plus keyword arguments `mech`, `repository`,
`revision`, `path`, `source_sha256`, `root_config`, `license`, and optional
`record_url`. The caller must verify that the SHA-256 identifies the bytes read
from that repository/commit/path and that publication is permitted. The function
checks the supplied provenance's shape and relationships, not remote existence
or the truth of the scientific claims.

`root_config` supplies `id_field`, ordered `name_fields`, `alias_fields`, and
`alias_value_fields`. Absent ID configuration tries `id` then `identifier`;
missing labels fall back to the record ID. Aliases may be strings, lists of
strings, or dictionaries inside a list; dictionary values are read only from
the explicitly configured alias value fields. Unknown dictionary shapes fail.

Identity is `gap-` followed by the full SHA-256 of compact UTF-8 JSON
`[repository.lower(), path, record_id, discussion_id]`. Record paths disambiguate
different native records sharing the same chemical CURIE and discussion ID.
Changing prose, order or source revision does not change identity. File moves
require an explicit downstream identity migration; they are not silently
collapsed. `validate_items` refuses duplicate identities across a complete list.

The source locator defaults to `discussions#<discussion_id>`. An explicit native
adapter may replace `source.locator` with its actual location, then revalidate
the item. The pinned source link always names the full relative Git path.
Identifiers and links are separate: URLs must be HTTPS without credentials or
control characters; file paths must be relative and normalized.

## Classification and public content

| Record evidence | Origin / basis | Current attribution | Review state | Lane |
|---|---|---|---|---|
| `posed_by: kg-microbe-kgscan`, with review requirement in rationale | scanner / current attribution | scanner | required | candidate |
| Same attribution without explicit review requirement | scanner / current attribution | scanner | unspecified | candidate |
| Other attribution and documented scan provenance, without current review requirement | scanner / documented scan provenance | other | unspecified | recorded |
| Other attribution and no documented scan provenance or review requirement | other / current attribution | other | unspecified | recorded |
| Documented scan provenance without current attribution or review requirement | scanner / documented scan provenance | unspecified | unspecified | recorded |
| No attribution, scan provenance or review requirement | unspecified / unspecified | unspecified | unspecified | recorded |

An explicit `curator review required` phrase in current rationale always selects
the candidate lane and required review state, independently of origin. Otherwise,
current scanner attribution selects the candidate lane; historical origin does not.

A scanner-shaped discussion ID does not establish current origin or review.
`storage_mode` is always `native_record` for this adapter, independently of the
item's scanner origin or candidate lane. Scanner artifacts need a separate
versioned adapter and are outside this module's input contract.
TraitMech's corrected `animal_pathogen` discussion retains its `kgscan-` ID and
documents its scanner origin, but has current `posed_by: claude`. It keeps scanner
origin with `origin_basis: documented_scan_provenance`, `current_attribution: other`,
a recorded lane and unspecified review. Conversely,
native MIM discussions retaining scanner attribution and an explicit review
requirement remain candidates even though they are committed. Recorded does
not mean reviewed or scientifically established. No state asserts review passed.
The explicit requirement test ignores letter case and whitespace within the
phrase; this is an observable provenance rule, not a natural-language review.
Historical scanner origin requires both an initial `Scan provenance` marker and
the explicit `kg-microbe-kgscan pass raised this discussion` clause in native notes.
Neither a scanner-shaped ID nor an incidental mention establishes that history.
The notes remain omitted; the pinned source locator exposes their provenance for
inspection. `current_attribution` preserves only the scanner/other/unspecified
category, never the author name or email address. Current scanner attribution is
the preferred basis if both current and historical scanner evidence exist.

The projection retains prompts, rationale, kind/status, attachments, evidence
references/support/explanations, every current shared ProposedExperiment field,
calendar dates and resolution notes. Missing kind/status/support is `UNSPECIFIED`;
missing dates are empty strings. YAML calendar dates become ISO dates; timestamps
are rejected in date-only fields. `NO_EVIDENCE` remains a contextual citation
relationship and never means that the literature contains no evidence.

Source excerpts, freeform `notes`, `posed_by` and unrecognized experiment fields
are omitted. Prompts and rationale can themselves contain source quotations;
dropping dedicated snippet fields does not establish redistribution rights.
Remaining projected text is checked for email addresses, which cause failure
rather than disclosure or silent editing. This projection does not decide public
fleet membership, or confer rights to other source text. Callers must apply their public allowlist and licence policy
before constructing artifacts and must not retain excluded raw records in a
public bundle.

## Failure and validation

Absent or empty Discussions return `[]`. Malformed populated discussions,
missing required identifiers/prompts, wrong types, unknown enums, invalid dates,
unsafe sources and duplicate identities raise `PublicExportError`. Callers must
record extraction failures and may not report a failed corpus as zero items.

`validate_item` enforces the closed JSON Schema and also checks stable identity,
source URL consistency, evidence-reference aggregation, valid origin/basis/current
attribution combinations and classification. Historical evidence is read from the
native record during normalization; public validation cannot independently verify
the omitted notes without reacquiring the pinned source.
`validate_items` adds cross-record collision checks. The schema alone cannot
prove those relationships; consumers should call the Python validator before
publication. A site's coverage/build manifest is a separate contract, since a
valid item list says nothing about uninspected records or unsupported roots.

Regression fixtures retain minimal classification inputs from TraitMech
`2ccbc22ccfb8bd00c9d9ca70e11e020f818fbc18` and MediaIngredientMech
`24d76baa823d7fd07e8ea2596f0cca50e66392e2`; test questions are shortened synthetic
stand-ins and source excerpts are not copied. Tests cover native scanner
candidates, corrected current attribution, record-path identity, every shared
experiment field, stripping, dates, schema closure and malformed inputs.
