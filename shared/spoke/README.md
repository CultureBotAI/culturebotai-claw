# Legacy fleet-governance mirror

This directory is the bounded Phase 1 compatibility mirror for governance
files that were canonical in CultureMech. New authority lives in the packaged
`src/kg_microbe_governance/` tree and its single
`vendored_artifacts.json` manifest.

The legacy `MANIFEST` and `scripts/audit_idlabel_fleet.sh` remain operational
while existing Mech pins are migrated. They intentionally keep the old
CultureMech comparison direction during the bootstrap commit; changing that
direction before a public claw commit exists would create an impossible pin.
Do not add new artifacts here. The old checker launcher is deliberately no
longer in this mirror: its replacement has different bytes, so retaining that
one legacy comparison would make every possible incremental rollout order
fail. Current consumers still self-check their old launcher; the replacement
five-Mech pin audit gates the new launcher before the authority flip.

The packaged manifest additionally governs the previously missing shared
schema, provider behavioral contract, Edison helper applicability, complete
ID/label set, history schema, backlog-loop contract, and the new standalone
claw checker. The synchronizer derives exact consumer paths and identities from
the fleet-aligned manifest rather than this legacy list.

After every Mech—including CultureMech—pins and passes the immutable claw
bootstrap revision, the final authority flip removes this mirror and rejects
the old hub/spoke model. The rollout, commands, safety rules, and rollback are
documented in
[`docs/guides/VENDORED_GOVERNANCE.md`](../../docs/guides/VENDORED_GOVERNANCE.md).
