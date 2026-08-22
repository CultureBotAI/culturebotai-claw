# Fleet-governance file mirror

Passive claw mirror of fleet-governance files that are canonical in
CultureMech and vendored byte-identical across all five Mechs.

## Why these cannot live in `shared/idlabel/`

`shared/idlabel/` mirrors CultureMech, and `scripts/audit_idlabel_fleet.sh`
audits every copy against `CultureMech@main`. That model requires the hub to
hold the canonical bytes.

The mirrored set covers the vendored-sync checker, Claude skill/command
frontmatter contract, deterministic curation-timestamp contract, and the
standard fleet backlog-loop prompt. CultureMech governs each canonical copy;
`audit_idlabel_fleet.sh` compares this mirror and every Mech copy directly with
CultureMech@main.

## What is here

See `MANIFEST`. Adding a file means mirroring the canonical bytes here at the
same relative path and listing it.

The claw repository is not a Mech and therefore does not carry the timestamp
schema test operationally. Its own `tests/test_skill_frontmatter.py` and
`prompts/backlog-loop-goal.md` are byte-identical operational copies. The fleet
audit compares those two files to this passive mirror as well as comparing all
five Mech repositories.

`.github/workflows/vendored-sync.yaml` is **not** here yet. Three of the four
spokes (MediaIngredientMech, CommunityMech, TraitMech) carry it as a standalone
file with byte-identical logic that differs only in comments naming each
repo's local gate, so they are not yet vendorable — normalising them is the
remaining half of TraitMech#209; the mechanism to hold them exists once that
is done. proteintraitsmech's equivalent gate is not a standalone file at all —
it is a job embedded inside a differently-named, differently-structured
workflow (`history-and-vendored.yaml`) — so it is not yet even comparable the
same way, let alone vendorable.

## Direction

claw is still a **mirror, not the canonical source**. CultureMech is the source
for both `shared/idlabel/` and this directory; the fleet audit enforces that
relationship rather than relying on prose.
