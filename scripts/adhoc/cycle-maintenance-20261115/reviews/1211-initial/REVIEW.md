# PR #1211 independent adversarial review

Verdict: **no new actionable finding in the full 21-path change set** at local head `553a6103c2275ce7f020f6c6519465323240aaa8`, compared with published main `99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d`. This is local-head review acceptance, not hosted-check or merge acceptance. I did not implement this PR or its repair.

## Scope and inspected boundaries

Reviewed all 21 changed paths: candidate declaration/parser/loader, resolver, synchronization and CLI integration, standalone checker, template identity and authority inventory, packaging, all changed skill/guide text, tests, retained checker fixture, combined provenance and its committed helper, and refreshed baseline. The retained 668-line checker fixture was authenticated against its historical source blob instead of being mistaken for new executable code. Public GH reads were limited to claw PR/issue/source-tree metadata; no private repository was queried.

The explicit candidate mode leaves ordinary fleet resolution and ordinary synchronization fleet-only. It binds the installed declaration and manifest to the same immutable source and selects only universal governed payloads. Origin validation is reused; canonical control-plane identity is reserved; private/fleet collisions and complete disabled/inapplicable capability decisions are checked in the package loader. Native identity overrides remain refused. The standalone checker validates origin, explicit/ambient identity and exact governed bytes. The original candidate declaration, resolver, standalone checker and candidate tests are byte-identical to original PR head `a5a98c7018c2216ac814f9ce9e97e13c02b18792`.

Diff inspection confirms unchanged fleet manifest, protected release/private-audit authorities, GitHub workflows and research configuration. Candidate preparation does not admit the repository, install a runtime, release a pin or activate a cycle. The declared repository ID/bootstrap state remains the original preparation evidence; I did not reauthenticate private metadata, per the task boundary.

## Independent validation

- **98 passed in 26.28s** across eight candidate/admitted/consumer/template/layout test modules, with `GITHUB_REPOSITORY=CultureBotAI/culturebotai-claw` explicitly set. Full repository coverage was not rerun.
- **Six fresh-process in-memory counterfactuals detected**, each with a passing unmodified control: reserved control-plane identity (#1213), explicit candidate mode, exact registry equality, ambient CI identity (#1217), 13-row union count (#1255), and historical digest protection (#1214). Implementation/test files stayed byte-identical throughout. See `counterfactuals.json` and retained `verify_counterfactuals.py`.
- All **13 provenance rows** equal the exact additive union of original PR and current main. Every fixture byte length, SHA-256, Git blob SHA, source path/ref and sealed snapshot agrees. The historical source commits were absent locally, so their blob IDs were independently authenticated with three retained public claw recursive-tree responses; each response was complete (not truncated). No downstream query was needed.
- The union SHA-256 is `e25d489133fc0ce6b2a53c5ce8f00f0f07d3fab3528a314f28d962a56c9952d8`. Running committed helper `scripts/adhoc/merge_fixture_provenance_1211_20261115.py` against exact original/current input commits reproduces those bytes. Helper SHA-256: `367961dfcb47180d01974f6aa893a14c6b654044a8f0b4ac1fc34e9835475376`.
- Baseline **1.1.0** authenticates all **62 authorities** against actual combined-source commit `1b419415a738c4d68c79c0dba6c838db77acc98d`. Baseline SHA-256 is `0239fb68573e8d9f4970c6aab76f5440aa88df501fd3df250bf7f77583227c31`. Maintained `check_baseline` and preview `refresh_baseline` agree with the committed baseline; no apply occurred.
- `git diff --check` and tracked/untracked Git status are clean. Ignored-inclusive scoped hygiene inspection of the new helper found only the canonical SSH origin spelling as an at-sign occurrence, with no machine path, email or session history. The first `uv run --no-sync` created an empty ignored `.venv` before reporting pytest unavailable; later checks used the existing shared environment. That disposable environment remains retained; no source/Git ref cleanup was attempted.

## Issue disposition and publication prerequisites

Live #1213, #1214, #1217 and #1255 were OPEN during review. Their described defects are addressed at this local head and covered by contrasting tests/counterfactuals; this review did not close them or mutate GitHub.

The final public readback still had main `99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d`, #1197 OPEN/unmerged, and #1211 OPEN at original remote head `a5a98c7018c2216ac814f9ce9e97e13c02b18792`. No hosted-check result for local head553a6103 exists yet, so historical remote green results are not credited to this repair. Parent must publish via ordinary fast-forward after its head check, obtain final-head hosted gates and preserve the normal merge requirements.

If #1197 merges first, integrate actual main normally, refresh the template baseline from the new committed combined source, and obtain focused exact-head re-review. That later baseline is not approved by this report. Review helpers/receipts are retained under the owned review directory for parent publication/packaging; no implementation, test, commit, push, merge, runtime or private-repository mutation was performed by this reviewer.
