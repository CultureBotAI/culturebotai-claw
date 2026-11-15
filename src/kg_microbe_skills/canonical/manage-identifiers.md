---
name: manage-identifiers
description: "Assign, mint, and audit record identifiers in {{ display_name }}. Covers which identifier a new record gets, how to mint one when the corpus mints its own, and the hygiene checks — duplicates, format, collisions, and identifiers that changed. Use when adding or importing records, promoting a placeholder, or reconciling a collision."
category: workflow
requires_database: false
requires_internet: false
version: 1.0.0
tags: [identifiers, curation, provenance]
---

# Identifier management

- Repository: `{{ github }}`
- Records this governs: {{ record_globs }}
- Schema: {{ schema_paths }}

## The invariants

<!-- canonical:begin the-invariants -->
**Durable session state.**
Use the gitignored `<repo>/.temp/` as the durable work root for review campaigns,
worktrees, batch state, draft review bundles and handoffs. Use
`~/agent-work/<repo>/` when a separate clone is needed. Verify `.temp/` is ignored
before use; provision a missing ignore rule through an authorized repository
change. Keep maintained helpers and accepted evidence in their native tracked
directories; a durable scratch root does not replace their provenance contract.

Never store session state or helper scripts in `/tmp/`, `/private/tmp/` or `$TMPDIR`.
Only disposable caches and pytest temporary fixtures may use system temp roots.
Use a unique subdirectory for each task and preserve other sessions' state.

Report every auxiliary clone for identity verification and inventory in
session_repository_roots, and owned campaign/handoff directories in
session_state_paths. Missing inventory is unknown, not healthy. Report new paths
to the supervisor/operator; do not edit live configuration or expand authority.

For authorized Git work, push each committed batch branch to `origin` the same
day, whether or not a PR is opened. Verify the exact pushed head with the remote;
a local commit or remote-tracking ref alone is not publication proof. Inspect
the repository's current workflow triggers before claiming a branch push runs
no CI. A goal delivering commits cannot close while recorded commits exist only
locally. Publication failure is a retained blocker, never permission to discard
the branch. This rule grants no Git mutation, merge, cleanup or provider
authorization beyond the task and the skill's existing boundaries.

Three rules hold in every Mech, whatever scheme it uses:

- **An identifier never changes once assigned.** Anything that cited the old
  value now points at nothing, and the fleet is built on cross-repository
  citation. If a record turns out to denote something else, that is a new
  record and a retirement, not an edit.
- **An identifier is never reused.** A retired id stays retired. Reuse is worse
  than a dangling reference, because a dangling reference is detectable and a
  silently repointed one is not.
- **Exactly one slot is the identity.** The schema marks it `identifier: true`.
  A record may carry many other CURIEs — grounding targets, cross-references,
  registry accessions — and none of them is the identity, however similar it
  looks.

The third is where corpora actually go wrong. A record whose `identifier`
happens to equal its ontology grounding is not thereby an ontology record: the
two fields answer different questions, and they are allowed to diverge.
<!-- canonical:end the-invariants -->

## Choosing a scheme

<!-- canonical:begin choosing-a-scheme -->
Several legitimate schemes are used below. This is an open set of examples,
not an exhaustive taxonomy. A corpus's scheme is its own policy, not a fleet
convention:

- **Minted sequential.** `<RepoName>:NNNNNN`, zero-padded, assigned in order and
  never reused. Right when the corpus defines entities nobody else has defined,
  so there is no upstream id to adopt.
- **Minted stable slug.** `<RepoName>:stable-slug`, assigned once under the
  native naming/collision rules. A later label or filename change does not
  rename the identifier. Right when a corpus uses readable local names without
  a sequential counter.
- **Upstream-first.** The record carries the ontology's own CURIE as its
  identity, with a minted prefix reserved only for entities the ontology does
  not yet cover. Right when an upstream ontology already enumerates the domain
  and the corpus is curating against it.
- **External CURIE with placeholder.** The identity is whichever external CURIE
  best denotes the thing — several prefixes in play — with a local placeholder
  for records not yet resolved, promoted to the real CURIE when they are. Right
  when the corpus is a mapping product: the identity *is* the mapping.

Adopting the wrong one is expensive to undo, because of invariant one. Decide
from the corpus: does something upstream already name these things?
<!-- canonical:end choosing-a-scheme -->

## Do not describe another repository's scheme

<!-- canonical:begin describing-siblings -->
**State this repository's scheme. Do not state a sibling's.** A sentence about
how another Mech mints ids has no check on it, and the sibling will change
without telling you.

This is not hypothetical. Measured on 2026-09-04, **three of the four** existing
copies carried false claims about their neighbours:

- one asserted that MediaIngredientMech "mints its own `<RepoName>:NNNNNN`
  sequential IDs" — MIM has **zero** such identifiers, and its own skill records
  that the legacy sequential id was deliberately removed;
- another described MediaIngredientMech as a "single-file collection" — it is
  2,952 separate YAML files;
- the third, and the origin of the pattern, is a document titled "Identifier
  Management for X-Mech Repositories" that lives inside a single Mech, declares
  its scope to be "all X-Mech repositories", and works its examples in
  `MediaIngredientMech:000001`.

All three were accurate about some earlier state and rotted in place. Each copy
is right about itself and wrong about its neighbours — the predictable result of
writing down something nothing verifies. The generic one rotted worst, because
breadth is exactly what nothing checks.

If a cross-repository fact matters, cite the check that establishes it rather
than the fact: `kg-microbe-skills check` for references, the sibling's own
schema for its identity slot. A pointer stays true; a copy does not.
<!-- canonical:end describing-siblings -->

## Hygiene

<!-- canonical:begin hygiene -->
Whatever the scheme, the same four things go wrong and are worth checking
before a batch lands:

- **Duplicates.** Two records claiming one identity. The corpus can no longer
  answer which one a citation meant.
- **Format.** A padding, prefix or case that differs from the rest. `CHEBI:1234`
  and `chebi:1234` are the same term to a reader and two strings to everything
  else.
- **Collisions on import.** A batch that mints from a stale high-water mark, or
  adopts upstream ids that already exist in the corpus.
- **Changed identifiers.** The invariant that is hardest to see, because the
  diff looks like an ordinary edit. Compare against the previous release, not
  against the working tree.

A gap in a sequence is **not** a defect. Retirement leaves holes, and a run that
closes them has renumbered records, which violates the first invariant.

**Record the retirement rather than merely permitting it.** A retired id that is
simply absent makes every citation to it fail silently; a recorded one resolves
to a retirement a reader can act on. The shape that works, which one Mech in the
fleet already operates:

- retirement is written down, not implied by absence;
- a successor claim requires an *established* successor — one for a merge, two
  or more for a split;
- when no successor is established, say so and **do not guess a redirect**. A
  wrong redirect is worse than an honest dead end, because it resolves.

Where that record lives and what columns it has is this repository's business;
that it exists is not.
<!-- canonical:end hygiene -->

## This repository's scheme

This section is {{ display_name }}'s, and it is the part worth reading. State
which scheme this corpus uses and why, the exact identity
slot, the prefixes actually in play with their counts, and the command that
mints or validates. Give a worked example using a real identifier from this
corpus.

If this corpus mints sequential ids, say where the high-water mark is read from.
For stable slugs, state the native collision and retirement rules. If it adopts
upstream ids, say which ontology and what happens when a term is absent. If it
uses placeholders, say the format and what promotion looks like.

## Related

- `kg-microbe-skills check` validates that every path and sibling-skill
  reference in `.claude/` resolves, which is the check that would have caught
  the rotted cross-repository claims above had they been references rather than
  prose.
- The `id-label-correspondence` skill governs a different question: whether an
  identifier carries its own correct label. Identity and labelling are separate
  failures — a record can have the right id and the wrong label, and the reverse.
