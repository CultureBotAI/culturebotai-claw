# Historical PR1112 verifier archive and source-loading limitation

Date: 2026-11-15. Issue:
[CultureBotAI/culturebotai-claw#1278](https://github.com/CultureBotAI/culturebotai-claw/issues/1278).
Classification base: `720776c99ba456e9c0ba3f2662ca7af162e25bd8`.
This additive note supersedes operational-reader interpretations of the retained
README and provenance, whose historical bytes are unchanged.

`verify_cleanup_group.py` is now preserved as
`verify_cleanup_group.executed.py.txt`, an inert historical source archive with
no replacement operational entry point. Only the filename changes. Its SHA256
remains `34d2ff30571e5a54a5c5c493a0418980de9bc154825194b1a65a459f55f4e33f`,
matching both the committed original and the privately retained `.py` copy.
The complete original four-file package also remains retained privately.
Historical references to the old filename map to the exact archive above.

The helper checks the retained reader source-file hash, then calls
`spec.loader.exec_module(reader)`, which independently loads source or cached
bytecode. The earlier source-hash observation is therefore not authentication
of the bytes executed by that loader. The historical `reused_reader_sha256`
and `reused_reader_unchanged` fields describe observed source identity, not a
cryptographic execution attestation. This rename does not repair the loading
mechanism. No actual misexecution or data loss is alleged.

The unchanged receipt records the 2026-11-15T10:35:32Z observation of 64,138
preserved entries across four completed PR1112 retirements and 85 retained
snapshot payloads. Inputs were the explicit task root, exact root-head advance
chain, quarantine manifests, operator proofs, restoration evidence and public
PR/ref reads. Output was a JSON receipt; the public version removed only
`private_detail`. Those dated observations remain available with the explicit
source-loading limitation above. They are not regenerated, extended into a
current-state claim or treated as new cleanup permission.

Unchanged historical identities:

| File | SHA256 |
| --- | --- |
| `README.md` | `1e55db2dbe2d8c4523736dd1d61a596ff4f2a0d297019b40456c516741ff2627` |
| `PROVENANCE.json` | `8bba758cd2dc51ad031f923d281ec50da46efd2f0912e03eec08be085555707c` |
| `VERIFICATION.json` | `2340b81491a420bad9cc39f07b5f0d7c3f43bdbd211abbb24be594f987f55f0a` |
| Private `verification-private.json` | `d2e1598175c21c51519248167c078846af0d150d4ad54aafb16be16d36259dd5` |

Validation of this classification is exact archive/original/committed-byte and
hash comparison, plus readback of the unchanged receipts and composition
history. No helper execution, actual inventory, cleanup or test rerun occurs.
Independent review of the exact archive and additive note precedes publication.
