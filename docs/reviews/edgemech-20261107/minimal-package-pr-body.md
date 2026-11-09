MIM's native EdgeMech adapter cannot install the full CLAW distribution without
conflicting with its LinkML constraint. Add a minimal distribution built from
17 exact canonical Git blobs: base identity/artifact/native validators require
only JSON Schema; review and ledger validation remain an optional LinkML 1.10
extra. Provenance and installed import-origin checks prevent source shadowing or
silent contract forks.

Depends on shared-contract PR #962. This PR targets main so the authoritative
fleet audit continues to execute protected base code; its shared-contract diff
is the already-reviewed #962 prerequisite. It performs no index publication or
MIM dependency change. Advances CultureBotAI/MediaIngredientMech#1144, which
remains open for permanent adoption and distribution policy.

Validation: fresh source archive and wheel; a clean six-package native-only
environment validates the real three-row MIM canary; a separate installed
reviews environment passes 148 canonical native/artifact/contract/ledger tests.
All 17 source files and 13 optional-runtime module origins are verified. The
11 packaging regression tests and lint pass. CI repeats both isolated installs.

Independent read-only adversarial review filed #985 for incomplete optional
review-runtime proof. The repair adds all-module origin verification, positive
review/ledger suites and two support-shadow regressions. Both regressions fail
when an isolated mutation restores the old gap; independent re-review passed.
Evidence: docs/guides/MINIMAL_CURATION_DISTRIBUTION.md.

Fixes #985. All merges remain subject to explicit human approval.
