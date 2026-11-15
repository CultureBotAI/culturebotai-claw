# Public provenance readback review

2026-11-15. Bounded PASS; no blocking provenance or publication-hygiene finding.
The exact 29 reviewed files are hash-bound in verification.json. No reviewed
source, Git object/ref, GitHub state or runtime was changed, and no tests were
rerun merely to repackage their existing results.

Independent scope: the other authors' dirty-snapshot capture/probe provenance,
the four-file PR1138 refresh package, and the main-refresh review helper/proofs.
The reviewer authored repairs/1197-refresh and dirty-snapshot-independent; those
two packages received hygiene and exact-ledger readback only. This report does
not provide an independent behavioral approval of the reviewer's own helpers.

The PR1138 metadata archive, merge-prepared receipt and proof are exact copies
of the retained private originals. The historical archive is explicitly inert
and distinct from the later commit and validation. Test/failure log hashes match
the proof. It accurately separates prepared merge metadata from committed local
head285e2b3fb2810f1ddc0bbafdd6b338fd953b0140 and does not claim new hosted checks.
The source explicitly fetches/forecasts, prepares the merge under its lease,
and leaves the normal commit/hooks to the caller, as the README states.

The main-refresh helper c220e06bc566c4195743ac3f8495c14803ea48f07d87dd09476b82c8c5127322
reads source trees and files, reconstructs expected tree maps in memory, validates
the baseline, and derives test counts from JUnit. It refuses failed, skipped or
empty validation before issuing a proof. Both public proofs are byte-identical
to generated private originals. Their log digests match private logs and JUnit
counts: PR1197 has215 tests, PR1138 has53; both have zero failures/errors/skips.
The prior helper references also retain their recorded hashes. Local review is
explicitly separated from publication and later hosted/queue checks.

Dirty-snapshot maintained/executed/probe hashes, capture hashes, preparation hash
and private restoration-plan hash all read back exactly. The executed archive is
kept inert and helper evolution is explicit. Earlier independent source/plan
review remains applicable because those exact sources are unchanged. Initial
index drift is described as an unexplained refusal, with no invented cause or
lost-content claim; ignored descendants remain expressly unmeasured at that step.

All scoped public text was inspected and scanned, including untracked files and
hidden/ignored names inside these exact package roots. No personal email, private
absolute path, private operational history or credential value was found. The
email-shaped matches are only standard git@github.com SSH URL syntax. Snapshot
labels and public PR/SHA provenance describe this bounded maintenance task and
include no external session identity. Original private evidence remains intact.

The reviewer-owned packages' file ledgers and test-result copies read back
correctly. Their pending-review/publication language records handoff-time state;
it is not a claim that a later review or publication has already occurred.
