# Shared curation-history layer

Packaged operational mirror of the append-only provenance layer ported from
monarch-initiative/dismech. CultureMech is the machine-canonical schema hub.
Records answer the one question nothing else in the
fleet does: **which model, using which tool, changed what, why, and under which
issue.**

## What lives where

| Piece | Path | Consumed how |
|---|---|---|
| LinkML schema (packaged mirror) | `shared/history/history.yaml` | packaged with the CLI and fleet-audited against CultureMech |
| Scaffolder + validator | `src/kg_microbe_history/` | installed as `kg-microbe-history` |

This mirrors `kg_microbe_kgscan`: one implementation here, thin per-repo justfile
recipes in the Mechs.

## The vendoring split, and why

The schema is **vendored** into each Mech; the scaffolder is **not**.

Each Mech validates a local schema copy so its correctness gate is self-contained
and pinned rather than dependent on another repository's current branch.
`linkml-validate --schema <vendored> --target-class HistoryRecord <files>` needs
nothing else. The installed CLI carries claw's audited mirror as package data,
so its default validation path also works outside a claw checkout.

Spoke CI validates its vendored schema directly without any claw checkout.

## Adoption status

| Repo | Vendored schema | Recipes | Advisory CI |
|---|:--:|:--:|:--:|
| TraitMech | yes — `src/traitmech/schema/history.yaml` | yes | yes — `curation-history.yaml` |
| CultureMech | yes | yes | yes — `curation-history.yaml` |
| MIM | yes | yes | yes — `curation-history.yaml` |
| CommunityMech | yes | yes | yes — `curation-history.yaml` |
| ProteinTraitsMech | yes | yes | yes — `history-and-vendored.yaml` |

CultureMech's copy is canonical. `scripts/check_vendored_sync.sh` includes the
path-mapped schema in every Mech, while claw's single fleet audit compares all
five copies and this packaged mirror against CultureMech. A Mech's pinned ref is
the deliberate propagation boundary.

## Enforcement model

Copied deliberately from DisMech, which is asymmetric:

- **Presence: advisory.** CI warns when a data record changes with no history
  record, and passes. A hard gate on provenance blocks legitimate work at
  inconvenient moments and trains people to route around it.
- **Validity: blocking.** A record that exists must be schema-valid.

## Design notes worth keeping

**Filenames are unguessable on purpose.** `<TIMESTAMP>-<actor>-<shortid>.yaml`
with `shortid = secrets.token_hex(3)`, inside a directory per target slug. Two
agents curating the same record concurrently cannot collide, so the layer has zero
merge-conflict surface. A single shared changelog would conflict on every parallel
PR; this never does. Given the fleet routinely runs dozens of concurrent sessions,
that property is the reason to adopt this ahead of any agent workflow.

**`outcome` is orthogonal to `type`.** It lets you record a `REVIEW` that found
nothing (`no_change`) or an `EDIT` that hit a wall (`blocked`) without inventing
event types. `no_change` is a real result: it says something was checked.

**`details` is required, and the placeholder is rejected.** A record without it
is just a timestamp. The CLI refuses to build one, and when you omit `--details`
it writes a TODO placeholder that **`validate` then fails on** — so a scaffolded
record that nobody filled in cannot pass the gate. That case matters most for an
agent that scaffolds and never returns.

**Only `record` and `schema` targets can derive a path from a slug.** Mappings are
`.sssom.tsv`, reports `.md`, infrastructure a justfile or workflow — so those
kinds require an explicit `--path`. Records are append-only, which makes a guessed
extension permanently wrong.

**The path is the last stdout line.** Everything human-facing goes to stderr, so
callers can capture the record path directly:

```bash
p=$(just new-history --kind record --slug foo --summary "..." --details "...")
```
