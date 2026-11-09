from pathlib import Path
import sys,os,importlib.util,json,hashlib
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];CLAW=RUN/'claw-owned-name';sys.path.insert(0,str(CLAW/'src'))
for name in ['owned_name_policy','sssom_artifacts']:
 fullname='kg_microbe_utils.'+name;spec=importlib.util.spec_from_file_location(fullname,HERE/'snapshot/src/kg_microbe_utils'/f'{name}.py');m=importlib.util.module_from_spec(spec);sys.modules[fullname]=m;spec.loader.exec_module(m)
a=sys.modules['kg_microbe_utils.sssom_artifacts'];p=sys.modules['kg_microbe_utils.owned_name_policy']
root=HERE/'journal-callback-control';root.mkdir(exist_ok=False);os.environ['OPENCLAW_WORKSPACE']=str(root/'workspace');source=root/'source.yaml';source.write_text('input\n');output=root/'out/candidate.tsv';paths=a.artifact_paths(output);outside=root/'outside-journals';outside.mkdir();journal_dir=output.parent/'.sssom-artifact-journals';calls=0
sssom=(f'# mapping_set_description: "{a.POLICY_MARKER}"\nsubject_id\tother\nMIM:Subject\tkept\n').encode()
def callback():
 global calls
 calls+=1;assert source.read_bytes()==b'input\n'
 if calls==5:journal_dir.symlink_to(outside,target_is_directory=True)
result={}
try:result=a.publish_candidate_artifacts(output,sssom,p.render_suppressed_aliases([]),{'producer_revision':'fixture'},callback,input_paths=[source],expected_before=a.capture_beforeimages(paths),claw_root=CLAW)
except Exception as exc:result={'exception':str(exc),'type':type(exc).__name__}
proof={'artifact_module_sha256':hashlib.sha256((HERE/'snapshot/src/kg_microbe_utils/sssom_artifacts.py').read_bytes()).hexdigest(),'input_check_calls':calls,'journal_path_is_symlink':journal_dir.is_symlink(),'returned':result,'outside_journals':[{'path':str(x),'status':json.loads(x.read_text())['status']} for x in outside.glob('*.json')],'intended_artifacts_published':all(x.exists() for x in paths)}
(HERE/'journal-callback-result.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
