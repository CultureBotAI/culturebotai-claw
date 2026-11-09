Prerequisite read-only review for #767 at CLAW `c26f3a0906916f9641a5f82b004b5541ae5fbe52` found that historical native approvals do not target newly selected KG occurrence/claim IDs. Current curation v1 correctly requires canonical scientific review of those exact IDs/digests for retain/amend; canonical RecordReview also rejects deterministic reviewers claiming scientific review.

Adapters therefore need an explicit, versioned native-assertion envelope. Do not fabricate agent/human authorship, label a deterministic conversion an independent scientific review, or weaken the existing v1 retain/amend guard.

Acceptance: preserve native locator, exact payload, interpretation context, source/review/evidence hashes and input closure, inherited-review status, native withholding and limitations. Canonical occurrence bundles may remain deferred/withheld while the census separately reports eligible inherited assertions. Reject changed payload/evidence, incompatible scope, false exact identity and endpoint-only biological reuse. Missing native claim-specific review stays unavailable, not approved by record-level or cohort-level coverage. Keep shared schemas in CLAW and native scientific exporters in their owning repositories.

This applies first to the pinned MIM source at `1848b0fe521bc2462f165912fcf92d09ad9a8cec`, then to TraitMech, HabitatMech and TaxonMech under #767.
