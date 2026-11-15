"""Package independent claw PR 1236 review, 2026-11-15; related MIM issue 1418.
Inputs: immutable reviewed Git objects and retained read-only evidence files.
Outputs: REVIEW.md, review.json and source-head-proof.json in the review root.
This never calls GitHub or modifies source/branches; run from the private review.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
_parser = __import__("argparse").ArgumentParser(description=__doc__)
_parser.add_argument("--review-tree", type=Path, required=True,
                     help="Owned isolated detached worktree at the exact reviewed head")
ROOT = _parser.parse_args().review_tree.resolve()
if Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=ROOT, text=True).strip()).resolve() != ROOT:
    raise SystemExit("Review path is not a worktree root")
if subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=ROOT,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 1:
    raise SystemExit("Review tree must be detached; feature branches are refused")
if subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], cwd=ROOT).returncode:
    raise SystemExit("Tracked source differs from the reviewed head")
OUT = ROOT.parent
HEAD = '7070392fcb5e31282499a599f7147b56b96e5aca'
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
assert git('rev-parse','HEAD') == HEAD
assert git('diff','--exit-code') == ''
baseline=json.loads((OUT/'baseline.json').read_bytes())
pr=json.loads((OUT/'pr-final.json').read_bytes())
assert pr['headRefOid'] == HEAD
main=(OUT/'main-final.txt').read_text().strip()
assert main == baseline['main']
proof={
 'reviewed_at':datetime.now(timezone.utc).isoformat(),
 'repository':'CultureBotAI/culturebotai-claw',
 'pr':1236,'head':HEAD,'head_tree':git('rev-parse','HEAD^{tree}'),
 'actual_main':main,'api_pr_base':pr['baseRefOid'],
 'merge_base':git('merge-base',main,HEAD),
 'prospective_merge_tree':'5317ead17c4d3b3308d2035d372954826f2f5884',
 'earlier_reviewed_tree_matches':git('diff','--name-only','e3b9ecdccd3fc79c9a6758b48fc91685198b5a0e',HEAD)=='',
 'tracked_source_unchanged':True,
 'origin':git('remote','get-url','origin'),
 'three_dot_diff_sha256':digest(OUT/'diff.patch'),
 'builder_sha256':digest(ROOT/'scripts/build_mim_ingredient_sssom.py'),
 'stable_mim_sha256':digest(ROOT/'src/kg_microbe_utils/stable_mim.py'),
 'native_additional_contract_sha256':digest(OUT/'upstream-additional-contract.py.txt'),
 'native_additional_contract_source_revision':'207ec6ab143e3af09fa0b0a57aac11390b608de9',
 'native_additional_contract_matches_upstream':(OUT/'upstream-additional-contract.py.txt').read_bytes()==(ROOT/'tests/resources/additional_mim_mappings/native_contract.py.txt').read_bytes(),
 'untracked_review_helpers':git('status','--short','--untracked-files=all').splitlines(),
}
(OUT/'source-head-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
evidence=['baseline.json','diff.patch','diff-stat.txt','log.txt','pr.json','comments.json',
 'hosted-test-run.json','hosted-test-run.log','issue-1193.json','pr-1195.json',
 'mim-issue-1418.json','mim-issue-1421.json','pytest-focused.log','pytest-final.log',
 'counterfactuals-initial.json','counterfactuals.json','additional-assertion-matrix.json',
 'mutation-control.log','omit-additional-rows.log','collapse-additional-predicate.log',
 'inherit-primary-aliases.log','replay-old-science-stamp.log','pr-final.json',
 'main-final.txt','source-head-proof.json','upstream-additional-contract.py.txt']
helpers=sorted((ROOT/'scripts/adhoc').glob('*pr1236*20261115*.py'))
review={
 'schema_version':1,'reviewer':'independent source reviewer',
 'reviewed_at':proof['reviewed_at'],'repository':proof['repository'],'pr':1236,
 'head':HEAD,'actual_main':main,'merge_base':proof['merge_base'],
 'verdict':'ready_for_source_only_closure_under_existing_user_authority',
 'findings':[], 'issues_filed':[],
 'checks':pr['statusCheckRollup'],
 'validation':{'focused_tests':275,'focused_skipped':0,'restored_final_tests':79,
   'restored_final_skipped':0,'predicate_status_cases':8,'counterfactuals_killed':4,
   'hosted_pytest':10707,'hosted_suite_skipped':543,'hosted_test_run':43677410737,
   'hosted_stable_mim_line_coverage_percent':96},
 'refuted_hypotheses':[{'hypothesis':'Alias inheritance is not detected by the added tests',
   'result':'A single direct-row fixture is nondistinguishing, but the unchanged full existing test module fails on test_native_candidate_cli_binds_new_contract_and_independent_extra when alias inheritance is introduced; no suite-level finding.'}],
 'dependency_chain':[1139,1191,1194,1195,1236],
 'boundaries':['No MIM consumer mutation or execution, canonical mapping installation, scientific approval or release qualification.',
   'MIM issues 1418 and 1421 remained OPEN at readback; do not close them solely because Claw source merges.',
   'Historical PR no-merge wording is not a new source-code blocker to the current explicit user maintenance authority. Current per-PR normal rules and exact-head checks still apply.',
   'The native source-binding test includes a protocol double; this review does not claim native end-to-end scientific publication.'],
 'limitations':['Hosted aggregate output reports 543 skips without individual reasons. The review did not independently classify every suite-wide skip; all 275 directly relevant selected tests ran without skips.',
   'Existing PR description reports prior private independent review receipts; this reviewer did not authenticate every prior private receipt and instead reran the source-level checks independently.',
   'No scientific correctness claims about ingredient mapping evidence were assessed.'],
 'evidence_sha256':{name:digest(OUT/name) for name in evidence},
 'helper_sha256':{str(p.relative_to(ROOT)):digest(p) for p in helpers},
}
(OUT/'review.json').write_text(json.dumps(review,indent=2)+'\n')
report=f'''# Independent review: claw PR #1236

| PR | Reviewed head | Verdict | Verified blocking findings |
|---|---|---|---:|
| [#1236](https://github.com/CultureBotAI/culturebotai-claw/pull/1236) | `{HEAD}` | Ready for source-only closure under existing user authority | 0 |

Reviewed at {proof['reviewed_at']}. No GitHub writes, branch pushes, merges,
original-source edits or downstream MIM mutations were performed.

## Source and dependency proof

- Actual published main: `{main}`.
- PR API base: `{pr['baseRefOid']}`; this is not substituted for live main.
- Three-dot merge base: `{proof['merge_base']}`.
- Reviewed head tree: `{proof['head_tree']}`.
- Clean prospective merge tree: `{proof['prospective_merge_tree']}`.
- No paths overlap between changes on main after the merge base and this PR's
  three-dot changes. The actual merge-tree simulation succeeds.
- The tree at prior documented review head `e3b9ecdccd3fc79c9a6758b48fc91685198b5a0e`
  equals the current head tree; `7070392f` is a check-refresh commit.
- The cumulative diff contains 45 files and the preserved dependency chain
  #1139 → #1191 → #1194 → #1195 → #1236. The review examined that cumulative
  source change, rather than mistaking behind-main files for reverts.
- Exact diff SHA256: `{proof['three_dot_diff_sha256']}`.

## What the code does

The stack adds explicit legacy versus stable MIM identity modes. Stable mode
validates the captured native mint/lifecycle contract and complete owner
inventory, preserves justified local-registry and CAS compatibility rows, and
separates native source-to-MIM candidates from ontology mappings. Digest-bound
retirement/CAS requests retain their evidence, full row selection and review
closure. Stable generation refuses old scientific stamp replay and protects its
three output artifacts against source drift and overlap.

The new tip adds separately reviewed additional ontology assertions, preserving
their own predicate, target, evidence, attribution and SUPPORTED/WITHHOLD status.
Their rows have no inherited aliases, confidence or validation stamps. The
license fix uses MIM's CC BY 4.0 data license. None of this installs a canonical
mapping or approves the science.

## Independent verification

- 275 focused tests passed, no skips, in `pytest-focused.log` (58.19 seconds).
- All eight exact/close/broad/narrow × SUPPORTED/WITHHOLD combinations preserved
  the assertion and owner; native row-binding checks accepted the generated rows.
- Four substantive mutations were killed in fresh pytest processes: omit extra
  rows, collapse the predicate to exactMatch, inherit primary aliases, and replay
  old science stamps. `counterfactuals.json` records substitutions and hashes.
- The first selected alias unit fixture had no surviving primary alias, so that
  single test did not distinguish alias inheritance. The complete unchanged test
  module caught the mutation in its native CLI assertion. The initial receipt is
  retained as `counterfactuals-initial.json`; the suspected suite gap is refuted.
- After restoration, 79 focused tests passed without skips in `pytest-final.log`.
  `git diff --exit-code` confirms all tracked source is byte-restored.
- The captured additional native contract was read from its exact public source
  revision `207ec6ab143e3af09fa0b0a57aac11390b608de9` and matches the fixture,
  SHA256 `{proof['native_additional_contract_sha256']}`.

## Hosted checks and effective coverage

Final readback reports OPEN DRAFT, CLEAN, MERGEABLE at the same head, with all
eight checks successful: isolated-contracts, candidate-contracts,
id-label-contract, pytest, public-fleet, embedding-projection, fleet-audit and
history-round-trip.

[Hosted run 43677410737](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/43677410737)
reports 10,707 passing tests, 543 suite-wide skips, two passing subtests and 96%
line coverage for `stable_mim.py`. Lint, safety-module type checks and coverage
gates succeeded. The embedding job passed 51 tests. The retained aggregate log
does not identify each skipped test; this review does not claim to have resolved
all 543 skip reasons. Every directly relevant selected test ran locally without
a skip. Native source-binding transport includes an explicit protocol double;
this is not evidence of a scientific publication run.

## Holds and closure scope

No new issue was filed because no candidate source-code finding survived
verification. Existing MIM #1418 and #1421 are OPEN at readback and remain native
implementation/scientific/publication obligations; a Claw source merge alone
does not settle them. Claw #1195 is still an open draft whose complete source
commit is included here. Preserve its bookkeeping when closing the stack.

The PR body's older no-merge wording records the original campaign boundary.
The current user assignment separately authorizes reviewed green Claw source
maintenance; that authority does not extend to MIM consumers, runtime adoption,
canonical installation or release. Follow current repository rules and recheck
head, base and the complete queue before any admission.

## Retained evidence and helpers

This report, `review.json`, `source-head-proof.json`, GitHub readbacks, exact diff,
test/mutation logs and input hashes remain in this private review root. The own
isolated worktree is detached at the reviewed head and retains only these new
untracked review helpers; original branches are untouched:

- `worktree/scripts/adhoc/review_pr1236_20261115.py`
- `worktree/scripts/adhoc/review_pr1236_20261115_initial.py`
- `worktree/scripts/adhoc/package_review_pr1236_20261115.py`

Each helper records purpose, inputs, outputs, date and related PR/issue. Their
hashes are in `review.json`. Preserve these helpers and evidence before removing
the isolated worktree. The private review clone borrows Git objects from the
recorded Git object source; do not remove that alternate source
without first making the review clone self-contained.
'''
(OUT/'REVIEW.md').write_text(report)
print(json.dumps({'report':str(OUT/'REVIEW.md'),'report_sha256':digest(OUT/'REVIEW.md'),'review_json_sha256':digest(OUT/'review.json'),'proof_sha256':digest(OUT/'source-head-proof.json')}))
