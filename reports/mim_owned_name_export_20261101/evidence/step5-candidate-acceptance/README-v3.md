# V3 preparation for the repaired captured-source boundary

Use **`verify_candidate_v3.py`** for the next root-approved acceptance run, with `--generation-harness "$RUN/generate_candidate_step5_v2.py"`. V1/V2 and their indices remain unchanged. V3 is syntax-parsed only; no candidate acceptance has run. The corrected generation at `step4-mim/output/step5-owned-name-candidate-v2` was still running when this preparation was requested; root must provide its completed receipt and exact journal before execution.

The inspected builder source has SHA-256 `38d59f42953305f6fc51e4fc24dfc59ee1919bfb961595b67a8afe9f8a46a1bc`. It loads dependent producers into a private captured-source graph and exposes `_POLICY_PRODUCER`/`_ARTIFACT_PRODUCER` plus entry-module function aliases. V2's public imports are therefore replaced by these actual captured modules.

V3 changes only the verifier:

- Read and hash the entrypoint bytes first; require equality with the generation harness's `executed_entry_source_sha256`, its producer/source-inventory hashes and the native generation manifest before source-compiling those exact bytes. Source-compile the native validator from its verified MIM Git blob as well. No timestamp-based entrypoint bytecode load is accepted.
- Check declared local producer bytes before import, then require the builder's complete `_IMPORTED_PRODUCER_BYTES` hash map to equal `producer_import_snapshot` and the normal source-input inventory. Run the builder's origin/path/byte drift checks before and after replay. This retains the stated trusted-caller/interpreter boundary; it is not cryptographic runtime attestation.
- Obtain owner indexing, sidecar rendering and artifact validation from the private modules actually used by the builder. Verify identity of the entry-module aliases and the `_row_from_yaml` globals binding.
- For the diagnostic-only unfiltered counterfactual, patch both the actual entry alias and its private policy binding, instrument calls and encountered owned pairs, and restore both in `finally`. Refuse unless calls occurred and their unique owned-pair set equals the real policy-event set. No source bytes or published artifacts are modified by this in-memory comparison.
- Independently reject a sidecar SUPPRESS pair when that subject already has the token as a source `REJECTED_LABEL`, including case/pipe-fragment normalization. This checks #707's disposition boundary in addition to exact native event replay.

All V2 source-preservation, manifest/journal, native empty-baseline Rule K, B4/schema, credited-owner/source-reference and observed-label/counterfactual classification checks remain. Root's clean producer SHA is passed explicitly; the known e78e220 generation remains forbidden. The producer and MIM checkouts must stay clean for the entire acceptance run, so portable packaging changes should follow the acceptance result.

The new invocation uses the original README options, replacing the verifier/harness and final bundle/output paths:

```sh
--bundle "$RUN/step4-mim/output/step5-owned-name-candidate-v2"
--generation-harness "$RUN/generate_candidate_step5_v2.py"
--producer-revision 90d110e663c10146351b09ae98d387dabdec0b1c
--output "$RUN/step5-candidate-acceptance/final-v3"
```

These are preparation arguments, not a report that the generation completed. Root supplies `--journal` after completion and confirms whether a later repair revision supersedes this one. `preparation-v3-inputs.json` and `preparation-v3-index.json` bind the inspected interface and prepared script; they do not replace final source/artifact receipts or independent review.
