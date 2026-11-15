# Optional supplementary-source locator

CommunityMech issue [1996](https://github.com/CultureBotAI/CommunityMech/issues/1996)
contains quotations from a supplementary table that the article-only reference
validator cannot find. The canonical shared schema now defines `SourceLocator`
and accepts it optionally on `SupportingReference`. Importing repositories can
reuse this class for their own evidence classes. The governed manifest binds
the updated schema at SHA256
`01d09b7d91a21235b97cc37d8482518a7b2c36ab63d8898796fede3877061ed9`.

The locator selects a supplementary asset/version and a one-based table, row
and cell, including header rows. All six locator fields are required, the kind
is `supplement`, identifiers must contain non-whitespace text and coordinates
must be positive integers. The enclosing citation retains its reference and
excerpt annotations. Existing citations need no changes.

This schema describes the selection. It does not fetch sources, authenticate
publisher ownership, replay extraction or match quotations. Adoption requires
the separately reviewed source-locator-aware reference validator and a reviewed
catalog binding the parent reference, asset/version and exact asset/extraction
hashes. Version 0.2.1 does not implement this routing. An omitted locator keeps
article-only validation; a supplied invalid locator must fail without fallback.
LinkML optional fields may admit explicit null structurally; the new runtime
rejects a present null locator. Schema acceptance alone is not routing proof.

The independent installed-wheel trial used the original Switchgrass record in
a private scratch directory, adding exactly three locators without changing
its claims or quotations. The retained DOCX asset has SHA256
`5bfa02fdb94538e9405fb0ec7d7b0dad338791a5ca0b4b651589f33148c8e0e7`;
its replayed `docx-table-cells-v2` projection has SHA256
`c322c14c7e754df924e3e3151fb3d8e18564537dd0448e43d9a856d4e3ef32a5`.
The reviewed runtime module has SHA256
`4560abcc81034c2cc69f241166935a8df217e1af3d6671990f4940d49d57ee6f`.
The trial ran LinkML and linkml-runtime 1.9.5; downstream dependency resolution
and trials on the adopted CommunityMech environment remain separate.

| Actual installed-runtime trial | Calls | Comparisons | Matches | Mismatches | Source-selection errors | Exit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Correct supplementary cells | 37 | 37 | 37 | 0 | 0 | 0 |
| Locators omitted | 37 | 37 | 35 | 2 | 0 | 1 |
| Wrong cell, despite article match | 37 | 37 | 36 | 1 | 0 | 1 |
| Wrong parent paper | 37 | 36 | 36 | 0 | 1 | 1 |
| Correct cells restored | 37 | 37 | 37 | 0 | 0 | 0 |

Every trial preserved its inputs and reported no network attempts. The positive
receipt is SHA256
`e911410ac55cda792b4b5e5d56df093e5b8c7e042398f1e467467aa571d863e3`.
These counts come from observed native matcher results, not the CLI's misleading
`Total checks: 0` issue counter. They establish lexical source routing for one
record, not scientific correctness or canonical CommunityMech adoption.

On Claw base `271fbbdb7f63e60b3771d5e28d398395da1d13cc` plus the schema/test
changes, a single generated-schema canary passed before the focused suite.
The suite passed 84 tests in 52.36 seconds: valid and malformed locators, existing
SupportingReference CLI traversal, canonical checksum governance, preparation
identities and EdgeMech governance boundaries. Its raw log is SHA256
`f53d109b5d45c8a916fa572931f072c35e5f08527bf963243975c94ba0c92bba`.
Ruff passed for the added test and recorder, log SHA256
`82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`.
The first exploratory positive used the generator's open-root default and
passed even before this field existed; it is not a rejection control. Final
tests use the closed generated schema and its declared JSON Schema dialect.
Immutable command receipts are under `.temp/supplement-schema-20261115/`,
produced by `scripts/adhoc/run_supplement_schema_checks_20261115.py`.

No consumer pin or deployed environment changes in this branch. CommunityMech
adoption must synchronize the governed artifact and exact Claw pin, add its
EvidenceItem slot, pin the reviewed validator, retain the private catalog and
assets, and repeat native source-selection controls. Other consumers remain on
their existing pins until separately synchronized. Full CI and independent PR
review remain required before proposing this branch for merge.
