from pathlib import Path
import datetime,hashlib,importlib.util,json,os,shutil,subprocess,sys
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];ORIGINAL=RUN/'step5-claw-independent/queue709/fda8972';CLAW=RUN/'claw-owned-name';PKG=Path('reports/mim_owned_name_export_20261101');SHA='fda8972b1820964d2d839d44165fb948b2917762';OLD='a56f3ae4563619a5129ad944878c9205267315d6';TARGET='src/kg_microbe_utils/owned_name_policy.py'
def digest(b):return hashlib.sha256(b).hexdigest()
def record(name,args,cwd,env=None):
 p=subprocess.run(args,cwd=cwd,env=env,capture_output=True)
 (HERE/(name+'.stdout')).write_bytes(p.stdout);(HERE/(name+'.stderr')).write_bytes(p.stderr)
 results[name]={'argv':args,'cwd':str(cwd),'exit_code':p.returncode,'stdout_sha256':digest(p.stdout),'stderr_sha256':digest(p.stderr)}
 return p
results={}
v4=(RUN/'step5-claw-evidence-packaging/package_evidence_v4.py').read_bytes();assert digest(v4)=='1377772d93374ce6a31de85fab0ba9fe5697f63430db1e075431360e35018422'
v3=(RUN/'step5-claw-evidence-packaging/package_evidence_v3.py').read_bytes();assert digest(v3)=='74ade999a59f91d61e83d1b41de9d6b00dbae2fd58a9b28f285724359b18c821'
(HERE/'source-v3.py').write_bytes(v3);(HERE/'source-v4.py').write_bytes(v4)
# Existing blocked integration evidence is read only. All substitutions are in
# newly copied disposable fixtures; the original queue commit is not altered.
full=HERE/'full-integration';shutil.copytree(ORIGINAL/'integration-export',full)
env={**os.environ,'GIT_DIR':str(ORIGINAL/'isolated.git'),'GIT_WORK_TREE':str(full),'PYTHONDONTWRITEBYTECODE':'1'}
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=full,env=env).decode().strip()==SHA
args=lambda root:[sys.executable,'-B',str(root/PKG/'verify.py'),'verify','--package',str(root/PKG),'--repository',str(root),'--require-tracked']
old=record('old-actual-squash',args(full),full,env);assert old.returncode!=0 and b'merge-base' in old.stderr
# A real local depth-one clone, detached at the observed integration. No network.
shallow=HERE/'shallow-consumer'
p=record('clone-shallow',['git','clone','--no-local','--depth=1','--no-checkout',(ORIGINAL/'isolated.git').as_uri(),str(shallow)],HERE);assert p.returncode==0
assert subprocess.check_output(['git','rev-parse','--is-shallow-repository'],cwd=shallow).decode().strip()=='true'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=shallow).decode().strip()==SHA
missing=record('old-objects-absent',['git','cat-file','-e',OLD+'^{commit}'],shallow);assert missing.returncode!=0
subprocess.run(['git','read-tree','HEAD'],cwd=shallow,check=True,capture_output=True)
shutil.copytree(ORIGINAL/'integration-export',shallow,dirs_exist_ok=True)
oldshallow=record('old-shallow',args(shallow),shallow);assert oldshallow.returncode!=0
# Update only the verifier and its two internal version/hash bindings in both
# disposable package copies. Selection, original evidence and13 source refs
# stay identical to the actual blocked integration; no real package is published.
def install(root):
 p=root/PKG;(p/'verify.py').write_bytes(v4)
 frozen=json.loads((p/'final-inputs.json').read_text());frozen['packager_sha256']=digest(v4)
 (p/'final-inputs.json').write_text(json.dumps(frozen,indent=2,sort_keys=True)+'\n')
 manifest=json.loads((p/'manifest.json').read_text())
 for n in ['verify.py','final-inputs.json']:
  b=(p/n).read_bytes();manifest['files'][n]={'bytes':len(b),'sha256':digest(b)}
 (p/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
for root in [full,shallow]:install(root)
p=record('v4-actual-squash',args(full),full,env);assert p.returncode==0,p.stderr
p=record('v4-shallow-no-old-objects',args(shallow),shallow);assert p.returncode==0,p.stderr
# Negative boundaries use full CLI where possible, and exact captured v4
# check_references for the selected-hash guard in isolation.
raw=(shallow/TARGET).read_bytes();(shallow/TARGET).write_bytes(raw+b'\n# altered working byte\n')
p=record('refuse-working-byte',args(shallow),shallow);assert p.returncode!=0 and b'Maintained reference differs' in p.stderr
(shallow/TARGET).write_bytes(raw)
# Put changed bytes into a new isolated commit/index but restore the working
# source bytes. This distinguishes current committed content from source hash.
changed=raw+b'\n# altered committed byte\n';(shallow/TARGET).write_bytes(changed)
subprocess.run(['git','add','--',TARGET],cwd=shallow,check=True,capture_output=True)
newtree=subprocess.check_output(['git','write-tree'],cwd=shallow).decode().strip()
gitenv={**os.environ,'GIT_AUTHOR_NAME':'Independent fixture','GIT_AUTHOR_EMAIL':'fixture@example.invalid','GIT_COMMITTER_NAME':'Independent fixture','GIT_COMMITTER_EMAIL':'fixture@example.invalid'}
newcommit=subprocess.check_output(['git','commit-tree',newtree,'-p',SHA,'-m','Isolated current-blob negative fixture'],cwd=shallow,env=gitenv).decode().strip()
(shallow/'.git/HEAD').write_text(newcommit+'\n');(shallow/TARGET).write_bytes(raw)
p=record('refuse-current-git-blob',args(shallow),shallow);assert p.returncode!=0 and b'Current committed reference differs' in p.stderr
(shallow/'.git/HEAD').write_text(SHA+'\n');subprocess.run(['git','read-tree',SHA],cwd=shallow,check=True,capture_output=True)
spec=importlib.util.spec_from_file_location('independent_package_v4',HERE/'source-v4.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
plan=json.loads((shallow/PKG/'selection.final.json').read_text())
module.check_references(plan,shallow)
bad=json.loads(json.dumps(plan));bad['maintained_file_references'][TARGET]['sha256']='0'*64
try:module.check_references(bad,shallow)
except ValueError as e:assert 'Maintained reference differs' in str(e);results['refuse-selected-hash']={'status':'PASS','error':str(e)}
else:raise AssertionError('Selected hash mismatch accepted')
try:module.check_references(plan,shallow,historical=True)
except subprocess.CalledProcessError:results['refuse-author-history-in-shallow']={'status':'PASS'}
else:raise AssertionError('Author historical source check was waived')
assert record('v4-restored-shallow',args(shallow),shallow).returncode==0
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=CLAW).decode().strip()=='1f5ad6779cdb3f39f39ba6f9f26d31840b7e7077'
# Preserve original blocked queue proof and package exactly.
index=json.loads((ORIGINAL/'index.json').read_text())
for name,item in index.items():assert digest((RUN/name).read_bytes())==item['sha256'],name
r={'status':'PASS_WITH_LIMITATIONS','reviewer':'/root/step4_design_review','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'issue':710,'v4_sha256':digest(v4),'original_actual_integration':SHA,'original_implementation':OLD,'actual_integration_current_source_references':'unchanged all13selectedrefs','original_v3_actual_squash':'REFUSED as recorded','v4_actual_squash':'PASS','v4_real_depth_one_clone_without_old_feature_objects':'PASS','working_byte_refusal':'PASS','current_HEAD_blob_refusal':'PASS','selected_hash_refusal':'PASS','strict_author_history_refusal':'PASS','original_proof_unchanged':True,'results':results,'limitations':['This tests frozen v4 source using isolated copies of the actual blocked integration package with verifier/version hash fields rebound; no replacement production package or new PR head has been published or reviewed.','A future final package/head/body and its actual queue integration must be reviewed separately.','Portable checks establish selected content/current tracked Git identity; historical provenance remains asserted and frozen under the separate author publication checks.','No scientific approval, production edits or GitHub mutations.'],'remaining_findings':[],'supervisor_binding':None}
(HERE/'replay-results.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k!='results'},indent=2))
