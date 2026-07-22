# id↔label validator — canonical source

This directory is the **single canonical copy** of the id↔label validator and
its chemical-formula plausibility helper, vendored byte-identical into the four
Mech repos (CultureMech / MediaIngredientMech / CommunityMech / TraitMech).

Before this existed, one Mech (CultureMech) was the hub and the others pinned
it. That worked but privileged a data repo as the home for shared tooling.
culturebotai-claw is the coordination repo across the Mechs, so the shared code
lives here now; no Mech is canonical.

## Files (canonical)

| file | role |
|---|---|
| `scripts/validate_id_label_correspondence.py` | the validator (Engine B) |
| `scripts/chem_formula.py` | element-multiset plausibility helper |
| `tests/test_id_label_empty_adapter.py` | validator unit tests |
| `tests/test_id_label_unknown_prefix.py` | validator unit tests |
| `tests/test_id_label_plausibility.py` | plausibility-gate tests |

The layout mirrors a Mech's own (`scripts/` + `tests/`) so the vendored tests
resolve the validator at `../scripts/…` unchanged, and so `id-label-canon` CI
here runs the exact tests the Mechs run.

## How the content was chosen

All four Mech copies were byte-identical when this canonical copy was seeded
(the "merge from all Mechs" was trivial — they already agreed, having just been
converged). Seeded from `CultureBotAI/CultureMech@main` at that point.

## How a Mech consumes it

Each Mech keeps a synced copy under its own `scripts/` + `tests/` (its CI runs
the validator locally and has no claw checkout). `scripts/check_vendored_sync.sh`
in each Mech fetches these files from `CultureBotAI/culturebotai-claw` at the
commit pinned in `scripts/.vendored_canon_ref` and byte-compares — a Mech that
edits its copy fails CI, because the reference lives here.

## Changing a vendored file

1. Change it **here** (this directory), land it in claw `main`.
2. In each Mech, sync the changed file(s) from claw and bump
   `scripts/.vendored_canon_ref` to the new claw commit — the deliberate
   propagation act. Use the `cross-mech-sync` skill.

Nothing but that sync keeps the copies aligned; the per-Mech pin verifies a copy
against itself, not across repos, which is why this cross-repo reference exists.
