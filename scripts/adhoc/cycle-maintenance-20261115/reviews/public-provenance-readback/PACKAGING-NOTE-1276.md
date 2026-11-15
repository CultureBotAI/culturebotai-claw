# Historical readback helper archive — issue #1276

Date: 2026-11-15. Issue:
[CultureBotAI/culturebotai-claw#1276](https://github.com/CultureBotAI/culturebotai-claw/issues/1276).
Preparation base: `d2847a32bdc6bcf8eee18f881998f4c3a28faf03`.

`verify_public_packages.executed.py.txt` is the exact executed source formerly
named `verify_public_packages.py`. Only its filename changes. Its SHA256 remains
`0877e243a6a511032215f6d0fe3e73495aea04124c6a306a52bc1b3a0559788b`.
The private original and the original source committed at snapshot
`2597b50f1cf9ee630316c880b43030e04cfac664` have the same bytes. No historical
execution, review, output or composition ledger is regenerated or replaced.

This is a dated source archive, not an operational verification command. Its
purpose was to read back the explicitly selected public packages against the
explicit root-checkout and durable-task-root inputs. Its stdout receipt records
selected file hashes, historical JUnit counts, copy checks and review scope.
It did not write inputs, invoke Git/GitHub or change runtime state. The later
#1270 packaging correction means its old inputs no longer describe the current
package layout; `PACKAGING-NOTE-1270.md` remains authoritative about that change.
The archive must not be used to manufacture a new current-head PASS.

Preserved output and composition identities:

| Unchanged file | SHA256 |
| --- | --- |
| `REVIEW.md` | `eb9dd9f4116f4d0a00f399fab1184a03dc47644cae17a72c10d8d9a482163084` |
| `verification.json` | `e3615bc3591dd5e3ca3745ae86772b975f0a0358f768e81b824886e888951de1` |
| `PACKAGING-NOTE-1270.md` | `889895199d5f88f70b590d993072df4340c5038f315641b820c792338ae784b7` |

The hosted failure identified the privacy-denylist regular expression as a
machine-specific root. Those historical source bytes are retained without
rewriting or concealing the expression. The repository's machine-independence
guard and all its allowlists remain byte-identical. Archiving this obsolete
probe removes it from the executable-script collection without asserting new
behavior or weakening the guard.

## Bounded validation

An isolated private fixture copied the entire current `scripts/` tree and the
unchanged `tests/test_scripts_are_machine_independent.py`, whose SHA256 is
`54499a805a9c9855076ddb548a7d776951fe072f740fa239acace84331ee30f1`.
No source script was executed. In fresh Python processes, the original targeted
test failed at its intended home-path assertion: one failure, no setup error.
After renaming only the fixture copy, the full test file passed: 1,444 passed,
10 skipped, no failures or errors. Eight skips are existing historical-ledger
entries and two are existing empty parametrizations; no skip was added.
The exact test invocation used `python -m pytest -q -p no:cacheprovider` with
`--junitxml` directed to retained private evidence. The initial run selected the
specific helper's home-path test; the second ran the entire test file.

Private validation artifacts are retained under `repairs/1276-archive/` in the
durable task evidence. They contain local paths/host details and are not copied
into this public package. Their identities are:

| Artifact | SHA256 |
| --- | --- |
| `original-test.log` | `398f31aefd892e0324e9fa64be4d63225ff08ffb9bf54e1237f1b67d7d8e5204` |
| `original-test.xml` | `b7f559e50d8f4d203a2b972d574831f88ca89f484135310300f5efaccf0dd6a6` |
| `fixed-full-check.log` | `2923e28e406150be56ce344b9d639e202a4eaefcdf9ecc24d775e160962dbe46` |
| `fixed-full-check.xml` | `f8f93e6fd9a599eabe79daedfa8ac875c86f908c50f507a715517150818b26c1` |

A complete recursive byte comparison of fixture scripts against the original
scripts tree showed only the old/new filename pair. The retained original
package, existing private snapshot copy and new archive have matching hashes.
The root worktree was not edited during this preparation. Independent review,
owner application and final hosted checks remain separate subsequent steps.
