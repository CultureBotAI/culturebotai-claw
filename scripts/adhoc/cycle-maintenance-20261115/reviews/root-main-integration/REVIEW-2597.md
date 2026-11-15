# Independent combined-source review

Read-only review of exact source `2597b50f1cf9ee630316c880b43030e04cfac664`.
The combined production source passes this bounded review. A separate confirmed
procedural/provenance finding in the newly retained PR1197 integration helper
was filed as issue1270; it does not change the production-tree conclusion.

The complete ordinary merge tree at `8db30dad3d818d166b5ee23d64e1bcb22605fd94`
was reconstructed in memory from its exact parents
`4970c9c83a8cb1cc2ee06a85ccdbad08589c55e5` and
`bd2b07480afd3b3984491a7fc729c64220d4dd81`, using common base
`99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d`. All 31 incoming paths match their
expected main versions except the sole overlapping supervisor file. That file
matches the original cycle-maintenance supervisor with exactly the two expected
port-pressure edits applied. The complete final tree then equals that merge plus
31 new evidence/helper paths; no existing path was silently changed by the
post-merge evidence commit. No Git object, ref or index was written for this check.

The overlapping edits preserve `controller_config_path` alongside `binding_files`
when validating pressure configuration, and exclude both adapter-specific values
from policy normalization in the runtime method. The added cycle-2.1 functions,
separate frozen issue/PR scopes, exact-head dispositions, closure proof, owned
worktree preservation verification and reviewed boundary migration remain intact.
The core PR-maintenance, remote verification, workflow schema, closure and issue
triage modules are byte-identical to their previously reviewed 1d0034 source.
No new production interaction defect was verified.

Independent tests ran against an immutable Git archive of 2597, with the root
checkout and its running environment unchanged. All 317 focused tests passed
with no skips: PR policy, remote observations, parent-2.1 supervisor integration,
port-pressure supervisor integration and boundary-only behavior, closure shape
and issue triage. Existing distinguishing maintenance mutation checks are included
in that suite. This review is independent of production authorship; the reviewer
authored an earlier subset of the remote-verifier tests and does not claim those
tests were independently authored here.

Issue1270: the retained PR1197 helper's common Git argv disables hooks and signing;
its apply path invokes `git merge --no-ff` without `--no-commit` while the metadata
lease is held. An injected offline command recorder independently confirms all
four facts without touching Git, locks, network or runtime. The original helper
hash and command-record proof are retained. Valid tree/test evidence does not
convert that historical execution into the requested prepare-then-normal-commit
procedure. The root owns the exact-byte archival and documentation correction.

This report does not claim hosted final-head checks, fleet deployment, consumer
adoption, active-controller behavior or a native canary. Source-only review and
local fixture validation are the full scope. The separate archival rereview
records the subsequent uncommitted issue1270 packaging state and its hashes.
