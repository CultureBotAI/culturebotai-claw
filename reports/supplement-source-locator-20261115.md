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

The initial hosted run stopped before pytest because the reusable Mech baseline
still named the old schema and manifest hashes. The finding is retained under
[issue 1220](https://github.com/CultureBotAI/culturebotai-claw/issues/1220#issuecomment-6903236255),
with failed CI log SHA256
`436188e66a00ef71774bade9be1677654f0cd3ad11d31aec598d3487b94d954c`.
Native `template_cli refresh` planning, application and `check-baseline` all
produced the same verified document, SHA256
`8c45a124efbd11c4b84873d763a66f9fdbc2490da2d74fb35c04631c2f531526`.
Only its source commit and the two changed authority hashes differ. The source
is the independently reviewed schema commit `75ce01bdd326ce74278bc2bbcde7f78f002eb803`.
The initial gate was not waived; the final hosted run remains required.
All 33 focused baseline/template/source-fetch regressions passed in 40.25 seconds,
raw log SHA256 `da2afe09358fef40141f28354bb7d6cc5c1c9336dec61587c5e8f7802e3cef51`.

The next hosted run reached 11,606 passing tests but failed all 17 new schema
cases during fixture setup: LinkML received null-tag YAML nodes before the
schema assertions ran. Its retained log has SHA256
`5bf7d06383f5588ad0b41fec60b69129ee71b3e97684afbd3396331c83eff200`.
This recurrence is recorded under
[issue 263](https://github.com/CultureBotAI/culturebotai-claw/issues/263#issuecomment-6903500649).
The fixture now follows the existing cross-corpus schema test: generate the
same closed schema with real LinkML in a fresh interpreter, then retain every
original JSON-schema assertion. The schema, manifest, baseline and runtime
bytes do not change. The test also proves that a deliberately damaged parent
loader fails in-process, that isolated generation still accepts a valid
locator and rejects missing/invalid coordinates, and that the parent loader
is unchanged and restored afterward.

The original fixture and all command triplets remain under
`.temp/supplement-schema-20261115/`. Actual controls at `846c4635` plus the test
change were:

| Recorder suffix | Result | Raw log SHA256 |
| --- | --- | --- |
| `supplement-loader-isolation-baseline-001` | Original 17 cases passed, 3.27 s | `3eccd66ebb651f3befee98610772e7eac1eeac28c8ba375d9821ad9ee07121fe` |
| `supplement-loader-isolation-poison-before-001` | New damaged-parent control failed at the original fixture, 3.81 s | `9505e619de8cb9b5f50a8d85aa3799e6bfa3b19a34a3144ce800f0d553f55ea6` |
| `supplement-loader-isolation-poison-after-001` | Same control and restoration passed, 6.99 s | `a75c257f1519da68d858e31f8a859632060acc2f27e3d8931d11880ee0dc2770` |
| `supplement-loader-isolation-ordered-controls-001` | YAML-platform, cross-corpus and supplement modules: 48 passed, 4 skipped, 3 warnings, 18.89 s | `a156cda21516a64b9d61dd25ea0ed872c3f3e5203d088152fe1934054f964a97` |
| `supplement-loader-isolation-ruff-001` | Ruff passed | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |

The ordered run enabled the hosted coverage source list to exercise that import
context. Its focused invocation disabled the aggregate coverage threshold;
it is not a full coverage or hosted-CI pass, and no CI configuration changed.
The consumer's new fixture has the same in-process shape and was reported for
separate consideration; no consumer failure was observed or consumer file
changed in this repair. A fresh full hosted run remains required.

No consumer pin or deployed environment changes in this branch. CommunityMech
adoption must synchronize the governed artifact and exact Claw pin, add its
EvidenceItem slot, pin the reviewed validator, retain the private catalog and
assets, and repeat native source-selection controls. Other consumers remain on
their existing pins until separately synchronized. Full CI and independent PR
review remain required before proposing this branch for merge.
