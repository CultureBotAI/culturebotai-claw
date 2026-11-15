# Dirty review snapshot preservation plan

Preparation only: neither snapshot was restored or removed. The associated PRs
were still open when their dependency receipts were captured. A separate
independent review, actual reviewed merge, fresh ownership/readers check and
exact source/index revalidation remain required before any action.

The first snapshot has15 staged paths and no unstaged or nonignored untracked
files. The second has7 modified tracked paths and12 nonignored untracked source
or fixture files. Original index bytes, changed HEAD/index/worktree blobs,
binary patches, modes and exact NUL-delimited restoration lists were captured
and read back in private bundles. All ignored roots remain in place; the first
snapshot additionally has an empty workspace/locks directory omitted by the
older plan. The later retirement inventory must preserve it too.

The private plan uses git restore only for the authenticated15 staged paths
(first snapshot, index and worktree) or7 unstaged paths (second snapshot,
worktree only). It leaves12 untracked files in place for the existing reviewed
retirement helper to quarantine with every other ignored/untracked extra.
It permits no broad clean, hard reset, forced removal or unrelated path change.

The initial second-snapshot capture refused because source index bytes changed
during inspection. No output bundle was created; the cause was not established
and no content loss is asserted. The exact executed helper is archived. The
maintained helper uses an authenticated private index copy for index-aware Git
queries; the subsequent probe and complete capture left source index bytes
unchanged. Original captures, refusal and probe evidence are retained privately.

PREPARATION.json records actual counts and hashes; PROVENANCE.json identifies
purpose, inputs, outputs and every executed helper. Helpers capture evidence
only. They do not restore source, change Git refs or perform cleanup.
