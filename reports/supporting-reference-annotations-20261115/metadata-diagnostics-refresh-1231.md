# Protected metadata diagnostics refresh

The human-approved diagnostics PR [#1231](https://github.com/CultureBotAI/culturebotai-claw/pull/1231)
merged at `2026-11-15T05:04:02Z` as
`4ed79ee03f42219de510b62c7ae1c4b35b0c11a6`. Its tree is identical to the reviewed
head `9bb2d05245489e8a02a9376978c829750ae45922`. The remote branch was removed
by GitHub; the local branch was removed after preserving its checkout and evidence
at that detached head. No live Claw deployment was updated.

The first queue attempt failed public metadata acquisition. One later queue
attempt passed the actual protected-main fleet audit and all required checks:

- [Governance run 43678658325](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/43678658325)
  passed the 17-public-repository audit at candidate `4ed79ee0`, with protected
  runtime `23899092a4a2aedf53ff4435c0bdc03ebd79e6be`. Its public receipt records
  `full_fleet_ok: true` and `public_component_ok: true`.
- [Tests run 43678658318](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/43678658318)
  reported 10,538 passed, 543 skipped, 391 warnings and two passed subtests.
  Total coverage was 87.30%; the safety-module check passed at 77%.

The successful retry does not establish the cause of the earlier transport
failures in [#1223](https://github.com/CultureBotAI/culturebotai-claw/issues/1223).
Those failures remain retained. The merged implementation adds bounded failure
diagnostics; it preserves the request and failure rules.

## SupportingReference branch refresh

Normal merge `7345431207d0c43773880f44db502d03d48b9fd6` has parents
`8e32614e59729539d824fef845cc344218c71c5c` and
`4ed79ee03f42219de510b62c7ae1c4b35b0c11a6`. The incoming changes are exactly the
four files from #1231. There were no conflicts or edits to SupportingReference
schema bytes, dependency pins, workflow authority, or consumer data.

On that combined source, the frozen offline environment passed **104 tests in
11.47 seconds** with:

```text
uv run --no-sync --offline --extra dev python -m pytest -q \
  tests/test_supporting_reference_annotations.py \
  tests/test_public_metadata_diagnostics.py \
  tests/test_discussions_public_export.py \
  tests/test_private_scaleup_audit.py::test_producer_version_requires_exact_authoritative_main_including_other_executable_files
```

Git whitespace validation passed for the incoming diff. Required CI must run on
the newly published head and bind its trusted runtime to the current protected
main. Prior successful suites do not transfer status checks to this head.
PR #1219 remains a separate, unmerged change requiring its own human approval.

## Retained evidence

The immutable raw queue artifacts remain under the diagnostics checkout's
`.temp/metadata-diagnostics-1223-20261115/mergequeue-002/`:

| Artifact | SHA-256 |
|---|---|
| Governance log | `0bfaf58485dae49fac3ad292624ba6e2abea961e94969855623bf829cc849705` |
| Governance metadata | `6fd6fd1c0bc629d8d170e8a6111da2ad684b9e12246952bd2a01f59089a26953` |
| Public fleet receipt | `2a59cd8fbf8d0a8fe50115829e15d8d77c5373cc064c6e76c719bde691f31eca` |
| Tests log | `edc30c4add05e2bf0868300baa991e53f026d0246fb727f068313e329e9c8304` |
| Tests metadata | `25fef13e5b37e2a9f34fb4fac663bcc8859a69b95b90556ca521574f9ebd0c90` |
