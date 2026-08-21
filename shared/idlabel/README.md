# id↔label validator — CI-verified mirror

This directory is a **CI-verified mirror** of the id↔label validator and its
chemical-formula plausibility helper, which are vendored byte-identical into the
five Mech repos (CultureMech / MediaIngredientMech / CommunityMech / TraitMech /
proteintraitsmech).

**The machine-canonical fetch-hub is the public `CultureBotAI/CultureMech`, not
this repo.** culturebotai-claw is private, so the Mechs' CI (they are public)
cannot fetch raw content from it. Each Mech's `scripts/check_vendored_sync.sh`
therefore diffs against `CultureBotAI/CultureMech` at the commit pinned in its
`scripts/.vendored_canon_ref`; a nightly `vendored-fleet-audit.yml` in
CultureMech historically compared the Mech copies this way too (see below —
this claw-side audit has since superseded it; CultureMech's `.github/workflows/`
no longer has a workflow under that name as of this writing, tracked in #92).

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

## How drift is caught

One check, `scripts/audit_idlabel_fleet.sh`, run by the `fleet-audit` job in
`.github/workflows/id-label-canon.yaml` nightly at 06:41 UTC and on any PR
touching this directory or the script.

It asserts both directions against `CultureBotAI/CultureMech@main`:

1. all five Mech repos carry byte-identical copies of the five validator files
   plus `mech_shared.yaml` (path-mapped to `src/<pkg>/schema/`), and
2. this mirror carries byte-identical copies of the five validator files.

It also reports any **tracked** file under `shared/idlabel/` that `MANIFEST` does
not list, since such a file is audited by nothing and vendored nowhere while
looking canonical.

That is 29 comparisons (5 files × 4 non-hub Mechs + 1 mapped entry × 4 + 5
mirror-vs-hub). It supersedes two earlier checks that asserted the same
invariant from two repos: this workflow's `matches-hub` job (mirror only) and
CultureMech's `vendored-fleet-audit` (Mechs only).

**`MANIFEST` is the single list.** The audit reads it rather than restating it,
and refuses to run against a missing or empty manifest instead of cheerfully
reporting zero comparisons. Adding a vendored file means editing `MANIFEST` and
nothing else.

**Consolidating the audit did not move canonicity.** CultureMech is still the
hub and this is still a passive mirror (claw#19, restated in claw#22). The audit
runs here because one enforcer is easier to reason about than two; it still
compares everything against CultureMech.
