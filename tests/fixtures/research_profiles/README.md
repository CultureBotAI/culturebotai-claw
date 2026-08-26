# Fleet research-profile fixtures

These files are test-only snapshots of each Mech's domain-owned
`conf/deep_research_provider.yaml`. They keep compatibility testing deterministic
when sibling repositories are unavailable in CI; they are not runtime defaults
or a new authority for Mech research focus.

Snapshot provenance (audited 2026-08-25):

- `culturemech.yaml`: CultureMech `0422968004b99c91ed356d6ee4e38b7e93f371d5`
- `mediaingredientmech.yaml`: MediaIngredientMech
  `82694054f5bbf74b5392bf8858c9962c2152a35a`
- `communitymech.yaml`: CommunityMech
  `ba596731b23b799f4baca96984ceb8f0d56874fe`
- `traitmech.yaml`: TraitMech `3ee94eeec831d98d2a2cc1ebe2368fe3fa122f69`
- `proteintraitsmech.yaml`: ProteinTraitsMech
  `a70ff8f5564b77a50963daafaacc2dde013eb1a2`

[`provenance.json`](provenance.json) records the repository, immutable commit,
source path, and SHA-256 digest for every snapshot. The fleet contract fails if
its exact Mech inventory or any fixture digest differs from that lock.

When an environment variable from the fleet manifest points to a local Mech
checkout, `test_research_fleet_contract.py` additionally compares the complete
parsed profile with its snapshot to expose downstream drift.
