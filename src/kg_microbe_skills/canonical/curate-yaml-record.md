---
name: curate-yaml-record
description: "Review and curate one {{ display_name }} record: verify what it denotes, check every scientific claim against an inspected source, resolve the gaps that evidence can close, and write back only through the path that records history. Use when asked to audit, improve, complete, correct, or add evidence to one named record. Not for bulk ingestion, generated-artifact edits, or as permission to spend credits, contact anyone, or mutate GitHub."
allowed-tools: Bash, Read, Grep, Glob, WebSearch, WebFetch, Edit, Write
metadata:
  category: curation
  requires_database: false
  requires_internet: true
  version: 1.0.0
---

# Curate one {{ display_name }} record

- Repository: `{{ github }}`
- Records: {{ record_globs }}
- Schema: {{ schema_paths }}

## The contract

<!-- canonical:begin the-contract -->
Produce a defensible record and an explicit account of four things: what is
**supported**, what was **corrected**, what is **still unresolved**, and what is
**genuinely unknown**. The last two are different — a gap you searched for and
could not close is a finding; a gap you did not look at is not.

**One target.** Resolve exactly one record before touching anything. If a label
matches several, or a request names a family rather than a member, stop and
disambiguate. Silently substituting a similar record is the error that no later
check catches, because everything downstream is then correct about the wrong
thing.

**Audit is read-only. Curation authorises edits to the named record only.** A
review or audit request changes nothing. A curate, improve, complete, correct or
add-evidence request authorises local edits to that record and the smallest
maintained path its provenance requires — not to neighbours, not to whatever
else looked wrong on the way.

**Search results are leads. Only an inspected source supports a claim.** A
search hit, a deep-research report, a rendered page, and a generated artifact are
each somewhere to look, and none is evidence. Evidence is text you read in the
source, attached to the narrowest assertion it actually supports.
<!-- canonical:end the-contract -->

## Boundaries

<!-- canonical:begin boundaries -->
- **A generated artifact is never the fix.** Pages, merged products, exports and
  derived indexes are outputs. Correct the input or rule that owns the value and
  regenerate; patching the output makes it look right once and diverge on the
  next build.
- **No outbound action without explicit authorisation for that action.** Do not
  launch paid research, contact an author, or create or edit a GitHub issue, PR
  or comment because curation seemed to call for it. Authorisation to curate a
  record is not authorisation to spend or to speak.
- **Absence is not evidence of falsity, and coverage is not a goal.** Never
  infer that an unstated optional property is false. Never fill an optional
  slot to make the record look more complete. An empty field the source does
  not address is correct.
- **Search before declaring anything absent — and search past `.gitignore`.**
  Before treating a record, evidence source, decision row or overlay as missing,
  search for its identifier, label and slug with an ignore-independent tool
  (`rg --no-ignore --hidden`, `grep -r`, or `find`). Ordinary search skips
  ignored files, so an ordinary miss is a search over a subset, not a result.
- **Preserve unrelated work.** Use a branch, and a separate worktree when the
  checkout is dirty or occupied by something else.
<!-- canonical:end boundaries -->

## Evidence standard

<!-- canonical:begin evidence-standard -->
- Each claim is its own object. A definition, an example, a relation and a
  mechanism edge are separate assertions; attach a source to the narrowest one
  it supports, never to the record as a whole.
- Resolve every DOI, PMID and CURIE, and read enough of the source to establish
  support for the *exact* claim and scope. A matching string from the wrong
  paper, or an unrelated sentence from the right one, is not support.
- A snippet is short verbatim text from the source. Interpretation belongs in a
  notes field, never inside the quotation.
- **The kind of source is part of the citation.** A database assertion, a
  primary experiment, a review, a prediction and a search snippet are different
  strengths of support. Cite each as what it is; never present a database row
  or a review as if it were the primary study.
- Association and prediction do not establish mechanism or causality. Do not
  let a co-occurrence or a computed score become a mechanism edge.
- **A near-miss is not a match.** Never ground to a CURIE or canonical label
  because it looks plausible, and never use a broader or related term as an
  exact identity. Unresolved stays unresolved, recorded as such, until a source
  resolves it.
- **Evidence about one thing supports a claim about that thing.** Do not
  generalise one organism, strain, protein instance, construct or experiment
  into a family-wide, universal or "optimal" claim. Scope inflation is the most
  common way a true observation becomes a false record.
- Keep conflicts. When sources disagree, record both and the disagreement; do
  not resolve it by omission.
- A bounded search that found nothing is a result. Report it as "not found,
  searched X" rather than leaving the field silently empty.
<!-- canonical:end evidence-standard -->

## Writing back

<!-- canonical:begin writing-back -->
**Write only through the path that preserves formatting and records history.**
Never hand-edit a curated YAML with a text editor or a generic dump: canonical
key order, quoting and derived metadata are what make the corpus diffable, and a
dump destroys them in one save.

Repositories in this fleet do this in three different, equally correct ways, and
which one applies is a property of the corpus:

- **Direct guarded write** — a narrowly scoped mutator loads the record, asserts
  its identity, changes only the reviewed nodes, appends a curation event, and
  writes through the repository's validated writer.
- **Registered editor** — no generic writer exists on purpose; in-place changes
  use text-preserving operations through an editor that is registered and
  behaviourally tested, and the writer audit rejects anything else.
- **Regenerate from inputs** — the record is a build product. The fix goes into
  the decision row, term request, overlay or source inventory that owns the
  value, and the record is regenerated; the YAML is never edited directly.

The section below says which one this repository uses and names the exact
functions or files. Do not guess from a sibling.

Inspect the diff before committing. Whole-file presentation churn — reordered
keys, requoted strings, a hundred lines changed to alter one value — means the
write path was bypassed; abandon and repair rather than commit it.
<!-- canonical:end writing-back -->

## History and attribution

<!-- canonical:begin history-and-attribution -->
- Use `curator="claude"` when no curator identity was supplied. **Never
  attribute an agent's judgement to the user.** The history entry is a record
  of who decided, and it will be read when the decision is questioned.
- Mark LLM assistance where the schema records it.
- **Do not append a history event when nothing substantive changed.** A
  no-op event is noise that makes real events harder to find.
- The history entry describes the actual diff. If the corpus derives status or
  history from inputs, never set them directly — change the input.
- A REVIEWED status means a human reviewed it. Do not invent one, and do not
  promote to it on the strength of an agent pass.
<!-- canonical:end history-and-attribution -->

## Workflow

### 1. Establish the baseline

Read the entire record and run this repository's schema and strict validators
on it before judging anything. A green schema gate proves shape, not scientific
correctness. Record what is there.

### 2. Verify identity first

This step is {{ display_name }}'s. Say what "the right record" means for this
corpus — which fields fix its identity, what it must not be confused with, and
which upstream identifiers must agree. Route identifier decisions to
`manage-identifiers` rather than restating that policy here.

### 3. Review every claim

This step is {{ display_name }}'s. Enumerate the claim types this corpus makes
and what each must be checked against. Say which source kinds count as primary
and which are only leads.

### 4. Assess completeness and resolve supported gaps

Apply this repository's review checklist. Use bounded, targeted searches for
consequential gaps, in priority order — identity and source first, then the
claims that change what the record means, then completeness. Record a
discussion or quality flag only for a concrete conflict or a consequential open
question, stating what was checked and what evidence would resolve it.

### 5. Write back

This step is {{ display_name }}'s. Name which of the three write shapes above
this repository uses, the exact function or file path, and any registration or
audit gate the write must pass. Give the real command sequence.

### 6. Verify and report

Re-run the focused validators, then the wider gates this repository's `qc`
defines, and read the emitted record again. Report: corrections and their
sources; retained claims and what they were checked against; unresolved gaps
and every bounded search that came back empty; which authoritative input each
change lives in; every validation result.

## Related

- `manage-identifiers` owns identity policy for this corpus; this skill routes
  to it rather than restating it.
- `id-label-correspondence` covers whether an identifier carries its correct
  label, which a record can get wrong while validating cleanly.
- This repository's own field-by-field review checklist sits in the references
  directory beside this skill. It is the Mech's, not claw's: the evidence
  standard above is canonical, the field table is not.
