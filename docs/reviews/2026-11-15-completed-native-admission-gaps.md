# Retire completed native admission gaps

Issue: [CLAW #1226](https://github.com/CultureBotAI/culturebotai-claw/issues/1226).
Checked on 2026-11-15 against CLAW
`271fbbdb7f63e60b3771d5e28d398395da1d13cc`.

The committed default branches below now carry every governed artifact path
that CLAW declares applicable to them. Each snapshot was cloned with
`--filter=blob:none --no-checkout --depth 1 --branch main`; its `origin/main`
was compared with the GitHub main commit before running the existing
`git ls-tree`-based completeness checks. No downstream checkout was edited.

| Consumer | Verified default-branch commit |
| --- | --- |
| CultureBotAI/CofactorMech | `1af737829b74a619610a7ee81972357d7fe178fd` |
| CultureBotAI/AssayMech | `2c39f17bfcd940c15c6f10dfdc26b4ce2d6e734e` |

Only these two obsolete `INCOMPLETE_CONSUMERS` entries are removed. The normal
artifact-presence guard, exact-gap mechanism and synthetic negative tests are
preserved. The new offline regression feeds a complete inventory through each
consumer's ordinary completeness check, so CI detects a reintroduced stale
exception even without downstream clones.

## Validation

With `COFACTORMECH_ROOT` and `ASSAYMECH_ROOT` pointing to the verified snapshots:

```bash
uv run --no-sync python -m pytest tests/test_vendored_consumer_completeness.py -q
```

- Before the change, selecting `-k 'cofactormech or assaymech'` reproduced the
  four failures reported in #1226: the ordinary and known-incomplete checks
  failed for each consumer because its missing-artifact list was empty.
- After the change, the complete test file passed: **49 passed, 1 skipped**.
  The skip is the empty known-incomplete parameter set, not either completed
  consumer's ordinary check.
- Mutation: restored the exact original two entries from the pinned CLAW
  commit, retained the new regression, and ran the selected tests in a fresh
  pytest process. **Six failures** resulted: the original four plus both new
  offline cases. The fixed file was restored immediately afterward.

This verifies artifact-path completeness. It does not assert byte equality,
capability enablement, coordinated release, or runtime adoption. Other locally
configured consumers exercised by the test file were not independently
refreshed for this narrowly scoped change.
