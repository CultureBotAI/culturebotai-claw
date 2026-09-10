---
name: metpo-aggregate
description: "Merge every Mech's METPO proposal cohorts into one aggregate ROBOT template, and report where the fleet's shared METPO ID space contradicts itself. Runs scripts/fleet_metpo_aggregate.py, which resolves the proposing Mechs from the manifest's metpo_proposal capability and always reports its coverage. Read-only: it writes an aggregate into claw's workspace and never touches a Mech or submits anything upstream."
category: cross-repo
requires_database: false
requires_internet: false
version: 1.0.0
tags: [metpo, ontology, proposal, cross-repo, fleet, aggregate, robot, read-only]
---

# METPO aggregate

## Purpose

Answer **what would the fleet propose to METPO if it proposed once?** — and,
more usefully, **does one METPO identifier mean one thing across the fleet?**

Each Mech mints METPO IDs in its own repository, from one shared numeric space.
The canonical rules in kg-microbe say to "pick the next unused `1007NNN` slot",
which is only satisfiable by someone who can see every slot already taken. No
Mech can see another's, and until this existed nothing looked at two cohorts at
once.

## Run it

```bash
uv run python scripts/fleet_metpo_aggregate.py            # merge + report
uv run python scripts/fleet_metpo_aggregate.py --check    # report only
uv run python scripts/fleet_metpo_aggregate.py --json
uv run python scripts/fleet_metpo_aggregate.py --out DIR
```

Exit codes: `0` merged with no collision, `1` a collision or an incomplete
read, `2` bad usage or an unresolvable repository. **Exit 1 means the aggregate
must not be submitted.**

## Reading the report

### The collision section is the point

The merged file is the deliverable; the collisions are the reason to build it.
Two distinct defects, and they are not interchangeable:

- **ID MEANS TWO THINGS** — one identifier, two labels. Submitting both hands
  METPO contradictory definitions for one term. This is the one that is
  already true: the fleet carries eight, all CommunityMech's, split across its
  `metpo_communitymech_v1` and `metpo_communitymech_interaction_semantics_v1`
  cohorts. `METPO:1007214` is both `interspecies electron transfer` and
  `direct interspecies electron transfer community`.
- **LABEL HAS TWO IDS** — one term, two identifiers. Nothing is contradictory,
  but downstream data splits across identifiers that will never be reconciled.

A run with neither says so explicitly. Silence is not how "clean" is reported.

### Cohorts are additive, not successive

A version number here is **provenance, not supersession**. Measured across
TraitMech's eleven cohorts, the union of class IDs equals the sum of the
per-cohort counts and no two consecutive cohorts share an ID. Keeping only the
newest cohort would drop 145 of its 160 proposed classes.

So do not read `metpo_traitmech_v11` as "the current proposal". It is the
eleventh batch.

### Coverage

`declared by the manifest` and `read` are printed separately on purpose. A Mech
that declares the capability and could not be read appears in the first and not
the second, and the report says INCOMPLETE — its collision list is then a lower
bound, because a collision needs both halves to be visible.

## Who proposes

Membership comes from the `metpo_proposal` capability in
`src/kg_microbe_fleet/fleet.yaml`, not from a list in this skill. Two Mechs
enable it today. The rest declare `disabled` or `not_applicable` with a reason,
so a Mech that starts proposing is picked up by flipping one declaration.

MediaIngredientMech is `not_applicable` rather than `disabled`: it grounds
ingredients in ChEBI and FOODON, and METPO models phenotypes and processes,
which is not the axis that corpus curates.

## The ROBOT template shape

Every cohort's file carries a header row and a **template row** — line two,
holding the OWL mapping for each column (`A IAO:0000115`, `SC %`). It is not
data. The aggregate carries it exactly once, at line two, because ROBOT would
read a second copy as a class.

All fourteen cohorts agree on both rows today. If one ever disagrees, the
**majority shape wins** and the deviating cohort is named and excluded rather
than merged, because merging misaligned columns produces a file that looks fine
and means something else. If no shape has a majority the run refuses, since
there is then no basis for calling either one the deviation.

## Boundaries

- **It does not submit anything upstream.** The aggregate lands in
  `workspace/metpo/` (gitignored). Opening a METPO pull request is a human
  action against a repository outside this fleet.
- **It does not edit a Mech.** Fixing a collision means editing the cohort that
  is wrong, which is a downstream mutation under the cross-repository checklist
  in `CLAUDE.md`.
- **It does not decide which side of a collision is right.** It reports both
  labels and the cohorts they came from; which term keeps the ID is a curation
  judgement.
- **It is not the proposal-authoring skill.** TraitMech and CommunityMech each
  carry a `metpo-proposal` skill for writing a cohort, and the canonical rules
  live in `kg-microbe/.claude/skills/metpo-proposal/SKILL.md`. This aggregates
  what those produce.

## Related

- `metpo-proposal` in TraitMech and CommunityMech — authoring a cohort. The two
  copies have drifted from each other and neither is canonical.
- `kg-microbe/.claude/skills/metpo-proposal/SKILL.md` — the upstream contract,
  in a repository that is not a fleet manifest member.
- `fleet-pr-status`, `fleet-branch-status` — the other manifest-resolved fleet
  inventories, and the source of this one's coverage conventions.

## Tests

`tests/test_fleet_metpo_aggregate.py` covers disagreement rather than the happy
path, and every guard is mutation-checked — each of these turns at least one
test red when removed:

| mutation | tests red |
|---|---:|
| read the ROBOT template row as data | 4 |
| stop detecting one ID with two labels | 2 |
| stop detecting one label with two IDs | 1 |
| let a later cohort overwrite an earlier one | 1 |
| let the first file seen define the template shape | 1 |
| drop an unresolvable Mech silently | 1 |
| pick a shape when no majority exists | 1 |
| exit zero on a collision | 1 |
| write files under `--check` | 1 |
| read Mechs the manifest has not enabled | 1 |

Two of those rows exist because the first version of the test did not earn
them. The additivity test used two different IDs, so every dedup policy passed
it; it now uses one identity with differing columns, which is the only input
where first-wins and last-wins diverge. And the template-shape test had a
single deviating cohort sorting first, which crowned the deviation — the fix
was in the script, not the test.
