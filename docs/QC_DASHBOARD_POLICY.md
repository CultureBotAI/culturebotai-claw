# QC dashboard artifact policy

The Mech fleet intentionally uses two publication policies for the shared QC
dashboard generator.

- TraitMech, MediaIngredientMech, and CommunityMech track
  `dashboard/index.html` and `dashboard/coverage.png`. A source or generator
  change must regenerate those artifacts in the same pull request. Staleness
  checks compare `index.html`; PNG bytes can vary across rendering stacks and
  are not a reliable CI diff gate.
- CultureMech does not track its dashboard. CI generates and publishes it from
  the authoritative corpus, avoiding a second committed copy of its large
  generated site. Reviewers inspect the workflow output rather than a source
  diff.
- ProteinTraitsMech has a distinct sharded browser and corpus-audit model; the
  four-Mech QC dashboard is not presented as a parity requirement there.

This difference is deliberate, not an unfinished migration. A repository that
changes policy must update its ignore rules, Pages workflow, and freshness gate
together.
