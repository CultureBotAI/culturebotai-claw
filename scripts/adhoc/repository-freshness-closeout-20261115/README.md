# Repository-freshness archive verification, 2026-11-15

This bundle addresses [issue #1252](https://github.com/CultureBotAI/culturebotai-claw/issues/1252)
for [PR #1138](https://github.com/CultureBotAI/culturebotai-claw/pull/1138).
`verify_release.py` reads existing local Git objects and public GitHub GET
responses. It writes a new receipt only; it does not fetch, generate candidates,
install, adopt, merge, publish, deploy or send session input.

The exact archive input is `d8d3b2ba8f101be2e2bc44aee57ef0525c0b7d53`, whose
parent is `9f7376b9045ec5ff898abbbef4d2b585951a1226`. The four candidate/proposal
hashes are fixed in the helper and independently compared with those Git blobs.
Every tracked input-head file and mode is checked against the worktree. This
does not claim that the old feature branch has integrated today's main.
`verification.json` records the observed main, input head/tree, source PR and
tree, release/tag/asset identities, downloaded audit digest, all 18 payloads,
historical/released fleet hashes, original canonical generator hash and this
helper's hash. It contains public provenance only.

The helper was adapted from the published
[AssayMech verifier](https://github.com/CultureBotAI/AssayMech/blob/aabe5bbcc46b451a2573252ba9d4f8e453fddba8/scripts/adhoc/repository-freshness-closeout-20261113/verify_release.py),
SHA-256 `515a89bcaef809a559013a81f942a59ad9304964b1968873fbe50ba62a59fa47`.
Packaging changes bind Claw's exact archive, preserve its different historical
manifest, remove Assay's helper archive/native-adapter dependency, and compare
the original input tree rather than asserting current-main integration.
The independent initial review helper remains separate evidence, SHA-256
`a2c80aef61b032d2a4fd6a31878e81f3a6352a41e84d602f65bede7a71a8847c`;
this is a new verifier, not a replacement for that historical evidence.

To reproduce, use an identity-verified clone with the recorded archive,
historical and released source objects and current main already present.
Choose a new output path; the helper refuses to overwrite an existing receipt:

```bash
uv run python scripts/adhoc/repository-freshness-closeout-20261115/verify_release.py \
  --repository-root "$PWD" \
  --output scripts/adhoc/repository-freshness-closeout-20261115/verification-new.json
```

The release remains mutable. A moved tag, missing object, changed observation,
altered archive, missing/extra audit payload or mismatched asset fails closed.
Publication verification is distinct from a new reviewed adoption decision;
`installed`, `adopted` and `runtime_authority_granted` remain false. The original
proposal flags and all four file bytes are preserved. No whole-source equality,
release-immutability or tag-protection guarantee is asserted.
