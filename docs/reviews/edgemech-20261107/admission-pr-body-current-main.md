This PR adds the separately authorized EdgeMech infrastructure admission for
#766/#767 and #960. It preserves the historical DUF release declaration,
fourteen-consumer cohort, exact consumer pins and rollout rules. Only EdgeMech's
explicit identity, fleet entry and reviewed data pin are admitted; scientific,
execution and publication capabilities remain disabled or inapplicable.

Protected main advanced during the final review. A normal merge integrates
`081e9c8f44c5ce28849e162b7fecac1b3ba17ad7` and resolves #997 without discarding
main's future-payload publication behavior. The frozen admitted manifest is
separately packaged and SHA-bound to the unchanged declaration and actual
`7e672227fb246a8359ad57b6d3975ce5ed329007` Git snapshot. Current payload digests
may evolve only while authority/layout remain exact; they never replace the
historical or admitted consumer bytes. Activation still requires approved
protected first-parent history, and the exact empty bootstrap reports zero
installed artifacts until a complete installation is verified.

A real dry-run exposed #1004: the public sync planner still assumed every pin
matched the current package. Its repair admits only the exact Edge identity/ref,
authenticates every frozen source byte and uses the same immutable desired tuple
through planning, transactional apply and post-verification. Generic canonical
verification stays strict. The corrected real dry/apply canaries at `a099f255`
and EdgeMech `375a86e9` verified 19 working/committed artifacts and the pin,
persisted independently rehashed receipts and made zero changes. Candidate
verification does not activate admission. The failed attempt is retained.

Independent reviews passed. Local validation includes 124 focused policy tests,
nine public sync tests, 51 existing governance/transaction/sparse tests, complete
Ruff, affected-module mypy, an installed-wheel public-plan smoke and five targeted
mutation controls. #1006 records and fixes a mutation-harness import-path refusal.
The final complete suite and five CI checks run on the pushed candidate; the
exact-head result is appended to this PR's handoff after completion.
[Integration evidence](docs/reviews/edgemech-20261107/current-main-integration-validation.md)
retains the receipts and distinguishes historical passes from this validation.

Shared contracts remain independently reviewable in #962 at unchanged runtime pin
`1b5391d083ba85ac94e5279c3cba25ac4fde243c`. Storage/native census evidence belongs
to CultureBotAI/EdgeMech#2; companion membership is
CultureBotAI/CultureBotAI.github.io#541. No downstream repin, native curation,
deployment, force push or PR merge occurred. Merging requires explicit human approval.

Closes #960. Closes #982. Closes #984. Closes #986. Closes #988. Closes #989.
Closes #997. Closes #1004. Closes #1006.
