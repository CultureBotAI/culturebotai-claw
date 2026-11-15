# Historical verifier archive and source-loading limitation

Date: 2026-11-15. Issue:
[CultureBotAI/culturebotai-claw#1278](https://github.com/CultureBotAI/culturebotai-claw/issues/1278).
This additive note supersedes any operational-reader interpretation of the
unchanged historical README and provenance. It does not replace their bytes.

The source formerly named `verify_cleanup_group.py` is now preserved only as
`verify_cleanup_group.executed.py.txt` in this public package. It is an inert
historical source archive, with no new operational entry point. The filename is
the only change; SHA256 remains
`73666d8597569218bdccf56cbfa07820a23ca2c23447d39246a88b9b0bf09fe6`.
The original `.py` and a complete pre-correction package copy remain retained
privately. Historical filenames in README.md, PROVENANCE.json and VERIFICATION.json
refer to this exact archived source through the mapping above.

The helper checks the retained reader's source-file hash, then calls
`importlib.loader.exec_module`, which independently reads source or cached
bytecode. The source hash observation therefore does **not** authenticate the
bytes executed by that loader. Renaming the helper does not fix its loading
mechanism and does not establish a cryptographic execution attestation. The
historical `reused_reader_sha256` field identifies the observed reader source,
not authenticated executed bytes. No actual misexecution or data loss has been
identified by this source review.

The retained result records the dated read-only observation of 483 preserved
entries at 2026-11-15T12:00:37Z, with root snapshot
`720776c99ba456e9c0ba3f2662ca7af162e25bd8` and merged PR1197 source
`748cfaf510e96ffa6f8b4b08c877742cf8a492d8`. Its original inputs were explicit task,
reader, retirement-helper and second-common-Git paths; its output was a JSON
readback receipt. The public result removed only `private_detail` from that
private receipt. This packaging correction preserves those observations with
the loading limitation above. It makes no new inventory, cleanup, current-state
verification or permission claim.

Unchanged historical identities:

| File | SHA256 |
| --- | --- |
| `README.md` | `b6a7faf61626823c0a5c2683fe923ca434794d16377cdff80b3869cf08c6fd5b` |
| `PROVENANCE.json` | `5348aede8e85a3a8e123e518a03a5950be8a2eac9cacdf7b55c0ef61e5cf6d2c` |
| `VERIFICATION.json` | `ad635ed22ad66e605c0b46ce708770a2a9b1084bf556fb2e12ecde35bd042154` |
| Private `verification-private.json` | `5c557f596cdcc4d802e09ecd7a3279d717ab661aebd486d25cc3efb14564c71c` |

Correction validation consists of exact-byte comparison and hash readback,
including the private original and pre-correction copy. The earlier helper
source, results and composition history are unchanged. No helper execution,
actual reinventory, cleanup or test rerun was performed for this classification.
Independent review of this exact archive and additive note is required before
the owner commits the package.
