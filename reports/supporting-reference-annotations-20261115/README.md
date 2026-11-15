# SupportingReference native coverage canary

The canonical annotation repair for [Claw #1218](https://github.com/CultureBotAI/culturebotai-claw/issues/1218)
causes actual native snippet comparisons in both shared containers. This is a
synthetic lexical test; it does not evaluate scientific support or adopt the
change in any downstream repository.

| Schema/container | Valid: comparisons / exit | Fabricated: comparisons / exit | Restored: comparisons / exit | Measurement |
|---|---:|---:|---:|---|
| Before / Discussion | 0 / 0 | 0 / 0 | 0 / 0 | FAIL: snippets unexamined |
| Annotated / Discussion | 1 / 0 | 1 / 1 | 1 / 0 | PASS |
| Annotated / Dataset | 1 / 0 | 1 / 1 | 1 / 0 | PASS |

Receipts: [before](before.json), [Discussion](discussion.json),
[Dataset](dataset.json). Each corrected case records both the excerpt occurrence
and actual native substring invocation. A native `Total checks: 0` is an emitted
issue count; positive cases above still compare one snippet. Removing the excerpt
annotation is a regression control that restores zero comparisons and fails the
measurement despite native exit 0.

Runs used the actual Typer `validate data` CLI through the same persisted
[helper](../../scripts/adhoc/check_supporting_reference_annotations_20261115.py),
with `--no-full-text`, a synthetic cache and guards refusing source acquisition,
network connections, enrichment and cache saving. No guards fired. Every source,
schema and individual input hash stayed unchanged during validation. Source text
is explicitly synthetic; its fixture identifier does not assert anything about
the real publication with that identifier.

The checkout base was `239efb49fea7ea63cdab30f827e1080e7bdd9651`; corrected
receipts bind the working-tree helper, dependency declaration and lockfile by
SHA-256 rather than claiming the edits already belonged to that base commit.
Canonical schema SHA-256 changed from
`c2e7054fd32635e380c698282bd886a9105861009b9f0474f02bb1b80865e895` to
`cf32864df1626201128e9311054b075bfc4ad3d8345491ac144122a5d5e67d11`.
The maintained manifest pins the latter. Tests use native
`linkml-reference-validator 0.2.1` and `linkml 1.11.1`.

Validation: the two positive/mutated/restored regression tests failed before
the annotation change, while the explicit unannotated negative control passed.
Afterward, 50 focused annotation, shared-schema and governance tests passed;
the four annotation tests also passed under CI-style `--cov=src` discovery.
That last check tests loader compatibility, not source coverage of Claw's other
packages. Focused Ruff and Black checks and `git diff --check` passed.

Hosted CI then correctly rejected a missing canonical composition refresh
([#1220](https://github.com/CultureBotAI/culturebotai-claw/issues/1220)). The
maintained `kg_microbe_skills.template_cli refresh` dry run and `--apply` updated
the baseline to published source commit `85b4d693002387b855ece75282fad7a324b761cc`
and exactly the two changed schema/manifest digests. `check-baseline` now passes;
66 focused template, governance and annotation regressions passed. The schema,
matcher canary and consumer pins were not changed by this refresh. The original
failed hosted run remains retained; no baseline check was bypassed.

The next hosted run exposed missing historical shared-schema fixtures (#1221)
and three native CLI failures with hidden exceptions (#1222). The exact old
schema is now retained from each consumer's sealed Git source, with three
additional provenance rows; immutable admission pins/manifests are unchanged.
Focused admission tests reproduced 14 failures and eight setup errors before
the fixture repair. Admission, consumer, installed-wheel and native CLI tests
then passed all 33 cases locally. The new CLI diagnostic retains exception
type and basename/function/line frames, excluding exception text, source lines
and local variables. A controlled native-construction failure verifies that
these diagnostics remain visible without publishing private values.

The Linux CLI cause is not yet established. Local full collection with the
new tests selected passed nine cases; the broader local diagnostic was
interrupted after 414 passing cases and two subtests (pytest exit 2), before
the native CLI cases, and is not a full-suite pass. No parser workaround or
coverage waiver is applied. The existing Linux CSafeLoader issues #233/#263
are investigative leads, not a confirmed explanation for this failure.
Raw logs remain at `.temp/admitted-before-001.log` (SHA-256
`4619281b7c0dc0e714e85bd914e1583f18812f258c674d64c6e83b60398d0c4d`),
`.temp/admitted-and-native-after-001.log` (`af5653993425e741100b098cd59edcbc5ca7de3a8dd539d4819f8a3ca17d0741`),
and `.temp/ci-full-repro-001.log` (`877ce99f09c92e444da6ed3a22934fd2068bab73158322674b1896951cfd743d`).

Private raw inputs/logs/exits remain in this checkout under
`.temp/supporting-reference-annotations-20261115/{before-001,discussion-002,dataset-001}/`.
The public receipts retain their input/log hashes and measured counts. Raw native
logs include the local schema path and are not published here. The first corrected
Discussion run (`discussion-001`) also passed; `discussion-002` repeats it after
adding source-file provenance fields to the helper.

CommunityMech [#476](https://github.com/CultureBotAI/CommunityMech/issues/476)
remains a downstream adoption dependency. Its prior 522 omitted snippets are not
claimed as repaired here. Adoption requires the published immutable Claw pin,
governed re-vendoring, generated products where needed, and measured native
coverage with explicit remaining source/annotation limitations. No other
manifest consumer was changed.
