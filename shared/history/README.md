# Shared curation-history layer

Canonical home of the append-only provenance layer ported from
monarch-initiative/dismech. Records answer the one question nothing else in the
fleet does: **which model, using which tool, changed what, why, and under which
issue.**

## What lives where

| Piece | Path | Consumed how |
|---|---|---|
| LinkML schema (canonical) | `shared/history/history.yaml` | vendored byte-identical into each adopting Mech |
| Scaffolder + validator | `src/kg_microbe_history/` | `PYTHONPATH=<claw>/src python -m kg_microbe_history` |

This mirrors `kg_microbe_kgscan`: one implementation here, thin per-repo justfile
recipes in the Mechs.

## The vendoring split, and why

The schema is **vendored** into each Mech; the scaffolder is **not**.

claw is private and the Mechs are public, so a Mech's CI cannot check claw out
without a token. Validation must therefore work from a local schema copy — and it
does: `linkml-validate --schema <vendored> --target-class HistoryRecord <files>`
needs nothing else. Scaffolding is a dev-time action where a claw checkout is a
fair assumption, so `just new-history` resolves the library through `CLAW_SRC`
and **fails loudly** when it is missing rather than skipping.

That fail-loud choice is deliberate. A skip-when-missing variant of exactly this
pattern is what let TraitMech's `vendored-sync` job pass while checking nothing
(TraitMech#182).

## Adoption status

| Repo | Vendored schema | Recipes | Advisory CI |
|---|:--:|:--:|:--:|
| TraitMech | yes — `src/traitmech/schema/history.yaml` | yes | yes — `curation-history.yaml` |
| CultureMech | not yet | not yet | not yet |
| MIM | not yet | not yet | not yet |
| CommunityMech | not yet | not yet | not yet |

TraitMech is the pilot. When a second repo adopts, add `history.yaml` to the
vendored-fleet drift check (`audit_vendored_fleet.sh` + each spoke's
`check_vendored_sync.sh`) so the copies cannot silently diverge — and note the
`trigger_paths` gap tracked in MIM#160 / CommunityMech#280 / TraitMech#184 applies
to any new vendored file too.

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

**`details` is required.** A record without it is just a timestamp. The CLI
refuses to build one, and writes a TODO placeholder when you omit `--details` so
the omission is visible rather than silent.

**The path is the last stdout line.** Everything human-facing goes to stderr, so
callers can capture the record path directly:

```bash
p=$(just new-history --kind record --slug foo --summary "..." --details "...")
```
