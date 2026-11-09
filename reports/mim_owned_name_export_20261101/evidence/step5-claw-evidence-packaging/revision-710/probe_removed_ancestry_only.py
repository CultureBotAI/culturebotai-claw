"""Show that removing only v3 ancestry still needs unavailable old Git objects."""
from pathlib import Path
import datetime,hashlib,json,os,subprocess,sys
D=Path(__file__).resolve().parent;P=D.parent;case=D/'controls'/'old-v3-shallow-without-ancestry';case.mkdir(exist_ok=False)
s=(P/'package_evidence_v3.py').read_text();old="subprocess.run(['git','merge-base','--is-ancestor',revision,'HEAD'],cwd=repository,check=True)";assert s.count(old)==1
module=case/'packager.py';module.write_text(s.replace(old,'pass  # isolate the remaining historical object dependency'))
argv=[sys.executable,str(P/'test_packager_v6.py'),'--module',str(module),'--scenario','shallow','--results',str(case/'results.json')]
r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPYCACHEPREFIX':str(case/'cache')})
(case/'test.log').write_bytes(r.stdout)
assert r.returncode!=0 and b'CalledProcessError' in r.stdout and b"'show'" in r.stdout,r.stdout[-1000:]
receipt={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Isolated old-code diagnostic; no production changes','argv':argv,'exit_code':r.returncode,'module_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),'log_sha256':hashlib.sha256(r.stdout).hexdigest(),'result':'Ancestry-only removal still fails real shallow consumer because historical git show object is absent.'}
(case/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
