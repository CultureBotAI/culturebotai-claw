from pathlib import Path
import os,sys,importlib.util,hashlib,json,traceback
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];CLAW=RUN/'claw-owned-name';sys.path.insert(0,str(CLAW/'src'))
for name in ['owned_name_policy','sssom_artifacts']:
 fullname='kg_microbe_utils.'+name;path=HERE/'snapshot/src/kg_microbe_utils'/f'{name}.py'
 spec=importlib.util.spec_from_file_location(fullname,path);module=importlib.util.module_from_spec(spec);sys.modules[fullname]=module;spec.loader.exec_module(module)
art=sys.modules['kg_microbe_utils.sssom_artifacts'];policy=sys.modules['kg_microbe_utils.owned_name_policy']
ROOT=HERE/'controls';ROOT.mkdir(exist_ok=False)
results=[]
def run(kind):
 root=ROOT/kind;root.mkdir();os.environ['OPENCLAW_WORKSPACE']=str(root/'workspace')
 source=root/'input.yaml';source.write_text('preferred_term: Owned\n')
 destination=root/'out';destination.mkdir();output=destination/'candidate.sssom.tsv';side=None
 if kind=='case_alias':side=destination/'CANDIDATE.SSSOM.TSV'
 if kind=='unicode_alias':output=destination/'caf\u00e9.sssom.tsv';side=destination/'cafe\u0301.sssom.tsv'
 paths=art.artifact_paths(output,side)
 sssom=(f'# mapping_set_description: "{art.POLICY_MARKER}"\nsubject_id\tother\nMIM:Subject\tkept\n').encode()
 aliases=policy.render_suppressed_aliases([])
 def check():assert source.read_bytes()==b'preferred_term: Owned\n'
 def publish(callback=check):return art.publish_candidate_artifacts(output,sssom,aliases,{'producer_revision':'6a7172585eb68da7f4fe01aee75a82458ddd470c','input_sha256':hashlib.sha256(source.read_bytes()).hexdigest()},callback,input_paths=[source],expected_before=art.capture_beforeimages(paths),claw_root=CLAW,sidecar_output=side)
 item={'case':kind,'output':str(output),'sidecar':str(paths[1]),'outputs_initially_absent':all(not p.exists() for p in paths)}
 try:
  if kind=='no_op_callback_drift':
   first=publish();assert first['status']=='complete'
   def concurrent_check():check();paths[1].write_bytes(b'concurrent replacement\n')
   result=publish(concurrent_check)
  elif kind=='complete_callback_drift':
   calls=0
   def concurrent_check():
    nonlocal calls
    calls+=1;check()
    if calls==6:paths[1].write_bytes(b'concurrent replacement\n')
   result=publish(concurrent_check);item['input_check_calls']=calls
  else:result=publish()
  item['return']=result
 except Exception as exc:item['exception']={'type':type(exc).__name__,'message':str(exc)}
 item['files']=[{'path':str(p),'exists':p.exists(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None} for p in paths]
 item['output_equals_intended']=output.is_file() and output.read_bytes()==sssom
 item['sidecar_equals_intended']=paths[1].is_file() and paths[1].read_bytes()==aliases
 item['samefile']=output.exists() and paths[1].exists() and output.samefile(paths[1])
 item['journals']=[{'path':str(p),'status':json.loads(p.read_text())['status']} for p in (destination/'.sssom-artifact-journals').glob('*.json')]
 results.append(item)
for kind in ['positive','case_alias','unicode_alias','no_op_callback_drift','complete_callback_drift']:run(kind)
(HERE/'artifact-probe-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
