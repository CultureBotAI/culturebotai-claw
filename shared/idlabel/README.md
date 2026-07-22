# id↔label validator — CI-verified mirror

This directory is a **CI-verified mirror** of the id↔label validator and its
chemical-formula plausibility helper, which are vendored byte-identical into the
four Mech repos (CultureMech / MediaIngredientMech / CommunityMech / TraitMech).

**The machine-canonical fetch-hub is the public `CultureBotAI/CultureMech`, not
this repo.** culturebotai-claw is private, so the Mechs' CI (they are public)
cannot fetch raw content from it. Each Mech's `scripts/check_vendored_sync.sh`
therefore diffs against `CultureBotAI/CultureMech` at the commit pinned in its
`scripts/.vendored_canon_ref`; the nightly `vendored-fleet-audit.yml` in
CultureMech compares all four copies.

This mirror exists for two reasons: a documented, human-readable home for the
shared set, and an isolated test-runner (`id-label-canon` CI runs the vendored
tests here without a full Mech checkout). To stop it becoming a second,
divergent "source of truth", the `matches-hub` job asserts it is byte-identical
to `CultureMech@main` on every change — if the two diverge, claw CI fails.

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
in each Mech fetches these files from `CultureBotAI/CultureMech` (the public
fetch-hub) at the commit pinned in `scripts/.vendored_canon_ref` and
byte-compares — a Mech that edits its copy fails CI, because the reference lives
in another repo.

## Changing a vendored file

1. Land the change in the fetch-hub, **`CultureBotAI/CultureMech`**, on `main`.
2. Sync this mirror (`shared/idlabel/*`) from `CultureMech@main` in claw so the
   `matches-hub` CI job stays green.
3. In each other Mech, sync the changed file(s) and bump
   `scripts/.vendored_canon_ref` to the new CultureMech commit — the deliberate
   propagation act. Use the `cross-mech-sync` skill.

Nothing but that sync keeps the copies aligned; the retired per-Mech sha256 pin
verified a copy against itself, not across repos, which is why the cross-repo
reference (against CultureMech) exists.
