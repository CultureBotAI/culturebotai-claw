# ID/label validator compatibility mirror

This directory remains the isolated test layout for the pre-Phase-1 ID/label
mirror. Its five payloads are byte-identical to their canonical copies under
`src/kg_microbe_governance/artifacts/`, where they are part of the complete
shared-artifact manifest.

The layout mirrors a Mech's `scripts/` and `tests/` directories so the existing
behavioral tests can resolve `../scripts/` unchanged. The scheduled
`id-label-canon` workflow continues testing this compatibility copy during the
coordinated migration.

Do not originate changes here or add files to the old `MANIFEST`. Canonical
changes start in `src/kg_microbe_governance/artifacts/`, update the digest in
`vendored_artifacts.json`, pass the installed-wheel and offline synchronization
tests, and are rolled to all five Mechs with an exact claw commit pin.

Until the downstream rollout completes, the old fleet audit still compares
this directory and legacy consumers to CultureMech. That temporary comparison
does not make CultureMech the new-code authority: it prevents an unpinned gap
between the bootstrap and final authority commits. Once every Mech pin is
verified, the final flip removes this mirror and the legacy hub contract.

See
[`docs/guides/VENDORED_GOVERNANCE.md`](../../docs/guides/VENDORED_GOVERNANCE.md)
for the manifest, dry-run/apply commands, rollout order, and rollback.
