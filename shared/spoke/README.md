# Spoke-only vendored files

Canonical copies of files that are byte-identical across the **spokes**
(MediaIngredientMech, CommunityMech, TraitMech) but do **not** exist in the hub.

## Why these cannot live in `shared/idlabel/`

`shared/idlabel/` mirrors CultureMech, and `scripts/audit_idlabel_fleet.sh`
audits every copy against `CultureMech@main`. That model requires the hub to
hold the canonical bytes.

These files break that assumption for a good reason. `check_vendored_sync.sh` is
what a *spoke* runs to diff itself against the hub. The hub has no copy and must
not get one: it would then check itself against itself at a pinned ref, which is
the self-referential pin CultureMech deleted (TraitMech#182, TraitMech#176).

So the hub's absence is an invariant, not a gap — and
`audit_idlabel_fleet.sh` asserts it rather than assuming it.

## What is here

See `MANIFEST`. Adding a file means putting the canonical bytes here at the same
relative path a spoke uses, and listing it.

`.github/workflows/vendored-sync.yaml` is **not** here yet. The three spokes'
copies share byte-identical logic but differ in comments that name each repo's
local gate, so they are not yet vendorable. Normalising them is the remaining
half of TraitMech#209; the mechanism to hold them exists once that is done.

## Direction

claw is still a **mirror, not the canonical source** (claw#19, claw#22). For
`shared/idlabel/` the source is CultureMech. For this directory there is no hub
copy to mirror, so claw holds the reference by necessity — which is a narrower
claim than claw being the fleet's canonical home, and does not revive claw#21.
