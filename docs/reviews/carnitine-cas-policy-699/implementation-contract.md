Independent review of the selected Step3 guard scope

The selected scope is defensible: keep the exact CAS461-05-2/CHEBI:48601 rejection, add a separate rejection for the two reviewed hydrochloride owner/source identities, and consume only CultureBotHT's existing exact carnitine correction. This is a preparatory contract assessment, not approval of future code. The root decision reviewed here has SHA256`9353e4dafa810d3193e69291ffb703188a39331f9f21cc0863103e3d375798d0`.

The implementation must preserve the following requirements. Root independently confirmed the preflight-before-yield requirement while this review was in progress; none requires a broader overlay port or early Step7 work.

1. **Validate before yielding any candidate.** `src_culturebotht` is consumed incrementally by an apply loop. If a later source row needs the reviewed correction, missing/conflicting evidence must be detected before an earlier row can be written. Read/validate the relevant source and correction snapshot before the first yield. Do not introduce a lazy exception after partial output. The source and overlay hashes must describe the same bytes actually parsed; avoid separate hash/read passes that could observe different files.
2. **The failure rule is conditional on needing the correction.** An exact raw duplicate tuple requiring correction must not silently use461-06-3 if the overlay file or required entry is absent, malformed, unreadable, changed, or duplicated. Refuse before any proposal-success count or write. A run with no relevant source row should not acquire a new dependency on this overlay, and an already-correct461-05-2 row should remain unchanged without falsely claiming a correction. Preserve existing behavior for missing source input and unrelated sources unless a separate supported requirement changes it.
3. **Inspect the exact entry, not a collapsed mapping.** Require a single matching overlay entry with the approved old/new CAS and form/evidence sufficient to identify the reviewed assertion. Duplicate identical and duplicate conflicting entries need explicit refusal. The upstream helper currently warns and passes through when the file is missing, and its dictionary loader uses last-wins assignment; merely importing that helper does not satisfy the selected contract. Unrelated overlay entries must not be applied. Whole-file updates to unrelated entries need not invalidate the approved tuple; record the actual file hash while validating the relevant tuple explicitly.
4. **Correct the raw tuple before lossy parsing.** Use the upstream exact `(compound.strip(), raw_cas.strip())` boundary. Do not first split a multi-CAS field or normalize away name distinctions and then treat the result as the original exact tuple. Case/whitespace normalization for the defensive amide-rejection rule is a separate policy. The existing overlay is case-sensitive and preserves internal whitespace; tests must distinguish these policies.
5. **Make provenance durable.** `Candidate.raw` alone is insufficient. Both current mapped and unmapped emitters omit the raw CAS and the overlay reference. Retain the source row/identifier, original CAS, corrected CAS, correction reason, overlay relative path and actual hash, and a durable upstream blob/reference/evidence locator in output history/evidence and the run report. Bind the actual overlay evidence used, not just an unversioned path. Keep the raw source bytes unchanged. Use maintained schema fields such as evidence notes/history; do not invent unsupported record fields. A blocked/unmapped result should describe the real rejection or missing evidence rather than incorrectly saying no CAS was present.
6. **Preserve ordinary owner skips and no-op behavior.** Existing indexed names/CAS should still be skipped without rewriting MIM records. Correcting the candidate's CAS may change the existing CAS-collision test, so exercise both name and CAS skips against the corrected source value. Preserve the original row in provenance even when the candidate is skipped or retained unresolved. Do not force NCIT:C216679 when rejecting the amide. The record/source rule remains necessary for missing-CAS tombstones, wrong-CAS stale artifacts and name-only contexts even after intake correction.

Actual offline probes

`probe.py` invoked existing native functions without network or production writes. The12 cases in `results.json` establish why these requirements matter:

- The upstream helper leaves the wrong raw CAS unchanged for a missing overlay or omitted tuple; it accepts a changed value and last-wins conflicting duplicate. An identical duplicate also goes undiagnosed.
- Native exact correction leaves `461-06-3/fixture-other` and `461-06-3 fixture-other` unchanged, whereas applying the same correction after Claw's existing splitting changes them to461-05-2. These are synthetic representation probes, not real catalogue values.
- Both native emitters accept a fixture candidate containing corrected CAS and the preserved old CAS in `Candidate.raw`, yet neither serialized output retains the old CAS or correction provenance. The mapped test used an explicit synthetic registry fallback result; it is not evidence of a new NCIT fallback or a production import.

Source hashes are bound to the existing Claw importer and tracked CultureBotHT correction helper. Claw and MIM remained clean. The previous25-file independent design-review bundle and all Step2 evidence remain untouched.

Bounded regression requirements for the future implementation

| Scenario | Required assertion |
|---|---|
| Reviewed wrong tuple, valid unique overlay | Correct only this candidate; raw assertion and actual overlay evidence survive the mapped/unmapped/dry-run/report path |
| Required overlay missing, unreadable, malformed, omitted, changed, duplicate-identical or duplicate-conflicting | Explicit refusal before the first generator yield, before any candidate success count and before all fixture writes; no wrong-CAS fallback |
| Failing reviewed row placed last after an otherwise valid row | Entire correction preflight fails before that earlier row is emitted/written |
| No reviewed wrong tuple; unrelated source; absent source CSV | Preserve documented existing behavior; no accidental global overlay dependency |
| Already-correct461-05-2 tuple | No double correction or invented correction provenance |
| Outer whitespace versus case/internal-space changes; multi-CAS values | Match only the supported exact raw correction boundary; defensive rejection remains separately normalized |
| Phenethylamine and the two other overlay entries | Values and behavior remain unchanged by this carnitine-only intake correction |
| Existing owner matched by name, and another fixture matched by corrected CAS | Existing skip/collision behavior remains safe; no duplicate MIM write |
| CorrectedCAS → cached/fresh48601; missing/wrongCAS for both reviewed source/owner names | Still reject the amide at acceptance and persisted-write boundaries; preserve the candidate and explicit rejection reason |
| Legitimate amide, unrelated salt, free DL-carnitine and distinct L-carnitine hydrochloride | No global48601 ban, no broad `carnitine` name matching, no unrelated chemistry/identity changes |
| Overlay/raw source changed after preflight snapshot | All provenance and decisions bind the captured bytes actually used; no reread that silently changes evidence |
| Direct persisted writer replay | Cannot bypass the shared rejection or lose the raw-to-corrected provenance |

Mutation tests should separately remove the preflight, use the permissive upstream helper directly, move correction after splitting, omit durable provenance, remove the owner/source rule, and restore a cached/persisted unconditional acceptance. Run those controls in fresh processes. These are future requirements, not completed implementation test results.

One entrypoint boundary remains to name explicitly

The phrase “CultureBotHT-specific intake” should identify the changed callers. The maintained `src_culturebotht` path is clear. The legacy `integrate_culturebotht_ingredients` also reads raw CAS, the historical `cas_chebi_lookup_pubchem` replays queue CAS rather than reloading that value from the compound CSV, and `add_remaining_culturebotht` creates registry fallbacks from raw CSV. Preventing amide proposals does not by itself correct every such source consumer. The last fallback-only producer is outside the narrow CAS-to-amide guarantee and can remain a documented legacy limit rather than requiring this PR to expand. The final PR must distinguish callers receiving the carnitine overlay from callers receiving only the scoped proposal rejection; it must not claim all Claw consumers or all raw-CAS conflicts are corrected.

The scope is suitable for implementation once those behavioral details and the caller list are made explicit. No new source correction, broad curation permission, GitHub action or final-head approval is granted by this review.
