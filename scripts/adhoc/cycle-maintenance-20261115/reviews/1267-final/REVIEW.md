# Independent issue1267 test review

No verified finding in the proposed correction to
`tests/test_freshness_contract.py`. Reviewed base is
`1f8e0a0db3a83ddd70723a6cdf8f1d579b3da099`; the proposed uncommitted test bytes
have SHA256 `dad6cc46a80ada374efee1ebf26f43f225a12083c8ead128da9224728b9a3839`.
Final commit/head verification remains the owner's responsibility.

The corrected assertion distinguishes retained historical parent2.0 from the
current parent2.1. It preserves the existing v1 availability assertion, verifies
historical v2's exact original digest and version, and checks that neither
historical2.0 nor current2.1 implicitly adopts repository freshness.

Independently read the original current-parent Git blob from
`99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d`. It is byte-identical to retained
`src/kg_microbe_workflows/templates/mech-cycle-v2.0.yaml` at the reviewed base,
with SHA256 `0d3e218c22c4ffe4e6dcddce8287d0177aaa52f637e156df1c737e4e7d84f913`.

All17 focused tests passed in an isolated source archive. Appending a valid-YAML
comment to that archive's historical template changed only its bytes, not its
version/semantics; the exact compatibility test then failed at the digest assertion
in a fresh interpreter. Restoring the original bytes made it pass. This proves
the new regression distinguishes a changed historical artifact from the preserved
one, instead of merely checking the version string. The original root checkout
and proposed test file remained unchanged throughout.

The retained helper records exact original/proposed/test/archive/helper hashes,
control and mutation outcomes, and restoration. Raw logs and copied source stay
private; the public-safe proof includes no home paths, process identities or
private operation history. No runtime, GitHub or branch action occurred.
