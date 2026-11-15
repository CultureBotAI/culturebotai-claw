"""Package independent PR 1112 review evidence, 2026-11-15; issues 1104-1111.
Inputs: exact Git source objects, offline test logs, read-only GitHub responses.
Outputs: REVIEW.md, review.json and source-head-proof.json in the private review.
No live monitor, session, deployment or GitHub write operation is performed.
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
OUT=ROOT.parent
HEAD='812bb455828dd32611da3b603732cd62e16cc37f'
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
assert git('rev-parse','HEAD')==HEAD and git('diff','--exit-code')==''
pr=json.loads((OUT/'pr-final.json').read_bytes())
assert pr['headRefOid']==HEAD
main=(OUT/'main-final.txt').read_text().strip()
base=git('merge-base',main,HEAD)
changed=lambda a,b:set(git('diff','--name-only',a,b).splitlines())
proof={'reviewed_at':datetime.now(timezone.utc).isoformat(),'repository':'CultureBotAI/culturebotai-claw',
 'pr':1112,'head':HEAD,'head_tree':git('rev-parse','HEAD^{tree}'),'actual_main':main,
 'merge_base':base,'api_pr_base':pr['baseRefOid'],'origin':git('remote','get-url','origin'),
 'prospective_merge_tree':(OUT/'merge-tree-final.txt').read_text().strip(),
 'integration_index_tree':subprocess.check_output(['git','write-tree'],cwd=OUT/'integration-worktree',text=True).strip(),
 'main_overlap':sorted(changed(base,main)&changed(base,HEAD)),
 'three_dot_diff_sha256':sha(OUT/'diff.patch'),'tracked_source_restored':True,
 'source_sha256':{name:sha(ROOT/name) for name in ('scripts/mech_approval_bindings.py',
  'scripts/prepare_mech_approval_binding_reload.py','scripts/mech_session_port_pressure.py',
  'scripts/mech_session_supervisor.py','scripts/mech_monitor_control.py',
  'src/kg_microbe_workflows/port_pressure.py','src/kg_microbe_workflows/port_pressure_identity.py')}}
assert proof['integration_index_tree']==proof['prospective_merge_tree']
(OUT/'source-head-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
files=['diff.patch','diff-stat.txt','log.txt','merge-tree.txt','merge-tree-final.txt','pr.json','pr-final.json',
 'main-final.txt','hosted-test-run.json','hosted-test-run.log','pytest-focused.log','pytest-integration.log',
 'pytest-integration-boundaries.log','pytest-final.log','counterfactuals.json','source-head-proof.json',
 *['issue-'+str(n)+'.json' for n in range(1104,1112)]]
mutation=json.loads((OUT/'counterfactuals.json').read_bytes())
files.extend(r['name']+'.log' for r in mutation['receipts'])
review={'schema_version':1,'reviewer':'independent source reviewer',
 'reviewed_at':proof['reviewed_at'],'repository':proof['repository'],'pr':1112,'head':HEAD,'actual_main':main,
 'verdict':'ready_for_code_only_closure_under_existing_user_authority','findings':[],'issues_filed':[],
 'checks':pr['statusCheckRollup'],
 'validation':{'exact_head_focused_passed':261,'exact_head_focused_skipped':0,
 'merged_supervisor_pressure_passed':463,'merged_freshness_boundary_passed':221,'merged_tests_skipped':0,
 'mutation_control_passed':11,'meaningful_counterfactuals_killed':8,'restored_final_passed':155,
 'restored_final_skipped':0,'hosted_passed':9153,'hosted_skipped':461,'hosted_run':42727461310,
 'resident_adapter_and_preparer_python39_syntax':'passed'},
 'issues_rechecked':list(range(1104,1112)),
 'boundaries':['Code-only review. No live configuration, port-pressure command, native process, monitor deployment, restart or canary was run.',
 'Historical preparation-only/no-merge wording does not itself withdraw the current explicit Claw maintenance authority. Separate runtime deployment/canary approval remains required.',
 'Current repository requirements and complete queue must be refreshed before any normal admission; six historical head checks are not a claim that later-added checks have run.'],
 'limitations':['Existing production-private migration inputs and actual live launch selectors were not read or reverified; deployment must bind freshly reviewed actual inputs.',
 'Python 3.9 grammar was validated for the two resident scripts, but the offline suites used the repository Python 3.13 environment rather than a real Python 3.9 runtime.',
 'Hosted output lists 461 suite-wide skips without per-test reasons. Those were not individually classified; all directly relevant local review tests ran without skips.',
 'Future parent cycle-maintenance changes are not part of the tested integration tree.'],
 'evidence_sha256':{name:sha(OUT/name) for name in files},
 'helper_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'scripts/adhoc').glob('*pr1112*20261115*.py'))}}
(OUT/'review.json').write_text(json.dumps(review,indent=2)+'\n')
report=f'''# Independent code-only review: claw PR #1112

| PR | Reviewed head | Verdict | Verified blocking findings |
|---|---|---|---:|
| [#1112](https://github.com/CultureBotAI/culturebotai-claw/pull/1112) | `{HEAD}` | Ready for code-only closure under existing user authority | 0 |

Reviewed at {proof['reviewed_at']}. No GitHub writes, original-branch edits,
live port-pressure actions, monitor changes, restarts, deployments or native
canaries occurred. All transport tests used injected synthetic processes and
fake input adapters; lifecycle tests manage only their own disposable children.

## Exact source and current-main integration

- Actual main: `{main}`; merge base and PR API base: `{base}`.
- Head tree: `{proof['head_tree']}`.
- Clean prospective merge tree: `{proof['prospective_merge_tree']}`.
- Three-dot diff SHA256: `{proof['three_dot_diff_sha256']}`.
- Fifteen changed files. Current-main overlap is limited to
  `scripts/mech_session_supervisor.py` and `docs/guides/MECH_PORT_PRESSURE.md`.
- The supervisor delta preserves `controller_config_path` alongside the existing
  `binding_files` transport setting. Current-main repository-freshness checks
  remain in the merged tree. The guide retains main's stronger body-file rule.
- The integration worktree index exactly equals the prospective merge tree.
  It is an isolated staged snapshot on detached main, not an edited feature branch.

## What this change implements

The policy adds explicit goal-boundary-only restart eligibility without changing
the combined-policy default. Both decision and transport layers reject idle
fallback under that setting. Closed, retained registration evidence binds exact
conversation/model/effort argv, executable bytes, target and footer labels.
The transport rechecks before quit, before resume and after resume.

The resident adapter provides data-only binding reload under existing lifecycle
and input locks. It verifies old bytes and source pins, preserves stable recovery
identity and other target fields, updates only the changed target integrity pin,
and requires acknowledgment of the effective generation from the same resident
process. Per-input checks validate without adopting a new generation. Partial,
stale or unacknowledged state keeps input blocked. Immutable pre-quit evidence
and subsequent binding receipts survive failures. The migration command only
prepares exact-hash output and never installs it. The native log parser accepts
the bounded server format while refusing ambiguity and lookalikes.

## Independent validation

- Exact-head focused suite: **261 passed**, no skips, 11.43 seconds.
- Current-main merged supervisor/pressure suite: **463 passed**, no skips,
  12.90 seconds.
- Additional merged freshness, goal-boundary, cycle compatibility and task
  controls: **221 passed**, no skips, 9.45 seconds. These are distinct test files
  from the 463-test integration run.
- Counterfactual baseline: **11 passed**. Eight independent mutations all failed
  their intended assertions in fresh processes with separate bytecode roots:
  idle fallback; direct transport boundary bypass; changed executable accepted;
  effective-map acknowledgment omitted; wrong lock root accepted; pre-quit
  evidence omitted; source pins not rechecked; changed code falsely acknowledged
  as resident. The evidence-order mutation fails all four failure-phase cases.
- After exact restoration: **155 passed**, no skips, 1.75 seconds;
  `git diff --exit-code` is clean for tracked source.
- Both new resident scripts parse with Python 3.9 grammar. A real Python 3.9
  runtime was not exercised; repository tests ran on Python 3.13.

## Hosted checks and previous findings

Final GitHub readback: OPEN, ready, CLEAN, MERGEABLE at the same exact head.
All six visible head checks succeeded: isolated-contracts, fleet-audit,
id-label-contract, pytest, embedding-projection and history-round-trip.
[Run 42727461310](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/42727461310)
at this head passed Ruff, safety-critical type checking, active-cron and governed
pin gates, **9,153 tests**, two subtests and coverage gates; it reports 461
suite-wide skips without individual reasons. The embedding job passed 51 tests.
This review did not classify every historical skip; every directly relevant
local selected test executed without a skip.

Issues #1104–#1111 are still OPEN at readback. Their stated failure modes are
repaired in this head and independently exercised here. In particular, the four
prior adversarial findings are covered by wrong-lock-root, data-only effective
acknowledgment, fresh source-pin and immutable pre-quit-evidence checks. No new
source finding survived review, so this reviewer filed no issue. The PR already
contains the eight closing references; verify closure after its normal merge.

## Remaining boundaries

This is code-only acceptance. The old PR preparation/no-merge text is historical;
the current user instruction separately authorizes reviewed green Claw source
maintenance. It does not authorize live deployment, port-pressure inspection
commands, runtime installation, a restart or native canary. Actual live
registration/loaded-image/model-selector evidence and the private migration
inputs were not reverified here and remain deployment prerequisites.

The six historical successful head checks do not assert that later-added
required checks ran. Refresh current head/base/complete queue and satisfy current
repository rules before admission. The parent's future cycle-maintenance delta
is not included in this tested tree and requires its own integration check.

## Retained evidence

`review.json` provides machine-readable results and evidence hashes;
`source-head-proof.json` binds source, main, merge base and integration tree.
Both worktrees and all logs are retained under this private review root.
The source worktree is detached at the reviewed head and holds only two new
untracked review helpers under `scripts/adhoc`:

- `review_pr1112_20261115.py`
- `package_review_pr1112_20261115.py`

Each helper records purpose, inputs, outputs, date and related issues. Preserve
them and the report before removing review worktrees. The shared private clone
still borrows objects from the recorded Git object source; do not
remove that source without first dissociating the review clone. PR #1236's
separate review worktree and evidence were preserved throughout.
'''
(OUT/'REVIEW.md').write_text(report)
print(json.dumps({'report':str(OUT/'REVIEW.md'),'report_sha256':sha(OUT/'REVIEW.md'),
 'review_json_sha256':sha(OUT/'review.json'),'proof_sha256':sha(OUT/'source-head-proof.json')}))
