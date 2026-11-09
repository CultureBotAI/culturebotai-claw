# Protected preparation names a fleet member in the generic workflow

The exact-head authoritative fleet-audit run for `90bf24612108653d0b608c3e1ab39042a90878f1`
failed `test_runtime_mech_checkouts_and_sparse_paths_come_from_manifest` with
183 other candidate-contract tests passing:
https://github.com/CultureBotAI/culturebotai-claw/actions/runs/42421302630/job/128550095493

The new historical-checkout guard directly names
`edgemech-infrastructure-admission-v1.json` in the generic workflow. The existing
manifest-derived fleet test correctly refuses an embedded fleet key, even
though this literal selects policy rather than a checkout. The workflow should
depend on the generic protected selector interface, leaving the specific
admission filename and consumer to the protected implementation.

Repair: detect the generic selector module only in the trusted checkout; older
trusted revisions without that module skip cleanly. The protected selector's
empty output means no admission and requires no fetch. Otherwise retain the
explicit exact-40-hex rejection before canonical-origin data fetch. Candidate
files never enable the step. Keep the existing manifest-derived test unchanged
and exercise both historical cases and malformed/valid output through the
actual shell step. No historical policy, scientific capability, source data
pin, consumer artifact or canary helper changes are needed.
