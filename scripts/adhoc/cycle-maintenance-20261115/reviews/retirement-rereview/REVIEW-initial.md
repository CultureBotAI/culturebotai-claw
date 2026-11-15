# Independent clean-worktree retirement review

2026-11-15. Read-only review of helper SHA256
`b1819e118861c2ba019406b711fbb342e11769662f07dc232173a2d2b61eb3d5`
and fixture suite SHA256
`55df5fa942732167cbaad664cff22ca174dded74f58531bc58a9af8c7419cbb9`.
No task worktree, real local branch, remote ref or runtime was changed.

One confirmed blocking finding: proof parsing and hash capture use different
reads. `inspect` parses the proof before inventory, then hashes another read
after its reader probe. `fast_recheck` authenticates the latter hash but validates
the earlier parsed proof. A changed or revoked operator attestation can therefore
be accepted while the helper reports successful readback.

Distinguishing offline reproduction: a probe changes `owner_complete` from true
to false during the first inventory probe. All fixture repository facts remain
valid. A regression expecting `Refusal` fails because `retire(..., apply=True)`
removes the miniature fixture worktree. Original production source is unchanged.
This is a binding failure within the documented trusted-operator boundary; it
does not require forged GitHub proof or another agent to be contacted.

The existing 15 offline fixtures pass independently. An additional partial-failure
fixture passes: failure at the second reader probe retains preserved extra bytes,
the recovery ref, the original local branch and worktree, and a failure journal.
The retained driver `verify_retirement_review.py` plus initial/results.json and
logs bind exact source and reproduction hashes. The failed proof regression is
a verified finding, not a credited passing test. Root and author were notified;
root owns issue filing and author owns the repair.

The reviewed design otherwise checks exact task/worktree/common-Git paths,
registered head and branch, public origin identity, merged ancestry and fresh
trusted proof, index equivalence, sparse flags, tracked bytes/modes, ignored and
untracked descendants, symlink targets, nested Git boundaries, operation markers,
reader-probe completion and late arrivals. Extras are renamed into exclusive
same-filesystem quarantine and hashed outside short metadata leases. Removal
uses Git without force, exact-old-tip branch deletion and a retained recovery
ref. Primary clones and dirty snapshots remain outside this helper's scope.

Limitations: owner completion and actual GitHub merge proof remain explicit
trusted operator inputs; the helper is not a cryptographic remote attestation.
The lsof probe and cooperative lease cannot exclude a new noncooperating writer
after the last observation. No live cleanup, native runtime, remote merge or
current owner release was exercised or inferred. Repair and independent rereview
are required before using this helper on task checkouts.
