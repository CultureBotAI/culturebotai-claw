# Hosted public-metadata diagnostic

Approved PR #1231 was queued at 2026-11-15T04:43:06Z but did not merge.
Its merge-group candidate `42e5678e6f5dc8c402c8ff6eb2aea305a011aed7`
failed the protected public-fleet step in run
[43677996526](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/43677996526)
at 04:45:25Z with `stage=public_metadata code=transport_refused`.
The protected runtime was still main `23899092a4a2aedf53ff4435c0bdc03ebd79e6be`.
The retained raw log has SHA-256
`9d6865c4587fde457a7a9ae26fb3c2c282861d4f9aab968b12b71dfaf5c64ae2`;
run metadata has SHA-256
`0f4dc08c0ab808c32f8acc6192d2d7bc0843e8796e405f8e2732755c2d9bf9c4`.
The existing issue owner is #1223. No cause, including rate limiting, has yet
been established for that failed request.

This separate diagnostic PR leaves the approved head `9bb2d052` unchanged.
Its new, nonauthoritative job makes one anonymous request for the manifest's
public AIMech consumer using the reviewed metadata client from #1231. It
records only confirmed public identity or the client's closed failure fields.
The native 30-second timeout, response bound and no-redirect policy remain.
There is no retry, credential, clone, protected-runtime substitution or change
to the authoritative audit. A refusal remains exit 2, with its receipt retained.

The no-network plan and one-request controls pass: **43 tests**, 3.35 seconds,
including the existing bounded diagnostics controls. Ruff and diff checks pass.
A separate read-only review found no actionable issue. Hosted execution is
pending at this checkpoint. Even a successful probe cannot retroactively explain
the failed request on another runner or authorize the protected merge gate.
