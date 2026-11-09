# Candidate completeness needs the explicit infrastructure bootstrap state

Read-only design review for #960 found another gate after the currently failing
release-policy assertion. `governance-fleet-audit.yaml` derives candidate roots,
clones newly declared EdgeMech main and runs
`tests/test_vendored_consumer_completeness.py`. That test requires every declared
governed path on main. EdgeMech main is the intentionally empty bootstrap commit
`e853bf22b9f708bfd381910107aec9283a3bcee3`; the reviewed files are in EdgeMech PR #2.
Fixing only the earlier frozen-manifest assertion would expose this later failure.

Implement #960's same explicit, versioned, exact-tip bootstrap distinction in
candidate completeness and trusted admission audit. It must inspect the real
Git identity and main tree and report pending admission with zero installed
artifacts, without claiming rollout or payload verification. Any changed main
tip, partial installation, unexpected identity or extra member must fail the
bootstrap path and require the complete installed-payload check. Do not add a
generic new-member exemption or repin the historical fourteen consumers.
