from pathlib import Path
import datetime,hashlib,io,json,os,subprocess,tarfile
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[2];CLAW=RUN/'claw-owned-name';HEAD='1f5ad6779cdb3f39f39ba6f9f26d31840b7e7077';INTEGRATION='fda8972b1820964d2d839d44165fb948b2917762';BASE='6a7172585eb68da7f4fe01aee75a82458ddd470c';IMPLEMENTATION='a56f3ae4563619a5129ad944878c9205267315d6';PKG='reports/mim_owned_name_export_20261101'
sha=lambda b:hashlib.sha256(b).hexdigest()
def git(*a):return subprocess.check_output(['git',*a],cwd=CLAW)
def tree(ref):
 d={}
 for x in git('ls-tree','-rz',ref).split(b'\0'):
  if x:
   meta,name=x.split(b'\t',1);d[name.decode()]=meta.decode()
 return d
ft=tree(HEAD);it=tree(INTEGRATION);bt=tree(BASE)
assert it==ft
parents=git('show','-s','--format=%P',INTEGRATION).decode().strip().split();assert parents==[BASE]
changed={p for p in it.keys()|bt.keys() if it.get(p)!=bt.get(p)}
previous=json.loads((RUN/'step5-claw-independent/final-1f5ad677/changed-paths.json').read_text());assert changed==set(previous) and len(changed)==479
ancestor=subprocess.run(['git','merge-base','--is-ancestor',IMPLEMENTATION,INTEGRATION],cwd=CLAW,capture_output=True);assert ancestor.returncode==1
# Export only the package plus its declared maintained references to a new fixture.
# Isolated detached Git metadata borrows existing read-only objects; no checkout,
# branch creation/update, network or source edits in either production repository.
selection=json.loads((CLAW/PKG/'selection.final.json').read_text());paths=[PKG,*selection['maintained_file_references']]
fixture=HERE/'integration-export';fixture.mkdir();archive=git('archive',INTEGRATION,'--',*paths)
with tarfile.open(fileobj=io.BytesIO(archive)) as t:t.extractall(fixture,filter='data')
meta=HERE/'isolated.git';subprocess.run(['git','init','--bare',str(meta)],check=True,capture_output=True)
common=Path(git('rev-parse','--git-common-dir').decode().strip());assert common.is_absolute()
(meta/'objects/info/alternates').write_text(str(common/'objects')+'\n');(meta/'HEAD').write_text(INTEGRATION+'\n')
env={**os.environ,'GIT_DIR':str(meta),'GIT_WORK_TREE':str(fixture),'PYTHONDONTWRITEBYTECODE':'1'}
subprocess.run(['git','read-tree',INTEGRATION],cwd=fixture,env=env,check=True,capture_output=True)
args=['python','-B',str(fixture/PKG/'verify.py'),'verify','--package',str(fixture/PKG),'--repository',str(fixture),'--require-tracked']
p=subprocess.run(args,cwd=fixture,env=env,capture_output=True)
(HERE/'actual-portable.stdout').write_bytes(p.stdout);(HERE/'actual-portable.stderr').write_bytes(p.stderr)
assert p.returncode!=0 and b'merge-base' in p.stderr and IMPLEMENTATION.encode() in p.stderr
r={'status':'CONFIRMED_FINDING','severity':'medium','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer':'/root/step4_design_review','integration':INTEGRATION,'integration_tree':git('rev-parse',INTEGRATION+'^{tree}').decode().strip(),'parents':parents,'reviewed_head':HEAD,'reviewed_feature_tree_identical':True,'changed_paths':479,'all_unrelated_base_paths_preserved':True,'implementation_ancestor_exit_code':ancestor.returncode,'actual_portable_verify_exit_code':p.returncode,'actual_portable_argv':args,'stderr_sha256':sha(p.stderr),'finding':'The documented portable verification requires historical implementation a56 to be an ancestor of HEAD, so the exact actual native squash integration fails despite identical reviewed tree/package bytes.','suggested_contract':'Bind maintained evidence to exact reviewed content and authentic historical implementation objects without requiring a pre-squash feature commit to be an ancestor of the current squash. Review the canonical post-merge portability contract; preserve historical source attribution. Add a real single-parent squash regression before re-review.','production_edits':False,'github_mutations':False,'branch_or_checkout_operations':False,'queue_checks':'Not reviewed/completed by this content probe','supervisor_binding':None}
(HERE/'finding.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2));print(p.stderr.decode())
