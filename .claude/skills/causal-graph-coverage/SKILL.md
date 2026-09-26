---
name: causal-graph-coverage
description: "Assess what fraction of each Mech's records carry a causal graph, which records are declared not to need one, how many graphs each record carries and of what kind, and the graphs' size, evidence, grounding and structural findings. Runs kg-microbe-graph coverage over the manifest-declared fleet. Exemptions are explicit per-Mech rules in the fleet manifest, never inferred from a record being a parent class or a habitat. Read-only."
category: quality
requires_database: false
requires_internet: false
version: 1.0.0
tags: [causal-graph, coverage, statistics, quality, fleet, read-only, reporting]
---

# Causal-graph coverage

## Purpose

Answer "how much of this corpus has a causal graph?" in a way that survives
the three things that make the naive answer wrong:

1. **Some records should not have a graph.** A deprecated record, a relation
   carrier, a concept that turned out not to be a habitat. Those leave the
   denominator — but only through a rule the Mech's manifest declaration
   names, with the source that justifies it.
2. **Some graphs are not mechanisms.** A NONMECHANISTIC topology graph, or an
   interaction list with no causal edge, is not the same as a mechanism.
3. **Some records need several graphs.** An ASSEMBLY and a FUNCTION graph, one
   BIOACTIVITY graph per target, a Rhea reaction plus its M-CSA catalysis.
   Presence alone does not say whether those are there.

The report is `kg-microbe-graph coverage`, configured per Mech by the
`causal_graph_coverage` capability in `src/kg_microbe_fleet/fleet.yaml`. The
mechanism lives in `src/kg_microbe_graph/coverage.py`; what counts as a graph,
an exemption or a mechanism in each corpus lives in the manifest.

## Parent classes and habitats are not automatic exemptions

This is the trap the skill exists to avoid, so it comes first. "General parent
classes and habitats don't need a causal graph" is true in some Mechs and
false in others, and the data says which:

| Mech | Parents / habitats | What the corpus shows |
|---|---|---|
| HabitatMech | every record is a habitat | 27 of the 32 graphs sit on parent classes; biome-level graphs are the curation pattern. The real exemption is `grounding_status=NOT_APPLICABLE`: the concept is not a habitat at all. |
| CellStructureMech | is-a parents, subcellular regions | 65 of 66 parents and 71 of 72 regions carry a graph. |
| TraitMech | upper classes, ECOLOGY habitat traits | Upper classes are exempt by the Mech's own priority config; ECOLOGY habitat traits all carry (NONMECHANISTIC) graphs and are not. |
| ProteinTraitsMech | EC and ARO parents | 699 of 741 ARO parents carry graphs. The 410 class-level EC numbers have none, but the Mech's backlog counts them as gaps, so they are not exempt. |
| TaxonMech | higher taxa, metagenomes | Higher taxa are never records. Nine metagenome and unidentified sample records look like the habitat case, but TaxonMech has not said they take no graph, so they are counted (the question is with its curators, #484). |

Measured 2026-09-25 against each Mech's `origin/main`. Re-run rather than
quote them. So: **never add a structural rule ("has children", "is in the
hierarchy", "is a habitat") as an exemption.** Add a rule only when the Mech's
own schema, documentation or tooling says records of that kind take no graph,
and cite that source in a comment beside the rule. A builder that merely skips
a kind of record is not such a statement; check whether the Mech's backlog
counts those records as gaps before calling them exempt.

## Before running: which checkout is being read

The report reads the configured working tree, like `kg-microbe-corpus`. A local
checkout can lag `origin/main` by a hundred commits, and a report on a stale
tree is a report on a corpus that no longer exists. Check first:

```bash
# Which Mechs declare a graph model, and where each checkout is (identity-checked).
uv run python -m kg_microbe_fleet list --capability causal_graph_coverage --format json
uv run python -m kg_microbe_fleet targets --capability causal_graph_coverage --dotenv .env
ROOT="$(uv run python -m kg_microbe_fleet targets --capability causal_graph_coverage \
          --dotenv .env | awk -F'\t' '$1 == "habitatmech" {print $5}')"
# An empty root means `targets` returned no checkout for habitatmech -- unset,
# or refused by its identity check (see its output above); `git -C ""` would
# otherwise act on claw.
: "${ROOT:?targets returned no checkout for habitatmech}"
git -C "$ROOT" fetch -q origin
git -C "$ROOT" rev-list --count origin/main --not HEAD   # 0 means current
```

If it is behind, either update the checkout (the `/fleet-pull` skill; that is a
change to the checkout's Git state, so ask first) or read a snapshot of
`origin/main` without touching the checkout at all:

```bash
# Named for the commit and extracted fresh: extracting over an older snapshot
# keeps records that upstream has since deleted.
SNAP="workspace/causal_graph_coverage/snapshots/habitatmech-$(git -C "$ROOT" rev-parse --short origin/main)"
rm -rf "$SNAP" && mkdir -p "$SNAP"
git -C "$ROOT" archive origin/main | tar -x -C "$SNAP"
uv run kg-microbe-graph coverage --mech habitatmech --root "$SNAP"
```

The command prints which commit it read on stderr: `HEAD <sha>`, plus whether
the record directories hold uncommitted or untracked changes, when the root is
itself a checkout; "not a git checkout (a snapshot?)" otherwise, as for the
snapshot above -- so name the snapshot's commit yourself. State which you read
whenever you quote a number. A root where the declared globs match nothing is
an error, not an empty corpus.

## Run it

```bash
uv run kg-microbe-graph coverage --mech traitmech            # one Mech, JSON
uv run kg-microbe-graph coverage --mech traitmech --summary  # one row
uv run kg-microbe-graph coverage --all --summary             # the fleet table
mkdir -p workspace/causal_graph_coverage
uv run kg-microbe-graph coverage --all > workspace/causal_graph_coverage/fleet.json
uv run kg-microbe-graph coverage --mech proteintraitsmech --sample 5000
```

Every record is parsed, so the two large corpora dominate a fleet run. A
corpus of 5,000 records or more is parsed in `--jobs` processes (default: up to
8), and the report is identical for any value: ProteinTraitsMech (about
430,000 records) took 206 s in one process and 74 s in eight on 2026-09-25,
TaxonMech (about 626,000) 560 s and 158 s.
`--sample N` reads the first N records in sorted order -- a different corpus,
which the report marks `sampled: true` and `--summary` marks with `*` -- so use
it to try a declaration, not to quote. `--summary` marks a row with `!` when
files were excluded from its counts, and says how many under the table.

Exit codes: `0` report produced (or the Mech declares no graph model and the
command printed why); `1` the report is **incomplete** — a record could not be
read, held no document at all, or did not have the declared shape (named
under `unreadable`, `empty` and `malformed`, and on stderr), or with `--all` a Mech could not be read or held
no records at its globs (named under `unavailable`); `2` bad usage, an
unresolvable or empty root for a single `--mech`, or a declaration the tool
cannot apply -- including one only the corpus refutes, such as a path rule that
reaches directories and no file. Do not quote a fraction from a run that exited `1` without saying
what it excluded.

## Reading the report

**`coverage`** — over the records that are *not* exempt:

| Field | Meaning |
|---|---|
| `eligible` | records minus exempt ones; the denominator |
| `with_graph` | at least one graph with at least one edge |
| `edgeless_only` | has graph entries, none with an edge — present but asserting no causal link (CommunityMech interactions with no `downstream`) |
| `no_graph` | nothing at all |
| `with_mechanistic_graph` | subset of `with_graph` whose graph scope is one the Mech names as mechanistic; `null` where graphs record no scope |
| `fraction_with_graph`, `fraction_mechanistic` | the two headline fractions, 4 d.p. |
| `graphless_but_referenced_elsewhere` | graphless records whose identifier is grounded in *another* record's graph: the mechanism may be modelled there |

`eligible = with_graph + edgeless_only + no_graph`, and
`records = eligible + exempt.records`, always.

**`exempt`** — records per rule, the first matching rule credited, zero
included (so a zero can also mean an earlier rule claimed every record this one
matches); and `with_graph`, exempt records that carry a graph anyway (TraitMech's
upper classes carry context graphs — not wrong, but worth knowing when a rule is
proposed).

**NONMECHANISTIC is its own number, not coverage and not exemption.** It means
"a mechanism does not apply" on TraitMech's reviewed records, "mechanism
deferred" on its proposed genomics systems, and "a topology graph instead" in
CellStructureMech. Report both fractions and let `strata` show which kind you
are looking at (TraitMech's `mapping_status` stratum separates its two
meanings exactly).

**`graphs`** — over every graph, exempt records included: `per_record`
(the multiplicity histogram), nodes and edges per graph (min/median/max, and an
edge-count histogram — a one-edge graph restates a single claim), evidence and
grounding counts, node types and top predicates (each `null` where the Mech
declares no such slot — not measured, not zero), `scopes`, and for each
declared facet the values per graph and the **combination each record
carries** (`ASSEMBLY+FUNCTION: 7`) — the answer to "does it have the several
graphs it needs?". A combination is a set of values: two FUNCTION graphs read
as `FUNCTION`, and how many graphs a record has is `per_record`.

**`structure`** — `kg_microbe_graph.audit` per graph, with the Mech's anchor
type. Each code is counted twice, as `findings` and as `graphs`, because
node-level codes (ORPHAN_NODE, UNREACHABLE_FROM_ANCHOR) and graph-level ones
(FRAGMENTED_GRAPH) are otherwise not comparable. `graphs_by_scope` splits them
by scope, so fragmentation a Mech's own audit deliberately skips for
NONMECHANISTIC graphs is still visible. The shared audit is stricter than some
native ones: it reports a fragmented graph NaturalProductMech's own test excuses
because the graph says it is partial. Report the finding and the Mech's rule;
do not call either wrong without reading the graph.

**`strata`** — every count broken down by each declared field (or
`@directory`). A headline that looks alarming is usually explained here:
in ProteinTraitsMech, which directories carry graphs at all is set by source,
and the stratum then shows the gaps left inside those that do (EC, BioLiP,
MetalPDB, ARO).

## What a "graph" is in each Mech

The authority is each Mech's declaration in `src/kg_microbe_fleet/fleet.yaml`
— the rules, and beside each one the source that justifies it. Every report
also echoes what it applied under `definition` (shape, graph slot, scope field,
mechanistic scopes, exemption rules, anchor types), so a saved report reads on
its own. In outline:

- **graph_list** Mechs (TraitMech, ProteinTraitsMech, AntibioticMech,
  CellStructureMech, HabitatMech, NaturalProductMech, TaxonMech) keep a list of
  graphs, each with `nodes` and `edges`.
- **CommunityMech** (`node_nested_edges`): the record is one graph —
  interactions are nodes and each lists the interactions it feeds as
  `downstream`. Edges carry no evidence slot, so evidence is not measured.
  Directed cycles are intended.
- **HabitatMech** graphs are authored as curation overlays and merged into
  records by the seeder; the report reads the merged records, so an overlay not
  yet merged is not counted.
- **CultureMech** (`not_applicable`) and **MediaIngredientMech** (`disabled`)
  have no causal-graph slot; each declaration says what their similarly named
  tooling measures instead.

## Declaring that a graph is not relevant

When a kind of record genuinely takes no graph:

1. Find the Mech's own statement of it — a schema enum description, a
   curation playbook, a documented policy. A builder that merely skips such
   records is not one: ProteinTraitsMech's EC builder skips class-level EC
   numbers while its backlog counts them as gaps (#470). If there is none, the
   exemption is a scientific decision for that Mech's curators, not for this
   report: file it there as a question.
2. Express it as one rule in `exempt_when`, with the quotation in a comment
   beside it:
   - `field=VALUE|OTHER` — a value at the path is one of these
   - `field~REGEX` — `re.search` on a value at the path (no surrounding
     whitespace; write `\s`)
   - `path:GLOB` — the record's path, with record-glob semantics (`*` does not
     cross a directory; a glob that reaches only directories is refused)
   A dotted path reaches every element of every list on the way, so
   `lineage.taxon_id=X` matches wherever X sits in the lineage. A boolean
   matches `true`, `yes` or `on` (or `false`, `no`, `off`) in any case, under
   either operator. Prefer a field the curators set
   over a path or a label pattern.
3. Run the report before and after. The rule's count, and `exempt.with_graph`,
   are the review evidence: a rule that exempts records carrying graphs is
   probably the wrong rule.
4. It is a change to claw's manifest: branch, PR, review. The tests check that
   every declaration can be applied, that each rule's field is carried by the
   corpus, and that each enum value is one the schema permits.

Records that need *more than one* graph are reported, not enforced: use the
facet combinations and the multiplicity histogram, and state the expectation
from the Mech's own documentation.

## Boundaries

- Read-only. It never writes a record, a schema, or a Mech's Git state.
  Updating a checkout, adding a disposition field to a Mech's schema, or
  editing records are downstream mutations under the cross-repository
  checklist in CLAUDE.md, each needing approval.
- It measures; it does not grade. There is no pass/fail threshold, and a new
  gate built on it lands non-blocking first.
- Coverage by inheritance (a species graph standing for its strains) and by
  reference beyond the one count above are not computed.

## Related

- `/schema-gap-analysis` — whether records match the schema the graphs live in.
- `/fleet-pull` — bring local Mech checkouts up to `origin/main`.
- `kg-microbe-corpus report` — per-field population, the same record walk.

## Tests

`tests/test_graph_coverage.py`: each distinction above against a fixture in
which the two sides differ, the manifest ledger, and — with Mech checkouts
configured — every declared field and exempted value against the real corpus
and schema.
