# Independent primary-clone archive review — initial findings

Date: 2026-11-15. Issues: CultureBotAI/culturebotai-claw#1272, #1273,
#1274 and #1275. This is historical review evidence, not cleanup authority.
No real clone was moved, inventoried in full or retired by this review.

The exact candidate archive helper (SHA256
417893f1064336d04c90e41cffebc1675c538ab16064ce28373bc498def107d9)
and its 22-test suite (0f24c3e1450f90132810e3e564b7cc6fe2e0c5e94ea9ca3887e2826dd9a444a2)
were copied byte-for-byte into an isolated review directory. All 22 tests passed
in 7.25 seconds, with no skips or errors. The shared retirement helper was pinned
to91c07258e5efdd77d5f4c91b07c1815469bc3cd803db87e5e62e223c27b5de2e.

The retained one-time probes use only disposable synthetic fixtures and are
archived as `.executed.py.txt`. These are exact copies of the executed `.py`
files; only filenames changed, with no content sanitization or behavior edits.
Inputs are the copied candidate tests/helper plus explicit durable fixture and
bytecode-cache roots. Outputs are private pytest logs/JUnit and this inspected
public summary. Raw logs contain local fixture paths and host information and
are retained privately, not republished. Hashes preserve their identity.

Confirmed distinguishing failures:

- #1272: absolute internal symlinks and relative escape-and-reentry symlinks
  passed preflight, then failed after the synthetic source had moved.
- #1273: identical evidence/archive directories passed the dry run and created
  output. The intended refusal assertion failed.
- #1274: a real Darwin ACL denying directory listing allowed metadata reads but
  caused the complete inventory to silently omit a descendant. The mode-zero
  control refused through other checks and did not expose this distinction.
- #1275: the exact shared helper's `walk()` accepted the same ACL-unlistable
  ignored-results shape. This probe called `walk()` only, never retirement.

All five failing cases reached their intended assertions; none was a setup
error. One additional mode-zero refusal probe passed. Prior real cleanup receipts
are not invalidated by these fixture findings; no actual data loss is alleged.
The author must repair, retain originals, add ongoing regression tests and obtain
an independent rereview before actual archival.

Baseline and probes ran in fresh Python processes with `pytest -q -p
no:cacheprovider --junitxml=...`, explicit `ARCHIVAL_SHARED_HELPER`,
`ARCHIVAL_FIXTURE_ROOT`, `PYTHONPYCACHEPREFIX` and the repository on `PYTHONPATH`.
Synthetic fixtures restore their ACLs before removing only their own contents.
The packaging operations were byte-preserving `cp -n`, exclusive text creation,
SHA256 readback and a scoped privacy search; no executable packaging helper was
created, and no generation was rerun for packaging.
