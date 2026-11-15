# Independent current-main integration reviews

Both local refreshed heads pass independent source review against main
`bd2b07480afd3b3984491a7fc729c64220d4dd81`. No blocking integration finding was
confirmed. Publication and hosted final-head/queue checks remain the owner's
next operational checks; these local receipts do not claim those checks ran.

| PR | Reviewed head | Tree | Independent focused validation |
| --- | --- | --- | --- |
| #1197 | `748cfaf510e96ffa6f8b4b08c877742cf8a492d8` | `f8d88d90cc6fb1c63b8adf8696cea978104b6c56` | 215 passed in 13.56s; no failures, errors or skips |
| #1138 | `285e2b3fb2810f1ddc0bbafdd6b338fd953b0140` | `a659ae65c4a6064a03d81a1a9e1fa4614cdc666d` | 53 passed in 31.64s; no failures, errors or skips |

Each is an ordinary two-parent merge of its previous reviewed head and the
specified main. The verifier independently reconstructed the entire expected
tree from main and the retained PR changes, then compared every tree entry.
It read back every tracked worktree blob/mode before and after testing. It did
not call merge-tree --write-tree or write any Git objects or references.

For #1197, the seven original non-catalogue paths remain exact. The catalogue
contains only the two previously reviewed reason-field changes over current
main. The baseline remains byte-identical, SHA256
`67b52e3880438c827458241c366bdf8005efacbbdaec8664180b9bb7d746c424`, version1.0.0,
source `66e6c6a15ff05a098bcb275686bcc6d74b20eaeb`. All60 authority inputs match
both that immutable source and the refreshed tree. The maintained baseline
check and refresh preview agree exactly; no unnecessary source pin was invented.

For #1138, all nine reviewed archive/provenance/test paths remain byte- and
mode-identical to the reviewed original and previous integration. The original
four inert candidate files and dated release-verification receipt are preserved.
#1138's diff against current main contains only those nine paths; it installs
no active policy, changes no adoption flag and installs no runtime hook.
Historical release verification was not rerun or relabeled as a fresh release
audit merely because main advanced.

The helper accepts explicit expected heads and a new output directory. Counts
come from completed pytest JUnit output; failures, errors, skips and empty
collection cannot yield a success proof. Full raw logs/JUnit remain private and
are bound by the public proof hashes. Both public proof JSON files are exact
copies of the generated receipts and contain no local paths.

No source edit, Git/GitHub mutation, environment update, deployment, native
canary, runtime adoption or cleanup was performed by this reviewer. Existing
helpers and prior evidence remain unchanged; PROVENANCE.json records the new
review helper's relationship to them.
