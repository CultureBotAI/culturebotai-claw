# Assay separate-admission proposal validation

This proposal starts independently from protected main ee3ae411 and binds only
Assay's published bootstrap 89bfceba and empty initial main a85aea61. Its source
manifest is retained verbatim; all payloads and 22 native obligations match that
published revision. The four original DUF/Edge release files are unchanged.
No Cofactor declaration, snapshot or fleet entry is included in this branch.
The explicit Cofactor descriptor remains dormant without its separate policy.

The initial registration suite passed 768 tests with 162 environment-dependent
skips, plus 21 critical integration checks. Seven registration mutations each
failed and passed after restoration. The inherited focused authority run passed
96 tests and exposed four fixture assumptions recorded in #1066. Corrected
Assay identity/current-payload fixtures and documentation parity passed 36 tests;
a separate positive canonical-equality case passed. No production authority
relaxation was needed. Thirteen authority/documentation mutations each failed
under the changed input and passed after source restoration.

Five combined-admission tests pass. Cofactor and Assay source commits originate
on independent branches and can each exclude the other new consumer while the
protected cohort composes both declarations. Crossed pins fail before any
artifact check. A second version of that fixture includes both consumers in
both frozen sources, with matching payloads, proving the pin refusal is not a
side effect of a missing identity. A fresh-process mutant accepting actual pins
makes five unauthorized installs falsely pass (historical Trait, DUF, Edge and
both crossed newcomer pins), and therefore all five regression cases fail by
assertion. Restoring the gate passes all five. A separate mutant requiring the
other newcomer in an independent snapshot fails the positive composition test;
restoring the supported subset contract passes it.

Full maintained Ruff and all 109 workflow mypy targets pass. Configuration
validation verifies the explicit Assay root. The supported synchronization dry
run at 89bfceba reports governed artifacts and pin current, with no writes.
All mutation source bytes were restored. The full coverage suite, hosted checks
and independent exact-head review remain separate pending gates at publication.
This receipt is not protected activation, queue authorization or a merge decision.
