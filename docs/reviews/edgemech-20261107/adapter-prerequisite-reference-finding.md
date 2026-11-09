Native adapter prerequisite references still point to admission PR #953 after
the shared contracts were separated into contracts-only PR #962.

The final read-only dependency audit found the stale reference in HabitatMech
PR 2313's body. TaxonMech's unpublished validation receipt used the same
reference. The immutable shared source pin remains
`1b5391d083ba85ac94e5279c3cba25ac4fde243c`; this is a dependency-description
correction, with no assertion or export changes.

Update the adapter PR descriptions to identify #962 as their shared-contract
prerequisite. Retain corrected body files with the implementation evidence.
Keep #953's admission-specific work and its separate blockers out of the
native adapter prerequisite chain. The historical Habitat receipt may retain
its original PR reference if the corrected active PR description makes the
new dependency explicit; no expensive scientific export needs rerunning for
this metadata correction.
