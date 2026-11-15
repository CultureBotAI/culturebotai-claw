# Final publication packaging amendment

2026-11-15; issues1272–1275. This amendment supersedes the earlier README
packaging proposal only for one-time verification scripts. Keep that proposal
and its exact original validation ledger as historical evidence.

Publish verify_archival_mutations.executed.py.txt and
verify_archival_repairs.executed.py.txt as exact inert archives, with the hashes
in PACKAGING.json. Their private .py originals and all raw outputs remain retained.
Do not introduce executable public generator entry points for these one-time
runs. Public results are exact inspected receipt copies, not regeneration claims.

The separately reviewed archive_primary_clone.py operator and the minimally
repaired retire_owned_worktree.py remain executable source candidates under
scripts/adhoc/cycle-maintenance-20261115/cleanup-inventory/. Both maintained test
files belong under tests/. No real cleanup or archival is performed by packaging.

Include the explicit inert pre-fix helper/test archives, the original unchanged
VALIDATION.json and paired-controls-public.json, and the new repair provenance,
VALIDATION-r2.json, paired-controls-r2-public.json and issue-paired-controls-public.json.
Do not copy raw private logs, fixture trees, OPERATOR-PRIVATE.md, Git/config/history
receipts or private paths into the public PR. Public report summaries distinguish
the original22-test candidate from the repaired29+20 tests and nine issue controls.
