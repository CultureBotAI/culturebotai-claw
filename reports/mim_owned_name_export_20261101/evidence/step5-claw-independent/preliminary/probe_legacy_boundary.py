from pathlib import Path
import sys,os,importlib.util,json,hashlib
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];CLAW=RUN/'claw-owned-name';sys.path.insert(0,str(CLAW/'src'))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
load('kg_microbe_utils.owned_name_policy',HERE/'snapshot/src/kg_microbe_utils/owned_name_policy.py')
a=load('kg_microbe_utils.sssom_artifacts',HERE/'snapshot/src/kg_microbe_utils/sssom_artifacts.py')
m=load('independent_legacy_publisher',HERE/'snapshot/scripts/publish_sssom.py');m.REPO_ROOT=CLAW
root=HERE/'legacy-controls';root.mkdir(exist_ok=False);os.environ['OPENCLAW_WORKSPACE']=str(root/'workspace');results=[]
for equal in [False,True]:
 d=root/('equal' if equal else 'different');d.mkdir();candidate=d/'candidate.tsv';canonical=d/'canonical.tsv'
 candidate.write_text(f'# mapping_set_description: "{a.POLICY_MARKER}"\nsubject_id\tother\nMIM:Subject\tkept\n');canonical.write_bytes(candidate.read_bytes() if equal else b'old canonical\n');before=canonical.read_bytes();m.WORKING_COPY=candidate;m.PUBLISHED=canonical;sys.argv=['publish_sssom.py','--apply']
 try:m.main();code=0
 except SystemExit as exc:code=exc.code
 assert code==2 and canonical.read_bytes()==before
 results.append({'case':'policy_refusal_equal' if equal else 'policy_refusal_different','exit_code':code,'canonical_preserved':True,'manifest_absent':not candidate.with_suffix('.tsv.manifest.json').exists()})
for code,diag in [(0,'Informational extension warning'),(1,'Unexpected validation failure'),(2,''),(0,'subject_id must be supplied')]:
 shim=root/f'validator-{len(results)}';shim.write_text('#!'+sys.executable+'\nimport sys\nprint('+repr(diag)+',file=sys.stderr)\nraise SystemExit('+str(code)+')\n');shim.chmod(0o755);m.SSSOM_BIN=str(shim);errors=m._validate(root/'fixture.tsv');expected=bool(code or 'must be supplied' in diag);assert bool(errors)==expected
 results.append({'case':'validator_real_process','returncode':code,'stderr':diag,'errors':errors,'correctly_refused':expected})
(HERE/'legacy-boundary-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
