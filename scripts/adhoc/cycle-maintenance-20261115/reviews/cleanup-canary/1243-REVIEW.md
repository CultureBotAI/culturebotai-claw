# Independent cleanup canary review: PR #1243

PASS at 2026-11-15T09:50:18.430038+00:00. All 3,045 preserved entries across
5 roots match the recorded complete inventory, including hashes, modes and
symlink targets. All 1,697 recorded tracked paths match the source recovery
commit. The five preserved roots include the task's ignored temporary evidence.

The worktree and its Git registration directory are absent. The registration
census changed from 9 to 8: only this target was removed, and every other
registration was unchanged. The checkout was detached; the cleanup deleted no
local branch. Recovery ref and source commit remain available in the retained
common Git directory.

A fresh public API read verified merged PR #1243 source
`04e14f6c0fe4c4e7e4aaa8da0b765546fdc9afa3` and merge
`5de2dfad3e0859acb8f3df4e3da744a49883f9f8`. The remote PR branch is absent; its deleting
actor was not verified. No space reclamation or environment execution is claimed.

The verifier is unchanged from commit
`59bce0f5f785936bd0552841e56d77beced52c02`, SHA256
`ac422830ec1719f2acdc6a1a9be52a8428277dc0b8112656bf826856d7bed348`. Inputs, private/public receipt hashes and
projection details are recorded in 1243-PROVENANCE.json. The earlier canary's
helpers and results remain unchanged. No cleanup or GitHub mutation was performed
by the independent reviewer.
