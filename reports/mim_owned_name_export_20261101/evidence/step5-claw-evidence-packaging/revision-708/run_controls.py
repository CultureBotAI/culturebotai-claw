"""Fresh-process regression/mutations on copied packagers and temporary fixtures."""
from pathlib import Path
import datetime,hashlib,json,os,subprocess,sys
D=Path(__file__).resolve().parent;P=D.parent
source=(P/'package_evidence_v3.py').read_text()
def sha(b):return hashlib.sha256(b).hexdigest()
originals={n:sha((P/n).read_bytes()) for n in ['package_evidence_v2.py','package_evidence_v3.py','test_packager_v5.py']}
cases=[('old-v2',P/'package_evidence_v2.py',None,False),('repaired-v3',P/'package_evidence_v3.py',None,True),
 ('mutant-no-plan-equality',None,("require(json.dumps(frozen['plan'], sort_keys=True) == json.dumps(expected, sort_keys=True),",'require(True,'),False),
 ('mutant-no-publish-binding',None,("selected = bound_selection(frozen, read(Path(frozen['selection_path'])), RUN)","selected = json.loads(read(Path(frozen['selection_path'])))"),False),
 ('mutant-no-portable-binding',None,("selected = bound_selection(frozen, read(package/'selection.final.json'))","selected = json.loads(read(package/'selection.final.json'))"),False),
 ('mutant-no-readme-binding',None,("require(read(package/'README.md') == selected['package_readme'].encode(), 'Packaged README differs from bound selection')",'pass  # deliberately disabled README binding'),False),
 ('mutant-no-active-root-binding',None,("require(run_root == str(expected_run_root), 'Recorded run root differs')",'pass  # deliberately disabled active root binding'),False)]
results=[]
for name,path,mutation,expect_pass in cases:
 case=D/name;case.mkdir(exist_ok=False)
 if mutation:
  old,new=mutation;assert source.count(old)==1;changed=source.replace(old,new);path=case/'packager.py';path.write_text(changed)
 argv=[sys.executable,str(P/'test_packager_v5.py'),'--module',str(path),'--results',str(case/'results.json')]
 env={**os.environ,'PYTHONPYCACHEPREFIX':str(case/'cache')}
 start=datetime.datetime.now(datetime.timezone.utc).isoformat()
 r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
 (case/'test.log').write_bytes(r.stdout)
 assert (r.returncode==0) if expect_pass else (r.returncode!=0 and b'did not refuse' in r.stdout),(name,r.returncode,r.stdout[-1200:])
 item={'name':name,'argv':argv,'started_at':start,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exit_code':r.returncode,'expected_pass':expect_pass,'expected_assertion_failure':not expect_pass,'module_sha256':sha(path.read_bytes()),'log_sha256':sha(r.stdout),'mutation':mutation}
 if expect_pass:item['passed_controls']=len(json.loads((case/'results.json').read_text())['results'])
 (case/'receipt.json').write_text(json.dumps(item,indent=2)+'\n');results.append(item)
assert originals=={n:sha((P/n).read_bytes()) for n in originals}
(D/'control-results.json').write_text(json.dumps({'scope':'Run-owned copied code and disposable real Git fixtures only','issue':'https://github.com/CultureBotAI/culturebotai-claw/issues/708','source_hashes':originals,'results':results,'maintained_sources_modified':False},indent=2)+'\n')
print(json.dumps([{'name':x['name'],'exit_code':x['exit_code'],'passed_controls':x.get('passed_controls')} for x in results],indent=2))
