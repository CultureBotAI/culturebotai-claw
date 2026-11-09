# Preliminary independent findings: Step 5 artifact publication

Scope: frozen artifact publisher SHA256 `126d891db86251083d462fd48dd9ded6354ccd3acb6ff34fd39075d9641607e5`, policy helper `18ffd0430d0256b6da6cbb1f3da2327c4cf3418e2b0b2da71ff283ee2f4351ae`, actual native `ValidatedWriteTransaction` and `LockManager`. Builder integration is still under development; this is not a final-head review. No production edits, GitHub writes or provider calls.

## Finding 1: absent filesystem-equivalent destinations write before refusal

Severity: medium. `artifact_paths`/`publish_candidate_artifacts` checks lexical equality and `samefile` only for existing destinations. On this M5 filesystem, initially absent `candidate.sssom.tsv` / `CANDIDATE.SSSOM.TSV`, and NFC `café.sssom.tsv` / NFD `café.sssom.tsv`, pass preflight. Actual native publication writes the set. The two paths then resolve to one physical file, and postvalidation raises `Artifact publication mismatch`. The TSV survives, the sidecar path contains the same TSV bytes, and the native journal already says `complete`.

This violates the approved pre-write collision refusal, not merely an abstract portability concern. Detect filesystem-equivalent reservations/identities before any candidate artifact is replaced; preserve old data and explicit failed evidence. Regression tests must exercise initially absent paths, and must assert no artifact publication occurred.

## Finding 2: final input-check callback can leave false success/no-op

Severity: medium. The final output validation precedes `input_check`, and the unchanged path checks outputs before the callback then returns from stale captured beforeimages. A real boundary injection replacing the sidecar during that callback yields (a) `status: unchanged` for an established set with a corrupt sidecar, or (b) `status: complete` after a fresh write with a corrupt sidecar. Both returned hashes describe the intended sidecar, not the current bytes; the existing journal is complete.

The probe wraps the ordinary input checker and simulates an uncoordinated destination write while source checks run. It does not replace the publisher, lock or transaction. Recheck actual artifact bytes and safe path identities after the final external callback on both exit paths; classify any failed postcheck truthfully and retain recovery evidence. Add both no-op and completed-publication regressions.

## Reproduction and controls

`probe_artifacts.py` loads exact immutable module snapshots and executes the native publisher/lock/transaction in the isolated `controls/` directory. `artifact-probe-results.json` retains the positive complete-set control and all four negative cases. The positive output and sidecar match exactly; both alias probes fail only after writing; both callback probes return successful statuses with wrong sidecar hashes.

Runner: `logs/step5-independent-artifacts-preliminary-v1.{json,log}`. Probe results and log SHA256: `64b7283b42adeb94e89a47f649f98788b49e77a292e1d8cb2c79f69d5a74368b`.

Findings were sent to root before any fixes; root owns issue filing and implementation.
