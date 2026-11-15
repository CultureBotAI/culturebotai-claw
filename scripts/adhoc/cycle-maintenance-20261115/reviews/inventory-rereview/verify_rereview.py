"""Independent offline re-review of inventory issues1263–1266, 2026-11-15.
Inputs: explicit source checkout, retained exact audit/review, new evidence dir.
Output: public-safe JSON; fake inputs and generated package stay private.
No network/Git mutation or source edits; no original report is rewritten.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PREFIX=Path('scripts/adhoc/cycle-maintenance-20261115')
WRAPPERS={
 'reviews/package_source_reviews.py':('--evidence-root','8f361c8b49222b363af157a55572e37d503e22ba55fc88fb68bd9c234f4e120a'),
 'reviews/package_followup_reviews.py':('--reviews-root','42ad7c3549aaf2428531aa41dcc0d0ca59c35cdfb524911d19093db2cc602615'),
 'reviews/1112/package_review_pr1112_20261115.py':('--review-tree','0f409dfc6059def0e31309c9dfe79c4b1fadd8fb7d907377353a2659218fe6d6'),
 'reviews/1236/package_review_pr1236_20261115.py':('--review-tree','f6508c1be607ed661ffbc05620631b7b8e24cef3280fef97c436f63a0b37f0e9'),
}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def load(path):
 spec=importlib.util.spec_from_file_location(path.stem,path);module=importlib.util.module_from_spec(spec)
 exec(compile(path.read_text(),str(path),'exec'),module.__dict__)
 return module

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 for name in ('root','audit-dir','review-dir','evidence-dir'):parser.add_argument('--'+name,type=Path,required=True)
 args=parser.parse_args();root=args.root.resolve();evidence=args.evidence_dir.absolute()
 assert not evidence.exists() and evidence.parent.is_dir()
 evidence.mkdir(mode=0o700)
 folder=root/PREFIX
 paths=[Path('inventory')/name for name in ('capture_pr_audit.py','review_pr1197_mutations.py','package_inventory.py','README.md','inventory-and-review.json','helper-repair-provenance.json')]+[Path(name) for name in WRAPPERS]
 sources={str(path):sha((folder/path).read_bytes()) for path in paths}
 capture=load(folder/'inventory/capture_pr_audit.py');package=load(folder/'inventory/package_inventory.py')
 rest=[{'number':n,'head':{'sha':'a'*40},'base':{'sha':'b'*40},'draft':False} for n in (1,2)]
 checks=[{'number':n,'headRefOid':'a'*40,'baseRefOid':'b'*40,'isDraft':False} for n in (1,2)]
 graph={'data':{'repository':{'nameWithOwner':capture.REPO,'defaultBranchRef':{'target':{'oid':'c'*40}},'pullRequests':{'totalCount':2,'pageInfo':{'hasNextPage':False},'nodes':copy.deepcopy(checks)}}}}
 assert capture.acquisition_agreement(rest,checks,graph,rest,'c'*40,'c'*40)['complete']
 try:capture.acquisition_agreement(rest,[],graph,rest,'c'*40,'c'*40)
 except ValueError as exc:assert 'drift' in str(exc)
 else:raise AssertionError('empty checks accepted')
 fake=evidence/'fake-worktree';(fake/'scripts').mkdir(parents=True)
 (fake/'scripts/fleet_issue_status.py').write_text('# unrelated source without mutation anchors\n')
 result=subprocess.run([sys.executable,str(folder/'inventory/review_pr1197_mutations.py'),'--worktree',str(fake),'--output',str(evidence/'missing-anchor-review')],capture_output=True,text=True,timeout=90)
 assert result.returncode!=0
 proof=json.loads((evidence/'missing-anchor-review/results.json').read_text())
 assert len(proof['results'])==4 and all(not row['killed'] for row in proof['results'])
 originals={str(key):sha((getattr(args,'audit_dir') if key.startswith('audit/') else getattr(args,'review_dir')).joinpath(key.split('/',1)[1]).read_bytes()) for key in package.ARCHIVE_HASHES}
 assert originals==package.ARCHIVE_HASHES
 generated=evidence/'valid-historical-package'
 package.package(args.audit_dir,args.review_dir,generated)
 assert (generated/'historical-inventory-and-review.json').read_bytes()==(folder/'inventory/inventory-and-review.json').read_bytes()
 summary=json.loads((generated/'inventory-and-review.json').read_bytes())
 assert summary['new_review_execution'] is False and summary['historical_input_sha256']==package.ARCHIVE_HASHES
 for output in (args.audit_dir,args.review_dir,args.audit_dir/'new-package',generated):
  try:package.package(args.audit_dir,args.review_dir,output)
  except ValueError:pass
  else:raise AssertionError('input alias/existing output accepted')
 report=evidence/'different-REVIEW.md';report.write_text('FAIL: unknown report\n')
 try:package.read_bound(report,package.ARCHIVE_HASHES['review/REVIEW.md'])
 except ValueError as exc:assert 'unrecognized historical' in str(exc)
 else:raise AssertionError('arbitrary report accepted')
 wrapper_results={}
 for relative,(option,archive_sha) in WRAPPERS.items():
  script=folder/relative
  archive=folder/'inventory/archive'/(script.stem+'.executed.py.txt')
  assert sha(archive.read_bytes())==archive_sha
  absent=evidence/(script.stem+'-absent')
  run=subprocess.run([sys.executable,str(script),option,str(absent)],capture_output=True,text=True)
  assert run.returncode==2 and 'archival-only' in run.stderr and not absent.exists()
  help_run=subprocess.run([sys.executable,str(script),'--help'],capture_output=True,text=True)
  assert help_run.returncode==0
  wrapper_results[relative]={'refusal_exit':2,'help_exit':0,'original_archive_sha256':archive_sha,'wrapper_sha256':sha(script.read_bytes())}
 assert originals=={str(key):sha((getattr(args,'audit_dir') if key.startswith('audit/') else getattr(args,'review_dir')).joinpath(key.split('/',1)[1]).read_bytes()) for key in package.ARCHIVE_HASHES}
 assert sources=={str(path):sha((folder/path).read_bytes()) for path in paths}
 output={'authority':'independent_offline_rereview','issues':[1263,1264,1265,1266],'source_sha256':sources,
  'missing_anchor_false_kills':0,'matching_capture_passes':True,'empty_checks_refused':True,
  'exact_archival_package_passes':True,'aliases_and_collisions_refused':True,'unknown_report_refused':True,
  'original_hashes_preserved':originals,'wrappers':wrapper_results,'source_unchanged':True,
  'expensive_review_rerun':False,'new_findings':0,'helper_sha256':sha(Path(__file__).read_bytes())}
 print(json.dumps(output,indent=2))

if __name__=='__main__':main()
