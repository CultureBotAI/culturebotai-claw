# Independent integration review, 2026-11-15

The four root-owned integration repairs pass this bounded re-review at the
source hashes in [verification.json](verification.json). Four regression tests
passed; four separate fresh-process counterfactuals restored a defect in memory,
and each corresponding test failed as expected. Source files were unchanged
throughout verification. This receipt does not accept a later committed head or
authorize release, adoption or runtime changes.

| Finding | Verified correction |
| --- | --- |
| [#1257](https://github.com/CultureBotAI/culturebotai-claw/issues/1257) | GraphQL selects check IDs inside the concrete union fragments. The original query failed against the actual API; corrected production-query readback succeeded. |
| [#1258](https://github.com/CultureBotAI/culturebotai-claw/issues/1258) | Final complete inventory rejects a terminal PR reopened as a draft and detects retained PR identity changes. |
| [#1259](https://github.com/CultureBotAI/culturebotai-claw/issues/1259) | Receipt collection preserves prior-goal backlog ownership using validated frozen membership; only new goal work contributes inferred current-goal associations. |
| [#1260](https://github.com/CultureBotAI/culturebotai-claw/issues/1260) | Both remote inventories are captured and validated before either is persisted, so a transient PR read failure leaves no partial scope and can retry. Established scopes still cannot be silently replaced. |

This reviewer independently examined remote observation, supervisor integration,
closure bounds, progress association collection and fleet limit parsing. The
pure PR-maintenance validator, LinkML schema and skill/guide changes were
authored by this reviewer and are expressly excluded from independent acceptance.
The complete final change still requires a separate final-head review.

## Retained helpers and provenance

[verify_review.py](verify_review.py) is the new portable re-review helper. It
reads repository source/tests, runs baseline pytest and four isolated in-memory
mutations, and writes a new receipt beside itself without overwriting an
existing file. Inputs and helper bytes are checksum-bound; raw pytest logs are
represented by hashes to avoid publishing local paths. Disposable subprocess
bytecode caches contain no session state. No live API call, Git mutation,
installation or session input occurs when running this helper.

```bash
uv run python scripts/adhoc/cycle-maintenance-20261115/reviews/cycle-preliminary/verify_review.py \
  --root . \
  --output scripts/adhoc/cycle-maintenance-20261115/reviews/cycle-preliminary/verification-new.json
```

[initial_reproductions.py](initial_reproductions.py) preserves the original
three offline reproduction cases. Its assertions demonstrate the old defects;
they are expected to fail against repaired source and are not the current
regression command. The only packaging edit is sorting imports for lint.
The original helper's SHA-256 is
`f30cc66fc0a89f412eb97acd9cc49357b6601b6f60a55680b9f8bad7bd5e22a8`.
The original helper/report remain retained separately; their hashes are in the
receipt. No original evidence was deleted or rewritten.

[graphql-proof.json](graphql-proof.json) is an unchanged, public-safe copy of
the initial API observation and corrected-query readback, SHA-256
`a6b1c36b1439c46a2f29be73db863965acf0afd1da1b00b0880e57dfc7b0f877`.
Those PR/check observations are dated evidence, not current check status.

Before packaging, the files were inspected for private paths, user email
addresses, credentials and private operations content. The public bundle
contains repository-relative source/test paths, public issue/PR identities,
synthetic test fixtures and hashes only.
