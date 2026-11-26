# MIM stewardship report refresh — 2026-11-26

Purpose: render the bounded fleet-ops review while preserving a complete issue/PR
ledger and distinguishing routing from actual assessment. Related infrastructure
and publication scopes are MediaIngredientMech issues1431 and1450.

Inputs: the maintained acquisition helper's baseline, final issue delta/comment
pages/counts and PR details, prior routing plus its raw issue/comment snapshot,
explicit current decision data, and actual issue-comment receipt URLs. Outputs:
a new private directory containing review.json/review.md and issue/PR TSV ledgers.

The producer checks exact repository identity, independent final counts, unique
IDs, comment coverage, unchanged target PR heads and complete routing. It compares
prior bodies/comments before describing routing continuity, resets all prior
verdicts, and refuses unknown new routing or an absent target PR. It never makes
GitHub requests, executes a corpus validator, resumes a session or changes data.
The two current substantive issue decisions are explicit inputs; other routing
is not a scientific verdict. Use a fresh output directory for every execution.

This source was committed before use and is retained on an authorized branch.
No new PR or merge is part of this bounded fleet-ops task. Private snapshots and
reports remain under the steward's durable workspace; no private paths are
hardcoded in this source.
