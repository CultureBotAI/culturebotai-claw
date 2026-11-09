"""Real-Git squash and shallow regressions, fresh-process copied-code mutations."""
from pathlib import Path
import datetime,hashlib,json,os,subprocess,sys
D=Path(__file__).resolve().parent;P=D.parent
source=(P/'package_evidence_v4.py').read_text()
def sha(b):return hashlib.sha256(b).hexdigest()
before={n:sha((P/n).read_bytes()) for n in ['package_evidence_v3.py','package_evidence_v4.py','test_packager_v6.py']}
cases=[('old-v3-'+scenario,'package_evidence_v3.py',scenario,None,'old-red') for scenario in ['squash','shallow']]
cases += [('fixed-v4-'+scenario,'package_evidence_v4.py',scenario,None,'pass') for scenario in ['squash','shallow','working','committed','manifest','historical']]
cases += [
 ('mutant-portable-history','package_evidence_v4.py','squash',("        check_references(plan,repository)","        check_references(plan,repository,historical=True)"),'old-red'),
 ('mutant-selected-hash','package_evidence_v4.py','manifest',("require(digest(raw) == expected['sha256'] and len(raw) == expected['bytes'],",'require(True,'),'assertion'),
 ('mutant-current-git-blob','package_evidence_v4.py','committed',("require(committed == raw,",'require(True,'),'assertion'),
 ('mutant-all-author-history','package_evidence_v4.py','historical',('if historical:', 'if False:  # mutation disables author history'),'assertion'),
 ('mutant-author-original-bytes','package_evidence_v4.py','historical',("original = subprocess.check_output(['git','show',revision+':'+name],cwd=repository)", 'original = raw'),'assertion')]
results=[]
for name,filename,scenario,mutation,expect in cases:
 case=D/'controls'/name;case.mkdir(parents=True,exist_ok=False);module=P/filename
 if mutation:
  old,new=mutation;assert source.count(old)==(2 if name=='mutant-all-author-history' else 1),(name,source.count(old))
  module=case/'packager.py';module.write_text(source.replace(old,new))
 argv=[sys.executable,str(P/'test_packager_v6.py'),'--module',str(module),'--scenario',scenario,'--results',str(case/'results.json')]
 started=datetime.datetime.now(datetime.timezone.utc).isoformat()
 r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPYCACHEPREFIX':str(case/'cache')})
 (case/'test.log').write_bytes(r.stdout)
 if expect=='pass':assert r.returncode==0,(name,r.stdout[-1200:])
 elif expect=='old-red':assert r.returncode!=0 and b'CalledProcessError' in r.stdout and b'merge-base' in r.stdout,(name,r.stdout[-1200:])
 else:assert r.returncode!=0 and b'did not refuse' in r.stdout,(name,r.stdout[-1200:])
 receipt={'name':name,'scenario':scenario,'expected':expect,'argv':argv,'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exit_code':r.returncode,'log_sha256':sha(r.stdout),'module_sha256':sha(module.read_bytes()),'mutation':mutation}
 if expect=='pass':receipt['passing_assertions']=len(json.loads((case/'results.json').read_text())['results'])
 (case/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');results.append(receipt)
assert before=={n:sha((P/n).read_bytes()) for n in before}
(D/'control-results.json').write_text(json.dumps({'scope':'Author run-owned copied packagers and disposable real Git repositories; no maintained or package publication edits','source_hashes':before,'results':results},indent=2)+'\n')
print(json.dumps([{'name':x['name'],'exit_code':x['exit_code'],'passing_assertions':x.get('passing_assertions')} for x in results],indent=2))
