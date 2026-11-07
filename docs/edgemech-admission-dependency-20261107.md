# EdgeMech admission requires a successor to the frozen DUF cycle release

Adversarial review of #953 for #766/#767 found a policy dependency introduced by
#924. The immutable `mech-cycle-v2-canary.json` binds release
`c26f3a0906916f9641a5f82b004b5541ae5fbe52`, the DUF lane, and the existing
14-consumer fleet. `cycle_release_audit.py` requires current governance manifest
and payload bytes to equal that release and all fleet identities to equal its
consumer roots. EdgeMech admission and native-test applicability scoping both
change those bytes. Disabling a capability does not resolve the membership rule.

The historical policy must not be rewritten or its checks weakened. Keep the
shared identity/review/artifact additions in a contracts-only PR with no fleet,
registry, or rollout changes. Keep #953 and the companion site admission draft
dependent on a separately reviewed successor/admission policy after the active
DUF lane has an approved transition. Do not automatically repin the 14 consumers.

Acceptance criteria:

- Preserve the historical policy and its provenance checks unchanged.
- Document completion/transition authority for the active release.
- Define an additive, versioned admission policy that makes the eligible cohort,
  consumer payload pins, native-test applicability, and trusted audit roots explicit.
- Run one end-to-end EdgeMech consumer synchronization/audit canary before any
  broader rollout, then verify candidate and trusted fleet gates.
- Keep #766 fleet admission and site publication pending until explicit merge
  approval; standalone storage, native exports and census may proceed.
