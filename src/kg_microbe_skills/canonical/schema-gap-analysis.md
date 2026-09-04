---
name: schema-gap-analysis
description: "Find where {{ display_name }}'s schema, its records, and the code that writes them have drifted apart. Runs LinkML structural validation, histograms the errors, and classifies each along three axes so the fix lands in the right place. Analysis only — remediation is a separately authorized change. Use when a tolerant project validator reports clean while curation tooling writes keys the schema does not declare."
category: quality
requires_database: false
requires_internet: false
version: 1.0.0
tags: [schema, validation, drift, linkml, audit]
---

# Schema gap analysis

- Repository: `{{ github }}`
- Schema: {{ schema_paths }}
- Records: {{ record_globs }}

## Analysis only

<!-- canonical:begin analysis-only -->
This reads schemas, records and source. It does not rewrite a record, change a
schema, install a package, or call a network service — which is what makes
`requires_internet: false` accurate rather than aspirational.

An accepted remediation plan becomes a **separately authorized change**. Keeping
the diagnosis and the repair apart is what lets an audit run freely: nothing it
does needs approval, so nothing about it needs to be cautious.
<!-- canonical:end analysis-only -->

## The three axes

<!-- canonical:begin the-three-axes -->
Every finding belongs to exactly one of three axes, and naming it is most of the
work — because the axis decides *where the fix goes*, and the same error message
lands differently on each:

- **Schema.** The schema is wrong or over-strict. The records are right and the
  declaration does not admit them. Fix: relax, or add the slot.
- **Instances.** The records are wrong. The schema says what it means. Fix:
  migrate the records — through the Mech's own writer, never by hand.
- **Process.** The code that emits records disagrees with the schema. The
  records are wrong *and will be wrong again tomorrow*, because the writer is
  still emitting them. Fix the writer first; migrating without it re-creates the
  drift on the next run.

Misclassification is expensive in one direction especially. A process defect
filed as an instance defect gets a migration that works once and silently rots.
Ask which side a *new* record written today would land on.
<!-- canonical:end the-three-axes -->

## Quick pass and deep pass

<!-- canonical:begin quick-and-deep -->
There are two depths and one method, not two methods:

- **Quick** — structural validation, an error histogram, three-axis
  classification. Minutes. Answers "did my last change break something?" and
  serves onboarding.
- **Deep** — additionally scans the writers and pipeline for drift, produces
  reports, and leaves a re-runnable harness. Tens of minutes. Run it when you
  suspect systemic drift or before a release.

Both Mechs that hit this question resolved it, in **opposite and equally valid**
directions: one keeps two skills and documents when to use which; the other
keeps one and leaves a thin alias that routes to it, carrying no duplicate audit
logic. Either is fine. What is not fine is two skills that both claim to be the
complete procedure, because then neither is maintained.

State which resolution this repository chose, below, and where the other name
points.
<!-- canonical:end quick-and-deep -->

## Do not write down the state

<!-- canonical:begin no-snapshots -->
**Never record corpus counts, error tallies, or validation status in this
skill.** Read them from live command output every time.

This is not a style preference; it has been measured. One copy of this skill
carried a table headed "current state" with a dated pass: 2,943 errors across
4,289 records, led by 1,195 `date` → `timestamp` failures. Checked on
2026-09-04, that corpus holds 6,286 records — 46% more — and the headline defect
is entirely fixed, with zero records carrying the old key and all 6,286 carrying
the new one. Every number in the table was wrong, and nothing had flagged it,
because prose has no test.

One Mech reached this conclusion first and wrote the rule as an anti-pattern —
*do not present a snapshot count as current repository state* — then deleted its
own snapshot and replaced it with the commands that regenerate one. That is the
pattern to copy.

Describing a **class** of gap is useful and stable: what the error looks like,
which axis it usually belongs to, why it recurs. Describing *how many there are
today* is a claim with a short half-life.
<!-- canonical:end no-snapshots -->

## Anti-patterns

<!-- canonical:begin anti-patterns -->
- **Do not patch the permissive validator alone.** The point of running strict
  structural validation is to find what the tolerant one hides. Making the
  tolerant one quieter deletes the finding, not the defect.
- **Do not weaken a schema pattern to make a gate pass.** If the gate is wrong,
  say why and change it deliberately; if it is right, the records are the work.
- **Do not rename a slot without following the code.** Generators, validators,
  helpers and tests still reference the old name. Search for it before renaming,
  not after the suite goes red.
- **Do not repair records with `sed`.** Go through the Mech's own writer, so
  canonical formatting and derived collection metadata are preserved rather than
  quietly corrupted.
- **Do not hand-edit generated audit output.** Re-run its producer. An edited
  report is a report nobody can reproduce.
<!-- canonical:end anti-patterns -->

## How this repository runs it

This section is {{ display_name }}'s. Give the real commands — the validator
this project actually has installed, the recipe names, and how to histogram
errors. Say which record globs map to which LinkML tree-root class; a repository
with more than one record shape must validate each against its own root rather
than silently picking the first.

State which resolution this repository chose for the quick/deep question, and
where the other name points.

Record the gap **classes** this corpus tends to produce and which axis each
belongs to. Do not record how many there are — the section above says why.

## Related

- The `manage-identifiers` skill covers identity, and `id-label-correspondence`
  covers whether an identifier carries its correct label. Both are different
  failures from structural drift: a record can validate cleanly against the
  schema and still assert the wrong identity.
- claw publishes the fleet-wide version of this method, which resolves the
  applicable repositories and their schema and record locations from the
  manifest rather than from a list in any skill.
