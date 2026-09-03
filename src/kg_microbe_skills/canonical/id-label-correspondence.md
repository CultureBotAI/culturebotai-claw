---
name: id-label-correspondence
description: "Validate that every ontology ID in {{ display_name }} carries its correct ontology label, across both curated records and published products. Checking that an ID resolves is not the same check. Uses LinkML schema bindings for record YAML (canonical label) and the shared OAK validator for products (canonical or synonym). Run report-then-enforce; triage each row as wrong-label or wrong-id."
category: validation
requires_database: false
requires_internet: true
version: 1.0.0
tags: [ontology, labels, validation, provenance]
---

# ID↔Label correspondence

- Repository: `{{ github }}`
- Records this checks: {{ record_globs }}
- Schema: {{ schema_paths }}

## The invariant

<!-- canonical:begin the-invariant -->
Every ontology **ID** must carry **its own correct label**, everywhere it
appears — curated records and published products alike.

That an ID *resolves* is a different, weaker check, and passing it proves
almost nothing. `CHEBI:26710` is a real term whether the record calls it
"sodium chloride", "NaCl", or "magnesium sulfate"; only the last is a defect,
and only a label check can see it.

The reason to care is what a wrong label usually means. A stale label beside
the right ID is a cosmetic defect: the record still denotes the right thing.
**A label that names a different term is evidence the ID itself is wrong**, and
then every downstream consumer has silently been given the wrong entity.
The label is the cheapest available witness to an error in the ID, which is
what makes this worth enforcing rather than tidying.
<!-- canonical:end the-invariant -->

## The hybrid policy

<!-- canonical:begin the-hybrid-policy -->
The two surfaces are held to deliberately different standards:

- **Label slots in curated records must be the canonical ontology label.**
  Nothing else. The source's own spelling, an abbreviation, a formula or a
  project name goes in the sibling `preferred_term` or `synonyms` slot, which
  exists for it. A record is where the fleet asserts identity, and one spelling
  per term is what makes two records comparable.
- **Label columns in published products accept the canonical label or an exact
  or related ontology synonym.** A product is a surface other people read, and
  the conventional surface form is often a synonym. Forcing canonical there
  would reject correct data.

This is a real distinction and not a leniency gradient. If it reads as "records
are strict and products are lax", the second rule is being misapplied: a
synonym is *accepted evidence of the same term*, and anything that is not a
name for that ID fails in both places.
<!-- canonical:end the-hybrid-policy -->

## The two engines

<!-- canonical:begin the-two-engines -->
**Engine A — LinkML-native, for record YAML.** The schema marks each label slot
`slot_uri: rdfs:label` and gives the term-bearing slot a range-less `binding`
(`binds_value_of: <id_field>`). `linkml-term-validator validate-data --labels`
then resolves the id's canonical label through OAK and fails where the asserted
label differs. The check lives in the schema, so it holds for anything that
validates against the schema rather than only for what a script remembered to
walk.

**Engine B — the shared OAK validator, for products.** A vendored script walks
the surfaces the repository declares, resolves canonical label plus synonyms
from OAK, and reports drift. It is vendored byte-identical across the fleet and
governed from claw: change it there, not here, or the next synchronization
reverts the edit and the repositories stop agreeing about what a mismatch is.

A prefix with no configured OAK adapter is reported as skipped, not as a pass.
That distinction matters when reading a clean report: an unadapted prefix was
never checked, and a report that conflated the two would count silence as
agreement.
<!-- canonical:end the-two-engines -->

## Rollout: report, then baseline, then enforce

<!-- canonical:begin rollout -->
**Do not add these gates to `qc` first.** Turning enforcement on over an
existing corpus fails on drift that predates the gate, and the usual next step
is to weaken the gate until it passes — which leaves a check that cannot fail
and a repository that believes it is checked.

The order that works:

1. Run the report. It writes a drift file and never fails.
2. Triage every row, using the section below. This is the actual work, and it
   is curation rather than mechanical repair.
3. Only once the drift is cleared, add the validators to `qc` and flip the CI
   workflow from non-blocking to blocking.

A repository partway through this is in a legitimate state, and should say
which step it is on rather than implying the gate is live.
<!-- canonical:end rollout -->

## Triage: wrong label, or wrong ID

<!-- canonical:begin triage -->
A `MISMATCH` says the asserted label is not a name for that ID. Two root
causes, and they are not equally serious:

- **Right ID, stale or wrong label.** The record denotes the right term and
  says the wrong thing about it. Replace the label with the canonical one and
  move the previous surface form to `preferred_term` or `synonyms`, where it is
  still recorded rather than discarded.
- **Wrong ID.** The label describes a *different* term, and it is the label
  that is telling the truth. Fix the ID. This is the serious case: until it is
  fixed the record asserts an identity nobody intended, and everything built
  from it inherits that.

Deciding which one you have means reading the record, not the row. The
mismatch cannot tell you which half is wrong.

An `ID_NOT_FOUND` is neither: the CURIE is absent or obsolete in the ontology,
so there is no correct label to compare against. Re-map it.
<!-- canonical:end triage -->

## How this repository runs it

This section is {{ display_name }}'s. Record the real commands, the recipe
names, and which step of the rollout above this repository is currently on —
report-only, baselining, or enforcing in `qc`.

Name the label-bearing slots this repository actually has and the products it
actually publishes, with the declared surfaces file if there is one. Give a
worked example with a real CURIE from this corpus: a template's example is
never the one someone recognises.

List the prefixes that have no OAK adapter here, so a reader can tell a skipped
prefix from a checked one without running anything.

## Related

- `kg-microbe-sssom check --mech {{ mech_key }}` judges the mapping files this
  overlaps with: the columns every published file carries, a `curie_map`
  covering the prefixes actually used, and confidences in range. A row
  recording no match has no object, and two rows asserting the same triple
  with different `mapping_justification` are independent evidence rather than a
  duplicate.
- claw publishes the reusable label-correspondence workflow that gives this
  check its shared CI shape. It is a workflow_call workflow, so it only ever
  runs from a caller; claw can check its shape and nothing more, which is why
  it stays experimental until a Mech calls it.
