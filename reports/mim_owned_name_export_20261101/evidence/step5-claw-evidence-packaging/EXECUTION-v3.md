# Step 5 portable evidence packaging, preparation v3

No repository package has been published. `selection.v6.draft.json` is the current explicit selection. `selection-v6-binding-check.json` records a read-only check of its current bytes, completed command/log pairs, receipt hashes, generated artifact triplet and native journal, accepted limitation report, and maintained source references. It is not a final-head review or scientific approval.

The package executable is `package_evidence_v3.py`. The original executable and original test files are preserved unchanged, with their checkpoint under `checkpoint-packager-v1/`. The v2 change accepts exactly `PASS` or `PASS_WITH_LIMITATIONS`; the latter additionally requires an explicit B4 limitation, missing-transform coverage, and an identical standalone coverage document. It does not turn a failure into a pass or add a scientific validation rule. `test_packager_v4.py`, `packager-test-v4.log`, and `packager-test-v4-results.json` retain all 15 synthetic controls, including refusal of FAIL, missing coverage, missing limitation, and changed standalone coverage. The first temporary-directory alias failure and subsequent passing tests remain available in the prior version evidence.

The current generation occurred at Claw `90d110e663c10146351b09ae98d387dabdec0b1c`. The later `a56f3ae4563619a5129ad944878c9205267315d6` commit changes only README mypy-target documentation; the selection binds all maintained references at that later commit. Final full-suite and safety coverage are still pending. The real full-suite-v3 parity failure, interruption receipts, and failed v3 acceptance remain selected with their dispositions.

After the root supplies the completed evidence and explicitly authorizes publication, append a new final selection with no pending inputs and a complete README. Do not overwrite a historical selection or assert a final check that has not completed. The sequence is:

```bash
python package_evidence_v3.py freeze --selection selection.final.json --output final-inputs.json
python package_evidence_v3.py publish --inputs final-inputs.json
```

Both commands are run from this preparation directory. Freeze is run-owned only; publish exclusively creates `claw-owned-name/reports/mim_owned_name_export_20261101` and refuses an existing destination. The publisher checks every original byte before and after copying. It uses deterministic gzip for payloads of at least 64 KiB and deduplicates identical payloads while preserving every original identity in the manifest. It never stages or commits.

Verify from the Claw repository, first without and then after root staging with `--require-tracked`:

```bash
python reports/mim_owned_name_export_20261101/verify.py verify \
  --package reports/mim_owned_name_export_20261101 --repository . --require-tracked
```

The portable verifier validates package membership, archive and decompressed hashes, original identities, explicit command/log and JSON bindings, candidate/sidecar/manifest linkage, native journal completion, acceptance status and limitations, and maintained source hashes. It does not rerun tests or confer scientific approval. Historical indexes retain their original identity and may list deliberately omitted duplicate fixture trees; the package manifest and explicit omission list define the portable selection.

The final package commit cannot be its own provenance input. Package inputs bind the actual implementation, generation and validation contexts and exact bytes. The independent review of the eventual committed head and PR body must remain external to the package to avoid self-reference. Likewise, do not insert the package's own resulting manifest hash into its README.

Issue #708 adds full frozen-plan equality to the hash-bound selection plus explicitly recorded run root, and exact packaged README equality. V2 and its independent failing proof remain unchanged. `revision-708/control-results-v2.json` records 21 passing checks, the original implementation failure, and four assertion-detected fresh mutants. The first control classifier diagnostic is retained separately. This is internal consistency under the stated trusted-caller boundary, not a signature or hostile-interpreter guarantee.
